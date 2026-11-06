"""`notion_import.py` and `mirror.py`: Notion into `ponos.db`, and the queue back out."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from support import _config, _NotionBoard, case

from ponos import mirror, notion, notion_import, store, tickets
from ponos.workspace import Workspace

SPACE = Workspace(tickets="tickets", projects="projects")
PROJECT = "3ca451680af481a8"


class Notion(_NotionBoard):
    """The fake board, with comments, a trash, and a way to go down."""

    def __init__(self) -> None:
        super().__init__()
        self.talk: dict[str, list[store.Comment]] = {}
        self.trashed: list[str] = []
        self.down = ""

    def _check(self) -> None:
        if self.down == "refused":
            raise notion.Refused("401 invalid token")
        if self.down == "offline":
            raise notion.Offline("no route to Notion")

    def comments(self, page_id: str) -> list[store.Comment]:
        return self.talk.get(page_id, [])

    def create_row(
        self, database_id: str, title: str, values: dict[str, Any] | None = None, at: str = ""
    ) -> str:
        self._check()
        return super().create_row(database_id, title, values, at)

    def update(self, database_id: str, page_id: str, values: dict[str, Any], at: str = "") -> None:
        self._check()
        super().update(database_id, page_id, values, at)

    def replace_markdown(self, page_id: str, markdown: str, at: str = "") -> int:
        self._check()
        return super().replace_markdown(page_id, markdown, at)

    def replace_section(self, page_id: str, titles: Any, markdown: str, at: str = "") -> int:
        self._check()
        return super().replace_section(page_id, titles, markdown, at)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self._check()
        super().comment(page_id, text, discussion_id)

    def trash(self, page_id: str) -> str:
        self._check()
        self.trashed.append(page_id)
        return ""


def _page(board: Notion, title: str, body: str = "", **values: Any) -> str:
    page = board.create_row("tickets", title, values)
    board.bodies[page] = body
    return page


BODY = "## Mission\n\nFais X.\n\n## Ce qui a été fait\n\n✅ Fait.\n\n### Historique\n\n- 12/10"


@case
def the_import_fills_the_database_and_a_second_one_adds_nothing(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    first = _page(
        board, "Ajouter X", BODY, statut="review", Priorité=70, Type="Code", Project=[PROJECT]
    )
    _page(board, "Suite", "## Mission\n\nSuite.", statut="ready", Après=[first])
    board.talk[first] = [store.Comment("Quoi ?", "2026-10-01T10:00:00Z", "c1", "d1", "someone")]
    report = notion_import.run(board, config, SPACE)
    assert (report.created, report.existing, report.comments) == (2, 0, 1)
    made = tickets.get(first)
    assert made is not None and made.title == "Ajouter X" and made.status == "review"
    assert made.mission == "Fais X." and made.report.startswith("✅ Fait.")
    assert made.priority == 70 and made.kind == "code" and made.project == PROJECT
    assert [c.text for c in tickets.comments(first)] == ["Quoi ?"]
    follower = next(t for t in tickets.listing() if t.title == "Suite")
    assert follower.after == [first] and follower.status == "ready"
    assert tickets.pending() == [], "what Notion has is not sent back to it"
    again = notion_import.run(board, config, SPACE)
    assert (again.created, again.existing, again.comments) == (0, 2, 0)
    assert len(tickets.listing()) == 2 and len(tickets.comments(first)) == 1


@case
def a_ticket_made_here_is_created_in_notion_with_its_two_parts(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    made = tickets.create("Neuf", mission="Fais Y.", status="ready", priority=80)
    passage = mirror.flush(board, config, SPACE)
    assert passage.sent == 1 and passage.failed == 0 and tickets.pending() == []
    linked = tickets.get(made.id)
    assert linked is not None and linked.notion in board.pages
    page = board.pages[linked.notion]
    assert page.title == "Neuf" and store.read(page, "statut") == "ready"
    assert "Fais Y." in board.bodies[linked.notion]


@case
def the_changes_that_follow_are_one_write_with_the_last_word(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    made = tickets.create("T", mission="M", status="ready")
    mirror.flush(board, config, SPACE)
    tickets.update(made.id, status="progress")
    tickets.update(made.id, progress="écrit", cost=0.5)
    tickets.update(made.id, report="Rapport.")
    tickets.update(made.id, mission="Autre mission.")
    tickets.comment(made.id, "Une question.", author="ponos")
    assert mirror.flush(board, config, SPACE).sent == 5
    page = tickets.get(made.id)
    assert page is not None
    shown = board.pages[page.notion]
    assert store.read(shown, "statut") == "progress" and store.read(shown, "Cost") == 0.5
    assert "Autre mission." in board.bodies[page.notion]
    assert "Rapport." in board.bodies[page.notion]
    assert board.said == [(page.notion, "Une question.")]
    tickets.delete(made.id)
    mirror.flush(board, config, SPACE)
    assert board.trashed == [page.notion]


@case
def notion_down_grows_the_queue_and_the_return_empties_it(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    board.down = "refused"
    first = tickets.create("Un", status="ready")
    second = tickets.create("Deux", status="ready")
    tickets.update(first.id, status="progress")
    passage = mirror.flush(board, config, SPACE)
    assert passage.sent == 0 and passage.failed == 2
    queue = tickets.pending()
    assert len(queue) == 3, "nothing is lost"
    assert queue[0].tries == 1 and "invalid token" in queue[0].error
    assert tickets.get(first.id) is not None and tickets.get(second.id) is not None, (
        "no ticket is held by it"
    )
    mirror.flush(board, config, SPACE)
    assert all(change.tries >= 2 for change in tickets.pending()[:1])
    board.down = ""
    passage = mirror.flush(board, config, SPACE)
    assert passage.failed == 0 and tickets.pending() == []
    mirrored = tickets.get(first.id)
    assert mirrored is not None
    assert store.read(board.pages[mirrored.notion], "statut") == "progress"
    assert len(board.pages) == 2


@case
def a_failed_creation_holds_back_the_rest_of_its_ticket_only(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    board.down = "offline"
    one = tickets.create("Un")
    tickets.comment(one.id, "Mot.")
    mirror.flush(board, config, SPACE)
    assert [change.tries for change in tickets.pending()] == [1, 0], "the comment waits its turn"
    board.down = ""
    mirror.flush(board, config, SPACE)
    assert tickets.pending() == [] and len(board.said) == 1


@case
def what_a_person_does_in_notion_rises_and_nothing_else_does(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    seen: dict[str, str] = {}
    page = _page(board, "Ancien", "## Mission\n\nV1.", statut="draft", Priorité=10)
    notion_import.run(board, config, SPACE)
    # A status, a Mission, a comment, a priority and a brand new page.
    board.update("tickets", page, {"statut": "ready", "Priorité": 99})
    board.bodies[page] = "## Mission\n\nV2."
    board.talk[page] = [store.Comment("Salut", "2026-11-01T09:00:00Z", "c1", "", "someone")]
    fresh = _page(board, "Nouveau", "## Mission\n\nNeuve.", statut="ready")
    report = notion_import.rise(board, config, SPACE, seen)
    assert report.created == 1 and report.changed == 1 and report.comments == 1
    ticket = tickets.get(page)
    assert ticket is not None and ticket.status == "ready" and ticket.mission == "V2."
    assert ticket.priority == 10, "the priority is Ponos's: the mirror writes over it"
    assert [c.text for c in tickets.comments(page)] == ["Salut"]
    created = tickets.get(fresh)
    assert created is not None and created.mission == "Neuve."
    assert tickets.pending() == [], "what rises is never sent back"
    assert not notion_import.rise(board, config, SPACE, seen), "a second reading finds nothing"


@case
def a_ticket_with_changes_in_the_queue_is_not_read_upward(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    page = _page(board, "T", "## Mission\n\nV1.", statut="ready")
    notion_import.run(board, config, SPACE)
    tickets.update(page, status="progress")
    board.bodies[page] = "## Mission\n\nV2."
    notion_import.rise(board, config, SPACE, {})
    ticket = tickets.get(page)
    assert ticket is not None and ticket.status == "progress" and ticket.mission == "V1."
    mirror.flush(board, config, SPACE)
    assert store.read(board.pages[page], "statut") == "progress"


@case
def a_comment_the_mirror_sent_does_not_come_back_as_a_second_one(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    page = _page(board, "T", "## Mission\n\nM.", statut="blocked")
    notion_import.run(board, config, SPACE)
    tickets.comment(page, "Je bloque.", author="notion-user")
    mirror.flush(board, config, SPACE)
    board.talk[page] = [
        store.Comment("Je bloque.", "2026-11-02T10:00:00Z", "c9", "", "notion-user")
    ]
    notion_import.rise(board, config, SPACE, {})
    assert [c.text for c in tickets.comments(page)] == ["Je bloque."]
