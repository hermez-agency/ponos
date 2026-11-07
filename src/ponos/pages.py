"""The pages that are not tickets, as `ponos.db` keeps them: projects, agents, goals, schedules.

A ticket is a row of `tickets.py`. Everything else a ticket points at —
the project it runs on, the agent that took it, the goal it serves, the
schedule that made it — is a row here, and `ledger.Ledger` hands every read
and write of them on to this store.

**Properties are kept flat, under the board's own names.** One JSON object per
page, `{"Status": "Ready", "Project": ["…"]}`, read back through
`store.written` with the kind `store.shape` declares for the column — the same
reduction every store hands the runner. A column that is not declared is read
as text.

**Nothing is ever deleted.** `trash` sets a flag; every read leaves the page
out, and taking it back is clearing the flag by hand.

**Pictures are files.** A cover or an icon uploaded from the console is written
beside `ponos.db` and the page keeps its `file://` address, which is how
`images.py` knows there is nothing to download.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from . import db, ids, vault
from .store import SLOTS, Comment, Missing, Page, Picture, StoreError, matches, read, shape, written

if TYPE_CHECKING:
    from .config import BoardNames
    from .workspace import Workspace

# The collections a board is made of. `tickets` is here only to be named: its
# rows are `tickets.py`'s, and `ledger.py` answers for them.
COLLECTIONS = ("tickets", "projects", "agents", "schedules", "goals")

# The standing context is the one page that is not in a collection, so it has no
# identifier of its own. This is the name it answers to when a caller addresses
# it as a page — `blocks_text`, `append_markdown`, `replace_markdown`.
CONTEXT_PAGE = "context"

# What a page carries about itself, as opposed to what the board carries about it.
RESERVED = ("id", "title", "created", "edited", "cover", "icon")

# The pictures kept beside a page, by what they are. What a browser can show,
# and nothing it would run: no SVG, which is a document.
PICTURES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


def now() -> str:
    """The moment a page was last written, to the microsecond."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def new_id() -> str:
    """A page identifier the rest of the runner already knows how to read.

    Thirty-two hexadecimal characters, which is what `config.is_identifier`
    accepts and what `short_id` takes its last eight from.
    """
    return uuid.uuid4().hex


def _blocks(markdown: str) -> int:
    """How many paragraphs that text holds, for the reports that count what they wrote."""
    return len([part for part in markdown.split("\n\n") if part.strip()])


