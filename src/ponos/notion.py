"""A minimal Notion client, on the runner's own HTTP (see http.py).

No SDK: three HTTP verbs and a handful of conversions are enough, and an SDK
would be one more layer, and one more dependency, for a handful of endpoints.

The client reads **the database schema** before writing anything. That is what
lets you rename a column in Notion, or switch `Status` from a status property to
a select, without touching the code: values are encoded according to the
declared type, and a property that does not exist is skipped silently rather
than failing the ticket.

It is one implementation of `store.Store`, and the one everything was written
against — `Page`, `Comment` and `read` are that module's now, re-exported here
because a Notion page is still what they were shaped after.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from . import http, vault
from .config import PLACEHOLDER
from .store import SLOTS, Comment, Page, Picture, StoreError, Unreachable, read

if TYPE_CHECKING:
    from .config import Notion
    from .workspace import Workspace

API = "https://api.notion.com/v1"
# The one seam in this file, and it exists for `tests/functional.py`: the
# functional suite stands a Notion of its own on a local port and runs a whole
# ticket against it. Read at each request rather than at import, so that the
# tests can point the runner somewhere else once the modules are loaded — and
# unset everywhere else, which is every installation.
API_ENV = "PONOS_NOTION_API"
VERSION = "2022-06-28"
MAX_ATTEMPTS = http.MAX_ATTEMPTS

# What Notion takes in one request of its File Upload API. Past it, an upload is
# sent in parts — which a picture the console has already shrunk never needs.
UPLOAD_LIMIT = 20 * 1024 * 1024

# Re-exported so that `notion.Page`, `notion.Comment` and `notion.read` keep
# meaning what they always meant.
__all__ = ["API", "Client", "Comment", "NotionError", "Page", "VERSION", "read"]


def endpoint() -> str:
    """Where the API lives: Notion's, unless `PONOS_NOTION_API` says."""
    return os.environ.get(API_ENV, "").strip().rstrip("/") or API


def _replayable(method: str, path: str) -> bool:
    """May this request be sent again after it may already have been carried out?

    A read, yes, and the two reads Notion spells as a POST — a database query and
    a search. A write that sets a value, too: setting it twice is setting it
    once. What *adds* something — a page, a comment, blocks appended to a page —
    is not: the second copy is a duplicate somebody has to delete by hand.
    """
    if method in ("GET", "DELETE"):
        return True
    if method == "POST":
        return path.endswith("/query") or path == "/search"
    if method == "PATCH":
        return not path.endswith("/children")
    return False


class NotionError(StoreError):
    """The API returned an error, or the network is unreachable."""


class Offline(NotionError, Unreachable):
    """Every attempt died on DNS or on the connection: Notion was never reached."""


