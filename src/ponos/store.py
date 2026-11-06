"""Where the board lives, whoever holds it.

The runner was written against Notion, and against nothing else: `notion.Client`
was passed around as *the* way to read a ticket, to write a status, to say
something on a page. That was true for as long as there was one place a board
could be — and it stopped being true the day the answer to "can this run without
Notion?" had to be yes.

So this module is the seam. Three things live here and nothing else:

- **the vocabulary.** `Page`, `Comment`, and `read` — a property reduced to a
  plain Python value. Their shape is Notion's, deliberately: a `Page` carries
  its properties the way the API writes them, and every backend produces that
  same shape rather than a dialect of its own. Which is why `read` is here and
  not in `notion.py` — it decodes what *any* store hands over, and a second
  decoder per backend is the bug nobody would find;
- **the interface.** `Store` says what the rest of the runner may ask of a
  board. It is a `Protocol` rather than a base class, because the fakes the test
  suite is made of are duck-typed and were never going to inherit from anything;
- **the choice.** `open()` hands back the board `ponos.db` keeps: its tickets
  from `ledger.py`, and the rest — projects, agents, goals, schedules — from
  Notion when a token is set, and from `pages.py` when there is none. Nothing
  above this module knows which it got.

What is *not* here is provisioning: creating a database, widening a select,
adding a property. That is Notion's own shape being built, it only ever happens
through `ponos init`, and a board without Notion has none of it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .config import Config, Notion
    from .workspace import Workspace

# The kinds of property Notion computes itself: a value written to one is not
# refused, it is dropped without a word (see `notion._encode`). A column the
# runner has to write — `Next` above all, see `Recurrence.recur` — must be none
# of these, or the write it counts on never lands.
READ_ONLY = (
    "formula",
    "rollup",
    "created_time",
    "created_by",
    "last_edited_time",
    "last_edited_by",
    "unique_id",
    "button",
    "verification",
)

# The columns of the tickets board the runner reads or writes: the kinds of
# property each one works as, and what a board without it goes without. One
# table for the two places that have to say it — `doctor`, before anything
# runs, and a run, the first time a write lands on a column that is not there.
# A missing column is never an error to Notion: it is a value quietly left
# out, and a 1st of October spent with fourteen tickets in progress that
# nothing was going to put back. So what it costs is spelled out.
COLUMNS: dict[str, tuple[tuple[str, ...], str]] = {
    "status": (("status", "select"), "no ticket can be claimed, moved or finished"),
    "project": (("relation",), "no ticket is tied to a project, so none reaches a repository"),
    "agent": (
        ("rich_text",),
        "which machine took a ticket is not written — fine on one machine, but a "
        "second one on this board would put back the tickets the first is running",
    ),
    "pull_request": (
        ("url",),
        "the pull request is not linked from its ticket, so a validated one is not merged for you",
    ),
    "session": (("url", "rich_text"), "no link to the session behind a ticket"),
    "model": (("select", "rich_text"), "no model per ticket — runner.model for every one"),
    "priority": (("number", "select"), "no ready ticket goes before another"),
    "cost": (("number",), "what a run cost is not written back"),
    "duration": (("number",), "how long a run took is not written back"),
    "progress": (("rich_text",), "nothing says what a session is doing while it runs"),
    "due": (("date",), "no ticket can be held until a date"),
    "waiting": (("checkbox",), "a ticket held back by the credit does not say so"),
    "plan": (("checkbox",), "no ticket can ask for a plan before its code is written"),
    "type": (("select",), "the kind a ticket was classified as is not kept on the board"),
    "block": (
        ("select",),
        "why a ticket stopped is not on the board, so no Notion view can filter blocks by cause",
    ),
    "ci": (
        ("select",),
        "the state of a pull request's checks is not on the board, so no Notion view can filter on it",
    ),
    "subtype": (
        ("select",),
        "a code ticket's sub-type is not kept, so its commit, its pull request and its "
        "CHANGELOG entry go by its title's prefix alone",
    ),
    "on": (
        ("rich_text",),
        "the prompt a ticket runs at each change of status is not read, so none runs",
    ),
}


def lost(settings: Any, name: str) -> str:
    """What the tickets board goes without when it has no column `name`."""
    for key, (_, cost) in COLUMNS.items():
        if settings.prop(key) == name:
            return cost
    return ""


class StoreError(Exception):
    """The board could not be read or written.

    One class for every backend: the callers that catch this are asking "did the
    board answer?", and the answer is no whether that was a 502 from Notion or a
    directory this user cannot write to.
    """


class Missing(StoreError):
    """The board answered, and the page asked for is not on it.

    Deleted, in another workspace, or never shared with the integration: Notion
    says the same 404 for all three. Told apart from a board that failed to
    answer because asking again changes nothing — the console says "not there"
    rather than offering to try again.
    """


class Unreachable(StoreError):
    """The board could not be reached at all: no DNS answer, no connection.

    Told apart from a refusal because the two ask for opposite things. A 4xx is
    about the request and a ticket that meets it has a reason to be failed; a
    network that is down is about the machine, and the ticket has done nothing
    wrong — the pass stops quietly, and the next one picks up where it was.
    """


@dataclass
class Comment:
    """One comment, and what it takes to answer it where it was written.

    `discussion_id` is the thread it belongs to: Notion groups comments into
    discussions, and answering *into* one is the whole difference between a
    conversation and a page covered in unrelated remarks. `created_by` is who
    wrote it — which is how the runner tells its own words from yours without
    having to recognise its own signature in a string.
    """

    text: str
    created_time: str = ""
    id: str = ""
    discussion_id: str = ""
    created_by: str = ""


@dataclass
class Page:
    id: str
    url: str
    title: str
    properties: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


# The two pictures a page carries beside its properties: a banner across its
# top, and a small mark in front of its title. Notion's words, and its places —
# neither is a column, and neither is read by `read`.
SLOTS = ("cover", "icon")


@dataclass
class Picture:
    """What a page's cover or icon is to become. At most one field is set.

    `data` is an image to be kept by the board itself — uploaded to Notion,
    written beside the file on disk; `url` is one somebody else keeps; `emoji`
    is only ever an icon. None of them is the picture going away.
    """

    data: bytes = b""
    type: str = ""
    name: str = ""
    url: str = ""
    emoji: str = ""

    @property
    def removed(self) -> bool:
        return not (self.data or self.url or self.emoji)


def read(page: Page, name: str) -> Any:
    """A property's value, reduced to a plain Python type."""
    prop = page.properties.get(name)
    if not prop:
        return None
    kind = prop.get("type")
    if kind in ("rich_text", "title"):
        return "".join(part.get("plain_text", "") for part in prop.get(kind, [])).strip()
    if kind == "status":
        return (prop.get("status") or {}).get("name")
    if kind == "select":
        return (prop.get("select") or {}).get("name")
    if kind == "url":
        return prop.get("url")
    if kind == "relation":
        return [item.get("id") for item in prop.get("relation", [])]
    if kind == "people":
        return [item.get("id") for item in prop.get("people", [])]
    if kind == "checkbox":
        return prop.get("checkbox")
    if kind == "number":
        return prop.get("number")
    if kind == "date":
        # A Notion date may be a range. The deadline is where it ends.
        value = prop.get("date") or {}
        return value.get("end") or value.get("start")
    if kind == "formula":
        inner = prop.get("formula") or {}
        return inner.get(inner.get("type", ""), None)
    return prop.get(kind)


