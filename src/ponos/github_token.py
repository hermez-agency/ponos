"""GitHub reached with a token, for whoever has no GitHub App to set up.

A GitHub App is the shape GitHub made for a robot (see github_app.py), and it
is a lot to ask of somebody who only wants a first ticket to come back as a pull
request: an app to create, install, and one more per organisation. A personal
access token — a fine-grained one, limited to the repositories it is made for —
does the same work in a paste. Both go through the one door tickets already
use, `git.token_for`: the token takes the place of the app's installation token
and nothing downstream knows which of the two it holds.

**Where the token lives.** Never in `config.toml`, a ticket or a log. It is
`PONOS_GITHUB_TOKEN` in `secrets.env` (what the console writes) or in the
environment (what a container is given), and `[github_access] token_item` may
instead name an item of a vault the machine already has — `pass:ponos/github`,
`keyring:ponos-github`, `bitwarden:…` — read through vault.py the way a
project's keys are. Every value read is handed to `vault.remember`, so it is
masked wherever the runner writes.

**Which of the two answers.** `[github_access] mode` says: `app`, `token`, or
nothing — and nothing is the old behaviour with the token added at the end, the
App first when it reaches the owner, then the token, then `gh`'s own accounts.

**Checked when it is saved, not at the first ticket.** A fine-grained token
does not tell what it may do; GitHub only answers for what it is asked. So
`check` asks: who it is, which repositories it reaches, whether it may write
to them (the `permissions` GitHub puts on each), and whether pull requests
answer at all. Writing a pull request is the one thing that cannot be tried
without opening one, so it is said, not guessed.

**Unlike an installation token, it does not lapse in an hour,** so a session
is simply handed it: no wrapper around `gh`, no helper that asks again.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.parse import quote

from . import config as config_module
from . import github_app, http, vault

# Where a token for Ponos is made, with the permissions it needs already filled
# in (GitHub reads them from the query string of this page).
CREATE_URL = (
    "https://github.com/settings/personal-access-tokens/new"
    "?name=Ponos&description=Ponos+runner&contents=write&pull_requests=write&metadata=read"
    "&workflows=write&actions=read&checks=read&statuses=read&issues=read"
)
# The permissions a code ticket cannot do without, as GitHub names them.
REQUIRED = (
    ("Contents", "Read and write"),
    ("Pull requests", "Read and write"),
    ("Metadata", "Read-only"),
)

# A value read from a vault is kept this long: a keyring or a `pass` is a
# subprocess, and a pass asks for a token for every git command.
KEPT_SECONDS = 60
TIMEOUT = 20
PAGES = 5


class GithubTokenError(Exception):
    pass


_lock = threading.Lock()
# When it was read, the value, and where it came from.
_kept: tuple[float, str, str] | None = None


# -- what the machine holds ------------------------------------------------------


def access() -> config_module.GithubAccess:
    """`[github_access]` as the files say it now — read again, since the console writes them."""
    path = config_module.config_path()
    return config_module.read_github_access(
        config_module.read_raw(path), config_module.read_secrets(config_module.secrets_path(path))
    )


def _read() -> tuple[str, str]:
    """The token and where it came from — a name, never the value."""
    global _kept
    with _lock:
        if _kept and time.monotonic() - _kept[0] < KEPT_SECONDS:
            return _kept[1], _kept[2]
    held = access()
    value, origin = "", ""
    if held.token_item:
        which, item = vault.where(held.token_item, "env")
        try:
            stored = config_module.read_secrets(config_module.secrets_path())
            value = vault.provider(which, stored).read(item).strip()
        except vault.VaultError:
            value = ""
        origin = held.token_item if value else ""
    if not value and held.token:
        stored = config_module.read_secrets(config_module.secrets_path())
        value = held.token
        origin = (
            "secrets.env"
            if stored.get(config_module.GITHUB_TOKEN_ENV, "").strip()
            else config_module.GITHUB_TOKEN_ENV
        )
    if value:
        vault.remember(value)
    with _lock:
        _kept = (time.monotonic(), value, origin)
    return value, origin


def token() -> str:
    """The token this machine was given, or nothing. Remembered, to be masked."""
    return _read()[0]


def unavailable() -> str:
    """Why `token_item` cannot be read, or "" — what `doctor` and the console say."""
    held = access()
    if not held.token_item:
        return ""
    which, item = vault.where(held.token_item, "env")
    try:
        provider = vault.provider(which, {})
    except vault.VaultError as error:
        return str(error)
    if why := provider.available():
        return why
    try:
        return "" if provider.read(item).strip() else f"{which} holds no item {item!r}"
    except vault.VaultError as error:
        return str(error)


def holds(value: str) -> bool:
    """Is this the token of the machine — how `git.run` tells it from a `gh` account's."""
    return bool(value) and value == token()


def save(value: str) -> None:
    """Keep a token in `secrets.env`, 0600 like the other secrets."""
    global _kept
    config_module.write_secrets(
        config_module.secrets_path(), {config_module.GITHUB_TOKEN_ENV: value.strip()}
    )
    vault.remember(value.strip())
    with _lock:
        _kept = None


