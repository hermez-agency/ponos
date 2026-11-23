"""A whole Ponos in one archive, and the same archive read back into another.

The copies `db.py` takes before a migration are the file itself, for this
machine and this version; an export is what a person carries to another
machine, a reinstallation, a drawer — so it is not the file. It is one zip:
a `manifest.json` that says what it holds, and one JSON file per category, each
a list of rows per table, under the columns' own names.

**By category, not by table.** A person picks "the tickets" or "the
conversations", not `ticket_results`; so each category names the tables that
make it up, and what it leaves out — the runs and their steps, the worktrees,
the logs, the caches, the library's files — is left out of every one. The
conversations are the one category not ticked by default: what was said to the
assistant is more private than the rest.

**Never a secret, and no case to tick for one.** The vault (`vault.db`) is not
read for its values at all, and `config.toml` is exported less the keys
`config.SECRETS` names. What is exported instead are the *names* — the entries
of the vault, Ponos's own secrets, the projects' grants — so that whoever
imports knows what to type again. Every string of the archive also goes
through `vault.masked` with Ponos's own secrets remembered, should one have
found its way into a ticket's text.

**An import never starts anything.** A ticket arrives in its status, except
the three the runner acts on by itself — ready, in progress, validated — which
arrive as drafts; its date and its « On » are kept, but the « On » starts from
the status it arrives in (`watched`), so nothing runs for the move; a
recurrence arrives switched off. Turning things back on is a person's gesture.

**Merge by default.** A row whose identifier is already there is left as it
is: an identical one is ignored, a different one is a conflict, listed by its
title. Page and ticket identifiers are kept as they are — they are what the
relations (ticket → project, goal, role; recurrence → project, goal) are made
of — and the rows numbered by SQLite (memories, skills, ideas, comments…) are
given new numbers, their own children following them. Replacing empties the
chosen categories first, which is why it asks for a confirmation and copies
`ponos.db` beside itself before it begins.

**The preview is the import, rolled back.** The same pass runs in a
transaction that is cancelled at the end, so what the preview says it would do
is what the import does — the configuration excepted, which is compared rather
than written.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__, db, disk, projectless, public_ids, schema, vault
from . import config as config_module

# What `manifest.json` says it is, and the format it is written in. A format is
# raised the day a category changes shape in a way an older reader would get
# wrong; a newer archive is refused, an older one read as far as it goes.
KIND = "ponos-export"
FORMAT = 1
OLDEST = 1

# The categories, in the order they are shown and imported — a project before
# the tickets that point at it — and whether each is ticked by default.
CATEGORIES: tuple[tuple[str, bool], ...] = (
    ("settings", True),
    ("projects", True),
    ("context", True),
    ("memories", True),
    ("goals", True),
    ("schedules", True),
    ("ideas", True),
    ("skills", True),
    ("tickets", True),
    ("conversations", False),
)
KEYS = tuple(key for key, _ in CATEGORIES)
DEFAULTS = tuple(key for key, ticked in CATEGORIES if ticked)

MERGE = "merge"
REPLACE = "replace"

# The statuses the runner acts on by itself, and what they arrive as.
HELD = {"ready": "draft", "progress": "draft", "validated": "draft"}

# What an archive may weigh, read whole and once unpacked: an export of years
# of tickets is a few megabytes, and a zip that unpacks to more is not ours.
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024

# The board's collections each page category holds.
_PAGES = {
    "projects": ("projects",),
    "context": ("context", "agents"),
    "goals": ("goals",),
    "schedules": ("schedules",),
}

# A column of bytes, written in JSON.
_BYTES = "$base64"


class TransferError(ValueError):
    """An archive that cannot be read, or an import that cannot be made."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def filename(moment: datetime | None = None) -> str:
    return f"ponos-export-{(moment or datetime.now(UTC)).strftime('%Y-%m-%d-%H%M')}.zip"