def written(kind: str | None, value: Any) -> dict[str, Any] | None:
    """One property, in the shape a `Page` carries it. The inverse of `read`.

    Type tag included, which is what tells this apart from `notion._encode`:
    that one builds the body of a `PATCH`, this one builds what `read` will be
    handed back. A store that keeps its pages on disk needs the second.
    """
    if kind is None or value is None:
        return None
    if kind in ("status", "select"):
        return {"type": kind, kind: {"name": str(value)}}
    if kind == "url":
        return {"type": "url", "url": str(value) or None}
    if kind in ("rich_text", "title"):
        return {"type": kind, kind: [{"plain_text": str(value), "type": "text"}]}
    if kind == "checkbox":
        return {"type": "checkbox", "checkbox": bool(value)}
    if kind == "number":
        return {"type": "number", "number": value}
    if kind == "date":
        return {"type": "date", "date": {"start": str(value), "end": None}}
    if kind == "relation":
        ids = value if isinstance(value, (list, tuple)) else [value]
        return {"type": "relation", "relation": [{"id": str(one)} for one in ids if one]}
    return None


@runtime_checkable
class Store(Protocol):
    """Everything the runner and the console ask of a board.

    Deliberately the surface `notion.Client` already had, rather than a smaller
    ideal one: the runner is written against it, and an interface that forced
    every call site to be rewritten would have been a rewrite pretending to be
    an abstraction. What changed is that it is now *named*, and that two other
    things implement it.
    """

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str: ...

    def schema(self, database_id: str) -> dict[str, str]: ...

    def options(self, database_id: str, name: str) -> list[str]: ...

    def title_property(self, database_id: str) -> str: ...

    def forget_database(self, database_id: str) -> None: ...

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Page]: ...

    def page(self, page_id: str) -> Page: ...

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str: ...

    def comments(self, page_id: str) -> list[Comment]: ...

    def attachment(self, block_id: str) -> str:
        """Where the file an image, file or PDF block holds can be fetched now.

        Asked at the moment it is wanted, never kept: a file Notion hosts is
        behind an address good for an hour. See `markdown.attached`. Raises
        LookupError when that block holds no file.
        """
        ...

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None: ...

    def create_row(
        self, database_id: str, title: str, values: dict[str, Any] | None = None
    ) -> str: ...

    def append_markdown(self, page_id: str, markdown: str) -> int: ...

    def replace_markdown(self, page_id: str, markdown: str) -> int: ...

    def replace_section(self, page_id: str, titles: Sequence[str], markdown: str) -> int:
        """Make a page end on `markdown`, in place of its part headed by one of `titles`.

        That heading and everything after it go, and so do the folded blocks
        an older run's live report left on the page; what is above stays block
        for block — the mission a person wrote, see ticket_page.py. A page
        without such a heading gets `markdown` appended. Returns the count of
        blocks written.
        """
        ...

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]: ...

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None: ...

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        """What `replace_markdown` would drop of this page, by kind and count.

        Empty on a board that is Markdown already; on Notion, the blocks and
        the bits of rich text a line of Markdown cannot hold. See
        `markdown.lost`.
        """
        ...

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None: ...

    def trash(self, page_id: str) -> str:
        """Put a page in the board's trash — never delete it — and say where to take it back.

        Notion keeps a trashed page for thirty days and `ponos.db` keeps the row
        flagged: either way somebody can undo it. What
        comes back is the address that does so (the page's own, in Notion), or
        nothing where the board has none.
        """
        ...

    def set_picture(self, page_id: str, slot: str, picture: Picture) -> Page:
        """Set a page's cover or icon, and hand back the page as it now is.

        The page, not nothing: what the board answers is what the next read
        will say, and `images.py` agrees on it at once rather than taking its
        own change, read back, for somebody else's.
        """
        ...

    # -- who we are ----------------------------------------------------------

    def me(self) -> str: ...

    def my_name(self) -> str: ...

    # -- the board's own shape -----------------------------------------------

    def workspace(self, settings: Notion) -> Workspace:
        """The databases and the standing context. See `workspace.Workspace`."""
        ...


