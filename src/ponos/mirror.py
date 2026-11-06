"""Carrying `ponos.db` to Notion, and bringing back the little that still comes up.

**Going out: the queue, replayed.** Every change of a ticket is a row of
`mirror_queue` (see `tickets.py`). A pass empties it in order. Notion not
answering stops the emptying at the first change and leaves the rest where it
is — no ticket waits on it, and the pass after the one where Notion is back
catches up. A change Notion *refuses* (a column it lacks, a page gone) is kept
with its error and its count, and the ones behind it go on: one bad ticket must
not hold the board back.

**A ticket's changes are one write.** The queue says what moved, not the new
value; the mirror reads the ticket when it sends. So a ticket changed five
times while Notion was away costs one `PATCH`, with the last word, and the
changes behind it leave the queue together.

**Coming up: a closed list.** Four things only, because every other column is
Ponos's to write and a person editing it in Notion is overwritten the next time
the ticket moves: a page created there, its status, its mission part, and its
comments (those are read when a ticket's discussion is asked for, see
`ledger.Ledger.comments`). The status and the mission are taken only for a
ticket with nothing queued — what Ponos has still to say wins over what Notion
says — and only for a page whose edit time moved since the mirror last read it,
so a quiet board costs one query.

**Notion's edit time is to the minute**, so a stamp from the last few minutes
is not trusted to mean "nothing since": the page is read again until the stamp
is old enough to be the last word.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from . import ids, ticket_page, tickets
from .ledger import COLUMNS, body_of, values_of
from .store import Page, StoreError, Unreachable

if TYPE_CHECKING:
    from .ledger import Ledger
    from .tickets import Change, Record

log = logging.getLogger(__name__)

# How long a Notion edit time is distrusted for: it is cut to the minute.
SETTLING = 180


@dataclass
class Report:
    sent: int = 0
    created: int = 0
    taken: int = 0
    problems: list[str] = field(default_factory=list)
    offline: bool = False

    def __bool__(self) -> bool:
        return bool(self.sent or self.created or self.taken or self.problems)


def _key_of(attribute: str) -> str:
    return next(key for key, value in COLUMNS.items() if value == attribute)


def _properties(
    ledger: Ledger, record: Record, attributes: list[str] | None = None
) -> dict[str, object]:
    """The values of a ticket by their Notion column name: all of them, or the ones named."""
    settings = ledger.settings
    values: dict[str, object] = {}
    for key, attribute in COLUMNS.items():
        if attributes is not None and attribute not in attributes:
            continue
        value: object = getattr(record, attribute)
        if attribute == "after":
            pages = [tickets.get(earlier) for earlier in record.after]
            value = [one.notion or one.id for one in pages if one is not None]
        elif attribute == "project":
            value = [record.project] if record.project else []
        values[settings.prop(key)] = value
    return values


def _notion_database(ledger: Ledger) -> str:
    """The id Notion gave the tickets database, resolved once a pass."""
    if not ledger._tickets_id:
        ledger.workspace(ledger.settings)
    if not ledger._tickets_id:
        raise StoreError("the tickets database of Notion is not known")
    return ledger._tickets_id


def _create(ledger: Ledger, record: Record) -> None:
    database = _notion_database(ledger)
    values = _properties(ledger, record)
    values.pop(ledger.settings.prop("after"), None)
    page = ledger.notion.create_row(database, record.title, values)
    tickets.attach(record.id, notion=page)
    body = body_of(record, live=False)
    if body:
        ledger.notion.append_markdown(page, body)
    after = _properties(ledger, record, ["after"])
    if any(after.values()):
        ledger.notion.update(database, page, after)


def _update(ledger: Ledger, record: Record, fields: set[str]) -> None:
    database = _notion_database(ledger)
    columns = fields - {"mission", "report", "title"}
    values = _properties(ledger, record, sorted(columns))
    if "title" in fields:
        values[ledger.notion.title_property(database)] = record.title
    if values:
        ledger.notion.update(database, record.notion, values)
    if "mission" in fields:
        ledger.notion.replace_markdown(record.notion, body_of(record, live=False))
    elif "report" in fields:
        report = re.sub(r"<!-- /?ponos:live -->", "", record.report).strip()
        if report:
            ledger.notion.replace_section(
                record.notion, ticket_page.DONE, f"## {ticket_page.DONE[0]}\n\n{report}"
            )


def push(ledger: Ledger, *, limit: int = 200) -> Report:
    """Tell Notion what the queue says, oldest first, and stop where it does not answer."""
    report = Report()
    queue = tickets.pending(limit)
    order: list[str] = []
    groups: dict[str, list[Change]] = {}
    for change in queue:
        if change.ticket not in groups:
            order.append(change.ticket)
        groups.setdefault(change.ticket, []).append(change)
    for ticket in order:
        group = groups[ticket]
        try:
            _push_ticket(ledger, ticket, group, report)
        except Unreachable as error:
            report.offline = True
            report.problems.append(str(error))
            tickets.failed(group[0].id, str(error))
            return report
        except StoreError as error:
            report.problems.append(f"{ticket}: {error}")
            log.warning("the mirror was refused for %s: %s", ticket, error)
            still = {pending.id for pending in tickets.pending(100_000)}
            for change in group:
                if change.id in still:
                    tickets.failed(change.id, str(error))
    return report


def _push_ticket(ledger: Ledger, ticket: str, group: list[Change], report: Report) -> None:
    record = tickets.get(ticket)
    fields: set[str] = set()
    made = False
    for change in group:
        if change.what == "deleted":
            page = str(change.payload.get("notion") or "")
            if page:
                ledger.notion.trash(page)
            tickets.sent(change.id)
            report.sent += 1
        elif record is None:
            tickets.sent(change.id)
        elif change.what in ("created", "status", "fields"):
            if not record.notion:
                _create(ledger, record)
                report.created += 1
                # The page was made from the ticket as it stands: whatever the
                # changes moved, this one and those behind it, is in it already.
                fields.clear()
                record = tickets.get(ticket) or record
                made = True
            elif not made:
                fields.update(change.payload.get("fields", []))
            tickets.sent(change.id)
            report.sent += 1
        elif change.what == "comment":
            _send_comment(ledger, record, change)
            tickets.sent(change.id)
            report.sent += 1
        else:
            tickets.sent(change.id)
    if record is not None and fields:
        fresh = tickets.get(ticket)
        if fresh is not None and fresh.notion:
            _update(ledger, fresh, fields)


def _send_comment(ledger: Ledger, record: Record, change: Change) -> None:
    if not record.notion:
        return
    number = change.payload.get("comment")
    remark = next((one for one in tickets.comments(record.id) if one.id == number), None)
    if remark is not None:
        ledger.notion.comment(record.notion, remark.text, remark.discussion)


def _same(first: str, second: str) -> bool:
    return " ".join(first.split()) == " ".join(second.split())


def _settled(stamp: str) -> bool:
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (datetime.now(UTC) - moment).total_seconds() > SETTLING


def born(ledger: Ledger, page: Page) -> Record:
    """A ticket for a page that Notion has and the table has not.

    Its id is the page's, so that everything else in `ponos.db` that names the
    ticket by it — the journal, the claims — is already about the same one.
    """
    values = values_of(ledger.settings, page, ledger.kinds())
    title = str(values.pop("title", "") or page.title)
    after = values.pop("after", [])
    parts = ticket_page.split(ledger.notion.blocks_text(page.id, live=False))
    created = str(page.raw.get("created_time") or "")
    extra: dict[str, Any] = {"created_at": created} if created else {}
    record = tickets.create(
        title,
        id=page.id,
        notion=ids.bare(page.id),
        notion_edited=str(page.raw.get("last_edited_time") or ""),
        mission=parts.mission,
        report=parts.done,
        **values,
        **extra,
    )
    # The relation is written after the row: `after` names tickets that may not be here yet.
    if after:
        tickets.update(record.id, after=after, mirrored=True)
    return record


def pull(ledger: Ledger) -> Report:
    """What comes up from Notion: pages born there, statuses and missions that moved."""
    report = Report()
    database = _notion_database(ledger)
    queued = {change.ticket for change in tickets.pending(100_000)}
    status_name = ledger.settings.prop("status")
    for page in ledger.notion.query(database):
        if page.raw.get("archived") or page.raw.get("in_trash"):
            continue
        record = tickets.by_notion(page.id)
        if record is None:
            try:
                born(ledger, page)
            except (StoreError, ValueError) as error:
                report.problems.append(f"{page.title or page.id}: {error}")
            else:
                report.created += 1
            continue
        stamp = str(page.raw.get("last_edited_time") or "")
        if record.notion_edited == stamp and _settled(stamp):
            continue
        if record.id in queued:
            continue
        moved = False
        values = values_of(ledger.settings, page, ledger.kinds())
        status = values.get("status")
        if status and status != record.status and status_name in page.properties:
            tickets.update(record.id, status=status, mirrored=True)
            moved = True
        text = ledger.notion.blocks_text(page.id, live=False)
        mission = ticket_page.split(text).mission
        if mission.strip() and not _same(mission, record.mission):
            tickets.update(record.id, mission=mission.strip(), mirrored=True)
            moved = True
        tickets.attach(record.id, edited=stamp)
        report.taken += moved
    return report


def run(ledger: Ledger) -> Report:
    """One mirroring: what is queued goes out first, then what changed over there comes in.

    In that order so that a ticket the runner moved a moment ago is not read
    back as it was. Never raises: Notion unreachable is the report's `offline`.
    """
    report = push(ledger)
    if report.offline:
        return report
    try:
        coming = pull(ledger)
    except Unreachable as error:
        report.offline = True
        report.problems.append(str(error))
        return report
    except StoreError as error:
        report.problems.append(str(error))
        return report
    report.created += coming.created
    report.taken += coming.taken
    report.problems.extend(coming.problems)
    return report


def imported(ledger: Ledger) -> tuple[int, int]:
    """`ponos import notion`: every page of the tickets board, once. (new, already here)."""
    database = _notion_database(ledger)
    new = known = 0
    for page in ledger.notion.query(database):
        if page.raw.get("archived") or page.raw.get("in_trash"):
            continue
        if tickets.by_notion(page.id) is not None:
            known += 1
            continue
        record = born(ledger, page)
        ledger.take_comments(record)
        new += 1
    return new, known
