"""The GitHub group: whether a pull request can be opened, and on which repository.

`gh`, the App and a token are three ways in; each is said, and a repository is
asked for its rights through the one the runner will use.
"""

from __future__ import annotations

import shutil
import subprocess
from urllib.parse import quote

from .. import config as config_module
from .. import git, github_app, github_token, state, store
from .check import ERROR, INFO, OK, PROBE_TIMEOUT, WARN, Check, _check, _first_line, _installing

_WRITING = {"WRITE", "MAINTAIN", "ADMIN"}


def _github_access(config: config_module.Config, *, code: bool = True) -> list[Check]:
    """The apps connected from the console, then `gh`, then the accounts `[github]` names.

    `code`: whether a project of the board has a repository. Without one no
    ticket opens a pull request, and GitHub not connected is only said.
    """
    found: list[Check] = []
    connected = github_app.describe(with_repositories=False)
    for app in connected:
        params = {"slug": app["slug"]}
        if app["error"]:
            found.append(
                _check(
                    "github.access",
                    ERROR,
                    "GitHub access",
                    "The GitHub App {{slug}} gets no answer from GitHub.",
                    params=params,
                    evidence=app["error"],
                    cause="The App was deleted on GitHub, or its key no longer matches.",
                    steps=["Connect the App again from Settings › GitHub."],
                )
            )
            continue
        if not app["installations"]:
            found.append(
                _check(
                    "github.access",
                    ERROR,
                    "GitHub access",
                    "The GitHub App {{slug}} is installed nowhere.",
                    params=params,
                    cause="The App exists, but no account or organisation gave it a repository.",
                    steps=["Install the GitHub App on your account, and choose the repositories."],
                    url=app["install_url"],
                )
            )
            continue
        for installation in app["installations"]:
            reached = {**params, "account": installation["account"]}
            if not github_app.token(installation["account"]):
                found.append(
                    _check(
                        "github.access",
                        ERROR,
                        "GitHub access",
                        "GitHub gives the App {{slug}} no token on {{account}}.",
                        params=reached,
                        cause="The installation was suspended or removed on GitHub.",
                        steps=["Install the GitHub App on this account again."],
                        url=app["install_url"],
                    )
                )
            else:
                found.append(
                    _check(
                        "github.access",
                        OK,
                        "GitHub access",
                        "GitHub App {{slug}} on {{account}}: token obtained, every repository."
                        if installation["selection"] == "all"
                        else "GitHub App {{slug}} on {{account}}: token obtained, the repositories chosen.",
                        params=reached,
                    )
                )
    found.extend(_gh(config, apps=bool(connected), code=code))
    return found


def _gh(config: config_module.Config, *, apps: bool, code: bool = True) -> list[Check]:
    """`gh`: what opens pull requests without an App, and the fallback beside one.

    Without an App it is the only way, and missing or signed out is an error
    once a project has a repository — before that, a line for the day one has;
    beside an App, only a repository the App does not reach needs it.
    """
    if not shutil.which("gh"):
        if apps:
            return [
                _check(
                    "github.access",
                    WARN,
                    "GitHub access",
                    "`gh` is not installed: a repository the GitHub App does not reach gets no pull request.",
                    url="https://cli.github.com",
                    **_installing("gh"),
                )
            ]
        if not code:
            return [
                _check(
                    "github.access",
                    INFO,
                    "GitHub access",
                    "GitHub is not connected: no pull request can be opened until it is.",
                    cause="No project of the board has a repository: writing, external and publishing tickets do without GitHub.",
                    url="https://cli.github.com",
                    **_installing(
                        "gh",
                        "Connect a GitHub App from Settings › GitHub, or install `gh` and run `gh auth login`.",
                    ),
                )
            ]
        return [
            _check(
                "github.access",
                ERROR,
                "GitHub access",
                "No GitHub App is connected and `gh` is not installed.",
                cause="Pull requests are opened with a GitHub App or with the `gh` command.",
                url="https://cli.github.com",
                **_installing(
                    "gh",
                    "Connect a GitHub App from Settings › GitHub, or install `gh` and run `gh auth login`.",
                ),
            )
        ]
    found: list[Check] = []
    answered = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, timeout=PROBE_TIMEOUT
    )
    if answered.returncode == 0:
        found.append(_check("github.access", OK, "GitHub access", "`gh` is signed in."))
    else:
        found.append(
            _check(
                "github.access",
                WARN if apps else ERROR if code else INFO,
                "GitHub access",
                "`gh` is not signed in.",
                cause="Without a token Ponos can neither push nor open a pull request.",
                steps=["In a terminal on this machine, run `gh auth login`."],
                evidence=_first_line(answered.stderr or answered.stdout),
            )
        )
    # The one place where a `[github]` line that names an account nobody
    # logged in is worth saying out loud: everywhere else it falls back on
    # the active account, which is deliberate — a ticket does not fail over
    # a line of configuration — and silent by the same token.
    for owner, account in sorted(config.github.items()):
        params = {"owner": owner, "account": account}
        if git.account_token(account):
            found.append(
                _check(
                    "github.account",
                    OK,
                    "GitHub account for {{owner}}",
                    "{{owner}}/* is worked as {{account}}.",
                    params=params,
                )
            )
        else:
            found.append(
                _check(
                    "github.account",
                    ERROR,
                    "GitHub account for {{owner}}",
                    "`gh` is not signed in as {{account}}, the account [github] names for {{owner}}/*.",
                    params=params,
                    steps=["In a terminal on this machine, run `gh auth login` as {{account}}."],
                )
            )
    return found


