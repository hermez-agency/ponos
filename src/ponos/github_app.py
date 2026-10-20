"""GitHub reached through an app of its own, rather than through a person's `gh`.

`gh auth login` works, and it is the wrong shape for a robot: a step somebody
types on the machine, a token tied to their own account, and one that sees
every repository they can. A GitHub App is the shape GitHub made for this — it
is installed on the repositories somebody picks, and it hands out tokens that
last an hour and reach those repositories alone.

**Created from a manifest, in one trip through the browser.** GitHub can make
an app out of a JSON description posted to it from a page: it shows the form
already filled in, the person says yes, and GitHub sends them back to the
console with a code. That code is worth the app's credentials for an hour,
once (`convert`). The console then sends them on to the installation page, and
GitHub sends them back again once repositories are chosen. Nothing to copy, no
token to paste. The `state` that goes out with the form is what the way back is
checked against: drawn here, good for an hour, and good once.

**Signed with the standard library.** The app proves itself with a JWT signed
RS256 by its private key — and the runner installs nothing, so no
`cryptography` either. An RSA signature is a padding and a modular
exponentiation: Python's integers do the second, and the first is written out
below (PKCS #1 v1.5, RFC 8017 § 9.2). Only signing is needed, never verifying,
and the key is the one GitHub itself just generated.

**Everything that already speaks `gh` keeps speaking it.** An installation token
goes where a `gh` account's token went: `git.token_for` returns it, `git.run`
puts it in `GH_TOKEN`, and every `gh pr …` the runner sends answers as the
app's bot. `git` itself is given a credential helper through the environment
— never in `.git/config`, never on a command line a `ps` or a log could show —
and SSH remotes are read as HTTPS for the length of the command, since the
token only opens the HTTPS door.

**An hour is shorter than some sessions.** A token is renewed ten minutes before
it lapses, for the runner's own calls. A session cannot be handed a new
environment half-way through, so it is handed ways to ask: a `gh` placed first
in its `PATH` and a credential helper, both of which take a fresh token from
here once the one they started with is about to lapse (`session_environment`).

**No app, nothing changes.** `token` answers nothing, and `token_for` goes on to
the `gh` accounts exactly as before. An app GitHub no longer knows, or a network
that does not answer, is the same nothing: a ticket falls back on `gh` rather
than failing over a connection somebody set up once.

The credentials live in `secrets.env` with the other secrets — the same file,
the same 0600 — as one JSON line, since a machine may have two apps: a private
app can only be installed on the account that owns it, so your own repositories
and an organisation's are two apps, one connection each. Neither the key nor a
token is ever printed: `describe` is what the console sees, and it holds names.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shlex
import shutil
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import config as config_module
from . import disk, http

API = "https://api.github.com"
WEB = "https://github.com"
# Where the API and the site are, when a test says otherwise — the same seam as
# `PONOS_NOTION_API`.
API_ENV = "PONOS_GITHUB_API"
WEB_ENV = "PONOS_GITHUB_WEB"

# The one line of `secrets.env` that holds every app this machine created.
APPS_ENV = "PONOS_GITHUB_APPS"

# What the app's page on GitHub links to.
WEBSITE = "https://the-ponos.app"

# What a code ticket does on GitHub, and nothing more: write its branch and its
# pull request, read why a check failed, rerun it, and touch a workflow file
# when the ticket is about one. No organisation permission at all.
PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "metadata": "read",
    "checks": "read",
    "statuses": "read",
    "workflows": "write",
    "actions": "read",
    "issues": "read",
}

# GitHub's own ceiling for an app's name.
LONGEST_NAME = 34

# A `state` lasts as long as the code it comes back with.
STATE_SECONDS = 3600
# A JWT may live ten minutes; it is drawn a minute in the past, against a clock
# a little ahead of GitHub's, and nine minutes in the future.
JWT_PAST = 60
JWT_FUTURE = 540
# An installation token lasts an hour; it is replaced ten minutes before that.
RENEW_SECONDS = 600
# Which accounts an app is installed on, asked again after this: an installation
# added on GitHub is heard within minutes, without a restart.
INSTALLATIONS_SECONDS = 300
FAILED_SECONDS = 60
TIMEOUT = 20

# The SHA-256 `DigestInfo` prefix of PKCS #1 v1.5 (RFC 8017 § 9.2, note 1).
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class GitHubAppError(Exception):
    pass


def api() -> str:
    return os.environ.get(API_ENV, "").strip().rstrip("/") or API


def web() -> str:
    return os.environ.get(WEB_ENV, "").strip().rstrip("/") or WEB


@dataclass(frozen=True)
class App:
    """One app this machine created, with what GitHub gave for it once."""

    id: int
    slug: str
    name: str
    owner: str
    pem: str
    client_id: str = ""
    client_secret: str = ""
    webhook_secret: str = ""
    html_url: str = ""

    @property
    def install_url(self) -> str:
        return f"{web()}/apps/{self.slug}/installations/new"

    @property
    def settings_url(self) -> str:
        """Where the app is deleted — the console only forgets it."""
        return self.html_url.replace("/apps/", "/settings/apps/", 1) if self.html_url else ""


# -- HTTP ---------------------------------------------------------------------


def _send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    """One request to GitHub, as its status and its body. Replaced by the tests."""
    answer = http.send("github", method, url, headers=headers, content=body, timeout=TIMEOUT)
    return answer.status, answer.body


def _call(method: str, path: str, *, bearer: str = "", payload: dict | None = None) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        status, raw = _send(method, f"{api()}{path}", headers, body)
    except (http.Unanswered, OSError, ValueError) as error:
        raise GitHubAppError(f"GitHub did not answer: {error}") from error
    try:
        answer = json.loads(raw.decode() or "{}")
    except ValueError:
        answer = {}
    if status >= 400:
        said = answer.get("message", "") if isinstance(answer, dict) else ""
        # The path, never the headers: a token or a JWT is not an error message.
        raise GitHubAppError(f"GitHub refused {method} {path.split('?')[0]} ({status}): {said}")
    return answer


# -- the apps this machine holds ----------------------------------------------


def _secrets_file() -> Path:
    return config_module.secrets_path()


def apps() -> list[App]:
    """Every app connected here: `secrets.env` first, then the environment."""
    raw = config_module.read_secrets(_secrets_file()).get(APPS_ENV) or os.environ.get(APPS_ENV, "")
    if not raw.strip():
        return []
    try:
        listed = json.loads(raw)
    except ValueError:
        return []
    known = {name for name in App.__dataclass_fields__}
    found = []
    for one in listed if isinstance(listed, list) else []:
        if isinstance(one, dict) and one.get("id") and one.get("slug") and one.get("pem"):
            found.append(App(**{key: value for key, value in one.items() if key in known}))
    return found


def _write(held: list[App]) -> None:
    value = json.dumps([asdict(app) for app in held], separators=(",", ":")) if held else None
    config_module.write_secrets(_secrets_file(), {APPS_ENV: value})
    with _lock:
        _installations.clear()


def save(app: App) -> None:
    """Keep an app's credentials — replacing an older one of the same account."""
    _write([*(one for one in apps() if one.slug != app.slug and one.owner != app.owner), app])