def chosen(categories: Iterable[str] | None) -> list[str]:
    """The categories asked for, in their own order; the defaults for none. Raises on an unknown one."""
    if categories is None:
        return list(DEFAULTS)
    asked = {str(key).strip() for key in categories if str(key).strip()}
    unknown = sorted(asked - set(KEYS))
    if unknown:
        raise TransferError(f"no such category: {', '.join(unknown)} — known: {', '.join(KEYS)}")
    return [key for key in KEYS if key in asked]


# -- rows ------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, memoryview)):
        return {_BYTES: base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _stored(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {_BYTES}:
        return base64.b64decode(str(value[_BYTES]))
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _rows(
    connection: sqlite3.Connection, sql: str, args: Iterable[Any] = ()
) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, tuple(args))
    names = [column[0] for column in cursor.description]
    return [
        {name: _jsonable(value) for name, value in zip(names, row, strict=True)} for row in cursor
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]


def _insert(
    connection: sqlite3.Connection, table: str, row: dict[str, Any], *, without: Iterable[str] = ()
) -> int:
    """Write one row, of the columns this schema has, and return its rowid.

    A column the archive has and this table does not — an archive from a
    newer Ponos of the same format — is dropped; one it lacks takes its default.
    """
    left_out = set(without)
    known = _columns(connection, table)
    names = [name for name in known if name in row and name not in left_out]
    if not names:
        raise TransferError(f"a row of {table} holds none of its columns")
    cursor = connection.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        [_stored(row[name]) for name in names],
    )
    return int(cursor.lastrowid or 0)


def _same(existing: dict[str, Any], row: dict[str, Any], columns: Iterable[str]) -> bool:
    return all(existing.get(name) == row.get(name) for name in columns if name in row)


def _one(
    connection: sqlite3.Connection, table: str, where: str, args: Iterable[Any]
) -> dict[str, Any] | None:
    found = _rows(connection, f"SELECT * FROM {table} WHERE {where}", args)
    return found[0] if found else None


# -- export ----------------------------------------------------------------------


def _pages(connection: sqlite3.Connection, collections: tuple[str, ...]) -> dict[str, Any]:
    marks = ", ".join("?" for _ in collections)
    pages = _rows(
        connection,
        f"SELECT * FROM board_pages WHERE collection IN ({marks}) AND trashed = 0 ORDER BY created, id",
        collections,
    )
    comments = _rows(
        connection,
        "SELECT * FROM board_comments WHERE page IN (SELECT id FROM board_pages"
        f" WHERE collection IN ({marks}) AND trashed = 0) ORDER BY at, id",
        collections,
    )
    return {"board_pages": pages, "board_comments": comments}


def _read_settings() -> dict[str, Any]:
    path = config_module.config_path()
    return {"config": schema.without_secrets(config_module.read_raw(path))}


def _gather(connection: sqlite3.Connection, category: str) -> dict[str, Any]:
    if category == "settings":
        return _read_settings()
    if category in _PAGES:
        found = _pages(connection, _PAGES[category])
        if category == "projects":
            found["project_settings"] = _rows(
                connection, "SELECT * FROM project_settings ORDER BY project"
            )
        return found
    if category == "memories":
        return {
            "memories": _rows(connection, "SELECT * FROM memories ORDER BY id"),
            "memory_options": _rows(connection, "SELECT * FROM memory_options ORDER BY name"),
        }
    if category == "ideas":
        return {
            "idea_batches": _rows(connection, "SELECT * FROM idea_batches ORDER BY id"),
            "ideas": _rows(connection, "SELECT * FROM ideas ORDER BY id"),
        }
    if category == "skills":
        return {
            "skills": _rows(connection, "SELECT * FROM skills ORDER BY id"),
            "skill_files": _rows(connection, "SELECT * FROM skill_files ORDER BY skill, path"),
        }
    if category == "tickets":
        return {
            "tickets": _rows(connection, "SELECT * FROM tickets ORDER BY created_at, id"),
            "ticket_after": _rows(connection, "SELECT * FROM ticket_after ORDER BY ticket, after"),
            "ticket_comments": _rows(connection, "SELECT * FROM ticket_comments ORDER BY id"),
            "ticket_results": _rows(connection, "SELECT * FROM ticket_results ORDER BY id"),
            "audit": _rows(connection, "SELECT * FROM audit ORDER BY id"),
            "history": _rows(connection, "SELECT * FROM history ORDER BY id"),
        }
    if category == "conversations":
        return {"chats": _rows(connection, "SELECT * FROM chats ORDER BY created, id")}
    raise TransferError(f"no such category: {category}")


