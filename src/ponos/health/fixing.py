"""The fixes a check offers, made once confirmed.

Apart from the checks because a fix writes — to somebody's clone, their
state directory — where a check only reads: the one module of the package
that changes anything.
"""

from __future__ import annotations

from .. import config as config_module
from .. import disk, git, leftovers, projects, store
from .. import workspace as workspace_module
from .board import _project_rows
from .check import PROBE_TIMEOUT, _first_line
from .installation import _spared
from .machine import CHECKOUTS


def fix(
    config: config_module.Config,
    client: store.Store,
    action: str,
    target: str = "",
    *,
    confirmed: bool = False,
) -> str:
    """Make one of the fixes a check offered, and say what was done.

    Refuses without `confirmed`: a fix changes somebody's clone or their
    machine, and the console asks first, but this does not rely on it.
    """
    if not confirmed:
        raise PermissionError("a fix is made only once it is confirmed")
    if action == "state_private":
        loose = disk.open_to_others(config_module.state_dir(), CHECKOUTS)
        tightened = sum(disk.tighten(path) for path in loose)
        return f"{tightened} entries tightened"
    if action == "stray_processes":
        root = leftovers.worktrees()
        worktree = root / target
        # Asked again: the ticket may have been taken up since the band was drawn.
        if not target or worktree.parent != root or worktree in _spared():
            raise LookupError("that worktree is not one left behind")
        pids = [pid for pid, _ in leftovers.processes(worktree)]
        leftovers.kill(pids)
        return f"{len(pids)} process(es) stopped"
    if action == "project_branch":
        space = workspace_module.resolve(client, config.board)
        row = next((row for row in _project_rows(client, space) if row["id"] == target), None)
        if row is None:
            raise LookupError("that project is not on the board")
        resolver = projects.Resolver(config.runner.workspace_root, config.projects, config.github)
        path = resolver.locate(row["name"], row["path"], row["repository"])
        if path is None:
            raise LookupError("that project has no local copy")
        result = git.git(["remote", "set-head", "origin", "--auto"], path, timeout=PROBE_TIMEOUT)
        if not result.ok:
            raise RuntimeError(
                _first_line(result.err or result.out) or "git remote set-head failed"
            )
        return git.default_branch(path)
    raise ValueError(f"unknown fix: {action}")