class Pages:
    """The pages that are not tickets. One implementation of `store.Store`, for them.

    Stateless on purpose: every read goes to the database, which is a local file.
    """

    def __init__(self, settings: BoardNames | None = None) -> None:
        self._settings = settings
        self._schemas: dict[str, dict[str, str]] | None = None

    def settings(self) -> BoardNames:
        if self._settings is None:
            from .config import BoardNames

            self._settings = BoardNames()
        return self._settings

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str:
        """A collection name, from whatever the caller had in hand."""
        name = str(identifier or "").strip().lower()
        return name if name in COLLECTIONS else "tickets"

    def forget_database(self, database_id: str) -> None:
        """Nothing is cached, so there is nothing to forget."""

    def schema(self, database_id: str) -> dict[str, str]:
        if self._schemas is None:
            self._schemas = shape(self.settings())
        return self._schemas.get(self.resolve_database(database_id), {})

    def options(self, database_id: str, name: str) -> list[str]:
        """Every value that column carries, plus the ones the board declares."""
        from .config import STATUS

        declared: list[str] = []
        if name == self.settings().prop("status"):
            declared = list(STATUS.values())
        seen = list(dict.fromkeys(declared))
        for page in self.query(database_id):
            value = read(page, name)
            if isinstance(value, str) and value and value not in seen:
                seen.append(value)
        return seen

    def title_property(self, database_id: str) -> str:
        return "Name"

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]:
        collection = self.resolve_database(database_id)
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT id, collection, title, properties, body, created, edited, cover, icon"
                " FROM board_pages WHERE collection = ? AND trashed = 0 ORDER BY created, id",
                (collection,),
            ).fetchall()
        pages = [self._page_of(row) for row in rows]
        return [page for page in pages if matches(page, filter_)]

    def page(self, page_id: str) -> Page:
        return self._page_of(self._row(page_id))

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        """A page's body. Already Markdown, so already what an agent reads."""
        return str(self._row(block_id)[4]).strip()

    def comments(self, page_id: str) -> list[Comment]:
        """The discussion of one page, oldest first."""
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT id, at, author, discussion, body FROM board_comments"
                " WHERE page = ? ORDER BY rowid",
                (ids.bare(page_id),),
            ).fetchall()
        return [
            Comment(str(body), str(at), id=str(one), discussion_id=str(discussion), created_by=by)
            for one, at, by, discussion, body in rows
        ]

    def workspace(self, settings: BoardNames) -> Workspace:
        """Five names and a page — which is all the board is made of."""
        from .workspace import Workspace

        # The naming settings decide what every column is called, so a board
        # resolved under new ones is a board whose schema has to be read again.
        if settings is not self._settings:
            self._settings, self._schemas = settings, None
        space = Workspace(
            tickets="tickets",
            projects="projects",
            agents="agents",
            schedules="schedules",
            goals="goals",
            rows={name: name for name in COLLECTIONS},
            context_page=CONTEXT_PAGE,
        )
        space.context = self.context()
        if not space.context:
            space.warnings.append(
                "the standing context is empty — nothing about you reaches the agent"
            )
        return space

    def _row(self, page_id: str) -> tuple[Any, ...]:
        bare = ids.bare(page_id)
        if not bare:
            raise StoreError("no page id to look for")
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT id, collection, title, properties, body, created, edited, cover, icon"
                " FROM board_pages WHERE id = ? AND trashed = 0",
                (bare,),
            ).fetchone()
        if row is None:
            raise Missing(f"no such page: {page_id}")
        return tuple(row)

    def _page_of(self, row: Sequence[Any]) -> Page:
        identifier, collection, title, raw_properties, body, created, edited, cover, icon = row
        schema = self.schema(collection)
        properties: dict[str, Any] = {
            "Name": {"type": "title", "title": [{"plain_text": title, "type": "text"}]}
        }
        for name, value in _loads(raw_properties).items():
            # A column the board does not declare is still a column somebody
            # typed: read as text.
            shaped = written(schema.get(name, "rich_text"), value)
            if shaped is not None:
                properties[name] = shaped
        return Page(
            id=identifier,
            url=f"ponos://page/{identifier}",
            title=str(title).strip(),
            properties=properties,
            raw={
                "created_time": created,
                "last_edited_time": edited,
                "collection": collection,
                "body": body,
                **{
                    slot: _picture(slot, value)
                    for slot, value in zip(SLOTS, (cover, icon), strict=True)
                },
            },
        )

    # -- writing -------------------------------------------------------------

    def create_row(
        self, database_id: str, title: str, values: dict[str, Any] | None = None, page_id: str = ""
    ) -> str:
        """A new page in a collection, and its identifier."""
        collection = self.resolve_database(database_id)
        identifier = ids.bare(page_id) or new_id()
        stamp = now()
        properties = self._values(collection, values or {})
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO board_pages (id, collection, title, properties, body, created, edited)"
                " VALUES (?, ?, ?, ?, '', ?, ?)",
                (identifier, collection, title.strip(), json.dumps(properties), stamp, stamp),
            )
        return identifier

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        """Write properties by name. The title is a property like the others here."""
        if not values:
            return
        with db.transaction() as connection:
            row = self._locked(connection, page_id)
            properties = _loads(row[3])
            title = row[2]
            for name, value in self._values(row[1], values).items():
                if name == self.title_property(row[1]):
                    title = str(value)
                else:
                    properties[name] = value
            connection.execute(
                "UPDATE board_pages SET title = ?, properties = ?, edited = ? WHERE id = ?",
                (title, json.dumps(properties), now(), row[0]),
            )

    def set_picture(self, page_id: str, slot: str, picture: Picture) -> Page:
        """A page's cover or icon, written beside the database. See `store.Store.set_picture`."""
        if slot not in SLOTS:
            raise StoreError(f"no such picture on a page: {slot}")
        with db.transaction() as connection:
            row = self._locked(connection, page_id)
            folder = db.path().parent / "pictures"
            for old in folder.glob(f"{row[0]}.{slot}.*"):
                old.unlink(missing_ok=True)
            value = ""
            if picture.data:
                suffix = PICTURES.get(picture.type.split(";")[0].strip().lower())
                if not suffix:
                    raise StoreError(
                        f"{picture.type or 'that file'} is not an image this board keeps"
                    )
                target = folder / f"{row[0]}.{slot}{suffix}"
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(picture.data)
                except OSError as error:
                    raise StoreError(f"{target}: {error}") from error
                value = target.as_uri()
            elif picture.url:
                value = picture.url
            elif picture.emoji:
                if slot != "icon":
                    raise StoreError("a cover is an image, not an emoji")
                value = picture.emoji
            connection.execute(
                f"UPDATE board_pages SET {slot} = ?, edited = ? WHERE id = ?",  # noqa: S608 - slot is checked above
                (value, now(), row[0]),
            )
        return self.page(page_id)

    def trash(self, page_id: str) -> str:
        """Take a page off the board. Flagged, not removed: see the module's docstring."""
        with db.transaction() as connection:
            row = self._locked(connection, page_id)
            connection.execute("UPDATE board_pages SET trashed = 1 WHERE id = ?", (row[0],))
        return ""

    def append_markdown(self, page_id: str, markdown: str) -> int:
        """Add to a page's body. Returns a block count, for what says so."""
        if ids.bare(page_id) == CONTEXT_PAGE:
            self.set_context(f"{self.context()}\n\n{markdown.strip()}")
            return _blocks(markdown)
        self._set_body(page_id, lambda body: f"{body}\n\n{markdown.strip()}".strip())
        return _blocks(markdown)

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        """Make a page's body say this and nothing else."""
        if ids.bare(page_id) == CONTEXT_PAGE:
            self.set_context(markdown)
            return _blocks(markdown)
        self._set_body(page_id, lambda body: markdown.strip())
        return _blocks(markdown)

    def replace_section(self, page_id: str, titles: Sequence[str], markdown: str) -> int:
        """The body's last part rewritten, what is above it kept. See `store.Store`."""
        from . import ticket_page

        def rewritten(body: str) -> str:
            lines = body.strip().splitlines()
            cut = next(
                (index for index, line in enumerate(lines) if ticket_page.is_heading(line, titles)),
                len(lines),
            )
            above = "\n".join(lines[:cut]).strip()
            return f"{above}\n\n{markdown.strip()}".strip()

        self._set_body(page_id, rewritten)
        return _blocks(markdown)

    def _set_body(self, page_id: str, change: Any) -> None:
        with db.transaction() as connection:
            row = self._locked(connection, page_id)
            body = change(str(row[4]))
            if body != str(row[4]).strip():
                connection.execute(
                    "UPDATE board_pages SET body = ?, edited = ? WHERE id = ?",
                    (vault.mask(body), now(), row[0]),
                )

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        """Say something on a page, into a thread or opening one."""
        identifier = new_id()
        with db.transaction() as connection:
            row = self._locked(connection, page_id)
            connection.execute(
                "INSERT INTO board_comments (id, page, at, author, discussion, body)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    row[0],
                    now(),
                    self.me(),
                    discussion_id or identifier,
                    vault.mask(text),
                ),
            )

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        """Nothing here is addressable below the page: the steps of a session are in the run journal."""
        return [ids.bare(block_id)] * len(blocks)

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None:
        """Nothing here is addressable below the page. See `append_blocks`."""

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        """Nothing: a page here is its Markdown, and writing it back is writing it."""
        return {}

    def _locked(self, connection: Any, page_id: str) -> tuple[Any, ...]:
        bare = ids.bare(page_id)
        row = connection.execute(
            "SELECT id, collection, title, properties, body FROM board_pages"
            " WHERE id = ? AND trashed = 0",
            (bare,),
        ).fetchone()
        if row is None:
            raise Missing(f"no such page: {page_id}")
        return tuple(row)

    # -- who we are ----------------------------------------------------------

    def me(self) -> str:
        """The name the runner's own words are signed with."""
        return "ponos"

    def my_name(self) -> str:
        return "ponos"

    # -- the standing context, as the console edits it -----------------------

    def context(self) -> str:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT body FROM board_pages WHERE id = ?", (CONTEXT_PAGE,)
            ).fetchone()
        return str(row[0]).strip() if row else ""

    def set_context(self, text: str) -> None:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO board_pages (id, collection, title, properties, body, created, edited)"
                " VALUES (?, 'context', 'Context', '{}', ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET body = excluded.body, edited = excluded.edited",
                (CONTEXT_PAGE, vault.mask(text.strip()), now(), now()),
            )

    def _values(self, collection: str, values: dict[str, Any]) -> dict[str, Any]:
        """Property values, reduced to what a JSON object can hold.

        A relation arrives as a list of IDs and stays one; a date arrives as a
        `datetime` and is written ISO, which is how it is read back.
        """
        schema = self.schema(collection)
        kept: dict[str, Any] = {}
        for name, value in values.items():
            kind = schema.get(name, "rich_text")
            if value is None:
                continue
            if isinstance(value, datetime):
                kept[name] = value.isoformat()
            elif kind == "relation":
                kept[name] = [
                    ids.bare(str(one))
                    for one in (value if isinstance(value, (list, tuple)) else [value])
                    if one
                ]
            elif kind == "checkbox":
                kept[name] = bool(value)
            else:
                kept[name] = value
        return kept


def _loads(text: object) -> dict[str, Any]:
    try:
        found = json.loads(str(text or "{}"))
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _picture(slot: str, value: object) -> dict[str, Any] | None:
    """A stored cover or icon, in the shape a `Page` carries it.

    A URL is somebody else's image, or a `file://` one of ours; a short line
    with neither a dot nor a slash in it is an emoji, and only an icon may be one.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"(https?|file)://", text):
        return {"type": "external", "external": {"url": text}}
    if slot == "icon" and len(text) <= 16 and not re.search(r"[./\\]", text):
        return {"type": "emoji", "emoji": text}
    return None
