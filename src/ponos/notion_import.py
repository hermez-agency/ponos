"""Notion → `ponos.db`: the import that fills it, and the little that goes on rising after.

**Two readers of one page, one list of what is read.** `ponos import notion`
fills the database from Master Tickets once; the pass that follows it keeps
the database level with what is *still* written in Notion. Both go through
`columns` and `body`, so that a ticket imported and a ticket that rose are the
same row.

**What rises is a closed list, and the rest is not read.** A page created, its
status, its Mission: those are the three things a person does in Notion that
Ponos has no other way to hear of. Its comments are no longer read: an answer
is given from the console, the MCP, Telegram or Slack. Every other column of a page
(the pull request, the cost, the progress…) is Ponos's, and the mirror writes
over it — taking it back from Notion would let a stale cell undo the database.
The import is the one exception, and only for a ticket the database does not
have: it is the start of the story, not a change in it. See « The mirror » in
guide/board.md.

**A ticket whose changes are still in the queue is not touched.** What the
database says has not reached Notion yet, and what Notion says is the older of
the two; the mirror will send first, and the next pass reads what is left.

Nothing here queues: what comes up is already in Notion. See `tickets.received`.

**The import is the way out of Notion.** `run` brings home everything Notion
still holds that `ponos.db` has not: the projects, agents, goals and schedules
(under their own identifiers, so that every relation lands), the standing
context, the body of every ticket with the files it names (`page_files.py`),
the comments, the « after » links, the done and cancelled tickets too. It can
be replayed: what is already here is left alone, what is missing is completed.
`check` counts both sides and lists what the database lacks — zero is the
condition for letting go of the token. Notion itself is only ever read.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from . import page_files, pages, store, ticket_page, tickets
from . import voice as voice_module
from .config import STATUS, Config
from .images import download
from .log import FILE_ONLY
from .workspace import Workspace

log = logging.getLogger(__name__)

# The statuses whose tickets wait for a person, and so may have been reworded
# since the last pass. A ticket that is done, cancelled or running is not read
# again: its Mission is not asked for on every pass.
# The collections of the workspace the import brings home beside the tickets.
COLLECTIONS = ("projects", "agents", "goals", "schedules")

# How many pages `check` reads from Notion at once: under its rate limit, past its latency.
_READERS = 3

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
    # Pages brought home, by collection; and the ones that were here already.
    brought: dict[str, int] = field(default_factory=dict)
    kept: dict[str, int] = field(default_factory=dict)
    context: bool = False
    files: int = 0
    # Files that are gone at their source (a dead link): no loss of ours.
    gone: int = 0
    links: int = 0
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
    for name, key in (("role", "role"), ("goal", "goal")):
        related = store.read(page, settings.prop(key)) or []
        values[name] = _id(related[0]) if related else ""
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


def _remarks(client: store.Store, ticket: str, page: str) -> int:
    """Keep the page's comments the ticket does not have yet; how many were new."""
    added = 0
    for remark in client.comments(page):
        added += tickets.heard(
            ticket,
            remark.text,
            at=remark.created_time,
            author=remark.created_by,
            discussion=remark.discussion_id,
        )
    return added


def run(client: store.Store, config: Config, space: Workspace) -> Report:
    """Bring home everything of Notion that `ponos.db` lacks. Idempotent.

    A ticket already in the database (same page) is left as it is and only has
    what is missing completed — its comments, its links, its files, a body it
    never got — so a second import adds nothing and never undoes what Ponos has
    written since the first. The projects are read to tell a ticket whose
    project is gone from one that has none: the relation is kept either way,
    the report says it.
    """
    report = Report()
    target = pages.Pages(config.notion)
    known: set[str] = set()
    if space.projects:
        known = {_id(page.id) for page in client.query(space.projects)}
        report.projects = len(known)
    for key in COLLECTIONS:
        if database := getattr(space, key):
            _collection(client, target, key, database, report)
    _context(client, target, space, report)
    for page in client.query(space.tickets):
        try:
            _one(client, config, page, report, known)
        except store.Unreachable:
            raise
        except store.StoreError as error:
            report.problems.append(f"{page.title or page.id}: {voice_module.line(error)}")
            log.warning("import of %s failed", page.id, exc_info=True, extra=FILE_ONLY)
    return report