def forget(slug: str) -> bool:
    """Drop an app's credentials from this machine. GitHub still has the app."""
    held = apps()
    kept = [one for one in held if one.slug != slug]
    if len(kept) == len(held):
        return False
    _write(kept)
    return True


# -- the manifest and its way back ---------------------------------------------

_states: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def draw_state(**data: str) -> str:
    """A `state` for one trip to GitHub and back."""
    state = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _lock:
        for old in [key for key, (until, _) in _states.items() if until < now]:
            del _states[old]
        _states[state] = (now + STATE_SECONDS, data)
    return state


def take_state(state: str) -> dict | None:
    """What a `state` was drawn with — once, and within the hour. None otherwise."""
    with _lock:
        held = _states.pop(state or "", None)
    if held is None or held[0] < time.monotonic():
        return None
    return held[1]


def app_name(installation: str) -> str:
    """ "Ponos — {this installation}", within GitHub's thirty-four characters."""
    return f"Ponos — {installation.strip() or 'console'}"[:LONGEST_NAME].rstrip()


def manifest(name: str, console: str) -> dict:
    console = console.rstrip("/")
    return {
        "name": name,
        "url": WEBSITE,
        "redirect_url": f"{console}/api/github/manifest/callback",
        "setup_url": f"{console}/api/github/installed",
        "setup_on_update": True,
        "public": False,
        "default_permissions": dict(PERMISSIONS),
        "default_events": [],
        # A webhook needs an address even switched off; nothing listens there yet.
        "hook_attributes": {"url": f"{console}/api/github/webhook", "active": False},
    }


