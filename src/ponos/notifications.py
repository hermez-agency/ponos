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

And **one line per ticket**: a ticket that asked four questions, each answered
in turn, read back as four lines would make the bell a log of the day rather
than a list of what waits. So the console is handed each ticket once, by what
it last rang for and how many times it rang so, and the count is of tickets
that wait — reading a line reads all its ticket rang.

And **a bell lets go of a ticket that moved on**: a question answered, a pull
request merged, a ticket the board now shows in another column asks for nothing
any more, and a count that kept it would be one nobody looks at. The console
settles them against every board it reads (`settle`), since it is the one that
holds the board — the runner rings, and a ticket moved by hand on the board moves
without it. A bell just rung is left alone for a moment: the board read beside
it may still be the one from before the move that rang it.

Written by the runner, read by the console — two processes, one file — so every
function here fails quietly, as `state.written_up` does: a bell that cannot be
written is never a reason for a ticket to fail.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

from . import blocks, db, timestamps

# In the order of what needs you most. `question` is the one that matters: a
# session is stopped and only you can start it again.
KINDS = ("question", "review", "ci", "failed", "blocked")

# The columns in which a ticket still needs what its bell rang for. Blocked and
# failed go together: a board that has one status for both draws one column.
STILL = {
    "question": ("blocked", "failed"),
    "review": ("review",),
    "ci": ("blocked", "failed"),
    "failed": ("failed", "blocked"),
    "blocked": ("blocked", "failed"),
}

# How long a bell is trusted over a board edited before it: longer than a read
# of the board may lag behind the move, shorter than anyone waits for the count.
SETTLING = timedelta(minutes=2)

# How long a notification you have read is kept.
KEEP_DAYS = 30

# How many tickets the console is handed: the bell lists the latest, not the archive
# — but never fewer than wait, which come first however old they are.
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
    if code in ("merge.checks-failed", "ci.rework-exhausted"):
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


def add(kind: str, ticket: str, title: str) -> bool:
    """Ring the bell for a ticket — unless it already rings for that kind.

    True when it rang anew: what a phone is told about (push.py), which a
    ticket already waiting unread for the same thing is not a second time.
    """
    if kind not in KINDS:
        return False
    try:
        with db.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM notifications WHERE ticket = ? AND kind = ? AND read_at = ''",
                (ticket, kind),
            ).fetchone():
                return False
            connection.execute(
                "INSERT INTO notifications (kind, ticket, title, at) VALUES (?, ?, ?, ?)",
                (kind, ticket, title, _now()),
            )
            _purge(connection)
    except db.ERRORS:
        return False
    return True


def settle(tickets: Iterable[Mapping[str, object]]) -> None:
    """Mark read what the board says no longer needs you.

    `tickets` are the board's, as `Api.board` gives them: a notification whose
    ticket is in a column `STILL` does not name for its kind is read — once the
    board was edited after it rang, or `SETTLING` has passed. A ticket the board
    does not hold is left as it is: a board read is not a deletion.
    """
    columns = {str(item.get("id", "")): item for item in tickets}
    if not columns:
        return
    now = datetime.now(UTC)
    try:
        with db.transaction() as connection:
            rows = connection.execute(
                "SELECT id, kind, ticket, at FROM notifications WHERE read_at = ''"
            ).fetchall()
            done = []
            for identifier, kind, ticket, at in rows:
                item = columns.get(ticket)
                if item is None or item.get("column") in STILL.get(kind, ()):
                    continue
                rung = timestamps.parse(at)
                edited = timestamps.parse(item.get("edited"))
                if rung is None or rung <= now - SETTLING or (edited and edited > rung):
                    done.append((_now(), identifier))
            if done:
                connection.executemany(
                    "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at = ''", done
                )
    except db.ERRORS:
        pass


def _purge(connection: sqlite3.Connection) -> None:
    oldest = (datetime.now(UTC) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    connection.execute("DELETE FROM notifications WHERE read_at != '' AND read_at < ?", (oldest,))


def recent(limit: int = LISTED) -> dict[str, object]:
    """One line per ticket, those that wait first, and how many tickets wait in all.

    A line is what its ticket rang for last, with `count` the times it rang for
    that kind; it is unread while anything its ticket rang for is. Every ticket
    the count counts is listed, `limit` or not: a badge saying five over a list
    showing two would ask you to find three lines it does not hand you. The read
    ones, latest first, fill what is left of `limit`.
    """
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT id, kind, ticket, title, at, read_at FROM notifications ORDER BY id DESC"
            ).fetchall()
    except db.ERRORS:
        return {"items": [], "unread": 0}
    latest: dict[str, tuple[int, str, str, str]] = {}
    counts: dict[str, int] = {}
    waiting: set[str] = set()
    for identifier, kind, ticket, title, at, read_at in rows:
        latest.setdefault(ticket, (identifier, kind, title, at))
        if kind == latest[ticket][1]:
            counts[ticket] = counts.get(ticket, 0) + 1
        if not read_at:
            waiting.add(ticket)
    lines = sorted(latest.items(), key=lambda line: line[0] not in waiting)
    return {
        "items": [
            {
                "id": identifier,
                "kind": kind,
                "ticket": ticket,
                "title": title,
                "at": at,
                "read": ticket not in waiting,
                "count": counts[ticket],
            }
            for ticket, (identifier, kind, title, at) in lines[: max(limit, len(waiting))]
        ],
        "unread": len(waiting),
    }


def read(identifier: int | None = None) -> None:
    """Mark read the ticket of one notification — or, with no identifier, all of them."""
    try:
        with db.transaction() as connection:
            if identifier is None:
                connection.execute(
                    "UPDATE notifications SET read_at = ? WHERE read_at = ''", (_now(),)
                )
            else:
                connection.execute(
                    "UPDATE notifications SET read_at = ? WHERE read_at = '' AND ticket = "
                    "(SELECT ticket FROM notifications WHERE id = ?)",
                    (_now(), identifier),
                )
            _purge(connection)
    except db.ERRORS:
        pass