def _files(client: store.Store, text: str, report: Report) -> None:
    """Keep the files a text names by block, the ones not kept yet."""
    for block in page_files.blocks(text):
        if page_files.find(block) is not None or page_files.gone(block):
            continue
        try:
            page_files.keep(block, client.attachment(block))
        except (page_files.Gone, LookupError) as error:
            # Not there for anybody: a dead link, a block that holds no file.
            # Written down, so that it is neither asked for again nor called a loss.
            page_files.lost(block, voice_module.line(error))
            report.gone += 1
        except store.StoreError as error:
            report.problems.append(f"file {block}: {voice_module.line(error)}")
        else:
            report.files += 1


def _collection(
    client: store.Store, target: pages.Pages, key: str, database: str, report: Report
) -> None:
    """The pages of one database of the workspace, under their own identifiers."""
    for page in client.query(database):
        try:
            body = client.blocks_text(page.id)
            _files(client, body, report)
            if target.adopt(key, page, body):
                report.brought[key] = report.brought.get(key, 0) + 1
                _pictures(target, page, report)
            else:
                report.kept[key] = report.kept.get(key, 0) + 1
        except store.Unreachable:
            raise
        except store.StoreError as error:
            report.problems.append(f"{key} {page.title or page.id}: {voice_module.line(error)}")
            log.warning("import of %s failed", page.id, exc_info=True, extra=FILE_ONLY)


def _pictures(target: pages.Pages, page: store.Page, report: Report) -> None:
    """A page's cover and icon: the emoji as it is, an image kept beside the database."""
    for slot in store.SLOTS:
        found = page.raw.get(slot)
        if not isinstance(found, dict):
            continue
        kind = str(found.get("type", ""))
        picture = store.Picture()
        try:
            if kind == "emoji":
                picture = store.Picture(emoji=str(found.get("emoji", "")))
            elif kind in ("file", "external"):
                url = str((found.get(kind) or {}).get("url", ""))
                if not url:
                    continue
                data, media = download(url)
                picture = store.Picture(data=data, type=media)
            else:
                continue
            if not picture.removed:
                target.set_picture(page.id, slot, picture)
        except store.StoreError as error:
            report.problems.append(f"{slot} of {page.title}: {voice_module.line(error)}")


def _context(client: store.Store, target: pages.Pages, space: Workspace, report: Report) -> None:
    """The standing context, unless the database already has one of its own."""
    if not space.context_page:
        return
    if target.context():
        report.context = False
        return
    try:
        text = client.blocks_text(space.context_page)
        _files(client, text, report)
    except store.Unreachable:
        raise
    except store.StoreError as error:
        report.problems.append(f"context: {voice_module.line(error)}")
        return
    if text.strip():
        target.set_context(text)
        report.context = True


