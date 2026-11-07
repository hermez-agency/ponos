"""What the board's writes left behind: the journal of `ponos.db`, and a page's fingerprint.

The console and the runner write a ticket and can be refused (a status moved
by somebody else meanwhile), see a card drift from what they held, or fail to
send a change: each is one line in `sync_journal`, which the board reads back
to say which cards hold a refusal nobody has answered yet. The table kept the
name it had before; the lines are the console's and the runner's alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db
from .store import Page


@dataclass
class Entry:
    """One thing the console or the runner wrote down, or refused to do.

    `what` is one of `seen`, `drift`, `console→board`, `write-failed`, or
    `conflict` when a status was not written over somebody else's.
    """

    what: str
    collection: str
    page: str
    title: str = ""
    detail: str = ""
    at: str = ""

    def row(self) -> tuple[str, str, str, str, str, str]:
        at = self.at or datetime.now(UTC).isoformat(timespec="seconds")
        return (at, self.what, self.collection, self.page, self.title, self.detail)


@dataclass
class Report:
    """What one read or one write amounted to, for whoever asked for it."""

    entries: list[Entry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def note(
        self, what: str, collection: str, page: str, title: str = "", detail: str = ""
    ) -> None:
        self.entries.append(Entry(what, collection, page, title, detail))

    def of(self, *kinds: str) -> list[Entry]:
        return [entry for entry in self.entries if entry.what in kinds]

    def __bool__(self) -> bool:
        return bool(self.entries)


def write_journal(report: Report, database: Path | None = None) -> None:
    """Append what happened, and never fail a pass for want of writing it down."""
    if not report.entries:
        return
    try:
        with db.transaction(location=database) as connection:
            connection.executemany(
                "INSERT INTO sync_journal (at, what, collection, page, title, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [entry.row() for entry in report.entries],
            )
    except db.ERRORS as error:
        report.problems.append(f"the journal could not be written: {error}")


def journal(limit: int = 50, database: Path | None = None) -> list[dict[str, Any]]:
    """The last entries of the journal, oldest first."""
    try:
        with db.transaction(immediate=False, location=database) as connection:
            rows = connection.execute(
                "SELECT at, what, collection, page, title, detail FROM sync_journal"
                " ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except db.ERRORS:
        return []
    names = ("at", "what", "collection", "page", "title", "detail")
    return [dict(zip(names, row, strict=True)) for row in reversed(rows)]


def conflicts(collection: str, database: Path | None = None) -> list[dict[str, Any]]:
    """The last conflict journalled on each page of a collection, oldest first.

    Asked of the whole journal rather than of its last lines: the console writes
    one per status it sees change, and a refusal nobody has answered yet must
    not slide out of a window under them.
    """
    try:
        with db.transaction(immediate=False, location=database) as connection:
            rows = connection.execute(
                "SELECT at, what, collection, page, title, detail FROM sync_journal"
                " WHERE id IN (SELECT MAX(id) FROM sync_journal"
                " WHERE what = 'conflict' AND collection = ? GROUP BY page)"
                " ORDER BY id",
                (collection,),
            ).fetchall()
    except db.ERRORS:
        return []
    names = ("at", "what", "collection", "page", "title", "detail")
    return [dict(zip(names, row, strict=True)) for row in rows]


# `now()` in a formula would make every page look edited on every pass.
_COMPUTED = ("formula", "rollup")


def fingerprint(page: Page) -> str:
    """What a page's properties say, in a few characters.

    What tells two versions of a page apart when the board's timestamp cannot: it
    is to the minute, and a minute is long enough for a ticket to go through
    three columns.
    """
    kept = {
        name: value
        for name, value in page.properties.items()
        if (value or {}).get("type") not in _COMPUTED
    }
    body = json.dumps(kept, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