def shape(settings: Notion) -> dict[str, dict[str, str]]:
    """{collection: {property: kind}}, from the one place the board is declared.

    `provision.py` builds the Notion databases from these very shapes, so a
    column added there is a column `ponos.db` reads the same day. The relation
    targets are named after the collections rather than after database IDs,
    since here that is what a relation points at.
    """
    from . import provision

    def kinds(schema: dict[str, Any]) -> dict[str, str]:
        return {name: next(iter(kind)) for name, kind in schema.items()}

    return {
        # The goal a ticket serves is a column Notion boards add by hand, so
        # `tickets_schema` does not declare it; `ponos.db` has it too.
        "tickets": {
            **kinds(provision.tickets_schema(settings, "projects", "agents", "tickets")),
            settings.prop("goal"): "relation",
        },
        "projects": kinds(provision.projects_schema()),
        "agents": kinds(provision.agents_schema(settings)),
        "schedules": kinds(provision.schedules_schema(settings, "tickets", "projects")),
        "goals": kinds(provision.goals_schema("projects")),
    }


def matches(page: Page, filter_: dict[str, Any] | None) -> bool:
    """Does this page satisfy one of the filters the runner builds?

    Three shapes and no more, because three is all there are: an `and` of
    clauses, an `equals`, and a `does_not_equal`. Anything else matches
    everything — a filter this cannot read must not silently empty the board.
    """
    if not filter_:
        return True
    if "and" in filter_:
        return all(matches(page, clause) for clause in filter_["and"])
    if "or" in filter_:
        return any(matches(page, clause) for clause in filter_["or"])
    name = filter_.get("property")
    if not name:
        return True
    for kind, test in filter_.items():
        if kind == "property" or not isinstance(test, dict):
            continue
        value = read(page, name)
        if "equals" in test:
            return bool(value == test["equals"])
        if "does_not_equal" in test:
            return bool(value != test["does_not_equal"])
    return True


def open(  # noqa: A001
    config: Config, *, dropped: Callable[[str, str], None] | None = None, notion_only: bool = False
) -> Store:
    """The store the configuration asks for.

    The tickets are served by `ponos.db` (see ledger.py); what is not a ticket
    is Notion's when the configuration holds a token, and the database's own
    otherwise (see pages.py). `notion_only` asks for the Notion client itself:
    the import and the checks of the board are about Notion, not about the
    tickets.

    `dropped` hears of every property a write leaves out because the database
    has no such column — `(database, name)` — which only Notion ever does.

    Imported here rather than at the top, so that an installation without
    Notion never loads a module whose only job is to talk to an API it will
    not use.
    """
    from .ledger import Ledger

    if config.standalone:
        from .pages import Pages

        return Ledger(Pages(config.notion), config.notion, config.runner.language)
    from .notion import Client

    client = Client(config.notion.token, dropped=dropped)
    if notion_only:
        return client
    return Ledger(client, config.notion, config.runner.language)
