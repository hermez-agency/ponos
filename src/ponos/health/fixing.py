"""The fixes a check offers, made once confirmed.

Apart from the checks because a fix writes — to somebody's Notion, their clone,
their `config.toml` — where a check only reads: the one module of the package
that changes anything.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .. import config as config_module
from .. import disk, git, leftovers, projects, provision, store, subtypes
from .. import workspace as workspace_module
from .check import PROBE_TIMEOUT, _first_line
from .columns import _on_option, _stray_subtypes
from .installation import _spared
from .machine import CHECKOUTS
from .notion import _project_rows


@runtime_checkable
class _Shaped(Protocol):
    """A board whose databases can be read whole and given new properties: Notion's."""

    def database(self, database_id: str) -> dict[str, Any]: ...

    def add_properties(self, database_id: str, properties: dict[str, Any]) -> None: ...


def _shaped(client: store.Store) -> _Shaped:
    """The board a column or a status is added to: Notion, mirrored or not.

    A mirrored board reads its schema from Notion, so it is offered the same
    fixes as a Notion one — and makes them on its Notion side, the only one
    with a schema to change.
    """
    from ..sync import Mirror

    board: object = client.primary if isinstance(client, Mirror) else client
    if not isinstance(board, _Shaped):
        raise ValueError("this board has no properties to add")
    return board


def fix(
    config: config_module.Config,
    client: store.Store,
    action: str,
    target: str = "",
    *,
    confirmed: bool = False,
) -> str:
    """Make one of the fixes a check offered, and say what was done.

    Refuses without `confirmed`: a fix changes somebody's Notion or somebody's
    clone, and the console asks first, but this does not rely on it.
    """
    if not confirmed:
        raise PermissionError("a fix is made only once it is confirmed")
    if action in ("notion_columns", "notion_statuses"):
        space = workspace_module.resolve(client, config.notion)
        settings = config.notion
        board = _shaped(client)
        if action == "notion_columns":
            wanted = provision.tickets_schema(settings, space.projects, space.agents)
            absent = provision.missing_properties(client.schema(space.tickets), wanted)
            board.add_properties(space.tickets, absent)
            return "added " + ", ".join(sorted(absent)) if absent else "nothing to add"
        widened = provision.missing_options(
            board.database(space.tickets),
            settings.prop("status"),
            provision.status_options(settings),
        )
        board.add_properties(space.tickets, widened)
        return "statuses added" if widened else "nothing to add"
    if action == "notion_schedule_columns":
        space = workspace_module.resolve(client, config.notion)
        if not space.schedules:
            raise LookupError("this board has no schedules database")
        wanted = provision.schedules_schema(config.notion, space.tickets, space.projects)
        absent = provision.missing_properties(client.schema(space.schedules), wanted)
        if absent:
            _shaped(client).add_properties(space.schedules, absent)
        return "added " + ", ".join(sorted(absent)) if absent else "nothing to add"
    if action == "notion_subtypes":
        space = workspace_module.resolve(client, config.notion)
        column = config.notion.prop("subtype")
        moved, emptied = 0, []
        for name, key, _ in _stray_subtypes(client, space.tickets, column):
            if not key:
                continue
            for page in _on_option(client, space.tickets, column, name):
                client.update(space.tickets, page.id, {column: subtypes.option(key)})
                moved += 1
            # Asked again: a ticket somebody set to it meanwhile would lose its value.
            if not _on_option(client, space.tickets, column, name):
                emptied.append(name)
        done = f"{moved} ticket(s) rewritten"
        try:
            board = _shaped(client)
        except ValueError:
            # A Markdown board has no options: they were only the values just rewritten.
            return done
        prop = (board.database(space.tickets).get("properties") or {}).get(column) or {}
        current = (prop.get("select") or {}).get("options") or []
        kept = [
            {"name": option.get("name"), "color": option.get("color", "default")}
            for option in current
            if option.get("name") not in emptied
        ]
        if emptied and len(kept) < len(current):
            # Notion replaces the whole list on a PATCH: what is left out is removed.
            board.add_properties(space.tickets, {column: {"select": {"options": kept}}})
            done += ", removed " + ", ".join(f"“{name}”" for name in emptied)
        return done
    if action == "state_private":
        loose = disk.open_to_others(config_module.state_dir(), CHECKOUTS)
        tightened = sum(disk.tighten(path) for path in loose)
        return f"{tightened} entries tightened"
    if action == "notion_shared":
        # Nothing to ask the board: the column stays as it is, read by one setting.
        changed = config_module.edit(config.path, [("notion.properties", "role", "")])
        return "role turned off" if changed else "nothing to change"
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
        space = workspace_module.resolve(client, config.notion)
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