class Client:
    def __init__(
        self,
        token: str,
        timeout: int = 30,
        *,
        dropped: Callable[[str, str], None] | None = None,
    ) -> None:
        self._token = token
        self._timeout = timeout
        # Told of every property a write leaves out for want of a column — see
        # `_encoded`. Nobody listening is the old silence.
        self._dropped = dropped
        self._databases: dict[str, dict[str, Any]] = {}
        self._me: dict[str, Any] | None = None

    # -- transport -----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        raw: bytes | None = None,
        kind: str = "application/json",
    ) -> dict[str, Any]:
        if not self._token.strip() or self._token.strip() == PLACEHOLDER:
            # A fresh installation: the console runs before anybody has typed a
            # token, and asks for the board every few seconds while a browser
            # is open. Sending the example's placeholder to Notion would only
            # buy a 401 — or a timeout — per poll, to say what is known here.
            raise NotionError(
                "no Notion token yet — the console's first connection, or `ponos init`, sets it"
            )
        # Masked here, at the one door every write to Notion goes through: a
        # comment, a page, a property — none of them carries a secret. See vault.py.
        data = (
            raw
            if raw is not None
            else json.dumps(vault.masked(body)).encode()
            if body is not None
            else None
        )
        try:
            answer = http.send(
                "notion",
                method,
                f"{endpoint()}{path}",
                content=data,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Notion-Version": VERSION,
                    "Content-Type": kind,
                },
                timeout=self._timeout,
                replayable=_replayable(method, path),
            )
        except http.Unanswered as error:
            raise (Offline if error.offline else NotionError)(
                f"{method} {path}: {error}"
            ) from error
        if answer.status >= 400:
            payload = answer.body.decode(errors="replace")
            message = payload
            try:
                message = json.loads(payload).get("message", payload)
            except (json.JSONDecodeError, AttributeError):
                pass
            last = f"{answer.status} {message}"
            if http.retried(answer.status, _replayable(method, path)):
                last += f" (gave up after {MAX_ATTEMPTS} attempts)"
            # Anything else is our fault — or a 5xx on a write, which Notion
            # may have carried out before failing to say so.
            raise NotionError(f"{method} {path}: {last}")
        try:
            decoded: dict[str, Any] = json.loads(answer.body or b"{}")
            return decoded
        except ValueError as error:
            # An answer that is not JSON is not going to become JSON either.
            raise NotionError(f"{method} {path}: {error}") from error

    def _paged(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Every result of a listing, a hundred at a time, following Notion's cursor.

        A read spelt as a GET carries the cursor in its query string, one
        spelt as a POST (a database query) in its body.
        """
        cursor: str | None = None
        while True:
            if method == "GET":
                separator = "&" if "?" in path else "?"
                suffix = f"&start_cursor={cursor}" if cursor else ""
                payload = self._request(method, f"{path}{separator}page_size=100{suffix}")
            else:
                sent: dict[str, Any] = {**(body or {}), "page_size": 100}
                if cursor:
                    sent["start_cursor"] = cursor
                payload = self._request(method, path, sent)
            yield from payload.get("results", [])
            if not payload.get("has_more"):
                return
            cursor = payload.get("next_cursor")

    # -- reading -------------------------------------------------------------

    def database(self, database_id: str) -> dict[str, Any]:
        """The raw database object, fetched once per run."""
        if database_id not in self._databases:
            self._databases[database_id] = self._request("GET", f"/databases/{database_id}")
        return self._databases[database_id]

    def forget_database(self, database_id: str) -> None:
        """Drop the cached database, so the next read asks Notion again.

        A run is short and reads the board's shape once. The console is not: it
        outlives any number of runs, and a column added in Notion this morning
        has to reach it before tomorrow.
        """
        self._databases.pop(database_id, None)

    def schema(self, database_id: str) -> dict[str, str]:
        """{property name: type}, cached for the lifetime of the run."""
        return {
            name: prop.get("type", "")
            for name, prop in self.database(database_id).get("properties", {}).items()
        }

    def options(self, database_id: str, name: str) -> list[str]:
        """The values a status or select property accepts, in Notion's order.

        A status the configuration names but the database does not offer is
        rejected at the end of a ticket, when the runner tries to write it —
        which is the worst possible moment to discover a typo. `doctor` uses
        this to catch it beforehand.
        """
        prop = self.database(database_id).get("properties", {}).get(name, {})
        kind = prop.get("type", "")
        return [option.get("name", "") for option in prop.get(kind, {}).get("options", [])]

    def title_property(self, database_id: str) -> str:
        """The name of the title column, whatever the database calls it.

        Every database has exactly one, and Notion lets you rename it — `Name`,
        `Titre`, `Ticket`. Writing a page's own name means finding it first.
        """
        schema = self.schema(database_id)
        return next((name for name, kind in schema.items() if kind == "title"), "Name")

    def find_database(self, name: str) -> str:
        """The ID of the database whose title matches `name`.

        Writing the database's name in the configuration is a reasonable thing
        to do, so it works: the search endpoint only ever sees what the
        integration was given access to, which makes an exact match reliable.
        """
        payload = self._request(
            "POST",
            "/search",
            {"query": name, "filter": {"value": "database", "property": "object"}},
        )
        candidates: list[tuple[str, str]] = []
        for item in payload.get("results", []):
            title = "".join(part.get("plain_text", "") for part in item.get("title", []))
            candidates.append((title.strip(), item.get("id", "").replace("-", "")))
        for title, identifier in candidates:
            if title.lower() == name.strip().lower():
                return identifier
        if len(candidates) == 1:
            return candidates[0][1]
        if not candidates:
            raise NotionError(
                f"no database named “{name}” is shared with this integration\n"
                "  share it: the database's ··· menu → Connections → your integration"
            )
        names = ", ".join(f"“{title}”" for title, _ in candidates[:5])
        raise NotionError(f"several databases match “{name}”: {names} — use its URL instead")

    def resolve_database(self, identifier: str) -> str:
        """A database ID, from an ID, the page holding it, or its name.

        Copying a Notion page URL is the natural gesture, but an inline database
        lives *inside* a page and carries a different ID — and the API then
        answers "object not found" without saying why. So we look at the page's
        blocks and take the database we find there. And a value that is not an
        identifier at all is taken for a name and searched.
        """
        from .config import is_identifier

        if not is_identifier(identifier):
            return self.find_database(identifier)
        try:
            self.schema(identifier)
            return identifier
        except Unreachable:
            raise  # not an answer about the identifier: nobody answered
        except NotionError:
            pass
        try:
            payload = self._request("GET", f"/blocks/{identifier}/children?page_size=100")
        except Unreachable:
            raise
        except NotionError as error:
            raise NotionError(
                f"neither a database nor a readable page for {identifier}: {error}\n"
                "  the database must be shared with the integration (··· menu → Connections)"
            ) from error
        for block in payload.get("results", []):
            if block.get("type") == "child_database":
                return str(block["id"]).replace("-", "")
        raise NotionError(
            f"{identifier} is a page with no database in it — "
            "give the URL of the database itself (··· → Copy link to view)"
        )

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]:
        body = {"filter": filter_} if filter_ else None
        return [
            _to_page(item) for item in self._paged("POST", f"/databases/{database_id}/query", body)
        ]

    def page(self, page_id: str) -> Page:
        return _to_page(self._request("GET", f"/pages/{page_id}"))

    def comments(self, page_id: str) -> list[Comment]:
        """The discussion on a page, oldest first.

        This is where a ticket gets answered. A run that ends `blocked` leaves
        its question here, you reply, and the ticket goes back to ready — so
        without reading this, the next run reopens the very question it asked.

        Reading comments is a separate capability of a Notion integration, and
        one that is off by default. A refusal is not a reason to fail a ticket:
        it comes back as no comments, and the caller says so.
        """
        found: list[Comment] = []
        for item in self._paged("GET", f"/comments?block_id={page_id}"):
            text = "".join(_written(part) for part in item.get("rich_text", []))
            if text.strip():
                found.append(
                    Comment(
                        text.strip(),
                        item.get("created_time", ""),
                        id=item.get("id", ""),
                        discussion_id=item.get("discussion_id", ""),
                        created_by=(item.get("created_by") or {}).get("id", ""),
                    )
                )
        return found

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        """A page's content, flattened into something an agent can read.

        `live=False` reads it as a brief: the toggles a run's live report left
        on the page are skipped, and not descended into — see `progress.is_live`.
        """
        from . import progress

        if depth > 3:
            return ""
        lines: list[str] = []
        for block in self._paged("GET", f"/blocks/{block_id}/children"):
            if not live and progress.is_live(block):
                continue
            lines.append(_block_text(block, depth))
            if block.get("has_children") and block.get("type") != "child_page":
                nested = self.blocks_text(block["id"], depth + 1, live=live)
                if nested:
                    lines.append(_indent(nested))
        return "\n".join(line for line in lines if line is not None).strip()

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        """What `replace_markdown` would not give back of this page, and how many times.

        Walks the page the way `blocks_text` does — the same blocks, nested the
        same depth — and asks `markdown.lost` of each one. Whatever is deeper
        than `blocks_text` goes is lost too, and said as `nested`.
        """
        from . import markdown as converter

        found: dict[str, int] = {}
        for block in self._paged("GET", f"/blocks/{block_id}/children"):
            for kind in converter.lost(block):
                found[kind] = found.get(kind, 0) + 1
            if block.get("has_children") and block.get("type") != "child_page":
                if depth >= 3:
                    found["nested"] = found.get("nested", 0) + 1
                    continue
                for kind, count in self.losses(block["id"], depth + 1).items():
                    found[kind] = found.get(kind, 0) + count
        return found

    def attachment(self, block_id: str) -> str:
        block = self._request("GET", f"/blocks/{block_id}")
        kind = block.get("type", "")
        payload = (block.get(kind) or {}) if kind in ("image", "file", "pdf") else {}
        url = (
            (payload.get("file") or {}).get("url")
            or (payload.get("external") or {}).get("url")
            or ""
        )
        # Somebody else's address is whatever was pasted; only the web is sent on.
        if not url.lower().startswith(("https://", "http://")):
            raise LookupError(f"block {block_id} holds no file")
        return url

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        """Write properties by name; those absent from the schema are left out.

        Left out, and said: whoever opened this client with `dropped` hears of
        each one. A column nobody created is not something Notion complains
        about — it is a write that never lands, and the runner went a whole
        day not signing its claims for want of one.

        The schema is cached for the run, and a run can last half an hour — long
        enough for someone to change a column's type in Notion meanwhile. Values
        are then encoded for a type the database no longer has, and Notion
        answers `400 X is expected to be url`. So a rejection on those grounds
        refreshes the schema and tries once more, rather than losing the write.
        """
        properties = self._encoded(database_id, values)
        if not properties:
            return
        try:
            self._request("PATCH", f"/pages/{page_id}", {"properties": properties})
        except NotionError as error:
            if "expected to be" not in str(error):
                raise
            self._databases.pop(database_id, None)
            retry = self._encoded(database_id, values)
            if retry:
                self._request("PATCH", f"/pages/{page_id}", {"properties": retry})

    def _encoded(self, database_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """The values the database has a column for, in the shape Notion wants."""
        schema = self.schema(database_id)
        properties: dict[str, Any] = {}
        for name, value in values.items():
            if name not in schema:
                if self._dropped is not None:
                    self._dropped(database_id, name)
                continue
            encoded = _encode(schema[name], value)
            if encoded is not None:
                properties[name] = encoded
        return properties

    def append_markdown(self, page_id: str, markdown: str) -> int:
        """Append markdown to a page, as real Notion blocks. Returns the count.

        Appending, never replacing: the ticket's own description is what the
        agent was asked to work from, and destroying it to make room for the
        answer would be a poor trade.
        """
        from . import markdown as converter

        blocks = converter.to_blocks(markdown)
        self.append_blocks(page_id, blocks)
        return len(blocks)

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        """Make a page say this and nothing else. Returns the block count.

        The one destructive write in this client, and it exists for the two
        places where a page is *a value* rather than a history: the standing
        context, which the console edits as a text area, and a page the Markdown
        side of a mirrored board has just won a conflict over. Appending there
        would grow a second copy under the first every time either is saved.

        Everything that is not those two appends — a report, an answer, a
        ticket's body — because a ticket's own description is what the agent was
        asked to work from, and destroying it to make room would be a poor trade.
        """
        self.delete_children(page_id)
        return self.append_markdown(page_id, markdown)

    def delete_children(self, block_id: str) -> int:
        """Empty a page, block by block, and say how many went.

        Notion has no "delete the contents of this page": archiving a block is
        one request each, and there is no batch. A hundred at a time is what
        `children` hands over, and the loop asks again until it hands over none.
        """
        gone = 0
        while True:
            payload = self._request("GET", f"/blocks/{block_id}/children?page_size=100")
            blocks = payload.get("results", [])
            if not blocks:
                return gone
            for block in blocks:
                self._request("DELETE", f"/blocks/{block['id']}")
                gone += 1
            if not payload.get("has_more"):
                return gone

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        """Append blocks under a page *or* under a block, and return their IDs.

        Notion takes a hundred at a time, hence the batching; and it answers
        with what it created, which is how the live report gets hold of the
        toggle it will then keep filling.
        """
        from . import markdown as converter

        created: list[str] = []
        for batch in converter.chunked(blocks):
            if not batch:
                continue
            payload = self._request("PATCH", f"/blocks/{block_id}/children", {"children": batch})
            created += [item.get("id", "") for item in payload.get("results", [])]
        return created

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None:
        """Rewrite a block in place — its text, not its type.

        Used by the live report to keep a toggle's title current: the count and
        the elapsed time belong on the line you see when it is collapsed.
        """
        self._request("PATCH", f"/blocks/{block_id}", payload)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        """Say something on a page — or *into* one of its threads.

        A report opens its own discussion, because it is the runner speaking
        first. An answer to a question belongs under the question: given a
        discussion, Notion threads it there, and the page keeps reading as a
        conversation instead of as a stack of monologues.
        """
        body: dict[str, Any] = {"rich_text": _comment_text(text)}
        if discussion_id:
            body["discussion_id"] = discussion_id
        else:
            body["parent"] = {"page_id": page_id}
        self._request("POST", "/comments", body)

    def trash(self, page_id: str) -> str:
        """Archive the page, which this API version calls what Notion's trash is.

        `archived` is the 2022-06-28 spelling of `in_trash`: the page leaves its
        database and every query, and stays restorable from the trash for thirty
        days. Its address keeps working, and is the way back.
        """
        return _to_page(self._request("PATCH", f"/pages/{page_id}", {"archived": True})).url

    def set_picture(self, page_id: str, slot: str, picture: Picture) -> Page:
        """Set the page's cover or icon. See `store.Store.set_picture`.

        An image of our own goes through the File Upload API first and is then
        attached by the upload's ID; a URL is attached as it is, `external`,
        without being fetched — Notion shows it from wherever it lives.
        """
        if slot not in SLOTS:
            raise NotionError(f"no such picture on a page: {slot}")
        value: dict[str, Any] | None
        if picture.data:
            upload = self.upload(picture.data, picture.type, picture.name or f"{slot}")
            value = {"type": "file_upload", "file_upload": {"id": upload}}
        elif picture.url:
            value = {"type": "external", "external": {"url": picture.url}}
        elif picture.emoji:
            if slot != "icon":
                raise NotionError("a cover is an image, not an emoji")
            value = {"type": "emoji", "emoji": picture.emoji}
        else:
            value = None
        return _to_page(self._request("PATCH", f"/pages/{page_id}", {slot: value}))

    def upload(self, data: bytes, kind: str, name: str) -> str:
        """Hand a file to Notion, and return the ID a page attaches it by.

        Two requests: one that says what is coming, one that carries it as a
        form — the only body in this client that is not JSON. What comes back
        is an upload nobody has attached yet; Notion forgets it within the
        hour, so it is attached at once.
        """
        if len(data) > UPLOAD_LIMIT:
            raise NotionError(
                f"{name}: {len(data) // (1024 * 1024)} MB is more than Notion takes in one piece"
            )
        created = self._request("POST", "/file_uploads", {"filename": name, "content_type": kind})
        identifier = str(created.get("id", ""))
        if not identifier:
            raise NotionError("POST /file_uploads: Notion answered without an upload ID")
        boundary = f"ponos-{os.urandom(12).hex()}"
        safe = name.replace('"', "").replace("\r", "").replace("\n", "")
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
                f"Content-Type: {kind}\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        self._request(
            "POST",
            f"/file_uploads/{identifier}/send",
            raw=body,
            kind=f"multipart/form-data; boundary={boundary}",
        )
        return identifier

    def me(self) -> str:
        """The integration's own user ID, fetched once.

        Everything the runner says in the comments comes back to it on the next
        pass. Recognising its own voice by the signature it writes would work
        until the day it writes something else — so it asks Notion who it is,
        and compares identifiers. Answering a comment is gated on this: without
        it, the runner cannot prove a comment is not its own, and a conversation
        with itself is the one failure mode that never stops.
        """
        return str(self._identity().get("id", ""))

    def my_name(self) -> str:
        """The name the integration answers to, as Notion shows it.

        Mentioning it in a comment is the natural way to address it, and a
        mention reaches the API as the name in plain text — so knowing the name
        is what makes “@Ponos, pourquoi ?” a message rather than a
        remark about the weather.
        """
        return str(self._identity().get("name", "")).strip()

    def workspace(self, settings: Notion) -> Workspace:
        """The databases and the standing context of this board. See workspace.py.

        Part of the store interface rather than of `workspace.resolve`, because
        "what is this board made of" is the one question each backend answers in
        its own terms: a Notion workspace is a directory database whose rows
        hold inline databases, and a Markdown board is four directories.

        Imported here rather than at the top: `workspace` reads pages through
        this very client, and the two modules would otherwise import each other.
        """
        from . import workspace as workspace_module

        return workspace_module.from_notion(self, settings)

    def _identity(self) -> dict[str, Any]:
        """Who Notion says we are. Cached on success only, so a network blip
        that hid our identity for one run does not hide it for the next."""
        if self._me is None:
            self._me = self._request("GET", "/users/me")
        return self._me

    # -- writing the shape, not the content ----------------------------------

    def child_databases(self, page_id: str) -> dict[str, str]:
        """{title: database id} for the databases living inside a page.

        `resolve_database` already walks these blocks to find *the* database of
        a page; provisioning needs to know whether the one it is about to
        create is already there, and under which title.
        """
        payload = self._request("GET", f"/blocks/{page_id}/children?page_size=100")
        found: dict[str, str] = {}
        for block in payload.get("results", []):
            if block.get("type") != "child_database":
                continue
            title = (block.get("child_database") or {}).get("title", "").strip()
            found.setdefault(title, block["id"].replace("-", ""))
        return found

    def create_database(
        self, parent_page_id: str, title: str, properties: dict[str, Any], *, inline: bool = True
    ) -> str:
        """Create a database inside a page and return its ID.

        Inline by default, because that is the shape the workspace is read as:
        a row of the directory is a page, and the database it holds lives in it.
        """
        payload = self._request(
            "POST",
            "/databases",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": _rich_text(title),
                "is_inline": inline,
                "properties": properties,
            },
        )
        return str(payload.get("id", "")).replace("-", "")

    def add_properties(self, database_id: str, properties: dict[str, Any]) -> None:
        """Add or widen properties on an existing database.

        Only ever called with what is missing: a column somebody retyped on
        purpose is theirs, and provisioning has no business overruling it.
        """
        if not properties:
            return
        self._request("PATCH", f"/databases/{database_id}", {"properties": properties})
        self._databases.pop(database_id, None)  # the cached schema just aged

    def create_row(self, database_id: str, title: str, values: dict[str, Any] | None = None) -> str:
        """Create a page in a database, titled, and return its ID."""
        properties: dict[str, Any] = {
            self.title_property(database_id): _encode("title", title),
            **self._encoded(database_id, values or {}),
        }
        payload = self._request(
            "POST",
            "/pages",
            {
                "parent": {"type": "database_id", "database_id": database_id},
                "properties": properties,
            },
        )
        return str(payload.get("id", "")).replace("-", "")

    def create_child_page(self, parent_page_id: str, title: str) -> str:
        """Create a plain page inside a page, and return its ID."""
        payload = self._request(
            "POST",
            "/pages",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "properties": {"title": {"title": _rich_text(title)}},
            },
        )
        return str(payload.get("id", "")).replace("-", "")

    def shared(self, directory: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """What has been shared with the integration: pages, and boards already built.

        The first connection's way of not asking for a URL. Sharing a page with
        an integration happens in Notion, and the only sign of it the API gives
        is that `search` starts returning the page — so the console asks, and
        offers what came back. A board is a database titled `directory` (what
        `provision` builds); a page that lives inside a database is a row of
        somebody's table, not a place to build under, and is left out.
        """
        pages: list[dict[str, Any]] = []
        found = self._request(
            "POST", "/search", {"filter": {"value": "page", "property": "object"}, "page_size": 50}
        )
        for item in found.get("results", []):
            if (item.get("parent") or {}).get("type") == "database_id" or item.get("archived"):
                continue
            page = _to_page(item)
            pages.append({"id": page.id.replace("-", ""), "title": page.title, "url": page.url})
        boards: list[dict[str, Any]] = []
        found = self._request(
            "POST",
            "/search",
            {"query": directory, "filter": {"value": "database", "property": "object"}},
        )
        for item in found.get("results", []):
            title = "".join(part.get("plain_text", "") for part in item.get("title", []))
            if title.strip().lower() != directory.lower() or item.get("archived"):
                continue
            boards.append({"id": item.get("id", "").replace("-", ""), "url": item.get("url", "")})
        return pages, boards


# -- conversions -------------------------------------------------------------


def _to_page(raw: dict[str, Any]) -> Page:
    properties = raw.get("properties", {})
    title = ""
    for prop in properties.values():
        if prop.get("type") == "title":
            title = "".join(part.get("plain_text", "") for part in prop.get("title", []))
            break
    return Page(
        id=raw.get("id", ""),
        url=raw.get("url", ""),
        title=title.strip(),
        properties=properties,
        raw=raw,
    )


def _encode(kind: str | None, value: Any) -> dict[str, Any] | None:
    if kind is None or value is None:
        return None
    if kind == "status":
        return {"status": {"name": str(value)}}
    if kind == "select":
        # An empty name is not an option, and Notion answers 400 to one. What
        # emptying a select means is clearing the cell, and `null` is how that
        # is said — which is what the console's "nothing said" sends.
        return {"select": {"name": str(value)} if str(value) else None}
    if kind == "url":
        return {"url": str(value) or None}
    if kind in ("rich_text", "title"):
        return {kind: _rich_text(str(value))}
    if kind == "checkbox":
        return {"checkbox": bool(value)}
    if kind == "number":
        return {"number": value}
    if kind == "date":
        # Emptied by `null`, as a select is: a due date taken off a goal.
        return {"date": {"start": str(value)} if str(value) else None}
    if kind == "relation":
        # A relation is written as a list of page IDs, and accepts one on its
        # own: a ticket created from the console names its project, and naming
        # it is the whole difference between code work and document work.
        ids = value if isinstance(value, (list, tuple)) else [value]
        return {"relation": [{"id": str(one)} for one in ids if one]}
    return None


def _rich_text(text: str) -> list[dict[str, Any]]:
    """Notion rejects a text block longer than 2000 characters."""
    chunks = [text[index : index + 1900] for index in range(0, len(text), 1900)] or [""]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks[:20]]


# A link as a report writes it: `[PR #58](https://…)`. Only http(s), because a
# comment is not where a `javascript:` address gets to become clickable.
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def _comment_text(text: str) -> list[dict[str, Any]]:
    """A comment as Notion draws it: its lines, and its links clickable.

    The line breaks stay in the text itself — Notion draws a `\n` inside a
    comment as a new line, which is what lets a blocked ticket ask its question
    one line per idea — and a Markdown link becomes a link rather than its own
    source, so that “PR #58” on a verdict line is the pull request. Everything
    else is `_rich_text`, cut where Notion would refuse it.
    """
    segments: list[dict[str, Any]] = []
    at = 0
    for found in _LINK.finditer(text):
        if found.start() > at:
            segments.extend(_rich_text(text[at : found.start()]))
        for linked in _rich_text(found.group(1)):
            linked["text"]["link"] = {"url": found.group(2)}
            segments.append(linked)
        at = found.end()
    if at < len(text) or not segments:
        segments.extend(_rich_text(text[at:]))
    # Notion takes a hundred pieces of rich text at most.
    return segments[:100]


def _written(part: dict[str, Any]) -> str:
    """One piece of a comment's rich text, read back as it was written."""
    plain = part.get("plain_text", "")
    url = ((part.get("text") or {}).get("link") or {}).get("url", "")
    return f"[{plain}]({url})" if url and plain else plain


def _block_text(block: dict[str, Any], depth: int) -> str:
    """One block as text. See `markdown.plain`, where the conversion lives."""
    from . import markdown as converter

    return converter.plain(block)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())