def _one(
    client: store.Store,
    config: Config,
    page: store.Page,
    report: Report,
    projects: set[str],
    *,
    comments: bool = True,
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
        report.links += len(after(page, config))
        _files(client, f"{mission}\n{done}", report)
    else:
        ticket = mine.id
        report.existing += 1
        _complete(client, config, page, mine, report)
        report.links += tickets.link(ticket, after(page, config))
    if comments:
        report.comments += _remarks(client, ticket, page.id)


def _complete(
    client: store.Store, config: Config, page: store.Page, mine: tickets.Record, report: Report
) -> None:
    """What a ticket imported earlier lacks: its relations, its body, its files.

    Only what is empty is filled; a Mission or a report Ponos has written since
    stays as it is.
    """
    values = columns(page, config)
    filled: dict[str, Any] = {
        name: values[name]
        for name in ("project", "role", "goal")
        if values[name] and not getattr(mine, name)
    }
    if not mine.mission.strip() and not mine.report.strip():
        mission, done = body(client, page.id)
        if mission.strip():
            filled["mission"] = mission
        if done.strip():
            filled["report"] = done
    if filled:
        tickets.received(mine.id, **filled, edited_at=mine.edited_at)
    _files(
        client,
        f"{filled.get('mission', mine.mission)}\n{filled.get('report', mine.report)}",
        report,
    )


@dataclass
class Parity:
    """What Notion holds and what the database holds, type by type, and what is missing."""

    rows: list[tuple[str, int, int]] = field(default_factory=list)
    losses: list[str] = field(default_factory=list)
    # What differs without being a loss: a file that was already gone in Notion.
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.losses


def check(client: store.Store, config: Config, space: Workspace) -> Parity:
    """Count both sides, type by type, and list what Notion has that the database lacks.

    Read-only on both. A difference that goes the other way (a ticket made
    since, a comment Ponos wrote) is not a loss and is not listed: only what
    would be gone with the token is.
    """
    parity = Parity()
    target = pages.Pages(config.notion)
    notion = {"tickets": 0, "comments": 0, "links": 0, "files": 0, "bodies": 0}
    held = {key: 0 for key in notion}
    blocks: set[str] = set()
    found = client.query(space.tickets)
    records = {page.id: tickets.of_page(page.id) for page in found}
    # The database is read here, Notion in a few threads: a board of two
    # thousand tickets is two thousand round trips, and a serial check outlived
    # the hour on the real one. A ticket whose two parts are both written here
    # cannot lose a text, so its body is not asked for again.
    whole = {
        page_id
        for page_id, mine in records.items()
        if mine is not None and mine.mission.strip() and mine.report.strip()
    }

    def reread(page: store.Page) -> tuple[tuple[str, str] | None, list[store.Comment]]:
        return (None if page.id in whole else body(client, page.id)), client.comments(page.id)

    wanted_pages = [page for page in found if records[page.id] is not None]
    with ThreadPoolExecutor(max_workers=_READERS) as pool:
        read = dict(
            zip((page.id for page in wanted_pages), pool.map(reread, wanted_pages), strict=True)
        )
    if whole:
        parity.notes.append(
            f"{len(whole)} ticket(s) not read again: both parts are written in ponos.db"
        )
    for page in found:
        notion["tickets"] += 1
        mine = records[page.id]
        if mine is None:
            parity.losses.append(f"ticket missing: {page.title or page.id}")
            continue
        held["tickets"] += 1
        name = page.title or page.id
        texts, remarks = read[page.id]
        mission, done = texts if texts is not None else (mine.mission, mine.report)
        for part, there, ours_text in (
            ("mission", mission, mine.mission),
            ("report", done, mine.report),
        ):
            if there.strip():
                notion["bodies"] += 1
                if ours_text.strip():
                    held["bodies"] += 1
                else:
                    parity.losses.append(f"{part} empty: {name}")
        blocks.update(page_files.blocks(f"{mission}\n{done}"))
        wanted = after(page, config)
        notion["links"] += len(wanted)
        for earlier in wanted:
            if _id(earlier) in mine.after:
                held["links"] += 1
            else:
                parity.losses.append(f"link missing: {name} after {earlier}")
        said = {remark.text for remark in tickets.comments(mine.id)}
        for remark in remarks:
            notion["comments"] += 1
            if remark.text in said:
                held["comments"] += 1
            else:
                parity.losses.append(f"comment missing: {name}: {remark.text[:60]}")
    others: list[tuple[str, int, int]] = []
    for collection in COLLECTIONS:
        if not (database := getattr(space, collection)):
            continue
        ours = {page.id: page for page in target.query(collection)}
        found = client.query(database)
        others.append((collection, len(found), sum(1 for page in found if _id(page.id) in ours)))
        for page in found:
            here = ours.get(_id(page.id))
            if here is None:
                parity.losses.append(f"{collection} missing: {page.title or page.id}")
                continue
            text = client.blocks_text(page.id)
            if text.strip() and not str(here.raw.get("body", "")).strip():
                parity.losses.append(f"{collection} body empty: {page.title or page.id}")
            blocks.update(page_files.blocks(text))
    if space.context_page:
        text = client.blocks_text(space.context_page)
        others.append(("context", int(bool(text.strip())), int(bool(target.context()))))
        if text.strip() and not target.context():
            parity.losses.append("context empty")
        blocks.update(page_files.blocks(text))
    for block in sorted(blocks):
        if reason := page_files.gone(block):
            parity.notes.append(f"file gone at its source, not a loss: block {block} ({reason})")
            continue
        notion["files"] += 1
        if page_files.find(block) is not None:
            held["files"] += 1
        else:
            parity.losses.append(f"file missing: block {block}")
    labels = (
        ("tickets", "tickets"),
        ("bodies", "ticket texts"),
        ("comments", "comments"),
        ("links", "after links"),
        ("files", "files"),
    )
    parity.rows = [(label, notion[key], held[key]) for key, label in labels] + others
    return parity


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
                _one(client, config, page, report, set(), comments=False)
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
        except store.Unreachable:
            raise
        except store.StoreError as error:
            report.problems.append(f"{page.title or page.id}: {voice_module.line(error)}")
            log.warning("rise of %s failed", page.id, exc_info=True, extra=FILE_ONLY)
    return report
