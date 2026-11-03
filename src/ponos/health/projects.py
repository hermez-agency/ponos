"""The projects group: each project of the board, found on this machine and reachable.

`base_without_ci` is asked by `__main__` too, outside the checks: a base whose
pushes run no CI is one where a red merge would go unseen.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config as config_module
from .. import git, github_app, projects
from .check import ERROR, OK, PROBE_TIMEOUT, WARN, Check, _check, _first_line, _fix
from .github import _github_rights, _repository


def _project(config: config_module.Config, row: dict[str, str]) -> list[Check]:
    name = row["name"]
    params = {"project": name}
    resolver = projects.Resolver(config.runner.workspace_root, config.projects, config.github)
    path = resolver.locate(name, row["path"], row["repository"])
    found: list[Check] = []
    if path is None:
        if row["repository"]:
            found.append(
                _check(
                    "projects.path",
                    WARN,
                    "Local copy of {{project}}",
                    "No local copy of {{project}} yet: it is cloned when its first ticket starts.",
                    params=params,
                )
            )
            return found
        found.append(
            _check(
                "projects.path",
                ERROR,
                "Local copy of {{project}}",
                "The path of {{project}} is not a git repository: {{path}}.",
                params={**params, "path": row["path"]},
                cause="The folder was moved or deleted, or the Path property is mistyped.",
                steps=[
                    "Correct the Path property of the project, or give its Repository so it can be cloned."
                ],
            )
        )
        return found
    found.append(
        _check(
            "projects.path",
            OK,
            "Local copy of {{project}}",
            "{{project}} is in {{path}}.",
            params={**params, "path": str(path)},
        )
    )

    remote = git.remote_url(path)
    if not remote:
        found.append(
            _check(
                "projects.remote",
                ERROR,
                "Remote of {{project}}",
                "{{project}} has no origin remote.",
                params=params,
                cause="Without it nothing can be pushed and no pull request opened.",
                steps=["In the repository, run `git remote add origin <url>`."],
            )
        )
        return found
    probe = git.run(
        ["git", "ls-remote", "--exit-code", "origin", "HEAD"], path, timeout=PROBE_TIMEOUT
    )
    if probe.ok:
        found.append(
            _check(
                "projects.remote",
                OK,
                "Remote of {{project}}",
                "The remote of {{project}} answers.",
                params=params,
            )
        )
    else:
        found.append(
            _check(
                "projects.remote",
                ERROR,
                "Remote of {{project}}",
                "The remote of {{project}} cannot be reached.",
                params=params,
                evidence=_first_line(probe.err or probe.out),
                cause="No network, a repository that moved, or credentials git does not have.",
                steps=["In the repository, run `git ls-remote origin` and fix what it prints."],
            )
        )
    if git.git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], path).ok:
        found.append(
            _check(
                "projects.branch",
                OK,
                "Default branch of {{project}}",
                "{{project}} starts from {{branch}}.",
                params={**params, "branch": git.default_branch(path)},
            )
        )
    else:
        found.append(
            _check(
                "projects.branch",
                WARN,
                "Default branch of {{project}}",
                "The default branch of {{project}} is not known: {{branch}} is assumed.",
                params={**params, "branch": git.default_branch(path)},
                cause="The clone never recorded which branch the origin treats as its default.",
                steps=["In the repository, run `git remote set-head origin --auto`."],
                fix=_fix(
                    "project_branch",
                    "Configure",
                    "Ask the origin of {{project}} for its default branch (git remote set-head origin --auto)?",
                    [name],
                    target=row["id"],
                )
                if probe.ok
                else None,
            )
        )
    owner_repo, owner = _repository(remote)
    if owner_repo and probe.ok:
        found.append(_github_rights(config, owner_repo, owner))
    return found


def _workspace_root(config: config_module.Config) -> list[Check]:
    """The folder the repositories are looked for in, and each repository found there.

    Every one of them, on the board or not: a base whose CI never runs at push
    breaks silently, and the first pull request to find it red is the one that
    pays. A repository the GitHub App does not reach falls back on `gh`, which a
    machine connected through the App may well not have signed in.
    """
    root = config.runner.workspace_root
    params = {"root": str(root)}
    if not root.is_dir():
        return [
            _check(
                "projects.workspace",
                ERROR,
                "Workspace folder",
                "{{root}} does not exist (runner.workspace_root).",
                params=params,
                steps=[
                    "Create it: `mkdir -p {{root}}`, or pick another folder in the console's first connection."
                ],
            )
        ]
    resolver = projects.Resolver(root, config.projects, config.github)
    index = resolver._index()  # noqa: SLF001 — diagnostics
    found = [
        _check(
            "projects.workspace",
            OK,
            "Workspace folder",
            "{{root}}: {{count}} repositories found.",
            params={**params, "count": str(sum(len(repos) for repos in index.values()))},
        )
    ]
    repositories = sorted({path for repos in index.values() for path in repos})
    with ThreadPoolExecutor(max_workers=8) as pool:
        for checks in pool.map(lambda repo: _local_repository(config, repo), repositories):
            found.extend(checks)
    return found


def _local_repository(config: config_module.Config, repo: Path) -> list[Check]:
    found: list[Check] = []
    params = {"repository": repo.name}
    base, ran = _ci_at_push(repo, config.github)
    if ran in ("none", "skipped"):
        found.append(
            _check(
                "projects.ci",
                WARN,
                "CI of {{repository}}",
                "{{base}} has no CI run at push: a red base would go unseen."
                if ran == "none"
                else "{{base}} has only skipped CI runs at push: a red base would go unseen.",
                params={**params, "base": base},
            )
        )
    remote = git.remote_url(repo)
    name = "/".join(git.reference_parts(remote)[1:3]) if "." in remote else ""
    if name and github_app.covers(name, git.owner(remote)) is False:
        found.append(
            _check(
                "github.reach",
                WARN,
                "GitHub App on {{repository}}",
                "{{repository}} is not reached by the GitHub App.",
                params={"repository": name},
                steps=["Add the repository to the App's installation on GitHub."],
            )
        )
    return found


def _ci_at_push(repo: Path, accounts: git.Accounts | None = None) -> tuple[str, str]:
    """The base of that repository, and what its CI does at push — see `git.ci_at_push`."""
    base = git.default_branch(repo)
    return base, git.ci_at_push(repo, base, accounts)


def base_without_ci(repo: Path, accounts: git.Accounts | None = None) -> str:
    """Why the base of that repository goes unwatched, or nothing when it is.

    Said for a base with no push run at all and for one whose runs are all
    skipped; a repository GitHub cannot be asked about says nothing.
    """
    base, found = _ci_at_push(repo, accounts)
    if found == "none":
        return f"{base} has no CI run at push — a red base would go unseen"
    if found == "skipped":
        return f"{base} has only skipped CI runs at push — a red base would go unseen"
    return ""
