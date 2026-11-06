"""The board when `ponos.db` holds the tickets and Notion only mirrors them.

`storage.mode = "db"`. The runner, the console, the MCP and the CLI were written
against `store.Store`, a board shaped like Notion's; so rather than rewrite each
of them, the tickets are served through that same interface — a `Page` is made
of a row of `tickets.py` on the way out, and a write on a page lands in the row
and in the queue the mirror empties (`mirror.py`).

**Only the tickets are in the database.** Projects, agents, schedules, goals and
the standing context are still Notion's, and are read through to it. What makes
that survivable without Notion is `notion-cache.json`: every read of those that
worked is kept, and one that fails is answered from it. A ticket is ready to run
as long as its project was seen once — which is what "Notion down blocks no
ticket" needs, and no more: a project created while Notion is away waits for it.

**A ticket page is its two columns put back together.** `mission` and `report`
are stored apart (see `tickets.py`); the page a reader gets is the mission, then
the "what was done" heading and the report, the shape `ticket_page.py` reads. A
write to the page is cut at that heading the same way. The live report of a
running session is a stretch of `report` between two comments, as on a Markdown
board, and is taken off whenever the page is read as a brief or the part is
rewritten.

**The database a page belongs to is "tickets".** `resolve_database` answers it
for the name the configuration uses and for the id Notion gave the database, so
a caller that resolved the workspace and one that never did meet on one word.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import ids, markdown, ticket_page, tickets
from .config import STATUS, TYPES, state_dir
from .store import (
    Comment,
    Missing,
    Page,
    Picture,
    StoreError,
    matches,
    read,
    written,
)
from .tickets import Record

if TYPE_CHECKING:
    from .config import Notion
    from .notion import Client
    from .workspace import Workspace

DATABASE = "tickets"

# The stretch of `report` a running session writes into, as `files.py` does.
LIVE_OPEN = "<!-- ponos:live -->"
LIVE_CLOSE = "<!-- /ponos:live -->"
_LIVE = re.compile(re.escape(LIVE_OPEN) + r".*?" + re.escape(LIVE_CLOSE), re.DOTALL)

# What a ticket column is called on the board (a key of `Notion.prop`) and the
# attribute of `tickets.Record` that holds it. `title` is the page's own name.
COLUMNS = {
    "status": "status",
    "project": "project",
    "agent": "agent",
    "pull_request": "pull_request",
    "session": "session",
    "model": "model",
    "priority": "priority",
    "cost": "cost",
    "duration": "duration",
    "progress": "progress",
    "due": "scheduled",
    "waiting": "waiting",
    "plan": "plan_first",
    "type": "kind",
    "subtype": "subtype",
    "on": "on_change",
    "block": "block",
    "ci": "ci",
    "after": "after",
}

# The columns that stay as they are when empty: a select with no name is no
# option, and reads back as nothing said.
_EMPTY_IS_NOTHING = ("select", "status", "url", "date", "relation")


def schema(settings: Notion) -> dict[str, str]:
    """{column: kind} of the tickets board, from the one place it is declared."""
    from . import provision

    shape = provision.tickets_schema(settings, "projects", "agents", "tickets")
    kinds = {name: next(iter(spec)) for name, spec in shape.items()}
    kinds[settings.prop("goal")] = "relation"
    return kinds


def page_of(settings: Notion, record: Record, kinds: dict[str, str] | None = None) -> Page:
    """A ticket as the page the runner reads."""
    kinds = kinds if kinds is not None else schema(settings)
    title_name = _title_name(kinds)
    properties: dict[str, Any] = {
        title_name: {"type": "title", "title": [{"plain_text": record.title, "type": "text"}]}
    }
    for key, attribute in COLUMNS.items():
        name = settings.prop(key)
        kind = kinds.get(name)
        value = getattr(record, attribute)
        if kind in _EMPTY_IS_NOTHING and value in ("", [], None):
            continue
        if kind == "relation" and isinstance(value, str):
            value = [value]
        shaped = written(kind, value)
        if shaped is not None:
            properties[name] = shaped
    return Page(
        id=record.id,
        url=f"https://www.notion.so/{record.notion}" if record.notion else "",
        title=record.title.strip(),
        properties=properties,
        raw={
            "created_time": record.created_at,
            "last_edited_time": record.edited_at,
            "collection": DATABASE,
        },
    )


def values_of(settings: Notion, page: Page, kinds: dict[str, str] | None = None) -> dict[str, Any]:
    """The columns of a ticket, read off a page of the board.

    The inverse of `page_of`, for what comes up from Notion: an import, a page
    created there. A column the page does not carry is left out, so that
    applying the result to a ticket moves only what the page said.
    """
    kinds = kinds if kinds is not None else schema(settings)
    values: dict[str, Any] = {"title": page.title.strip()}
    for key, attribute in COLUMNS.items():
        name = settings.prop(key)
        if name not in page.properties:
            continue
        value = read(page, name)
        if attribute == "after":
            values["after"] = [ids.bare(one) for one in value or []]
        elif attribute == "project":
            first = (value or [""])[0] if isinstance(value, list) else value
            values["project"] = ids.bare(first)
        elif attribute in ("waiting", "plan_first"):
            values[attribute] = bool(value)
        elif attribute == "priority":
            values[attribute] = _number(value, 50, whole=True)
        elif attribute in ("cost", "duration"):
            values[attribute] = _number(value, 0.0)
        elif attribute == "scheduled":
            values[attribute] = str(value or "")
        else:
            values[attribute] = "" if value is None else str(value)
    status = values.get("status")
    if status is not None and status not in tickets.STATUSES:
        values.pop("status")
    return values


def _number(value: Any, default: float, *, whole: bool = False) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return int(number) if whole else number


def _title_name(kinds: dict[str, str]) -> str:
    return next((name for name, kind in kinds.items() if kind == "title"), "Name")


def body_of(record: Record, *, live: bool = True) -> str:
    """The page as one text: the mission, then what was done under its heading."""
    report = record.report if live else _LIVE.sub("", record.report)
    report = re.sub(r"\n{3,}", "\n\n", report).strip()
    if not report:
        return record.mission.strip()
    return f"{record.mission.strip()}\n\n## {ticket_page.DONE[0]}\n\n{report}".strip()


def _stripped(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _LIVE.sub("", text)).strip()


class Ledger:
    """A `Store` whose tickets are rows of `ponos.db` and whose remainder is Notion's."""

    def __init__(self, notion: Client, settings: Notion, cache: Path | None = None) -> None:
        self.notion = notion
        self._settings = settings
        self._kinds: dict[str, str] | None = None
        self._cache = cache
        self._known: dict[str, Any] | None = None
        self._tickets_id = ""

    # -- the cache of what Notion said last ----------------------------------

    @property
    def settings(self) -> Notion:
        return self._settings

    def kinds(self) -> dict[str, str]:
        if self._kinds is None:
            self._kinds = schema(self._settings)
        return self._kinds

    def _path(self) -> Path:
        return self._cache or state_dir() / "notion-cache.json"

    def _remembered(self) -> dict[str, Any]:
        if self._known is None:
            try:
                loaded = json.loads(self._path().read_text(encoding="utf-8"))
                self._known = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                self._known = {}
        return self._known

    def _remember(self, key: str, value: Any) -> None:
        known = self._remembered()
        known[key] = value
        path = self._path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            scratch = path.with_suffix(f".{os.getpid()}.tmp")
            scratch.write_text(json.dumps(known), encoding="utf-8")
            scratch.replace(path)
        except OSError:
            pass

    def _page_from(self, raw: dict[str, Any]) -> Page:
        return Page(**{key: raw[key] for key in ("id", "url", "title", "properties", "raw")})

    # -- which side a page is on ---------------------------------------------

    def _mine(self, page_id: str) -> Record | None:
        return tickets.by_notion(page_id) if ids.bare(page_id) else None

    def _is_tickets(self, database_id: str) -> bool:
        wanted = ids.bare(database_id)
        return wanted in ("", DATABASE) or (
            bool(self._tickets_id) and wanted == ids.bare(self._tickets_id)
        )

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str:
        """`tickets` for the tickets database, whatever it was called; Notion's answer otherwise."""
        configured = ids.bare(self._settings.tickets_database)
        if self._is_tickets(identifier) or (configured and ids.bare(identifier) == configured):
            return DATABASE
        return self.notion.resolve_database(identifier)

    def forget_database(self, database_id: str) -> None:
        if not self._is_tickets(database_id):
            self.notion.forget_database(database_id)

    def schema(self, database_id: str) -> dict[str, str]:
        if self._is_tickets(database_id):
            return self.kinds()
        return self.notion.schema(database_id)

    def options(self, database_id: str, name: str) -> list[str]:
        """What a column of the tickets may say: the board's own words, then what is in use."""
        if not self._is_tickets(database_id):
            return self.notion.options(database_id, name)
        settings = self._settings
        declared: list[str] = []
        if name == settings.prop("status"):
            declared = list(STATUS.values())
        elif name == settings.prop("type"):
            declared = list(TYPES.values())
        seen = list(dict.fromkeys(declared))
        for page in self.query(DATABASE):
            value = read(page, name)
            if isinstance(value, str) and value and value not in seen:
                seen.append(value)
        return seen

    def title_property(self, database_id: str) -> str:
        if self._is_tickets(database_id):
            return _title_name(self.kinds())
        return self.notion.title_property(database_id)

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]:
        if self._is_tickets(database_id):
            pages = [page_of(self._settings, record, self.kinds()) for record in tickets.listing()]
            return [page for page in pages if matches(page, filter_)]
        key = f"query:{database_id}:{json.dumps(filter_, sort_keys=True)}"
        try:
            found = self.notion.query(database_id, filter_)
        except StoreError:
            if key not in self._remembered():
                raise
            return [self._page_from(raw) for raw in self._remembered()[key]]
        self._remember(key, [asdict(page) for page in found])
        return found

    def page(self, page_id: str) -> Page:
        record = self._mine(page_id)
        if record is not None:
            return page_of(self._settings, record, self.kinds())
        key = f"page:{ids.bare(page_id)}"
        try:
            found = self.notion.page(page_id)
        except Missing:
            raise
        except StoreError:
            if key not in self._remembered():
                raise
            return self._page_from(self._remembered()[key])
        self._remember(key, asdict(found))
        return found

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        record = self._mine(block_id)
        if record is not None:
            return body_of(record, live=live)
        key = f"text:{ids.bare(block_id)}"
        try:
            text = self.notion.blocks_text(block_id, depth, live=live)
        except Missing:
            raise
        except StoreError:
            if key not in self._remembered():
                raise
            return str(self._remembered()[key])
        if depth == 0 and live:
            self._remember(key, text)
        return text

    def comments(self, page_id: str) -> list[Comment]:
        """The ticket's discussion: what Notion said since last asked, then the table.

        A comment written in Notion reaches `ponos.db` here, the moment it is
        looked for, so that an answer is read no later than it was before the
        database held the tickets. Notion not answering is not an error: the
        discussion is what the table has.
        """
        record = self._mine(page_id)
        if record is None:
            return self.notion.comments(page_id)
        if record.notion:
            with contextlib.suppress(StoreError):
                self.take_comments(record)
        return [
            Comment(
                remark.text,
                remark.at,
                id=str(remark.id),
                discussion_id=remark.discussion,
                created_by=remark.author,
            )
            for remark in tickets.comments(record.id)
        ]

    def take_comments(self, record: Record) -> int:
        """Bring up the comments Notion has on a ticket's page that the table lacks."""
        mine = self.notion.me()
        known = {remark.text.strip() for remark in tickets.comments(record.id)}
        added = 0
        for comment in self.notion.comments(record.notion):
            if comment.created_by == mine or comment.text.strip() in known:
                continue
            tickets.comment(
                record.id,
                comment.text,
                author=comment.created_by or "notion",
                discussion=comment.discussion_id,
                mirrored=True,
            )
            known.add(comment.text.strip())
            added += 1
        return added

    def attachment(self, block_id: str) -> str:
        return self.notion.attachment(block_id)

    # -- writing -------------------------------------------------------------

    def _columns(self, values: dict[str, Any]) -> dict[str, Any]:
        """Property values by their board name, as the columns of a ticket."""
        settings = self._settings
        title_name = self.title_property(DATABASE)
        by_name = {settings.prop(key): attribute for key, attribute in COLUMNS.items()}
        columns: dict[str, Any] = {}
        for name, value in values.items():
            if name == title_name:
                columns["title"] = str(value or "").strip()
                continue
            attribute = by_name.get(name)
            if attribute is None or value is None:
                continue
            if attribute == "after":
                columns[attribute] = [
                    ids.bare(one)
                    for one in (value if isinstance(value, (list, tuple)) else [value])
                    if one
                ]
            elif attribute == "project":
                chosen = value if isinstance(value, (list, tuple)) else [value]
                columns[attribute] = ids.bare(chosen[0]) if chosen else ""
            elif attribute in ("waiting", "plan_first"):
                columns[attribute] = bool(value)
            elif attribute == "priority":
                columns[attribute] = _number(value, 50, whole=True)
            elif attribute in ("cost", "duration"):
                columns[attribute] = _number(value, 0.0)
            elif isinstance(value, datetime):
                columns[attribute] = value.isoformat()
            else:
                columns[attribute] = str(value)
        return columns

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if not self._is_tickets(database_id) and self._mine(page_id) is None:
            self.notion.update(database_id, page_id, values)
            return
        record = self._mine(page_id)
        if record is None:
            raise Missing(f"no such ticket: {page_id}")
        columns = self._columns(values)
        if columns:
            try:
                tickets.update(record.id, **columns)
            except ValueError as error:
                raise StoreError(str(error)) from error

    def create_row(self, database_id: str, title: str, values: dict[str, Any] | None = None) -> str:
        if not self._is_tickets(database_id):
            return self.notion.create_row(database_id, title, values)
        columns = self._columns(values or {})
        columns.pop("title", None)
        try:
            return tickets.create(title.strip(), **columns).id
        except ValueError as error:
            raise StoreError(str(error)) from error

    def _write(
        self, record: Record, *, mission: str | None = None, report: str | None = None
    ) -> None:
        columns: dict[str, Any] = {}
        if mission is not None and mission.strip() != record.mission.strip():
            columns["mission"] = mission.strip()
        if report is not None and report.strip() != record.report.strip():
            columns["report"] = report.strip()
        if columns:
            tickets.update(record.id, **columns)

    def append_markdown(self, page_id: str, markdown_text: str) -> int:
        record = self._mine(page_id)
        if record is None:
            return self.notion.append_markdown(page_id, markdown_text)
        parts = ticket_page.split(markdown_text)
        mission = f"{record.mission}\n\n{parts.mission}".strip() if parts.mission else None
        self._write(record, mission=mission, report=parts.done or None)
        return len(markdown.to_blocks(markdown_text))

    def replace_markdown(self, page_id: str, markdown_text: str) -> int:
        record = self._mine(page_id)
        if record is None:
            return self.notion.replace_markdown(page_id, markdown_text)
        parts = ticket_page.split(markdown_text)
        self._write(record, mission=parts.mission, report=parts.done)
        return len(markdown.to_blocks(markdown_text))

    def replace_section(self, page_id: str, titles: Sequence[str], markdown_text: str) -> int:
        record = self._mine(page_id)
        if record is None:
            return self.notion.replace_section(page_id, titles, markdown_text)
        # The text begins with its own heading; the column holds what is under it.
        lines = markdown_text.strip().splitlines()
        if lines and ticket_page.is_heading(lines[0], (*titles, *ticket_page.DONE)):
            lines = lines[1:]
        self._write(record, report="\n".join(lines).strip())
        return len(markdown.to_blocks(markdown_text))

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        """A running session's live report, kept in a stretch of `report` of its own."""
        record = self._mine(block_id)
        if record is None:
            return self.notion.append_blocks(block_id, blocks)
        text = "\n".join(markdown.plain(block) for block in blocks).strip()
        if not text:
            return [record.id] * len(blocks)
        report = record.report.strip()
        opens = any(block.get("type") == "toggle" for block in blocks)
        if not opens and report.endswith(LIVE_CLOSE):
            report = f"{report[: -len(LIVE_CLOSE)].rstrip()}\n\n{text}\n\n{LIVE_CLOSE}"
        else:
            report = f"{report}\n\n{LIVE_OPEN}\n\n{text}\n\n{LIVE_CLOSE}".strip()
        self._write(record, report=report)
        return [record.id] * len(blocks)

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None:
        if self._mine(block_id) is None:
            self.notion.update_block(block_id, payload)

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        if self._mine(block_id) is not None:
            return {}
        return self.notion.losses(block_id, depth)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        record = self._mine(page_id)
        if record is None:
            self.notion.comment(page_id, text, discussion_id)
            return
        tickets.comment(record.id, text, author=self.me(), discussion=discussion_id)

    def trash(self, page_id: str) -> str:
        record = self._mine(page_id)
        if record is None:
            return self.notion.trash(page_id)
        tickets.delete(record.id)
        return f"https://www.notion.so/{record.notion}" if record.notion else ""

    def set_picture(self, page_id: str, slot: str, picture: Picture) -> Page:
        if self._mine(page_id) is not None:
            raise StoreError("a ticket has no cover or icon in ponos.db")
        return self.notion.set_picture(page_id, slot, picture)

    # -- who we are ----------------------------------------------------------

    def me(self) -> str:
        """The name the runner's own comments carry in the table: no API to ask."""
        return "ponos"

    def my_name(self) -> str:
        """The integration's name, for the mentions of a comment; Notion's, when it says."""
        try:
            return self.notion.my_name() or "ponos"
        except StoreError:
            return "ponos"

    # -- the board's own shape -----------------------------------------------

    def workspace(self, settings: Notion) -> Workspace:
        """Notion's workspace with the tickets database swapped for the table.

        Notion not answering is not a reason to stop: the workspace is the one
        the last pass saw, and when none was ever seen the tickets are still
        there, with no project to run them in.
        """
        from .workspace import Workspace

        if settings is not self._settings:
            self._settings, self._kinds = settings, None
        key = "workspace"
        try:
            space = self.notion.workspace(settings)
        except StoreError as error:
            if key in self._remembered():
                space = Workspace(**self._remembered()[key])
                space.warnings.append(
                    f"Notion does not answer — the workspace is the last one seen ({error})"
                )
            else:
                space = Workspace(warnings=[f"Notion does not answer: {error}"])
        else:
            self._remember(key, asdict(space))
        self._tickets_id = space.tickets
        space.tickets = DATABASE
        return space