def _github_billing() -> list[Check]:
    """The accounts whose GitHub Actions billing refuses their jobs, one warning each.

    Read off what the runner wrote the first time a merge met it (`state.hold_billing`):
    the dashboard asks GitHub nothing, and an account of which no merge waits
    is not listed — there is nothing for it to stop.
    """
    return [
        _check(
            "github.billing",
            WARN,
            "GitHub Actions billing",
            "GitHub Actions is blocked by the billing of {{account}}: no job of its "
            "repositories starts, and their merges wait.",
            params={"account": str(hold["name"])},
            evidence=str(hold["reason"]),
            cause="A recent payment of the account failed, or its Actions spending limit is reached.",
            steps=[
                "Settle the payment or raise the spending limit in the billing settings of the "
                "account on GitHub (an organisation's are in its own settings).",
                "Ponos asks GitHub to run the refused jobs again every hour, and merges what "
                "waited once they pass.",
            ],
            url="https://github.com/settings/billing",
        )
        for hold in state.billing_holds()
    ]


def _github_token() -> list[Check]:
    """The personal access token, if one is given: who it is, and what it lacks."""
    if why := github_token.unavailable():
        return [
            _check(
                "github.token",
                ERROR,
                "GitHub token",
                "The token [github_access] token_item names cannot be read.",
                evidence=why,
            )
        ]
    held = github_token.token()
    if not held:
        return [
            _check(
                "github.token",
                INFO,
                "GitHub token",
                "No personal token (Settings › GitHub, or PONOS_GITHUB_TOKEN).",
            )
        ]
    params = {"source": github_token.source()}
    try:
        checked = github_token.check(held)
    except github_token.GithubTokenError as error:
        return [
            _check(
                "github.token",
                ERROR,
                "GitHub token",
                "The token from {{source}} is refused.",
                params=params,
                evidence=str(error),
            )
        ]
    params["login"] = checked["login"]
    found: list[Check] = []
    if checked["missing"]:
        found.append(
            _check(
                "github.token",
                ERROR,
                "GitHub token",
                "The token of {{login}} from {{source}} lacks {{needs}}.",
                params={
                    **params,
                    "needs": ", ".join(
                        f"{one['permission']} ({one['level']})" for one in checked["missing"]
                    ),
                },
                steps=["Give the token these permissions on GitHub, or make a new one."],
            )
        )
    else:
        found.append(
            _check(
                "github.token",
                OK,
                "GitHub token",
                "The token of {{login}} from {{source}}: {{kind}}, {{count}} repositories, {{writable}} writable.",
                params={
                    **params,
                    "kind": checked["kind"],
                    "count": str(len(checked["repositories"])),
                    "writable": str(len(checked["writable"])),
                },
            )
        )
    for warning in checked["warnings"]:
        found.append(
            _check(
                "github.token",
                WARN,
                "GitHub token",
                "The token of {{login}} lacks what some tickets need.",
                params=params,
                evidence=warning,
            )
        )
    return found


def _repository(remote: str) -> tuple[str, str]:
    """(owner/name, owner) of a remote, or empty when it is not a GitHub one."""
    parts = git.reference_parts(remote)
    if len(parts) < 3 or "github.com" not in remote:
        return "", ""
    return "/".join(parts[1:3]), git.owner(remote)


