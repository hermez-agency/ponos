"""`ponos.db` → Notion: the queue emptied, and what a failure leaves behind.

Every change to a ticket is a row of `mirror_queue` (tickets.py) and Notion is
told of it here, once a pass, in the order it happened. Notion is a copy: a
board that does not answer is a board that is behind, and no ticket waits for
it — which is why nothing in this module raises. A change Notion refused or
did not hear stays in the queue with its count of tries and its last error,
and is sent again by the next pass; the row leaves only when Notion has taken it.

**The page is read when the change is sent, not when it was made.** The queue
says *what* moved, so five edits in a row are five rows and one write with the
last word. A ticket deleted since has nothing left to say and its changes are
dropped.

**A ticket's changes go in order, and one that fails holds the rest of its
ticket back.** A comment cannot land on a page whose creation was refused. The
other tickets carry on. After `GIVE_UP` failures in a row, though, the pass
stops: it is Notion that is down, or the token, and asking a hundred times would
only repeat the answer.

The columns written are those of `PROPERTIES`, by the names the board gives
them; the two parts of the page are written as `ticket_page` shapes them, the
second alone when only it moved so that the Mission's blocks stay as a person
made them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import store, ticket_page, tickets
from . import voice as voice_module
from .config import Config
from .log import FILE_ONLY
from .workspace import Workspace

log = logging.getLogger(__name__)

# Consecutive failures after which a pass stops asking.
GIVE_UP = 3


@dataclass
class Passage:
    """What one emptying of the queue did."""

    sent: int = 0
    failed: int = 0
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.sent or self.failed)


def _values(
    record: tickets.Record, config: Config, names: set[str] | None = None
) -> dict[str, Any]:
    """The properties of the board for these columns of the ticket, by the board's names."""
    settings = config.notion
    kind = (
        settings.kind(record.kind)
        if record.kind in ("code", "writing", "external", "publication")
        else ""
    )
    wanted: dict[str, Any] = {
        "status": ("status", record.status),
        "project": ("project", [record.project] if record.project else []),
        "kind": ("type", kind),
        "subtype": ("subtype", record.subtype),
        "pull_request": ("pull_request", record.pull_request),
        "session": ("session", record.session),
        "agent": ("agent", record.agent),
        "model": ("model", record.model),
        "progress": ("progress", record.progress),
        "block": ("block", record.block),
        "ci": ("ci", record.ci),
        "on_change": ("on", record.on_change),
        "scheduled": ("due", record.scheduled),
        "priority": ("priority", record.priority),
        "cost": ("cost", record.cost),
        "duration": ("duration", record.duration),
        "waiting": ("waiting", record.waiting),
        "plan_first": ("plan", record.plan_first),
        "after": ("after", record.after),
    }
    return {
        settings.prop(key): value
        for name, (key, value) in wanted.items()
        if names is None or name in names
    }


def _page(record: tickets.Record, config: Config) -> str:
    """The whole page, in its two parts."""
    words = voice_module.Voice(config.runner.language)
    if not record.report.strip():
        return ticket_page.template(words, record.mission)
    return (
        f"## {words.say('page-mission')}\n\n{record.mission.strip()}\n\n"
        f"## {words.say('page-done')}\n\n{record.report.strip()}"
    )


def _send(client: store.Store, config: Config, space: Workspace, change: tickets.Change) -> None:
    """Tell Notion of one change. Raises `store.StoreError` when it did not take it."""
    record = tickets.get(change.ticket)
    if change.what == "deleted":
        if page := change.payload.get("notion"):
            client.trash(page)
        return
    if record is None:
        return  # deleted since: nothing to say
    if change.what == "created":
        if record.notion:
            return
        page = client.create_row(space.tickets, record.title, _values(record, config))
        tickets.received(record.id, notion=page, edited_at=record.edited_at)
        if record.mission or record.report:
            client.replace_markdown(page, _page(record, config))
        return
    if not record.notion:
        raise store.StoreError("its page is not created yet")
    if change.what == "comment":
        for remark in tickets.comments(record.id):
            if remark.id == change.payload.get("comment"):
                client.comment(record.notion, remark.text, remark.discussion)
        return
    if change.what in ("status", "fields"):
        fields = set(change.payload.get("fields") or ["status"])
        if "title" in fields:
            client.update(
                space.tickets, record.notion, {client.title_property(space.tickets): record.title}
            )
        if values := _values(record, config, fields):
            client.update(space.tickets, record.notion, values)
        if "mission" in fields:
            client.replace_markdown(record.notion, _page(record, config))
        elif "report" in fields:
            words = voice_module.Voice(config.runner.language)
            client.replace_section(
                record.notion,
                ticket_page.DONE,
                f"## {words.say('page-done')}\n\n{record.report.strip()}",
            )
        return
    raise store.StoreError(f"no such kind of change: {change.what}")


def flush(client: store.Store, config: Config, space: Workspace, *, limit: int = 100) -> Passage:
    """Send the queue, oldest first. Never raises: a failure is a row that stays."""
    passage = Passage()
    held: set[str] = set()
    in_a_row = 0
    for change in tickets.pending(limit):
        if change.ticket in held:
            continue
        try:
            _send(client, config, space, change)
        except store.StoreError as error:
            reason = voice_module.line(error)
            tickets.failed(change.id, reason)
            held.add(change.ticket)
            passage.failed += 1
            in_a_row += 1
            log.warning(
                "mirror: change %s of %s not sent", change.id, change.ticket, extra=FILE_ONLY
            )
            if in_a_row >= GIVE_UP or isinstance(error, store.Unreachable):
                passage.problems.append(f"Notion does not answer ({reason}) — the queue waits")
                break
            continue
        in_a_row = 0
        tickets.sent(change.id)
        passage.sent += 1
    return passage