def forget() -> bool:
    """Drop the token from `secrets.env`. One the environment gives stays."""
    global _kept
    present = bool(
        config_module.read_secrets(config_module.secrets_path()).get(config_module.GITHUB_TOKEN_ENV)
    )
    config_module.write_secrets(
        config_module.secrets_path(), {config_module.GITHUB_TOKEN_ENV: None}
    )
    with _lock:
        _kept = None
    return present


def source() -> str:
    """Where the token comes from — a name, never the value."""
    return _read()[1]


# -- who answers ------------------------------------------------------------------


def for_owner(owner: str) -> str:
    """The token that works that owner's repositories, or nothing — see `git.token_for`."""
    mode = access().mode
    if mode == "token":
        return token() or github_app.token(owner)
    granted = github_app.token(owner)
    if granted or mode == "app":
        return granted
    return token()


def session_environment(owner: str) -> dict[str, str]:
    """What a session on that owner's repository is given: the App's, else the token's."""
    mode = access().mode
    if mode != "token":
        if found := github_app.session_environment(owner):
            return found
        if mode == "app":
            return {}
    value = token()
    if not value:
        return {}
    return {"GH_TOKEN": value, "GITHUB_TOKEN": value, **github_app.git_environment()}


# -- checking a token -------------------------------------------------------------


def _send(url: str, bearer: str) -> tuple[int, dict[str, str], bytes]:
    """One GET to GitHub: status, headers (lower-cased) and body. Replaced by the tests."""
    answer = http.send(
        "github",
        "GET",
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {bearer}",
        },
        timeout=TIMEOUT,
    )
    return answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.body


def _get(value: str, path: str) -> tuple[int, dict[str, str], object]:
    try:
        status, headers, raw = _send(f"{github_app.api()}{path}", value)
    except (http.Unanswered, OSError, ValueError) as error:
        raise GithubTokenError(f"GitHub did not answer: {error}") from error
    try:
        answer = json.loads(raw.decode() or "null")
    except ValueError:
        answer = None
    return status, headers, answer


def check(value: str) -> dict[str, Any]:
    """What a token is and what it lacks. Raises GithubTokenError when it is no token at all.

    `missing` is what stops a code ticket (a permission and the level it needs),
    `warnings` what only some tickets need. Nothing here holds the token.
    """
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        raise GithubTokenError("Paste the token as GitHub shows it, on one line")
    status, headers, user = _get(value, "/user")
    if status == 401:
        raise GithubTokenError("GitHub refuses this token: it is mistyped, expired or revoked")
    if status >= 400 or not isinstance(user, dict) or not user.get("login"):
        said = user.get("message", "") if isinstance(user, dict) else ""
        raise GithubTokenError(
            f"GitHub could not identify this token ({status}): {said}".rstrip(": ")
        )

    # Only a classic token carries its scopes in a header; a fine-grained one has none.
    classic = "x-oauth-scopes" in headers
    scopes = {one.strip() for one in headers.get("x-oauth-scopes", "").split(",") if one.strip()}
    missing: list[dict[str, str]] = []
    warnings: list[str] = []

    repositories: list[dict[str, Any]] = []
    for page in range(1, PAGES + 1):
        status, _, listed = _get(value, f"/user/repos?per_page=100&page={page}&sort=pushed")
        if status >= 400 or not isinstance(listed, list):
            break
        repositories += [one for one in listed if isinstance(one, dict) and one.get("full_name")]
        if len(listed) < 100:
            break
    writable = [
        one["full_name"] for one in repositories if (one.get("permissions") or {}).get("push")
    ]

    if classic and "repo" not in scopes:
        missing.append({"permission": "repo", "level": "scope"})
    if classic and "workflow" not in scopes:
        warnings.append(
            "without the workflow scope, a ticket cannot change a file of .github/workflows"
        )
    if not repositories:
        missing.append({"permission": "Repository access", "level": "at least one repository"})
    elif not writable and not (classic and "repo" not in scopes):
        missing.append({"permission": "Contents", "level": "Read and write"})
    elif len(writable) < len(repositories):
        warnings.append(
            "read-only on "
            + ", ".join(
                sorted(
                    one["full_name"] for one in repositories if one["full_name"] not in writable
                )[:10]
            )
        )
    if writable and not classic:
        status, _, _ = _get(value, f"/repos/{quote(writable[0])}/pulls?per_page=1&state=all")
        if status in (403, 404):
            missing.append({"permission": "Pull requests", "level": "Read and write"})
        else:
            warnings.append("the write access to pull requests is only seen when one is opened")

    return {
        "login": str(user["login"]),
        "kind": "classic" if classic else "fine-grained",
        "repositories": sorted(one["full_name"] for one in repositories),
        "writable": sorted(writable),
        "missing": missing,
        "warnings": warnings,
        "ok": not missing,
    }


def describe() -> dict[str, Any]:
    """The token as the console and `doctor` show it: where from, who it is — never the value."""
    value = token()
    shown: dict[str, Any] = {
        "configured": bool(value),
        "source": source(),
        "mode": access().mode,
        "vault": unavailable(),
        "create_url": CREATE_URL,
    }
    if not value:
        return shown
    try:
        shown["check"] = check(value)
    except GithubTokenError as error:
        shown["error"] = str(error)
    return shown