# What each category counts as one item of it, in the manifest and the preview.
_COUNTED = {
    "projects": "board_pages",
    "context": "board_pages",
    "goals": "board_pages",
    "schedules": "board_pages",
    "memories": "memories",
    "ideas": "ideas",
    "skills": "skills",
    "tickets": "tickets",
    "conversations": "chats",
}


def count(category: str, data: dict[str, Any]) -> int:
    if category == "settings":
        return len(_leaves(data.get("config") or {}))
    rows = data.get(_COUNTED[category])
    return len(rows) if isinstance(rows, list) else 0


def secrets() -> dict[str, list[Any]]:
    """What has to be typed again after an import: names, never a value."""
    from . import vault_store

    try:
        entries = [
            {
                "name": entry["name"],
                "kind": entry["kind"],
                "variables": entry["variables"],
                "projects": entry["projects"],
            }
            for entry in vault_store.listing()
        ]
        own = vault_store.own_names()
    except (vault.VaultError, sqlite3.Error, OSError):
        entries, own = [], []
    kept = set(own)
    expected = [
        {"setting": f"{table}.{key}", "name": name}
        for (table, key), name in config_module.SECRETS.items()
        if name in kept or os.environ.get(name, "").strip()
    ]
    return {"vault": entries, "own": sorted(kept), "config": expected}


def _remember_secrets() -> None:
    """Mask Ponos's own secrets, and those of the environment, in what is written."""
    for value in config_module.kept_secrets().values():
        vault.remember(value)
    for name in config_module.SECRETS.values():
        vault.remember(os.environ.get(name, "").strip())