def begin(console: str, organisation: str = "", installation: str = "") -> dict:
    """What the console's page posts to GitHub: where, the manifest, the state."""
    organisation = organisation.strip().lstrip("@")
    state = draw_state(organisation=organisation)
    where = (
        f"{web()}/organizations/{quote(organisation)}/settings/apps/new"
        if organisation
        else f"{web()}/settings/apps/new"
    )
    return {
        "action": f"{where}?state={quote(state)}",
        "manifest": json.dumps(manifest(app_name(installation), console)),
        "state": state,
    }


def convert(code: str) -> App:
    """The app GitHub created, from the code it sent back. Good once, for an hour."""
    if not code or not code.replace("-", "").replace("_", "").isalnum():
        raise GitHubAppError("GitHub sent back no usable code")
    answer = _call("POST", f"/app-manifests/{quote(code)}/conversions")
    if not isinstance(answer, dict) or not answer.get("id") or not answer.get("pem"):
        raise GitHubAppError("GitHub's answer holds no app")
    return App(
        id=int(answer["id"]),
        slug=str(answer.get("slug") or ""),
        name=str(answer.get("name") or ""),
        owner=str((answer.get("owner") or {}).get("login") or ""),
        pem=str(answer["pem"]),
        client_id=str(answer.get("client_id") or ""),
        client_secret=str(answer.get("client_secret") or ""),
        webhook_secret=str(answer.get("webhook_secret") or ""),
        html_url=str(answer.get("html_url") or ""),
    )


# -- RS256, by hand -----------------------------------------------------------


def _der(data: bytes, at: int) -> tuple[int, bytes, int]:
    """One DER element at `at`: its tag, its content, and where the next starts."""
    tag, length = data[at], data[at + 1]
    at += 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(data[at : at + size], "big")
        at += size
    return tag, data[at : at + length], at + length


def _children(sequence: bytes) -> list[tuple[int, bytes]]:
    found, at = [], 0
    while at < len(sequence):
        tag, content, at = _der(sequence, at)
        found.append((tag, content))
    return found


