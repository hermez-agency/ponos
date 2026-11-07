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
    assert report.created == 1 and report.changed == 1 and report.comments == 0
    ticket = tickets.get(page)
    assert ticket is not None and ticket.status == "ready" and ticket.mission == "V2."
    assert ticket.priority == 10, "the priority is Ponos's: the mirror writes over it"
    assert tickets.comments(page) == [], "a comment written in Notion is no longer read"
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
def a_comment_in_notion_is_not_read_after_the_import(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    page = _page(board, "T", "## Mission\n\nM.", statut="blocked")
    notion_import.run(board, config, SPACE)
    board.talk[page] = [store.Comment("Oui.", "2026-11-02T10:00:00Z", "c9", "", "notion-user")]
    notion_import.rise(board, config, SPACE, {})
    assert tickets.comments(page) == []


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
BLOCK = "a1" * 16
FILE_LINE = f"[image attached to the ticket: schéma (Notion block {BLOCK})]"


class Archive(Notion):
    """A Notion with every kind of page, and a file behind a block."""

    def attachment(self, block_id: str) -> str:
        if block_id != BLOCK:
            raise LookupError(f"block {block_id} holds no file")
        return "https://files.example/schema.png"


def _archive() -> tuple[Any, Workspace]:
    board: Any = Archive()
    board.context = "Je suis Salva."
    space = Workspace(
        tickets="tickets",
        projects="projects",
        agents="agents",
        schedules="schedules",
        goals="goals",
        context_page="ctx",
    )
    project = board.create_row("projects", "Ponos", {"Repository": "~/ponos"})
    board.bodies[project] = "Notes du projet."
    board.create_row("agents", "Relecteur")
    board.create_row("goals", "Livrer")
    board.create_row("schedules", "Chaque lundi")
    return board, space


def _serve_files() -> None:
    import httpx

    from ponos import http

    http.forget()
    http.transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )


@case
def the_import_brings_home_the_pages_the_context_the_files_and_the_links(state_home: Path) -> None:
    from ponos import page_files, pages

    board, space = _archive()
    config = _config("")
    first = _page(
        board, "Compte rendu", f"## Mission\n\nFais X.\n\n## Ce qui a été fait\n\n{FILE_LINE}"
    )
    _page(board, "Suite", "## Mission\n\nS.", statut="done", Après=[first])
    board.talk[first] = [store.Comment("Quoi ?", "2026-10-01T10:00:00Z", "c1", "d1", "someone")]
    _serve_files()
    try:
        report = notion_import.run(board, config, space)
    finally:
        from ponos import http

        http.transport = None
        http.forget()
    assert report.problems == []
    assert report.brought == {"projects": 1, "agents": 1, "goals": 1, "schedules": 1}
    assert report.context and report.files == 1 and report.links == 1
    target = pages.Pages(config.notion)
    assert [p.title for p in target.query("projects")] == ["Ponos"]
    assert target.context() == "Je suis Salva."
    assert target.blocks_text(target.query("projects")[0].id) == "Notes du projet."
    kept = page_files.find(BLOCK)
    assert kept is not None and kept.read_bytes() == PNG
    done = tickets.get(next(t.id for t in tickets.listing() if t.title == "Suite"))
    assert done is not None and done.status == "done" and done.after == [first]
    # Replayed: nothing doubles, nothing new.
    again = notion_import.run(board, config, space)
    assert (again.created, again.brought, again.files, again.links) == (0, {}, 0, 0)
    assert len(target.query("projects")) == 1
    parity = notion_import.check(board, config, space)
    assert parity.ok, parity.losses
    assert ("comments", 1, 1) in parity.rows and ("files", 1, 1) in parity.rows


@case
def the_parity_report_lists_what_the_database_lacks(state_home: Path) -> None:
    board, space = _archive()
    config = _config("")
    _page(board, "Un", "## Mission\n\nM.", statut="done")
    notion_import.run(board, config, space)
    assert notion_import.check(board, config, space).ok
    late = _page(board, "Écrit après", "## Mission\n\nN.", statut="ready")
    board.talk[late] = [store.Comment("Salut", "2026-11-01T09:00:00Z", "c1", "", "someone")]
    parity = notion_import.check(board, config, space)
    assert not parity.ok
    assert "ticket missing: Écrit après" in parity.losses
    assert ("tickets", 2, 1) in parity.rows
    assert tickets.get(late) is None, "checking writes nothing"


@case
def a_file_already_dead_in_notion_is_noted_and_is_not_a_loss(state_home: Path) -> None:
    import httpx

    from ponos import http, page_files

    board, space = _archive()
    config = _config("")
    dead = "b2" * 16
    _page(board, "Vieux", f"## Mission\n\n[image attached to the ticket (Notion block {dead})]")
    board.attachment = lambda block: "https://raw.example/gone.png"
    http.forget()
    http.transport = httpx.MockTransport(lambda request: httpx.Response(404))
    try:
        report = notion_import.run(board, config, space)
        assert (report.gone, report.problems) == (1, [])
        assert page_files.gone(dead) and page_files.find(dead) is None
        again = notion_import.run(board, config, space)
        assert again.gone == 0, "a file known to be gone is not asked for again"
        parity = notion_import.check(board, config, space)
    finally:
        http.transport = None
        http.forget()
    assert parity.ok and len(parity.notes) == 1


@case
def the_parity_report_does_not_read_again_a_ticket_whose_two_parts_are_here(
    state_home: Path,
) -> None:
    board, space = _archive()
    config = _config("")
    whole = _page(board, "Plein", "## Mission\n\nM.\n\n## Ce qui a été fait\n\nFait.")
    half = _page(board, "Moitié", "## Mission\n\nM.")
    notion_import.run(board, config, space)
    read: list[str] = []
    reading = board.blocks_text

    def counted(page: str, *args: Any, **kwargs: Any) -> str:
        read.append(page)
        return str(reading(page, *args, **kwargs))

    board.blocks_text = counted
    parity = notion_import.check(board, config, space)
    assert parity.ok, parity.losses
    assert half in read and whole not in read
    assert "1 ticket(s) not read again: both parts are written in ponos.db" in parity.notes
