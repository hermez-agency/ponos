"""The ticket as `ponos.db` keeps it: a row, and its comments.

`ticket.py` is a page read the way a run reads it; this is the ticket itself.
The runner, the console, the MCP and the CLI reach it through `ledger.py`, a
`store.Store` that serves the tickets from these tables.

**The three parts of a ticket are three columns.** `mission` is what you write,
`result` what the ticket delivers — the last version of `ticket_results`, see
results.py — and `journal` what Ponos rewrites at the end of every session;
they are not one Markdown body cut at headings, because each is rewritten
without ever having to read the others back.

**The id is a UUID, dashes removed.** Every other table of this file names a
ticket that way (`runs.ticket`, `history.ticket`…).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import db
from .config import STATUS

STATUSES = tuple(STATUS.values())

# The columns `update` may set, and the kind each one holds. `id` and the two
# dates are the table's own.
_TEXT = (
    "title",
    "project",
    "status",
    "kind",
    "subtype",
    "mission",
    "result",
    "journal",
    "pull_request",
    "session",
    "agent",
    "model",
    "progress",
    "block",
    "ci",
    "on_change",
    "due",
    "scheduled",
    "role",
    "goal",
    "twin",
)
_NUMBERS = ("priority", "cost", "duration", "attempts")
_FLAGS = ("waiting", "plan_first")


@dataclass
class Record:
    id: str
    title: str = ""
    project: str = ""
    status: str = "draft"
    priority: int = 50
    kind: str = ""
    subtype: str = ""
    mission: str = ""
    result: str = ""
    journal: str = ""
    pull_request: str = ""
    session: str = ""
    agent: str = ""
    model: str = ""
    progress: str = ""
    block: str = ""
    ci: str = ""
    on_change: str = ""
    cost: float = 0.0
    duration: float = 0.0
    due: str = ""
    scheduled: str = ""
    role: str = ""
    goal: str = ""
    waiting: bool = False
    plan_first: bool = False
    attempts: int = 1
    twin: str = ""
    created_at: str = ""
    edited_at: str = ""
    after: list[str] = field(default_factory=list)


@dataclass
class Version:
    """One version of a ticket's result — see results.py."""

    version: int
    text: str
    source: str = "session"
    author: str = ""
    note: str = ""
    at: str = ""


@dataclass
class Remark:
    """One comment on a ticket — the shape of `store.Comment`, with a row's id."""

    id: int
    ticket: str
    text: str
    at: str = ""
    author: str = ""
    discussion: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _key(ticket: str) -> str:
    return ticket.replace("-", "")


def _record(connection: sqlite3.Connection, row: sqlite3.Row | tuple[Any, ...]) -> Record:
    names = [
        column[0] for column in connection.execute("SELECT * FROM tickets LIMIT 0").description
    ]
    values = dict(zip(names, row, strict=True))
    values["waiting"] = bool(values["waiting"])
    values["plan_first"] = bool(values["plan_first"])
    record = Record(**values)
    record.after = [
        after
        for (after,) in connection.execute(
            "SELECT after FROM ticket_after WHERE ticket = ? ORDER BY after", (record.id,)
        )
    ]
    return record


def create(title: str, *, id: str = "", after: list[str] | None = None, **values: Any) -> Record:
    """Write a new ticket.

    `id` is given when the ticket already has one somewhere else; without one,
    a new one is drawn. Raises `ValueError` on a status or a column that does
    not exist, and on an id already taken.
    """
    ticket = _key(id) or uuid.uuid4().hex
    row = {"id": ticket, "title": title, **values}
    _check(row)
    now = _now()
    row.setdefault("created_at", now)
    row.setdefault("edited_at", now)
    for flag in _FLAGS:
        if flag in row:
            row[flag] = int(bool(row[flag]))
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with db.transaction() as connection:
        try:
            connection.execute(
                f"INSERT INTO tickets ({columns}) VALUES ({marks})", tuple(row.values())
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"ticket {ticket} already exists") from error
        for earlier in after or []:
            connection.execute(
                "INSERT OR IGNORE INTO ticket_after (ticket, after) VALUES (?, ?)",
                (ticket, _key(earlier)),
            )
    found = get(ticket)
    assert found is not None
    return found


def _check(values: dict[str, Any]) -> None:
    allowed = {*_TEXT, *_NUMBERS, *_FLAGS, "id", "created_at", "edited_at"}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"no such ticket column: {', '.join(unknown)}")
    if "status" in values and values["status"] not in STATUSES:
        raise ValueError(f"no such status: {values['status']!r}")


def get(ticket: str) -> Record | None:
    with db.transaction(immediate=False) as connection:
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (_key(ticket),)).fetchone()
        return _record(connection, row) if row else None


def of_page(page: str) -> Record | None:
    """The ticket a page id names, or None for a page that is not a ticket."""
    return get(page)


