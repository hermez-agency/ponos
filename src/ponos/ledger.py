"""The board as `ponos.db` keeps it: tickets read and written there, the other pages beside them.

The runner, the console, the MCP and the CLI were written against
`store.Store` — a page whose properties are typed values — and rewriting the
hundred and thirty places that read or write one would have been a rewrite
pretending to be a refactor. So the tickets keep that shape on the way out
(`_page`: a `Page` whose properties are those of the board, built from a row of
`tickets.py`) and on the way in (`_row`: the properties a caller writes, back
into columns), and everything that is not a ticket goes on to `pages.py`
untouched: projects, agents, goals, schedules, the standing context.

**The three parts of a page are three columns.** A body read is the mission,
the result and the journal under their headings; a body written
(`replace_markdown`, `replace_section`, `append_markdown`) is cut again at the
same headings (`ticket_page.split`), and gives back the mission and the journal
— a result is only ever a new version (`tickets.set_result`). The steps of a session are in the run journal, and the
progress is a column.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from . import ids, store, ticket_page, tickets, vault
from . import voice as voice_module
from .config import STATUS, TYPES, BoardNames
from .pages import Pages
from .store import Comment, Page, Picture
from .workspace import Workspace

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
# The kinds of property that read as nothing when unset.
_NULLABLE = ("status", "select", "url", "date", "number")


def _bare(page: object) -> str:
    return ids.bare(page)


class Ledger:
    """A `store.Store` whose tickets are rows of `ponos.db`. Everything else is `pages.py`'s."""

    def __init__(
        self, backend: Pages, settings: BoardNames, language: str = "", console: str = ""
    ) -> None:
        self.backend = backend
        self.settings = settings
        self.words = voice_module.Voice(language)
        self.console = console.rstrip("/")
        schema = store.shape(settings)["tickets"]
        self._schema = schema
        self._by_name = {settings.prop(key): column for column, key in _PROPERTIES}
        self._title = next((name for name, kind in schema.items() if kind == "title"), "Name")

    def __getattr__(self, name: str) -> Any:
        # The standing context, the pictures of the other pages: what only the
        # pages have is asked of them.
        return getattr(self.backend, name)

    # -- what is ours --------------------------------------------------------

    def _live(self, database_id: str) -> bool:
        """Whether this is the tickets collection."""
        return self.backend.resolve_database(database_id) == "tickets"

    @staticmethod
    def _ticket(page_id: str) -> tickets.Record | None:
        """The ticket a page id names, or None for a page that is not one."""
        return tickets.of_page(page_id)

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str:
        return self.backend.resolve_database(identifier)

    def forget_database(self, database_id: str) -> None:
        self.backend.forget_database(database_id)

    def schema(self, database_id: str) -> dict[str, str]:
        if self._live(database_id):
            return dict(self._schema)
        return self.backend.schema(database_id)

    def options(self, database_id: str, name: str) -> list[str]:
        if not self._live(database_id):
            return self.backend.options(database_id, name)
        if name == self.settings.prop("status"):
            return list(STATUS.values())
        return store.options(self.settings, name)

    def title_property(self, database_id: str) -> str:
        if self._live(database_id):
            return self._title
        return self.backend.title_property(database_id)

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]:
        if not self._live(database_id):
            return self.backend.query(database_id, filter_)
        pages = [self._page(record) for record in tickets.listing()]
        return [page for page in pages if store.matches(page, filter_)]

    def page(self, page_id: str) -> Page:
        if (record := self._ticket(page_id)) is not None:
            return self._page(record)
        return self.backend.page(page_id)

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        if (record := self._ticket(block_id)) is not None:
            return self._body(record)
        return self.backend.blocks_text(block_id, depth, live=live)

    def comments(self, page_id: str) -> list[Comment]:
        if (record := self._ticket(page_id)) is None:
            return self.backend.comments(page_id)
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

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        record = self._ticket(page_id) if self._live(database_id) else None
        if record is None:
            self.backend.update(database_id, page_id, values)
            self._nudge({"status": values.get(self.settings.prop("status"))})
            return
        row = self._row(values)
        self._write(lambda: tickets.update(record.id, **row))
        self._nudge(row)

    def create_row(self, database_id: str, title: str, values: dict[str, Any] | None = None) -> str:
        if not self._live(database_id):
            return self.backend.create_row(database_id, title, values or {})
        row = self._row(values or {})
        after = row.pop("after", None)
        made = self._write(lambda: tickets.create(vault.mask(title.strip()), after=after, **row))
        self._nudge(row)
        return made.id if made else ""

    def _nudge(self, row: dict[str, Any]) -> None:
        """A ticket just made ready or validated: the daemon is told now, not at its next look.

        Whoever wrote it — the console, the MCP, a channel's answer, the CLI —
        writes through here. The daemon's own writes do not wake it: it knows.
        """
        status = row.get("status")
        if status and status in (self.settings.state("ready"), self.settings.state("validated")):
            from . import daemon

            daemon.nudge()

    def append_markdown(self, page_id: str, markdown: str) -> int:
        if (record := self._ticket(page_id)) is None:
            return self.backend.append_markdown(page_id, markdown)
        self._rewrite(record, f"{self._body(record)}\n\n{markdown.strip()}")
        return _blocks(markdown)

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        if (record := self._ticket(page_id)) is None:
            return self.backend.replace_markdown(page_id, markdown)
        self._rewrite(record, markdown)
        return _blocks(markdown)

    def replace_section(self, page_id: str, titles: Sequence[str], markdown: str) -> int:
        if (record := self._ticket(page_id)) is None:
            return self.backend.replace_section(page_id, titles, markdown)
        lines = self._body(record).splitlines()
        cut = next(
            (index for index, line in enumerate(lines) if ticket_page.is_heading(line, titles)),
            len(lines),
        )
        above = "\n".join(lines[:cut]).strip()
        self._rewrite(record, f"{above}\n\n{markdown.strip()}")
        return _blocks(markdown)

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        return {}

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        if (record := self._ticket(page_id)) is None:
            self.backend.comment(page_id, text, discussion_id)
            return
        self._write(
            lambda: tickets.comment(
                record.id, vault.mask(text), author=self.me(), discussion=discussion_id
            )
        )

    def trash(self, page_id: str) -> str:
        if (record := self._ticket(page_id)) is None:
            return self.backend.trash(page_id)
        tickets.delete(record.id)
        return ""

    def set_picture(self, page_id: str, slot: str, picture: Picture) -> Page:
        if self._ticket(page_id) is not None:
            raise store.StoreError("a ticket carries no picture")
        return self.backend.set_picture(page_id, slot, picture)

    # -- who we are ----------------------------------------------------------

    def me(self) -> str:
        return self.backend.me()

    def my_name(self) -> str:
        return self.backend.my_name()

    # -- the board's own shape -----------------------------------------------

    def workspace(self, settings: BoardNames) -> Workspace:
        return self.backend.workspace(settings)

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
                value = settings.kind(value) if value in TYPES else ""
            elif column in _ONE:
                value = [value] if value else []
            elif column in ("cost", "duration"):
                value = value or None
            if value == "" and kind in _NULLABLE:
                continue
            if (written := store.written(kind, value)) is not None:
                properties[name] = written
        # The ticket's address is the console's.
        url = (
            f"{self.console}/tickets/{record.id}" if self.console else f"ponos://ticket/{record.id}"
        )
        raw = {
            "id": record.id,
            "url": url,
            "created_time": record.created_at,
            "last_edited_time": record.edited_at,
            "properties": properties,
            # Not a property of the board: what the card shows of the result.
            "result": record.result,
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
                continue  # a column the ticket has no use for: left out
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

    def _body(self, record: tickets.Record) -> str:
        words = self.words
        text = f"## {words.say('page-mission')}\n\n{record.mission.strip()}"
        if record.result.strip():
            text += f"\n\n## {words.say('page-result-heading')}\n\n{record.result.strip()}"
        if record.journal.strip():
            text += f"\n\n## {words.say('page-done')}\n\n{record.journal.strip()}"
        return text

    def _rewrite(self, record: tickets.Record, markdown: str) -> None:
        """Cut a whole page back into its parts, and keep the mission and the journal.

        The result is not written here: a new version of it is a gesture of its
        own (`tickets.set_result`), never the side effect of a page rewritten.
        """
        # The database is a door like the others: see vault.py.
        parts = ticket_page.split(vault.mask(markdown))
        done = parts.done
        for words in voice_module.every("page-done-empty"):
            if done.strip().strip("*").strip() == words:
                done = ""
        if parts.mission != record.mission or done != record.journal:
            self._write(lambda: tickets.update(record.id, mission=parts.mission, journal=done))

    @staticmethod
    def _write(action: Any) -> Any:
        try:
            return action()
        except ValueError as error:
            raise store.StoreError(str(error)) from error


def _blocks(markdown: str) -> int:
    return len([part for part in markdown.split("\n\n") if part.strip()])