def private_key(pem: str) -> tuple[int, int]:
    """The modulus and the private exponent of an RSA key, PKCS #1 or PKCS #8."""
    body = "".join(
        line for line in pem.strip().splitlines() if line and not line.startswith("-----")
    )
    try:
        data = base64.b64decode(body)
        _, outer, _ = _der(data, 0)
        parts = _children(outer)
        if len(parts) >= 3 and parts[1][0] == 0x30:  # PKCS #8: the key is wrapped
            _, outer, _ = _der(parts[2][1], 0)
            parts = _children(outer)
        modulus = int.from_bytes(parts[1][1], "big")
        exponent = int.from_bytes(parts[3][1], "big")
    except (ValueError, IndexError) as error:
        raise GitHubAppError("the app's private key cannot be read") from error
    return modulus, exponent


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(message: bytes, pem: str) -> bytes:
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017 § 8.2.1)."""
    modulus, exponent = private_key(pem)
    size = (modulus.bit_length() + 7) // 8
    digest = SHA256_PREFIX + hashlib.sha256(message).digest()
    if size < len(digest) + 11:
        raise GitHubAppError("the app's private key is too short")
    encoded = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    return pow(int.from_bytes(encoded, "big"), exponent, modulus).to_bytes(size, "big")


def jwt(app: App, now: float | None = None) -> str:
    """What the app proves itself with: ten minutes at the most, as GitHub asks."""
    moment = int(time.time() if now is None else now)
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {
        "iat": moment - JWT_PAST,
        "exp": moment + JWT_FUTURE,
        "iss": app.client_id or str(app.id),
    }
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{_b64(sign(signing, app.pem))}"


# -- installations and their tokens ---------------------------------------------

# Per app: when its installations were read, and what they were.
_installations: dict[int, tuple[float, list[dict]]] = {}
# Per installation: its token and when it lapses, in seconds since the epoch.
_tokens: dict[int, tuple[str, float]] = {}
# Every token handed out here — how `git.run` tells one from a `gh` account's.
_issued: set[str] = set()


def installations(app: App, fresh: bool = False) -> list[dict]:
    """Where the app is installed: `{"id", "account", "selection", "permissions"}` each."""
    now = time.monotonic()
    with _lock:
        held = _installations.get(app.id)
    if held and not fresh and now - held[0] < INSTALLATIONS_SECONDS:
        return held[1]
    try:
        answer = _call("GET", "/app/installations?per_page=100", bearer=jwt(app))
    except GitHubAppError:
        # Not asked again for a minute: every git command of a pass would
        # otherwise wait on a GitHub that does not answer before going to `gh`.
        with _lock:
            _installations[app.id] = (now - INSTALLATIONS_SECONDS + FAILED_SECONDS, [])
        raise
    found = [
        {
            "id": int(one["id"]),
            "account": str((one.get("account") or {}).get("login") or ""),
            "selection": str(one.get("repository_selection") or ""),
            "permissions": one.get("permissions")
            if isinstance(one.get("permissions"), dict)
            else {},
        }
        for one in (answer if isinstance(answer, list) else [])
        if isinstance(one, dict) and one.get("id")
    ]
    with _lock:
        _installations[app.id] = (now, found)
    return found


def _expiry(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time() + 3600


def installation_token(app: App, installation: int, now: float | None = None) -> str:
    """A token for that installation — the one in hand, unless it lapses soon."""
    moment = time.time() if now is None else now
    with _lock:
        held = _tokens.get(installation)
    if held and held[1] - moment > RENEW_SECONDS:
        return held[0]
    answer = _call(
        "POST", f"/app/installations/{installation}/access_tokens", bearer=jwt(app, moment)
    )
    token = str(answer.get("token") or "") if isinstance(answer, dict) else ""
    if not token:
        raise GitHubAppError("GitHub gave no installation token")
    with _lock:
        _tokens[installation] = (token, _expiry(str(answer.get("expires_at") or "")))
        _issued.add(token)
    return token


def lapses(token: str) -> float:
    """When a token handed out here lapses, in seconds since the epoch; 0 if unknown."""
    with _lock:
        return next((until for held, until in _tokens.values() if held == token), 0.0)


def issued(token: str) -> bool:
    return bool(token) and token in _issued


def installation_for(owner: str) -> tuple[App, dict] | None:
    """The app and the installation that work an owner's repositories, if any."""
    owner = owner.strip().lower()
    if not owner:
        return None
    for app in apps():
        try:
            for one in installations(app):
                if one["account"].lower() == owner:
                    return app, one
        except GitHubAppError:
            continue
    return None


def token(owner: str) -> str:
    """An installation token for that owner's repositories, or nothing — see `git.token_for`."""
    found = installation_for(owner)
    if not found:
        return ""
    try:
        return installation_token(found[0], found[1]["id"])
    except GitHubAppError:
        return ""