def export(categories: Iterable[str] | None = None) -> tuple[str, bytes, dict[str, Any]]:
    """(file name, the archive, its manifest) for these categories — the defaults for None."""
    keys = chosen(categories)
    _remember_secrets()
    data: dict[str, dict[str, Any]] = {}
    with db.transaction(immediate=False) as connection:
        for key in keys:
            data[key] = vault.masked(_gather(connection, key))
    manifest = {
        "kind": KIND,
        "format": FORMAT,
        "ponos": __version__,
        "created": now(),
        "categories": keys,
        "counts": {key: count(key, data[key]) for key in keys},
        "secrets": vault.masked(secrets()),
        "excluded": ["vault", "secrets", "runs", "logs", "worktrees", "caches", "library files"],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for key in keys:
            archive.writestr(f"{key}.json", json.dumps(data[key], ensure_ascii=False))
    return filename(), buffer.getvalue(), manifest


# -- reading an archive ------------------------------------------------------------


@dataclass
class Archive:
    manifest: dict[str, Any]
    data: dict[str, dict[str, Any]]

    @property
    def categories(self) -> list[str]:
        return [key for key in KEYS if key in self.data]


def _member(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        raw = archive.read(name)
    except KeyError:
        raise TransferError(f"the archive has no {name}") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TransferError(f"{name} in the archive is not JSON: {error}") from None


def read(blob: bytes) -> Archive:
    """The archive's manifest and categories, checked — or a TransferError that says why not."""
    if len(blob) > MAX_ARCHIVE:
        raise TransferError(f"the archive is larger than {MAX_ARCHIVE // (1024 * 1024)} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise TransferError("this file is not a Ponos export: it is not a zip archive") from None
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED:
            raise TransferError("the archive unpacks to more than Ponos reads")
        if "manifest.json" not in archive.namelist():
            raise TransferError("this file is not a Ponos export: it has no manifest.json")
        manifest = _member(archive, "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("kind") != KIND:
            raise TransferError("this file is not a Ponos export: its manifest says otherwise")
        version = manifest.get("format")
        if not isinstance(version, int):
            raise TransferError("the export's manifest says no format version")
        if version > FORMAT:
            raise TransferError(
                f"this export is in format {version}, written by Ponos {manifest.get('ponos', '?')}; "
                f"this Ponos ({__version__}) reads up to format {FORMAT} — update it, then import again"
            )
        if version < OLDEST:
            raise TransferError(
                f"this export is in format {version}, which this Ponos no longer reads "
                f"(format {OLDEST} at the oldest) — export it again from a recent Ponos"
            )
        listed = manifest.get("categories")
        if not isinstance(listed, list):
            raise TransferError("the export's manifest lists no categories")
        data: dict[str, dict[str, Any]] = {}
        for key in KEYS:
            if key not in listed:
                continue
            content = _member(archive, f"{key}.json")
            if not isinstance(content, dict):
                raise TransferError(f"{key}.json in the archive is not an object")
            data[key] = content
    return Archive(manifest, data)


# -- import ----------------------------------------------------------------------


@dataclass
class Outcome:
    """What one category came to."""

    key: str
    count: int = 0
    imported: int = 0
    ignored: int = 0
    conflicts: list[str] = field(default_factory=list)

    def shown(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "count": self.count,
            "imported": self.imported,
            "ignored": self.ignored,
            "conflicts": self.conflicts,
        }


class _Rollback(Exception):
    """Raised at the end of a preview, to cancel what it wrote."""


def _list(data: dict[str, Any], table: str) -> list[dict[str, Any]]:
    rows = data.get(table) or []
    if not isinstance(rows, list):
        raise TransferError(f"{table} in the archive is not a list")
    return [row for row in rows if isinstance(row, dict)]


def _empty(connection: sqlite3.Connection, category: str) -> None:
    """What `replace` removes of a category before it writes the archive's."""
    if category in _PAGES:
        collections = _PAGES[category]
        marks = ", ".join("?" for _ in collections)
        connection.execute(
            f"DELETE FROM board_comments WHERE page IN (SELECT id FROM board_pages"
            f" WHERE collection IN ({marks}))",
            collections,
        )
        connection.execute(f"DELETE FROM board_pages WHERE collection IN ({marks})", collections)
        if category == "projects":
            connection.execute("DELETE FROM project_settings")
        return
    tables = {
        "memories": ("memories", "memory_options"),
        "ideas": ("ideas", "idea_batches"),
        "skills": ("skill_files", "skills"),
        "tickets": (
            "ticket_after",
            "ticket_comments",
            "ticket_results",
            "audit",
            "history",
            "tickets",
        ),
        "conversations": ("chats",),
    }[category]
    for table in tables:
        connection.execute(f"DELETE FROM {table}")


def _page_title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("id") or "")


def _switched_off(row: dict[str, Any]) -> dict[str, Any]:
    """A page as it is written: a recurrence arrives inactive, to be switched on by hand."""
    if row.get("collection") != "schedules":
        return row
    try:
        properties = json.loads(str(row.get("properties") or "{}"))
    except json.JSONDecodeError:
        properties = {}
    if not isinstance(properties, dict):
        properties = {}
    properties[config_module.PROPERTIES["active"]] = False
    return {**row, "properties": json.dumps(properties, ensure_ascii=False)}


def _import_pages(
    connection: sqlite3.Connection, category: str, data: dict[str, Any], done: Outcome
) -> None:
    for row in _list(data, "board_pages"):
        if row.get("collection") not in _PAGES[category]:
            continue
        existing = _one(connection, "board_pages", "id = ?", (row.get("id"),))
        if existing is None:
            _insert(connection, "board_pages", _switched_off(row))
            done.imported += 1
        elif any(
            _same(existing, written, ("collection", "title", "properties", "body"))
            for written in (row, _switched_off(row))
        ):
            done.ignored += 1
        elif row.get("collection") == "context" and not str(existing.get("body") or "").strip():
            connection.execute(
                "UPDATE board_pages SET body = ?, edited = ? WHERE id = ?",
                (row.get("body") or "", now(), row.get("id")),
            )
            done.imported += 1
        else:
            done.conflicts.append(_page_title(row))
    for row in _list(data, "board_comments"):
        if (
            connection.execute(
                "SELECT 1 FROM board_pages WHERE id = ?", (row.get("page"),)
            ).fetchone()
            and not connection.execute(
                "SELECT 1 FROM board_comments WHERE id = ?", (row.get("id"),)
            ).fetchone()
        ):
            _insert(connection, "board_comments", row)
    if category == "projects":
        for row in _list(data, "project_settings"):
            existing = _one(connection, "project_settings", "project = ?", (row.get("project"),))
            if existing is None:
                _insert(connection, "project_settings", row)
            elif not _same(existing, row, ("settings",)):
                done.conflicts.append(f"{row.get('name') or row.get('project')} (settings)")


def _import_memories(connection: sqlite3.Connection, data: dict[str, Any], done: Outcome) -> None:
    for row in _list(data, "memories"):
        existing = _one(
            connection, "memories", "scope = ? AND mark = ?", (row.get("scope"), row.get("mark"))
        )
        if existing is None:
            _insert(connection, "memories", row, without=("id",))
            done.imported += 1
        elif _same(existing, row, ("text", "kind", "status")):
            done.ignored += 1
        else:
            done.conflicts.append(str(row.get("text") or "")[:80])
    for row in _list(data, "memory_options"):
        existing = _one(connection, "memory_options", "name = ?", (row.get("name"),))
        if existing is None:
            _insert(connection, "memory_options", row)
        elif not _same(existing, row, ("value",)):
            done.conflicts.append(f"option {row.get('name')}")


def _import_ideas(connection: sqlite3.Connection, data: dict[str, Any], done: Outcome) -> None:
    batches = {row.get("id"): row for row in _list(data, "idea_batches")}
    numbered: dict[Any, int] = {}

    def batch_of(old: Any) -> int | None:
        if old is None or old not in batches:
            return None
        if old not in numbered:
            row = batches[old]
            found = connection.execute(
                "SELECT id FROM idea_batches WHERE created_at = ? AND scope = ? AND project = ?",
                (row.get("created_at"), row.get("scope"), row.get("project")),
            ).fetchone()
            numbered[old] = (
                int(found[0])
                if found
                else _insert(connection, "idea_batches", row, without=("id",))
            )
        return numbered[old]

    for row in _list(data, "ideas"):
        if connection.execute(
            "SELECT 1 FROM ideas WHERE scope = ? AND project = ? AND title = ? AND created_at = ?",
            (row.get("scope"), row.get("project"), row.get("title"), row.get("created_at")),
        ).fetchone():
            done.ignored += 1
            continue
        _insert(connection, "ideas", {**row, "batch": batch_of(row.get("batch"))}, without=("id",))
        done.imported += 1


def _import_skills(connection: sqlite3.Connection, data: dict[str, Any], done: Outcome) -> None:
    files: dict[Any, list[dict[str, Any]]] = {}
    for row in _list(data, "skill_files"):
        files.setdefault(row.get("skill"), []).append(row)
    for row in _list(data, "skills"):
        existing = _one(connection, "skills", "name = ?", (row.get("name"),))
        if existing is not None:
            if _same(existing, row, ("description", "scope")):
                done.ignored += 1
            else:
                done.conflicts.append(str(row.get("name") or ""))
            continue
        number = _insert(connection, "skills", row, without=("id",))
        for kept in files.get(row.get("id"), []):
            _insert(connection, "skill_files", {**kept, "skill": number})
        done.imported += 1


def _import_tickets(connection: sqlite3.Connection, data: dict[str, Any], done: Outcome) -> None:
    taken: set[str] = set()
    for row in _list(data, "tickets"):
        identifier = str(row.get("id") or "")
        existing = _one(connection, "tickets", "id = ?", (identifier,))
        if existing is not None:
            if _same(existing, row, ("title", "mission", "result", "journal")):
                done.ignored += 1
            else:
                done.conflicts.append(str(row.get("title") or identifier))
            continue
        status = str(row.get("status") or "draft")
        held = HELD.get(status, status)
        # Numbered here, whatever the archive says: its `PON-12` may be this
        # board's `PON-12` already — see public_ids.py.
        prefix, number = public_ids.take(connection, str(row.get("project") or projectless.ID))
        _insert(
            connection,
            "tickets",
            {
                **row,
                "status": held,
                "progress": "",
                "waiting": 0,
                "prefix": prefix,
                "number": number,
            },
        )
        # The « On » starts from the status the ticket arrives in: the import
        # is not a change of status — see transitions.py.
        connection.execute(
            "INSERT OR REPLACE INTO watched (ticket, status, depth, at) VALUES (?, ?, 0, ?)",
            (identifier, held, now()),
        )
        taken.add(identifier)
        done.imported += 1
    for row in _list(data, "ticket_after"):
        if row.get("ticket") in taken:
            connection.execute(
                "INSERT OR IGNORE INTO ticket_after (ticket, after) VALUES (?, ?)",
                (row.get("ticket"), row.get("after")),
            )
    for table in ("ticket_comments", "ticket_results", "audit", "history"):
        for row in _list(data, table):
            if row.get("ticket") in taken:
                _insert(connection, table, row, without=("id",))


def _import_conversations(
    connection: sqlite3.Connection, data: dict[str, Any], done: Outcome
) -> None:
    for row in _list(data, "chats"):
        existing = _one(connection, "chats", "id = ?", (row.get("id"),))
        if existing is None:
            _insert(connection, "chats", row)
            done.imported += 1
        elif _same(existing, row, ("messages",)):
            done.ignored += 1
        else:
            done.conflicts.append(str(row.get("title") or row.get("id") or ""))


def _import(
    connection: sqlite3.Connection, category: str, data: dict[str, Any], done: Outcome
) -> None:
    if category in _PAGES:
        _import_pages(connection, category, data, done)
    elif category == "memories":
        _import_memories(connection, data, done)
    elif category == "ideas":
        _import_ideas(connection, data, done)
    elif category == "skills":
        _import_skills(connection, data, done)
    elif category == "tickets":
        _import_tickets(connection, data, done)
    elif category == "conversations":
        _import_conversations(connection, data, done)


# -- the configuration -------------------------------------------------------------


def _leaves(raw: dict[str, Any], table: str = "") -> list[tuple[str, str, Any]]:
    """(table, key, value) for every value of a parsed TOML file; tables followed, dots joined."""
    found: list[tuple[str, str, Any]] = []
    for key, value in raw.items():
        if isinstance(value, dict):
            found += _leaves(value, f"{table}.{key}" if table else str(key))
        elif table:
            found.append((table, str(key), value))
    return found


def _settings_changes(
    data: dict[str, Any], mode: str, done: Outcome
) -> list[tuple[str, str, object]]:
    """The edits `config.edit` is to make, and the conflicts the merge leaves alone."""
    wanted = data.get("config") or {}
    if not isinstance(wanted, dict):
        raise TransferError("settings.json in the archive holds no configuration")
    current = schema.without_secrets(config_module.read_raw(config_module.config_path()))
    have = {(table, key): value for table, key, value in _leaves(current)}
    changes: list[tuple[str, str, object]] = []
    secret = set(config_module.SECRETS)
    given = _leaves(wanted)
    for table, key, value in given:
        if (table, key) in secret:
            continue
        if (table, key) not in have:
            changes.append((table, key, value))
            done.imported += 1
        elif have[(table, key)] == value:
            done.ignored += 1
        elif mode == REPLACE:
            changes.append((table, key, value))
            done.imported += 1
        else:
            done.conflicts.append(f"{table}.{key}")
    if mode == REPLACE:
        named = {(table, key) for table, key, _ in given}
        changes += [(table, key, None) for table, key in have if (table, key) not in named]
    return changes


def _apply_settings(changes: list[tuple[str, str, object]]) -> None:
    if not changes:
        return
    path = config_module.config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        disk.write_private(path, "")
    config_module.edit(path, changes)


# -- the whole import ----------------------------------------------------------------


def backup() -> Path:
    """A copy of `ponos.db` as it is now, beside it — what `replace` takes before it starts."""
    location = db.path()
    copy = location.with_name(
        f"{location.name}.before-import-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.bak"
    )
    writing = copy.with_name(f"{copy.name}.{os.getpid()}")
    connection = db.connect()
    try:
        os.close(os.open(writing, os.O_CREAT | os.O_RDWR | os.O_TRUNC, 0o600))
        target = sqlite3.connect(writing)
        try:
            connection.backup(target)
        finally:
            target.close()
        os.replace(writing, copy)
    except (OSError, sqlite3.Error) as error:
        writing.unlink(missing_ok=True)
        raise TransferError(f"cannot copy {location} before replacing: {error}") from error
    return copy


def run(
    archive: Archive,
    categories: Iterable[str] | None = None,
    *,
    mode: str = MERGE,
    apply: bool = False,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Import (or, without `apply`, preview) the chosen categories of an archive.

    `categories` None is every category the archive holds. Replacing is only
    applied when `confirmed`, and copies `ponos.db` first.
    """
    if mode not in (MERGE, REPLACE):
        raise TransferError(f"no such mode: {mode} — {MERGE} or {REPLACE}")
    present = archive.categories
    keys = present if categories is None else [key for key in chosen(categories) if key in present]
    if apply and mode == REPLACE and not confirmed:
        raise TransferError("replacing what is here asks for an explicit confirmation")
    copy = backup() if apply and mode == REPLACE else None
    outcomes = {key: Outcome(key, count(key, archive.data[key])) for key in present}
    settings_changes: list[tuple[str, str, object]] = []
    try:
        with db.transaction() as connection:
            for key in keys:
                done = outcomes[key]
                if key == "settings":
                    settings_changes = _settings_changes(archive.data[key], mode, done)
                    continue
                if mode == REPLACE:
                    _empty(connection, key)
                _import(connection, key, archive.data[key], done)
            if not apply:
                raise _Rollback
    except _Rollback:
        pass
    except sqlite3.Error as error:
        raise TransferError(f"the import was cancelled, nothing was written: {error}") from error
    if apply:
        try:
            _apply_settings(settings_changes)
        except (config_module.ConfigError, OSError) as error:
            outcomes["settings"].conflicts.append(f"refused: {error}")
            outcomes["settings"].imported = 0
    manifest = archive.manifest
    return {
        "applied": apply,
        "mode": mode,
        "format": manifest.get("format"),
        "ponos": str(manifest.get("ponos") or ""),
        "created": str(manifest.get("created") or ""),
        "available": present,
        "chosen": keys,
        "categories": [outcomes[key].shown() for key in present],
        "backup": str(copy) if copy else "",
        "secrets": _secrets_of(manifest),
    }


def _secrets_of(manifest: dict[str, Any]) -> dict[str, list[Any]]:
    said = manifest.get("secrets")
    said = said if isinstance(said, dict) else {}
    return {
        name: list(said.get(name) or []) if isinstance(said.get(name), list) else []
        for name in ("vault", "own", "config")
    }
