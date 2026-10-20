"""The bell: what asks for your attention, kept until you have seen it.

A desktop notification or a message on a phone is said once and gone; a console
opened an hour later has no way to know that a session has been waiting for an
answer since lunch. So the moments worth a bell — a question, a pull request to
read, a red CI, a failure, a block — are also written down, in `ponos.db`, by the
run that lived them, and read back by the console like the rest of its data.

Rare on purpose: a ticket picked up or moved to progress is routine and never
lands here. The project is not kept: the console reads it off the board, which
it already holds. And **one unread notification per ticket and kind**: a ticket that
asks twice before you looked is still one question waiting, and a bell that
counted retries would be one nobody trusts.

Written by the runner, read by the console — two processes, one file — so every
function here fails quietly, as `state.written_up` does: a bell that cannot be
written is never a reason for a ticket to fail.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from . import blocks, db

# In the order of what needs you most. `question` is the one that matters: a
# session is stopped and only you can start it again.
KINDS = ("question", "review", "ci", "failed", "blocked")

# How long a notification you have read is kept.
KEEP_DAYS = 30

# How many the console is handed: the bell lists the latest, not the archive.
LISTED = 50


def kind_of(verdict: str, code: str = "") -> str:
    """The bell a moment of a ticket rings, or `""` for the routine ones.

    `verdict` is what `_tell` says (`review`, `blocked`, `failed`…) and `code`
    the cause of a stop, when there is one: a stop whose cause is a question, or
    that only an answer lifts, is a session waiting for you; a pull request whose
    checks are red is the CI's; any other block is only blocked.
    """
    if verdict == "review":
        return "review"
    if verdict == "failed":
        return "failed"
    if verdict != "blocked":
        return ""
    if code == "merge.checks-failed":
        return "ci"
    try:
        found = blocks.cause(code) if code else None
    except ValueError:
        found = None
    if found is None or found.family == "question" or found.action == "answer":
        return "question"
    return "blocked"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def add(kind: str, ticket: str, title: str) -> None:
    """Ring the bell for a ticket — unless it already rings for that kind."""
    if kind not in KINDS:
        return
    try:
        with db.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM notifications WHERE ticket = ? AND kind = ? AND read_at = ''",
                (ticket, kind),
            ).fetchone():
                return
            connection.execute(
                "INSERT INTO notifications (kind, ticket, title, at) VALUES (?, ?, ?, ?)",
                (kind, ticket, title, _now()),
            )
            _purge(connection)
    except db.ERRORS:
        pass


def _purge(connection: sqlite3.Connection) -> None:
    oldest = (datetime.now(UTC) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    connection.execute("DELETE FROM notifications WHERE read_at != '' AND read_at < ?", (oldest,))


def recent(limit: int = LISTED) -> dict[str, object]:
    """The latest notifications, newest first, and how many are unread in all."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT id, kind, ticket, title, at, read_at FROM notifications "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            unread = connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE read_at = ''"
            ).fetchone()[0]
    except db.ERRORS:
        return {"items": [], "unread": 0}
    return {
        "items": [
            {
                "id": row[0],
                "kind": row[1],
                "ticket": row[2],
                "title": row[3],
                "at": row[4],
                "read": bool(row[5]),
            }
            for row in rows
        ],
        "unread": int(unread),
    }


def read(identifier: int | None = None) -> None:
    """Mark one notification read — or, with no identifier, all of them."""
    try:
        with db.transaction() as connection:
            if identifier is None:
                connection.execute(
                    "UPDATE notifications SET read_at = ? WHERE read_at = ''", (_now(),)
                )
            else:
                connection.execute(
                    "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at = ''",
                    (_now(), identifier),
                )
            _purge(connection)
    except db.ERRORS:
        pass