def repositories(app: App, installation: int) -> list[str]:
    """`owner/name` of every repository the installation reaches."""
    bearer = installation_token(app, installation)
    names: list[str] = []
    for page in range(1, 11):
        answer = _call("GET", f"/installation/repositories?per_page=100&page={page}", bearer=bearer)
        listed = answer.get("repositories", []) if isinstance(answer, dict) else []
        names += [str(one.get("full_name") or "") for one in listed if isinstance(one, dict)]
        if len(listed) < 100:
            break
    return sorted(name for name in names if name)


def covers(reference: str, owner: str) -> bool | None:
    """Does an installation reach that repository? None: no app is connected here."""
    if not apps():
        return None
    found = installation_for(owner)
    if not found:
        return False
    if found[1]["selection"] == "all":
        return True
    try:
        reachable = {name.lower() for name in repositories(found[0], found[1]["id"])}
    except GitHubAppError:
        return False
    return reference.lower() in reachable


def describe(with_repositories: bool = True) -> list[dict]:
    """The apps as the console and `doctor` show them: names, never a secret."""
    shown = []
    for app in apps():
        entry: dict = {
            "slug": app.slug,
            "name": app.name,
            "owner": app.owner,
            "url": app.html_url,
            "settings_url": app.settings_url,
            "install_url": app.install_url,
            "installations": [],
            "error": "",
        }
        try:
            for one in installations(app, fresh=with_repositories):
                drawn = {
                    "id": one["id"],
                    "account": one["account"],
                    "selection": one["selection"],
                    "repositories": [],
                    "error": "",
                }
                if with_repositories:
                    try:
                        drawn["repositories"] = repositories(app, one["id"])
                    except GitHubAppError as error:
                        drawn["error"] = str(error)
                entry["installations"].append(drawn)
        except GitHubAppError as error:
            entry["error"] = str(error)
        shown.append(entry)
    return shown


def bot(app: App) -> tuple[str, str]:
    """The name and the address commits are signed with, as `{slug}[bot]`."""
    login = f"{app.slug}[bot]"
    try:
        answer = _call("GET", f"/users/{quote(login)}")
        user = int(answer.get("id") or 0) if isinstance(answer, dict) else 0
    except GitHubAppError:
        user = 0
    address = (
        f"{user}+{login}@users.noreply.github.com" if user else f"{login}@users.noreply.github.com"
    )
    return login, address


_bots: dict[int, tuple[str, str]] = {}


# -- what git and the sessions are given ---------------------------------------


def _config(entries: list[tuple[str, str]], base: dict[str, str] | None = None) -> dict[str, str]:
    """Git configuration carried by the environment (`GIT_CONFIG_COUNT`, git ≥ 2.31).

    After whatever the environment already carried this way, never over it.
    """
    try:
        start = int((base if base is not None else os.environ).get("GIT_CONFIG_COUNT", "0") or 0)
    except ValueError:
        start = 0
    out = {"GIT_CONFIG_COUNT": str(start + len(entries))}
    for index, (key, value) in enumerate(entries, start):
        out[f"GIT_CONFIG_KEY_{index}"] = key
        out[f"GIT_CONFIG_VALUE_{index}"] = value
    return out


# The helper for the runner's own commands: the token is in GH_TOKEN, which
# `git.run` has just set — read from there, so that it is in no argument.
STATIC_HELPER = (
    '!f() { test "$1" = get && echo username=x-access-token && echo "password=$GH_TOKEN"; }; f'
)


def git_environment(
    helper: str = STATIC_HELPER, base: dict[str, str] | None = None
) -> dict[str, str]:
    """The environment that has git authenticate to github.com with the app's token."""
    return _config(
        [
            # An empty helper first: whatever the machine's own configuration
            # names for github.com — `gh auth setup-git` writes one — is set aside.
            ("credential.https://github.com.helper", ""),
            ("credential.https://github.com.helper", helper),
            ("credential.https://github.com.useHttpPath", "true"),
            ("url.https://github.com/.insteadOf", "git@github.com:"),
            ("url.https://github.com/.insteadOf", "ssh://git@github.com/"),
        ],
        base,
    )


