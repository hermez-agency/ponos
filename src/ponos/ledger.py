"""The board as `ponos.db` keeps it: tickets read and written there, the rest left to Notion.

This is the seam's fourth backend, and the one that makes the database the
source of truth. The runner, the console, the MCP and the CLI were written
against `store.Store` — a page with Notion-shaped properties — and rewriting
the hundred and thirty places that read or write one would have been a rewrite
pretending to be a refactor. So the tickets keep their shape on the way out
(`_page`: a `Page` whose properties are those of the board, built from a row of
`tickets.py`) and on the way in (`_row`: the properties a caller writes, back
into columns), and everything that is not a ticket goes on to the Notion client
untouched: projects, agents, goals, schedules, the standing context.

**Notion is touched by the mirror and by nothing else here.** A write to a
ticket is a write to `ponos.db` and a row in the mirror's queue; the board is
told on the next pass (`board.Board.mirror`). A Notion that is down, or whose
token is refused, changes nothing for a ticket: the columns and the options
the runner asks about come from the shape of the board (`store.shape`), not
from a request, and the databases it resolved last are kept in a small file
(`_Remembered`) for the pass that cannot resolve them.

**Until the database has a ticket, this is Notion.** `ponos import notion` is
what fills it (notion_import.py); a board never imported goes on being read and
written in Notion as before, and starts being served from the database the
moment the first ticket is in it — no restart, the question is asked at each
call.

**The two parts of a page are two columns.** A body read is the mission and the
report under their headings; a body written (`replace_markdown`,
`replace_section`, `append_markdown`) is cut again at the same headings
(`ticket_page.split`). The live blocks the Notion page used to carry
(`append_blocks`) have no place here: the steps of a session are in the run
journal, and the progress is a column.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from . import db, ids, pages, provision, store, ticket_page, tickets, vault
from . import voice as voice_module
from .config import STATUS, Notion
from .log import FILE_ONLY
from .store import Comment, Page, Picture
from .workspace import Workspace

log = logging.getLogger(__name__)

# (column of the ticket, key of the board's property). `project`, `role` and
# `goal` each hold one page id; `after` holds several.
_PROPERTIES = (
    ("status", "status"),
    ("project", "project"),
    ("role", "role"),
    ("goal", "goal"),
    ("kind", "type"),
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
    ("priority", "priority"),
    ("cost", "cost"),
    ("duration", "duration"),
    ("waiting", "waiting"),
    ("plan_first", "plan"),
    ("after", "after"),
)
_ONE = ("project", "role", "goal")
_DEFAULTS = {"priority": 50, "cost": 0.0, "duration": 0.0}
# The kinds of property that read as nothing when unset, as Notion answers them.
_NULLABLE = ("status", "select", "url", "date", "number")


def _bare(page: object) -> str:
    return ids.bare(page)


class _Remembered:
    """What was last learnt from Notion and a pass cannot do without.

    The ids of the databases of the workspace, and who the integration is. Kept
    in a file beside `ponos.db`, written only when Notion answered: it is what
    lets a pass start while Notion refuses to.
    """

    def __init__(self) -> None:
        self.path = db.path().parent / "notion-identity.json"

    def read(self) -> dict[str, Any]:
        try:
            found = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return found if isinstance(found, dict) else {}

    def write(self, **values: Any) -> None:
        merged = {**self.read(), **values}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            writing = self.path.with_name(f"{self.path.name}.{os.getpid()}")
            writing.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")
            writing.replace(self.path)
        except OSError:
            log.warning("could not remember the Notion identity", exc_info=True, extra=FILE_ONLY)


class _Pages:
    """The pages of the other databases a pass has read, kept for a pass that cannot.

    A ticket points at its project, and the project page says which repository
    it runs on: with Notion refusing, that page is what stands between a ready
    ticket and a session. Each page is written as Notion last gave it, and only
    when it changed.
    """

    def __init__(self) -> None:
        self.path = db.path().parent / "notion-pages.json"

    def _all(self) -> dict[str, Any]:
        try:
            found = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return found if isinstance(found, dict) else {}

    def keep(self, pages: list[Page]) -> None:
        held = self._all()
        changed = False
        for page in pages:
            entry = {"id": page.id, "url": page.url, "title": page.title, "raw": page.raw}
            if held.get(_bare(page.id)) != entry:
                held[_bare(page.id)] = entry
                changed = True
        if not changed:
            return
        try:
            writing = self.path.with_name(f"{self.path.name}.{os.getpid()}")
            writing.write_text(json.dumps(held), encoding="utf-8")
            writing.replace(self.path)
        except OSError:
            log.warning("could not keep a Notion page", exc_info=True, extra=FILE_ONLY)

    def get(self, page_id: str) -> Page | None:
        entry = self._all().get(_bare(page_id))
        if not isinstance(entry, dict):
            return None
        raw = entry.get("raw") or {}
        return Page(
            entry.get("id", page_id),
            entry.get("url", ""),
            entry.get("title", ""),
            raw.get("properties", {}),
            raw,
        )


class Ledger:
    """A `store.Store` whose tickets are rows of `ponos.db`. Everything else is `notion`'s."""

    def __init__(self, notion: store.Store, settings: Notion, language: str = "") -> None:
        self.notion = notion
        self.settings = settings
        self.words = voice_module.Voice(language)
        self._tickets = ""
        # Without Notion there is nothing to fall back on: the tickets are the
        # database's from the first one, adopted or not.
        self._alone = isinstance(notion, pages.Pages)
        self._remembered = _Remembered()
        self._pages = _Pages()
        schema = store.shape(settings)["tickets"]
        self._schema = schema
        self._by_name = {settings.prop(key): column for column, key in _PROPERTIES}
        self._title = next((name for name, kind in schema.items() if kind == "title"), "Name")

    def __getattr__(self, name: str) -> Any:
        # Provisioning, the setup page, the pictures of the other databases:
        # what only Notion has is asked of Notion.
        return getattr(self.notion, name)

    # -- what is ours --------------------------------------------------------

    def _live(self, database_id: str) -> bool:
        """Whether this database is the tickets one and the database holds tickets."""
        return bool(self._tickets) and _bare(database_id) == self._tickets and self._adopted()

    def _adopted(self) -> bool:
        return self._alone or tickets.adopted()

    def _ticket(self, page_id: str) -> tickets.Record | None:
        """The ticket a page id names, or None for a page that is not one (or no ledger yet)."""
        if not self._tickets or not self._adopted():
            return None
        return tickets.of_page(page_id)

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str:
        return self.notion.resolve_database(identifier)

    def forget_database(self, database_id: str) -> None:
        self.notion.forget_database(database_id)

    def schema(self, database_id: str) -> dict[str, str]:
        if self._live(database_id):
            return dict(self._schema)
        return self.notion.schema(database_id)

    def options(self, database_id: str, name: str) -> list[str]:
        if not self._live(database_id):
            return self.notion.options(database_id, name)
        if name == self.settings.prop("status"):
            return list(STATUS.values())
        shape = provision.tickets_schema(self.settings).get(name) or {}
        found: dict[str, Any] = next(iter(shape.values()), {})
        return [str(item["name"]) for item in found.get("options", [])]

    def title_property(self, database_id: str) -> str:
        if self._live(database_id):
            return self._title
        return self.notion.title_property(database_id)

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]:
        if not self._live(database_id):
            found = self.notion.query(database_id, filter_)
            if not filter_:
                self._pages.keep(found)
            return found
        pages = [self._page(record) for record in tickets.listing()]
        return [page for page in pages if store.matches(page, filter_)]

    def page(self, page_id: str) -> Page:
        if (record := self._ticket(page_id)) is not None:
            return self._page(record)
        try:
            page = self.notion.page(page_id)
        except store.Missing:
            raise
        except store.StoreError:
            if (kept := self._pages.get(page_id)) is not None:
                return kept
            raise
        self._pages.keep([page])
        return page

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        if (record := self._ticket(block_id)) is not None:
            return self._body(record)
        return self.notion.blocks_text(block_id, depth, live=live)

    def comments(self, page_id: str) -> list[Comment]:
        if (record := self._ticket(page_id)) is None:
            return self.notion.comments(page_id)
        return [
            Comment(
                remark.text,
                created_time=remark.at,
                id=str(remark.id),
                discussion_id=remark.discussion,
                created_by=remark.author,
            )
            for remark in tickets.comments(record.id)
        ]

    def attachment(self, block_id: str) -> str:
        return self.notion.attachment(block_id)

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        record = self._ticket(page_id) if self._live(database_id) else None
        if record is None:
            self.notion.update(database_id, page_id, self._for_notion(values))
            return
        self._write(lambda: tickets.update(record.id, **self._row(values)))

    def create_row(self, database_id: str, title: str, values: dict[str, Any] | None = None) -> str:
        if not self._live(database_id):
            return self.notion.create_row(database_id, title, self._for_notion(values or {}))
        row = self._row(values or {})
        after = row.pop("after", None)
        made = self._write(lambda: tickets.create(vault.mask(title.strip()), after=after, **row))
        return made.id if made else ""

    def append_markdown(self, page_id: str, markdown: str) -> int:
        if (record := self._ticket(page_id)) is None:
            return self.notion.append_markdown(page_id, markdown)
        self._rewrite(record, f"{self._body(record)}\n\n{markdown.strip()}")
        return _blocks(markdown)

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        if (record := self._ticket(page_id)) is None:
            return self.notion.replace_markdown(page_id, markdown)
        self._rewrite(record, markdown)
        return _blocks(markdown)

    def replace_section(self, page_id: str, titles: Sequence[str], markdown: str) -> int:
        if (record := self._ticket(page_id)) is None:
            return self.notion.replace_section(page_id, titles, markdown)
        lines = self._body(record).splitlines()
        cut = next(
            (index for index, line in enumerate(lines) if ticket_page.is_heading(line, titles)),
            len(lines),
        )
        above = "\n".join(lines[:cut]).strip()
        self._rewrite(record, f"{above}\n\n{markdown.strip()}")
        return _blocks(markdown)

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        if self._ticket(block_id) is None:
            return self.notion.append_blocks(block_id, blocks)
        return [_bare(block_id)] * len(blocks)

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None:
        if self._ticket(block_id) is None:
            self.notion.update_block(block_id, payload)

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        if self._ticket(block_id) is not None:
            return {}
        return self.notion.losses(block_id, depth)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        if (record := self._ticket(page_id)) is None:
            self.notion.comment(page_id, text, discussion_id)
            return
        self._write(
            lambda: tickets.comment(
                record.id,
                vault.mask(text),
                author=self._remembered.read().get("me", ""),
                discussion=discussion_id,
            )
        )

    def trash(self, page_id: str) -> str:
        if (record := self._ticket(page_id)) is None:
            return self.notion.trash(page_id)
        tickets.delete(record.id)
        return ""

    def set_picture(self, page_id: str, slot: str, picture: Picture) -> Page:
        record = self._ticket(page_id)
        if record is None:
            return self.notion.set_picture(page_id, slot, picture)
        if not record.notion:
            raise store.StoreError("its page is not created in Notion yet")
        self.notion.set_picture(record.notion, slot, picture)
        return self._page(record)

    # -- who we are ----------------------------------------------------------

    def me(self) -> str:
        """The integration's id, from Notion when it answers, else as last remembered."""
        try:
            found = self.notion.me()
        except store.StoreError:
            return str(self._remembered.read().get("me", ""))
        if found:
            self._remembered.write(me=found)
        return found

    def my_name(self) -> str:
        try:
            found = self.notion.my_name()
        except store.StoreError:
            return str(self._remembered.read().get("name", ""))
        if found:
            self._remembered.write(name=found)
        return found

    # -- the board's own shape -----------------------------------------------

    def workspace(self, settings: Notion) -> Workspace:
        """Notion's workspace; the last one it gave when it will not answer now.

        Remembered only whole: a pass that cannot resolve and has nothing to
        fall back on fails as it always did. The context is not kept — it is a
        page of Notion, and a pass without it says so.
        """
        try:
            space = self.notion.workspace(settings)
        except store.StoreError:
            kept = self._remembered.read().get("workspace")
            if not isinstance(kept, dict) or not kept.get("tickets"):
                raise
            space = Workspace(**kept)
            space.warnings.append("Notion does not answer — the databases are those last seen")
        else:
            self._remembered.write(
                workspace={
                    name: getattr(space, name)
                    for name in ("tickets", "projects", "agents", "schedules", "goals", "rows")
                }
            )
            self.me()
        self._tickets = _bare(space.tickets)
        return space

    # -- tickets as pages ----------------------------------------------------

    def _page(self, record: tickets.Record) -> Page:
        settings = self.settings
        properties: dict[str, Any] = {
            self._title: {"type": "title", "title": [{"plain_text": record.title, "type": "text"}]}
        }
        for column, key in _PROPERTIES:
            name = settings.prop(key)
            kind = self._schema.get(name)
            value: Any = getattr(record, column)
            if column == "kind":
                value = (
                    settings.kind(value)
                    if value in ("code", "writing", "external", "publication")
                    else ""
                )
            elif column in _ONE:
                value = [value] if value else []
            elif column in ("cost", "duration"):
                value = value or None
            if value == "" and kind in _NULLABLE:
                continue
            if (written := store.written(kind, value)) is not None:
                properties[name] = written
        url = f"https://www.notion.so/{record.notion}" if record.notion else ""
        raw = {
            "id": record.id,
            "url": url,
            "created_time": record.created_at,
            "last_edited_time": record.edited_at,
            "properties": properties,
        }
        return Page(record.id, url, record.title, properties, raw)

    def _row(self, values: dict[str, Any]) -> dict[str, Any]:
        """The properties a caller writes, as columns of the ticket."""
        row: dict[str, Any] = {}
        for name, value in values.items():
            if name == self._title:
                row["title"] = str(value or "").strip()
                continue
            column = self._by_name.get(name)
            if column is None:
                continue  # a column the ticket has no use for: left out, as Notion's own client does
            if column == "after":
                row[column] = [_bare(one) for one in value or []]
            elif column in _ONE:
                related = value if isinstance(value, (list, tuple)) else [value]
                row[column] = next((_bare(one) for one in related if one), "")
            elif column == "kind":
                row[column] = self.settings.kind_of(str(value or ""))
            elif column in _DEFAULTS:
                row[column] = _DEFAULTS[column] if value is None else value
            elif column in ("waiting", "plan_first"):
                row[column] = bool(value)
            elif isinstance(value, datetime):
                row[column] = value.isoformat()
            else:
                row[column] = "" if value is None else str(value)
        return row

    def _for_notion(self, values: dict[str, Any]) -> dict[str, Any]:
        """A write to a page of another database, its relations to tickets made Notion's.

        A ticket born here has an id of its own until the mirror has made its
        page; a relation (a schedule's last ticket) can only name the page, and
        one that has none yet is left out. Anything that is not a ticket is
        passed on as it came — and so is everything, without a Notion: a ticket
        is then the only page a relation can name.
        """
        if self._alone:
            return dict(values)
        out: dict[str, Any] = {}
        for name, value in values.items():
            if isinstance(value, (list, tuple)):
                kept = []
                for one in value:
                    record = self._ticket(one) if isinstance(one, str) else None
                    if record is None:
                        kept.append(one)
                    elif record.notion:
                        kept.append(record.notion)
                out[name] = kept
            else:
                out[name] = value
        return out

    def _body(self, record: tickets.Record) -> str:
        words = self.words
        text = f"## {words.say('page-mission')}\n\n{record.mission.strip()}"
        if record.report.strip():
            text += f"\n\n## {words.say('page-done')}\n\n{record.report.strip()}"
        return text

    def _rewrite(self, record: tickets.Record, markdown: str) -> None:
        """Cut a whole page back into its two parts and keep them."""
        # The database is a door like the others: see vault.py.
        parts = ticket_page.split(vault.mask(markdown))
        done = parts.done
        for words in voice_module.every("page-done-empty"):
            if done.strip().strip("*").strip() == words:
                done = ""
        if parts.mission != record.mission or done != record.report:
            self._write(lambda: tickets.update(record.id, mission=parts.mission, report=done))

    @staticmethod
    def _write(action: Any) -> Any:
        try:
            return action()
        except ValueError as error:
            raise store.StoreError(str(error)) from error


def _blocks(markdown: str) -> int:
    return len([part for part in markdown.split("\n\n") if part.strip()])
