"""Notion → `ponos.db`: the import that fills it, and the little that goes on rising after.

**Two readers of one page, one list of what is read.** `ponos import notion`
fills the database from Master Tickets once; the pass that follows it keeps
the database level with what is *still* written in Notion. Both go through
`columns` and `body`, so that a ticket imported and a ticket that rose are the
same row.

**What rises is a closed list, and the rest is not read.** A page created, its
status, its Mission, its comments: those are the four things a person does in
Notion that Ponos has no other way to hear of. Every other column of a page
(the pull request, the cost, the progress…) is Ponos's, and the mirror writes
over it — taking it back from Notion would let a stale cell undo the database.
The import is the one exception, and only for a ticket the database does not
have: it is the start of the story, not a change in it. See « The mirror » in
guide/board.md.

**A ticket whose changes are still in the queue is not touched.** What the
database says has not reached Notion yet, and what Notion says is the older of
the two; the mirror will send first, and the next pass reads what is left.

Nothing here queues: what comes up is already in Notion. See `tickets.received`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import store, ticket_page, tickets
from . import voice as voice_module
from .config import STATUS, Config
from .log import FILE_ONLY
from .workspace import Workspace

log = logging.getLogger(__name__)

# The statuses whose tickets wait for a person, and so may have been answered
# or reworded since the last pass. A ticket that is done, cancelled or running
# is not read again: its comments are not asked for on every pass.
_LIVELY = ("draft", "ready", "blocked", "review", "validated", "paused")

# The columns that are written as they are, field by field: (Record field, key
# of the board's property). `project`, `kind`, `status` and `after` need more
# than a copy and are handled in `columns`.
_COPIED = (
    ("subtype", "subtype"),
    ("pull_request", "pull_request"),
    ("session", "session"),
    ("agent", "agent"),
    ("model", "model"),
    ("progress", "progress"),
    ("block", "block"),
    ("ci", "ci"),
    ("on_change", "on"),
    ("scheduled", "due"),
)
_NUMBERS = (("priority", "priority"), ("cost", "cost"), ("duration", "duration"))
_FLAGS = (("waiting", "waiting"), ("plan_first", "plan"))


@dataclass
class Report:
    """What a reading of the board changed in the database."""

    created: int = 0
    existing: int = 0
    changed: int = 0
    comments: int = 0
    projects: int = 0
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.created or self.changed or self.comments)


def _id(page: str) -> str:
    return page.replace("-", "")


def status_of(page: store.Page, config: Config) -> str:
    """The page's status, or `draft` for one the database does not know."""
    value = str(store.read(page, config.notion.prop("status")) or "")
    return value if value in tickets.STATUSES else STATUS["draft"]


def columns(page: store.Page, config: Config) -> dict[str, Any]:
    """The ticket's columns, as a page says them — Mission and « What was done » apart."""
    settings = config.notion
    values: dict[str, Any] = {"status": status_of(page, config)}
    projects = store.read(page, settings.prop("project")) or []
    values["project"] = _id(projects[0]) if projects else ""
    values["kind"] = settings.kind_of(str(store.read(page, settings.prop("type")) or ""))
    for name, key in _COPIED:
        values[name] = str(store.read(page, settings.prop(key)) or "")
    for name, key in _NUMBERS:
        number = store.read(page, settings.prop(key))
        if number is not None:
            values[name] = number
    for name, key in _FLAGS:
        values[name] = bool(store.read(page, settings.prop(key)))
    return values


def after(page: store.Page, config: Config) -> list[str]:
    return [_id(one) for one in store.read(page, config.notion.prop("after")) or []]


def body(client: store.Store, page: str) -> tuple[str, str]:
    """The page's Mission and « What was done », cut at the heading the format gives."""
    parts = ticket_page.split(client.blocks_text(page))
    done = parts.done
    # The placeholder a new page carries is the format's, not a report.
    for words in voice_module.every("page-done-empty"):
        if done.strip().strip("*").strip() == words:
            done = ""
    return parts.mission, done