def _github_rights(config: config_module.Config, name: str, owner: str) -> Check:
    """May the runner read, push and open a pull request on that repository?"""
    title = "GitHub rights on {{repository}}"
    params = {"repository": name}
    if github_app.apps():
        reached = github_app.covers(name, owner)
        if reached is False:
            app = github_app.apps()[0]
            return _check(
                "github.repository",
                ERROR,
                title,
                "The GitHub App does not reach {{repository}}.",
                params=params,
                cause="The App is installed without this repository, or on another account.",
                steps=[
                    "Install the GitHub App on this repository: choose it in the installation's list."
                ],
                url=app.install_url,
            )
        if reached:
            granted = (github_app.installation_for(owner) or (None, {}))[1].get("permissions") or {}
            weak = [
                name
                for name in ("contents", "pull_requests")
                if granted and granted.get(name) != "write"
            ]
            if weak:
                return _check(
                    "github.repository",
                    ERROR,
                    title,
                    "The GitHub App cannot write {{rights}} on {{repository}}.",
                    params={**params, "rights": " or ".join(weak)},
                    cause="The App was created with read-only permissions, or the installation was not accepted again.",
                    steps=["Open the App's installation on GitHub and accept its new permissions."],
                    url=github_app.apps()[0].install_url,
                )
            return _check(
                "github.repository",
                OK,
                title,
                "The GitHub App reaches {{repository}}.",
                params=params,
            )
    token = git.token_for(name, config.github)
    answered = (
        git.run(
            [
                "gh",
                "repo",
                "view",
                "--json",
                "viewerPermission",
                "--jq",
                ".viewerPermission",
                "--",
                name,
            ],
            timeout=PROBE_TIMEOUT,
            token=token,
        )
        if shutil.which("gh")
        else None
    )
    if answered is None:
        return _check(
            "github.repository",
            WARN,
            title,
            "{{repository}} cannot be checked without `gh`.",
            params=params,
        )
    if not answered.ok:
        return _check(
            "github.repository",
            ERROR,
            title,
            "{{repository}} cannot be reached with this GitHub account.",
            params=params,
            evidence=_first_line(answered.err or answered.out),
            cause="The repository does not exist, or the account has no access to it.",
            steps=[
                "Check the Repository property of the project, and that the account can open it on GitHub."
            ],
        )
    permission = answered.out.strip()
    if permission in _WRITING:
        return _check(
            "github.repository",
            OK,
            title,
            "Push and pull requests allowed on {{repository}}.",
            params=params,
        )
    return _check(
        "github.repository",
        ERROR,
        title,
        "The account can only {{permission}} {{repository}}.",
        params={**params, "permission": "read" if permission == "READ" else permission.lower()},
        cause="Pushing a branch and opening a pull request need write access.",
        steps=["Ask for write access on this repository, or connect an account that has it."],
        url=f"https://github.com/{name}",
    )


def _issues(config: config_module.Config, client: store.Store) -> list[Check]:
    """The repositories a `github` board is made of: reachable, labelled, and writable.

    Three things a ticket needs of them and that fail without a word: the issues
    are on, the account may label and comment (triage or above — reading is not
    enough), and the label that makes an issue a ticket exists, since an issue
    nobody can find the label for is a ticket nobody will ever create.
    """
    from ..github_issues import Issues

    found: list[Check] = []
    if not isinstance(client, Issues):
        return found
    label = config.issues.label
    for repository in config.issues.repositories:
        params = {"repository": repository, "label": label}
        if not git.is_repository(repository):
            found.append(
                _check(
                    "github.issues",
                    ERROR,
                    "GitHub issues",
                    "{{repository}} is not a repository name, owner/name.",
                    params=params,
                    steps=["Fix `issues.repositories` in the settings."],
                )
            )
            continue
        try:
            about = client.call(repository, "GET", "")
        except store.StoreError as error:
            found.append(
                _check(
                    "github.issues",
                    ERROR,
                    "GitHub issues",
                    "The repository {{repository}} cannot be read.",
                    params=params,
                    cause="It does not exist, or no account Ponos works under can see it.",
                    steps=[
                        "Connect the GitHub App on it, or sign `gh` in with an account that can."
                    ],
                    evidence=_first_line(error),
                )
            )
            continue
        rights = (about or {}).get("permissions") or {}
        if not (about or {}).get("has_issues", True):
            found.append(
                _check(
                    "github.issues",
                    ERROR,
                    "GitHub issues",
                    "The issues of {{repository}} are turned off.",
                    params=params,
                    steps=["Turn them on: the repository's Settings › Features › Issues."],
                    url=f"https://github.com/{repository}/settings",
                )
            )
        elif rights and not (rights.get("push") or rights.get("triage") or rights.get("admin")):
            found.append(
                _check(
                    "github.issues",
                    ERROR,
                    "GitHub issues",
                    "The account cannot label or comment issues of {{repository}}.",
                    params=params,
                    cause="Moving a ticket is a label, and a question is a comment: both need triage rights.",
                    steps=[
                        "Ask for triage or write access on this repository, or connect an account that has it."
                    ],
                    url=f"https://github.com/{repository}",
                )
            )
        else:
            found.append(
                _check(
                    "github.issues",
                    OK,
                    "GitHub issues",
                    "Issues of {{repository}} readable and writable.",
                    params=params,
                )
            )
        try:
            client.call(repository, "GET", f"labels/{quote(label, safe='')}")
        except store.Missing:
            found.append(
                _check(
                    "github.label",
                    WARN,
                    "GitHub issues",
                    "{{repository}} has no label “{{label}}”: no issue can be a ticket yet.",
                    params=params,
                    steps=["Create it: `gh label create {{label}} --repo {{repository}}`."],
                    url=f"https://github.com/{repository}/labels",
                )
            )
        except store.StoreError as error:
            found.append(
                _check(
                    "github.label",
                    WARN,
                    "GitHub issues",
                    "The label “{{label}}” of {{repository}} could not be checked.",
                    params=params,
                    evidence=_first_line(error),
                )
            )
        else:
            found.append(
                _check(
                    "github.label",
                    OK,
                    "GitHub issues",
                    "The label “{{label}}” exists on {{repository}}.",
                    params=params,
                )
            )
    return found