def listing(*, status: str = "", project: str = "") -> list[Record]:
    """The tickets in a status and/or a project: highest priority first, oldest first among equals."""
    where, args = [], []
    if status:
        where.append("status = ?")
        args.append(status)
    if project:
        where.append("project = ?")
        args.append(_key(project))
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            f"SELECT * FROM tickets{clause} ORDER BY priority DESC, created_at, id", args
        ).fetchall()
        return [_record(connection, row) for row in rows]


def update(ticket: str, **values: Any) -> Record | None:
    """Change columns of a ticket; None when the ticket does not exist.

    A change that sets nothing new leaves `edited_at` as it was.
    """
    ticket = _key(ticket)
    after = values.pop("after", None)
    _check(values)
    for flag in _FLAGS:
        if flag in values:
            values[flag] = int(bool(values[flag]))
    with db.transaction() as connection:
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket,)).fetchone()
        if row is None:
            return None
        before = _record(connection, row)
        moved = {
            name: value
            for name, value in values.items()
            if getattr(before, name) != (bool(value) if name in _FLAGS else value)
        }
        if after is not None:
            wanted = sorted({_key(item) for item in after})
            if wanted != before.after:
                connection.execute("DELETE FROM ticket_after WHERE ticket = ?", (ticket,))
                connection.executemany(
                    "INSERT INTO ticket_after (ticket, after) VALUES (?, ?)",
                    [(ticket, item) for item in wanted],
                )
                moved["after"] = wanted
        if moved:
            sets = ", ".join(f"{name} = ?" for name in moved if name != "after")
            if sets:
                connection.execute(
                    f"UPDATE tickets SET {sets}, edited_at = ? WHERE id = ?",
                    (*[v for n, v in moved.items() if n != "after"], _now(), ticket),
                )
            else:
                connection.execute(
                    "UPDATE tickets SET edited_at = ? WHERE id = ?", (_now(), ticket)
                )
    return get(ticket)


def delete(ticket: str) -> bool:
    ticket = _key(ticket)
    with db.transaction() as connection:
        connection.execute("DELETE FROM ticket_results WHERE ticket = ?", (ticket,))
        return connection.execute("DELETE FROM tickets WHERE id = ?", (ticket,)).rowcount > 0


def comment(ticket: str, text: str, *, author: str = "", discussion: str = "") -> Remark:
    """Add a comment to a ticket; raises `ValueError` on a ticket that is not here."""
    ticket = _key(ticket)
    at = _now()
    with db.transaction() as connection:
        if not connection.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket,)).fetchone():
            raise ValueError(f"no such ticket: {ticket}")
        number = connection.execute(
            "INSERT INTO ticket_comments (ticket, discussion, author, text, at) VALUES (?, ?, ?, ?, ?)",
            (ticket, discussion, author, text, at),
        ).lastrowid
        assert number is not None
    return Remark(number, ticket, text, at, author, discussion)


def comments(ticket: str) -> list[Remark]:
    with db.transaction(immediate=False) as connection:
        return [
            Remark(*row)
            for row in connection.execute(
                "SELECT id, ticket, text, at, author, discussion FROM ticket_comments "
                "WHERE ticket = ? ORDER BY id",
                (_key(ticket),),
            )
        ]


def set_result(
    ticket: str, text: str, *, source: str = "session", author: str = "", note: str = ""
) -> Version | None:
    """Keep a new version of a ticket's result, and make it the ticket's.

    Never overwrites: the earlier versions stay in `ticket_results`. A text
    the same as the last version is not kept twice — None then, and None for
    a ticket that is not here.
    """
    ticket = _key(ticket)
    text = text.strip()
    with db.transaction() as connection:
        row = connection.execute("SELECT result FROM tickets WHERE id = ?", (ticket,)).fetchone()
        if row is None:
            return None
        last = connection.execute(
            "SELECT MAX(version) FROM ticket_results WHERE ticket = ?", (ticket,)
        ).fetchone()[0]
        if row[0] == text and (last or not text):
            return None
        version = int(last or 0) + 1
        at = _now()
        connection.execute(
            "INSERT INTO ticket_results (ticket, version, text, source, author, note, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticket, version, text, source, author, note, at),
        )
        connection.execute(
            "UPDATE tickets SET result = ?, edited_at = ? WHERE id = ?", (text, at, ticket)
        )
    return Version(version, text, source, author, note, at)


def results(ticket: str) -> list[Version]:
    """Every version of a ticket's result, the newest first."""
    with db.transaction(immediate=False) as connection:
        return [
            Version(*row)
            for row in connection.execute(
                "SELECT version, text, source, author, note, at FROM ticket_results "
                "WHERE ticket = ? ORDER BY version DESC",
                (_key(ticket),),
            )
        ]
