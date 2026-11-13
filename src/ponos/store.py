"""Where the board lives, and the words every part of the runner reads it with.

`ponos.db` holds the board: the tickets in `tickets.py`, served by
`ledger.Ledger`, and everything else — projects, agents, goals, schedules, the
standing context — in `pages.py`. This module is what the two have in common,
and nothing else:

- **the vocabulary.** `Page`, `Comment`, and `read` — a property reduced to a
  plain Python value. A `Page` carries its properties as typed values,
  `{"type": "select", "select": {"name": "ready"}}`, and every part of the
  board hands over that same shape rather than a dialect of its own — which is
  why `read` is here: a second decoder is the bug nobody would find;
- **the interface.** `Store` says what the rest of the runner may ask of a
  board. It is a `Protocol` rather than a base class, because the fakes the test
  suite is made of are duck-typed and were never going to inherit from anything;
- **the shape.** `shape` declares each collection's columns and the kind each
  holds, `options` the values a select of the tickets offers — the board is the
  code's own, there is nothing to discover;
- **the choice.** `open()` hands back the board `ponos.db` keeps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .config import BoardNames, Config
    from .workspace import Workspace

# What `claude --model` accepts. A select rather than free text: the whole point
# of the column is to pick without remembering the spelling.
MODELS = ("opus", "sonnet", "haiku", "fable")


class StoreError(Exception):
    """The board could not be read or written.

    One class for every part of the board: the callers that catch this are
    asking "did the board answer?", and the answer is no whether that was a
    locked database or a value the board refuses.
    """


class Missing(StoreError):
    """The board answered, and the page asked for is not on it.

    Deleted, or never there. Told apart from a board that failed to
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

    `discussion_id` is the thread it belongs to: comments are grouped into
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
# top, and a small mark in front of its title — neither is a column, and neither is read by `read`.
SLOTS = ("cover", "icon")


@dataclass
class Picture:
    """What a page's cover or icon is to become. At most one field is set.

    `data` is an image to be kept by the board itself — written beside
    `ponos.db`; `url` is one somebody else keeps; `emoji`
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
        # A date may be a range. The deadline is where it ends.
        value = prop.get("date") or {}
        return value.get("end") or value.get("start")
    if kind == "formula":
        inner = prop.get("formula") or {}
        return inner.get(inner.get("type", ""), None)
    return prop.get(kind)


def written(kind: str | None, value: Any) -> dict[str, Any] | None:
    """One property, in the shape a `Page` carries it. The inverse of `read`."""
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

    The surface the runner was written against, named: `ledger.Ledger` answers
    for it, and the doubles the tests are made of do too.
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

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None: ...

    def create_row(
        self, database_id: str, title: str, values: dict[str, Any] | None = None
    ) -> str: ...

    def append_markdown(self, page_id: str, markdown: str) -> int: ...

    def replace_markdown(self, page_id: str, markdown: str) -> int: ...

    def replace_section(self, page_id: str, titles: Sequence[str], markdown: str) -> int:
        """Make a page end on `markdown`, in place of its part headed by one of `titles`.

        That heading and everything after it go; what is above stays as it
        was — the mission a person wrote, see ticket_page.py. A page without
        such a heading gets `markdown` appended. Returns the count of
        paragraphs written.
        """
        ...

    def losses(self, block_id: str, depth: int = 0) -> dict[str, int]:
        """What `replace_markdown` would drop of this page, by kind and count.

        Empty: a page is its Markdown, and writing it back is writing it.
        """
        ...

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None: ...

    def trash(self, page_id: str) -> str:
        """Put a page in the board's trash — never delete it — and say where to take it back.

        `ponos.db` keeps the row flagged, so somebody can undo it. What comes
        back is the address that does so, or nothing where the board has none.
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

    def workspace(self, settings: BoardNames) -> Workspace:
        """The collections and the standing context. See `workspace.Workspace`."""
        ...


def shape(settings: BoardNames) -> dict[str, dict[str, str]]:
    """{collection: {property: kind}}, the one place the board is declared.

    The relation targets are named after the collections, since that is what a
    relation points at.
    """
    prop = settings.prop
    return {
        "tickets": {
            "Name": "title",
            prop("status"): "select",
            prop("agent"): "rich_text",
            # What the session is doing right now. Written every few seconds
            # while the ticket runs, cleared when it ends.
            prop("progress"): "rich_text",
            prop("session"): "url",
            prop("pull_request"): "url",
            prop("model"): "select",
            # A score from 0 to 100, highest first: see priority.py.
            prop("priority"): "number",
            prop("cost"): "number",
            prop("duration"): "number",
            prop("due"): "date",
            prop("waiting"): "checkbox",
            # Ticked, the first session proposes a plan and waits for a yes
            # before writing any code: see planning.py.
            prop("plan"): "checkbox",
            prop("type"): "select",
            prop("block"): "select",
            prop("ci"): "select",
            prop("subtype"): "select",
            # The prompt run at every change of status — see transitions.py.
            prop("on"): "rich_text",
            prop("project"): "relation",
            prop("role"): "relation",
            prop("after"): "relation",
            prop("goal"): "relation",
        },
        "projects": {"Name": "title", "Repository": "rich_text", "Path": "rich_text"},
        # An agent is a page — its body is the role. The columns are the exceptions.
        "agents": {"Name": "title", prop("model"): "select"},
        # A schedule is the recipe for a ticket, and how often it is born: the
        # columns you fill in, then the three a pass writes back.
        "schedules": {
            "Name": "title",
            prop("cadence"): "select",
            prop("at"): "rich_text",
            prop("day"): "rich_text",
            prop("active"): "checkbox",
            prop("next_run"): "date",
            prop("last_run"): "date",
            prop("model"): "select",
            prop("priority"): "number",
            prop("type"): "select",
            prop("subtype"): "select",
            prop("last_ticket"): "relation",
            prop("project"): "relation",
            # The goal every ticket it makes serves, when it serves one.
            prop("goal"): "relation",
        },
        # A goal is a name, what meets it and when. The tickets point at the
        # goal, never the other way round: `Api.goals` counts them.
        "goals": {
            "Name": "title",
            "Description": "rich_text",
            "Critère": "rich_text",
            "Échéance": "date",
            "Statut": "select",
            "Priorité": "number",
            "Projets": "relation",
        },
    }


def options(settings: BoardNames, name: str) -> list[str]:
    """The values a select of the tickets offers, in the board's order; none for another column."""
    from . import blocks, ci, subtypes

    offered: dict[str, list[str]] = {
        settings.prop("model"): list(MODELS),
        # From the most harmless road to the most guarded one.
        settings.prop("type"): [
            settings.kind(key)
            for key in ("writing", "diagnostic", "code", "external", "publication")
        ],
        settings.prop("block"): list(blocks.CODES),
        settings.prop("ci"): list(ci.LABELS.values()),
        settings.prop("subtype"): [subtype.option for subtype in subtypes.SUBTYPES],
    }
    return offered.get(name, [])


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


def open(config: Config) -> Store:  # noqa: A001
    """The board `ponos.db` keeps: its tickets from `ledger.py`, the rest from `pages.py`."""
    from .ledger import Ledger
    from .pages import Pages

    return Ledger(Pages(config.board), config.board, config.runner.language, config.console_url)
