"""The ticket as `ponos.db` keeps it: a row, its comments, and what Notion is yet to be told.

`ticket.py` is a Notion page read the way a run reads it; this is the ticket
itself, for the day the database is the source and the board only a mirror.
`ledger.py` reads and writes it for the runner, the console, the MCP and the
CLI, and `mirror.py` is what carries it to Notion and brings back the little
that still comes up.

**The two parts of the page are two columns.** `mission` is what you write and
`report` is what Ponos rewrites when it is done; they are not one Markdown
body cut at a heading, because the mirror writes the second without ever
having to read the first back, and the first is one of the few things that
still comes up from Notion.

**The id is the board's, dashes removed.** Every other table of this file names
a ticket that way (`runs.ticket`, `history.ticket`…); a new id of our own would
have meant translating at each join. A ticket born here, before any page
exists, draws a UUID of the same shape, and `notion` holds the page that
mirrors it once there is one — empty until then.

**Every change is also a row in `mirror_queue`.** Written in the same
transaction as the change, so a ticket changed while Notion is down is not
lost and a ticket that was not changed is not queued. The queue says *what*
changed (`created`, `status`, `fields`, `comment`…), not the new value: the
mirror reads the ticket when it sends, so five edits in a row are one write
to Notion with the last word.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import db
from .config import STATUS

STATUSES = tuple(STATUS.values())

# The columns `update` may set, and the kind each one holds. `id`, `notion` and
# the two dates are the table's own.
_TEXT = (
    "title",
    "project",
    "status",
    "kind",
    "subtype",
    "mission",
    "report",
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
)
_NUMBERS = ("priority", "cost", "duration")
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
    report: str = ""
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
    waiting: bool = False
    plan_first: bool = False
    notion: str = ""
    created_at: str = ""
    edited_at: str = ""
    notion_edited: str = ""
    after: list[str] = field(default_factory=list)


@dataclass
class Remark:
    """One comment on a ticket — the shape of `store.Comment`, with a row's id."""

    id: int
    ticket: str
    text: str
    at: str = ""
    author: str = ""
    discussion: str = ""


@dataclass
class Change:
    """One thing the mirror has still to tell Notion."""

    id: int
    ticket: str
    what: str
    payload: dict[str, Any]
    at: str
    tries: int = 0
    error: str = ""


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


def _queue(connection: sqlite3.Connection, ticket: str, what: str, **payload: Any) -> None:
    connection.execute(
        "INSERT INTO mirror_queue (ticket, what, payload, at) VALUES (?, ?, ?, ?)",
        (ticket, what, json.dumps(payload, sort_keys=True), _now()),
    )


def create(title: str, *, id: str = "", after: list[str] | None = None, **values: Any) -> Record:
    """Write a new ticket and queue its creation for the mirror.

    `id` is given when a page already exists (an import, a ticket made in
    Notion); without one the ticket is born here. Raises `ValueError` on a
    status or a column that does not exist, and on an id already taken.
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
        if not row.get("notion"):
            _queue(connection, ticket, "created")
    found = get(ticket)
    assert found is not None
    return found


def _check(values: dict[str, Any]) -> None:
    allowed = {
        *_TEXT,
        *_NUMBERS,
        *_FLAGS,
        "id",
        "notion",
        "created_at",
        "edited_at",
        "notion_edited",
    }
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"no such ticket column: {', '.join(unknown)}")
    if "status" in values and values["status"] not in STATUSES:
        raise ValueError(f"no such status: {values['status']!r}")


def get(ticket: str) -> Record | None:
    with db.transaction(immediate=False) as connection:
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (_key(ticket),)).fetchone()
        return _record(connection, row) if row else None


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


def update(ticket: str, *, mirrored: bool = False, **values: Any) -> Record | None:
    """Change columns of a ticket and queue the change; None when the ticket does not exist.

    A change that sets nothing new is not queued: the mirror has nothing to
    tell Notion. The kind of change the queue holds is `status` when the
    status is the only column that moved, `fields` otherwise.

    `mirrored` is for a change that came up from Notion: it is already there,
    and queuing it would send it back.
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
            if not mirrored:
                _queue(
                    connection,
                    ticket,
                    "status" if list(moved) == ["status"] else "fields",
                    fields=sorted(moved),
                )
    return get(ticket)


def delete(ticket: str) -> bool:
    ticket = _key(ticket)
    with db.transaction() as connection:
        row = connection.execute("SELECT notion FROM tickets WHERE id = ?", (ticket,)).fetchone()
        gone = connection.execute("DELETE FROM tickets WHERE id = ?", (ticket,)).rowcount > 0
        if gone:
            # The row is gone when the mirror looks, so the page to trash is
            # carried in the change itself.
            _queue(connection, ticket, "deleted", notion=row[0] if row else "")
    return gone


def comment(
    ticket: str, text: str, *, author: str = "", discussion: str = "", mirrored: bool = False
) -> Remark:
    """Add a comment to a ticket and queue it; raises `ValueError` on a ticket that is not here.

    `mirrored` is for a comment that came up from Notion: it is already there,
    and queuing it would send it back.
    """
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
        if not mirrored:
            _queue(connection, ticket, "comment", comment=number)
    return Remark(number, ticket, text, at, author, discussion)


def attach(ticket: str, *, notion: str | None = None, edited: str | None = None) -> None:
    """Note which page mirrors a ticket, and when Notion last edited it.

    Neither is a change of the ticket: nothing is queued and `edited_at` stays.
    """
    sets, args = [], []
    for column, value in (("notion", notion), ("notion_edited", edited)):
        if value is not None:
            sets.append(f"{column} = ?")
            args.append(_key(value) if column == "notion" else value)
    if not sets:
        return
    with db.transaction() as connection:
        connection.execute(
            f"UPDATE tickets SET {', '.join(sets)} WHERE id = ?", (*args, _key(ticket))
        )


def by_notion(page: str) -> Record | None:
    """The ticket that a Notion page mirrors, whichever id the ticket was born with."""
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            "SELECT * FROM tickets WHERE id = ? OR notion = ?", (_key(page), _key(page))
        ).fetchone()
        return _record(connection, row) if row else None


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


def pending(limit: int = 100) -> list[Change]:
    """What the mirror has still to tell Notion, oldest first."""
    with db.transaction(immediate=False) as connection:
        return [
            Change(row[0], row[1], row[2], json.loads(row[3]), row[4], row[5], row[6])
            for row in connection.execute(
                "SELECT id, ticket, what, payload, at, tries, error FROM mirror_queue "
                "ORDER BY id LIMIT ?",
                (limit,),
            )
        ]


def sent(change: int) -> None:
    """Notion took it: the change leaves the queue."""
    with db.transaction() as connection:
        connection.execute("DELETE FROM mirror_queue WHERE id = ?", (change,))


def failed(change: int, error: str) -> None:
    """Notion refused or did not answer: the change stays, with the count and the reason."""
    with db.transaction() as connection:
        connection.execute(
            "UPDATE mirror_queue SET tries = tries + 1, error = ? WHERE id = ?", (error, change)
        )