def _tools() -> tuple[Path, Path]:
    """The credential helper and the `gh` a session is given, written once a start."""
    place = config_module.state_dir() / "github"
    helper, wrapper = place / "credential", place / "bin" / "gh"
    source = Path(__file__).resolve().parents[1]
    python = shlex.quote(sys.executable or "python3")
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    # Replaced rather than rewritten: another session may be reading it now.
    disk.write_atomic(
        helper,
        "#!/bin/sh\n"
        f"exec {python} -I -c 'import sys; sys.path.insert(0, sys.argv[1]); "
        "from ponos import github_app; raise SystemExit(github_app.helper(sys.argv[2:]))' "
        f'{shlex.quote(str(source))} "$@"\n',
        mode=0o700,
    )
    real = shutil.which("gh")
    # Never itself: a runner started from a session would find this one first.
    if real and Path(real).resolve().parent != wrapper.parent.resolve():
        disk.write_atomic(
            wrapper,
            "#!/bin/sh\n"
            f'fresh=$({shlex.quote(str(helper))} token) && [ -n "$fresh" ] && '
            "GH_TOKEN=$fresh GITHUB_TOKEN=$fresh && export GH_TOKEN GITHUB_TOKEN\n"
            f'exec {shlex.quote(real)} "$@"\n',
            mode=0o700,
        )
    return helper, wrapper


def session_environment(owner: str) -> dict[str, str]:
    """What a session on that owner's repository is given, when an app works it.

    The token, its end, and the two ways to replace it once it nears that end —
    the credential helper for `git`, a `gh` first in the `PATH` for `gh`. And
    the bot's name on the commits, so that the work reads as the app's own.
    Nothing when no app reaches that owner: the session runs as it always has.
    """
    found = installation_for(owner)
    if not found:
        return {}
    app, installation = found
    try:
        token_now = installation_token(app, installation["id"])
    except GitHubAppError:
        return {}
    try:
        helper, wrapper = _tools()
    except OSError:
        return {}
    if app.id not in _bots:
        _bots[app.id] = bot(app)
    name, address = _bots[app.id]
    environment = {
        "GH_TOKEN": token_now,
        "GITHUB_TOKEN": token_now,
        "PONOS_GITHUB_OWNER": owner,
        "PONOS_GITHUB_LAPSES": str(int(lapses(token_now))),
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": address,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": address,
        **git_environment(shlex.quote(str(helper))),
    }
    if wrapper.exists():
        environment["PATH"] = f"{wrapper.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    return environment


def _current(owner: str) -> str:
    """The token a session holds while it lasts, a fresh one once it nears its end."""
    held = os.environ.get("GH_TOKEN", "")
    try:
        until = float(os.environ.get("PONOS_GITHUB_LAPSES", "0") or 0)
    except ValueError:
        until = 0.0
    if held and until - time.time() > RENEW_SECONDS:
        return held
    return token(owner) or held


def helper(argv: list[str], read: Callable[[], str] | None = None, out=None) -> int:
    """`credential get` for git, `token` for the `gh` wrapper — a session's two askers."""
    out = out or sys.stdout
    action = argv[0] if argv else ""
    owner = os.environ.get("PONOS_GITHUB_OWNER", "")
    if action == "token":
        fresh = _current(owner)
        if fresh:
            print(fresh, file=out)
        return 0 if fresh else 1
    if action != "get":
        return 0  # `store` and `erase`: nothing is kept, so nothing to forget
    asked = dict(
        line.split("=", 1) for line in (read or sys.stdin.read)().splitlines() if "=" in line
    )
    if asked.get("host", "") != "github.com":
        return 0
    path = asked.get("path", "").strip("/")
    fresh = _current(path.split("/")[0] if "/" in path else owner)
    if fresh:
        print(f"username=x-access-token\npassword={fresh}", file=out)
    return 0