def _remarks(client: store.Store, ticket: str, page: str, *, rising: bool = False) -> int:
    """Keep the page's comments the ticket does not have yet; how many were new.

    Ponos's own words are matched by their text alone once the database is
    live (`rising`): the mirror sent them, and Notion dates them its own way.
    The import has no such echo to recognise and keeps every comment.
    """
    me = client.me() if rising else ""
    added = 0
    for remark in client.comments(page):
        added += tickets.heard(
            ticket,
            remark.text,
            at=remark.created_time,
            author=remark.created_by,
            discussion=remark.discussion_id,
            echo=bool(me) and remark.created_by == me,
        )
    return added


def run(client: store.Store, config: Config, space: Workspace) -> Report:
    """Fill the database from Master Projects and Master Tickets. Idempotent.

    A ticket already in the database (same page) is left as it is and only has
    its comments completed — a second import adds nothing, and never undoes
    what Ponos has written since the first. The projects are read to tell a
    ticket whose project is gone from one that has none: the relation is kept
    either way, the report says it.
    """
    report = Report()
    known: set[str] = set()
    if space.projects:
        known = {_id(page.id) for page in client.query(space.projects)}
        report.projects = len(known)
    pages = client.query(space.tickets)
    for page in pages:
        try:
            _one(client, config, page, report, known)
        except store.Unreachable:
            raise
        except store.StoreError as error:
            report.problems.append(f"{page.title or page.id}: {voice_module.line(error)}")
            log.warning("import of %s failed", page.id, exc_info=True, extra=FILE_ONLY)
    return report


def _one(
    client: store.Store, config: Config, page: store.Page, report: Report, projects: set[str]
) -> None:
    ticket = _id(page.id)
    if (mine := tickets.of_page(page.id)) is None:
        mission, done = body(client, page.id)
        values = columns(page, config)
        if projects and values["project"] and values["project"] not in projects:
            report.problems.append(f"{page.title}: its project is not in Master Projects")
        created = page.raw.get("created_time", "")
        edited = page.raw.get("last_edited_time", "")
        tickets.create(
            page.title,
            id=ticket,
            notion=ticket,
            mission=mission,
            report=done,
            after=after(page, config),
            **({"created_at": created} if created else {}),
            **({"edited_at": edited} if edited else {}),
            **values,
        )
        report.created += 1
    else:
        ticket = mine.id
        report.existing += 1
    report.comments += _remarks(client, ticket, page.id)


def rise(client: store.Store, config: Config, space: Workspace, seen: dict[str, str]) -> Report:
    """What a person did in Notion since the last pass: the closed list, and nothing else.

    `seen` maps a ticket to the `last_edited_time` of the page the last time its
    Mission was read, kept by the caller for as long as it lives: the body of a
    page is a request, and an untouched page is not asked for again.
    """
    report = Report()
    for page in client.query(space.tickets):
        ticket = _id(page.id)
        try:
            mine = tickets.of_page(page.id)
            if mine is None:
                _one(client, config, page, report, set())
                seen[ticket] = page.raw.get("last_edited_time", "")
                continue
            ticket = mine.id
            if tickets.waiting(ticket):
                continue
            moved: dict[str, Any] = {}
            if (status := status_of(page, config)) != mine.status:
                moved["status"] = status
            edited = page.raw.get("last_edited_time", "")
            if mine.status in _LIVELY and seen.get(ticket) != edited:
                mission, _ = body(client, page.id)
                if mission != mine.mission:
                    moved["mission"] = mission
                seen[ticket] = edited
            if moved:
                tickets.received(ticket, **moved)
                report.changed += 1
            if mine.status in _LIVELY or moved.get("status") in _LIVELY:
                report.comments += _remarks(client, ticket, page.id, rising=True)
        except store.Unreachable:
            raise
        except store.StoreError as error:
            report.problems.append(f"{page.title or page.id}: {voice_module.line(error)}")
            log.warning("rise of %s failed", page.id, exc_info=True, extra=FILE_ONLY)
    return report
