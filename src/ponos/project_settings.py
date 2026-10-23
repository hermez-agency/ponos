"""What a project decides for itself, over what `config.toml` decides for all.

The configuration is one file for every project, and some decisions are not
the same on every project: merging unread is a convenience on a project of
your own and a mistake on a client's. So a project may hold its own answer to
a setting, and the runner reads that one first — the project's when it has
one, the file's otherwise. A project that says nothing behaves exactly as it
did before there were project settings at all.

**Here, not on the board.** A setting of Ponos's is not something to add a
column to somebody's Notion database for, nor something a Markdown board should
have to carry in its front matter. It lives in `ponos.db`, beside what the
runner keeps about its own work — see migration 16 in db.py — and survives a
restart the way the history does.

**One switch says whether the project decides at all.** Owning a setting is a
decision of its own, apart from what the setting says: a project that has its
own automatic validation with every type off is a project that wants every
ticket read, whatever the file says tomorrow. So "its own" is the presence of
the entry, and the values inside it are taken as they are — never merged with
the file's, which would turn a switch left off into "whatever the file says".

**A database that cannot be read validates nothing.** Every other note the
runner keeps for itself falls back on "as if it were not there"; this one
cannot, because a project that asked to be read would then be merged on the
strength of the global switch. Not validating is the side a mistake can be
undone from: the ticket waits in review, as it would have without any setting.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from . import db
from .config import Config
from .kinds import KINDS

# The keys a project may hold: one JSON object, the settings beside each other.
VALIDATION = "validation"
# Whether ideas are found for it on a schedule, against what the file says for
# all — see idea_schedule.py. A boolean: absent, the file decides.
IDEAS = "ideas"


def key(project: str) -> str:
    """A project's page id as the table keys it: no dashes, lower case."""
    return project.replace("-", "").strip().lower()


def _read(project: str) -> dict:
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            "SELECT settings FROM project_settings WHERE project = ?", (key(project),)
        ).fetchone()
    if not row:
        return {}
    try:
        settings = json.loads(row[0] or "{}")
    except ValueError:
        return {}
    return settings if isinstance(settings, dict) else {}


def validation(project: str) -> dict[str, bool] | None:
    """The project's own automatic validation, type by type — or None, the file's.

    Raises `db.ERRORS` when the database cannot be read: the caller decides
    which side to fall on, and the runner falls on not validating.
    """
    if not key(project):
        return None
    own = _read(project).get(VALIDATION)
    if not isinstance(own, dict):
        return None
    return {kind: bool(own.get(kind, False)) for kind in KINDS}


def set_validation(project: str, name: str, values: dict[str, bool] | None) -> None:
    """Give a project its own automatic validation, or hand it back to the file (None)."""

    def change(settings: dict) -> None:
        if values is None:
            settings.pop(VALIDATION, None)
        else:
            settings[VALIDATION] = {kind: bool(values.get(kind, False)) for kind in KINDS}

    _write(project, name, change)


def ideas(project: str) -> bool | None:
    """Whether ideas are found for the project on a schedule, if it says — None, the file's word."""
    if not key(project):
        return None
    own = _read(project).get(IDEAS)
    return own if isinstance(own, bool) else None


def set_ideas(project: str, name: str, value: bool | None) -> None:
    """Say yes or no for the project, or hand the question back to the file (None)."""

    def change(settings: dict) -> None:
        if value is None:
            settings.pop(IDEAS, None)
        else:
            settings[IDEAS] = value

    _write(project, name, change)


def every_ideas() -> dict[str, bool]:
    """What each project that says its own word about ideas says, by project id."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute("SELECT project, settings FROM project_settings").fetchall()
    except db.ERRORS:
        return {}
    said: dict[str, bool] = {}
    for project, settings in rows:
        try:
            held = json.loads(settings or "{}")
        except ValueError:
            continue
        if isinstance(held, dict) and isinstance(held.get(IDEAS), bool):
            said[str(project)] = held[IDEAS]
    return said


def _write(project: str, name: str, change: Callable[[dict], None]) -> None:
    """Change one project's settings object, and drop the row when nothing is left in it."""
    if not key(project):
        raise ValueError("only a project with a page can have settings of its own")
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT settings FROM project_settings WHERE project = ?", (key(project),)
        ).fetchone()
        try:
            settings = json.loads(row[0]) if row else {}
        except ValueError:
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        change(settings)
        if settings:
            connection.execute(
                "INSERT INTO project_settings (project, name, settings) VALUES (?, ?, ?) "
                "ON CONFLICT (project) DO UPDATE SET name = excluded.name, settings = excluded.settings",
                (key(project), name, json.dumps(settings, sort_keys=True)),
            )
        else:
            connection.execute("DELETE FROM project_settings WHERE project = ?", (key(project),))


def owning_validation() -> list[dict[str, str]]:
    """The projects with their own automatic validation: their id and their name, as saved."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT project, name, settings FROM project_settings ORDER BY name COLLATE NOCASE"
            ).fetchall()
    except db.ERRORS:
        return []
    owning = []
    for project, name, settings in rows:
        try:
            held = json.loads(settings or "{}")
        except ValueError:
            continue
        if isinstance(held, dict) and isinstance(held.get(VALIDATION), dict):
            owning.append({"id": str(project), "name": str(name)})
    return owning


def forced_validation(config: Config, kind: str, project: str) -> str:
    """Whose decision it is to validate a ticket of that type on that project.

    "project" or "global" when it is validated without waiting for anybody —
    which of the two said so is what the ticket's report says — and "" when it
    waits for its review. The project's own switches when it has them, even
    against the file's, in either direction; the file's otherwise.
    """
    if not kind:
        return ""
    try:
        own = validation(project)
    except db.ERRORS:
        return ""
    if own is not None:
        return "project" if own.get(kind, False) else ""
    return "global" if config.runner.forces_validation(kind) else ""
