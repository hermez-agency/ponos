"""`ledger.py`: the tickets served from `ponos.db`, the rest left to Notion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from support import _config, case
from test_mirror import Notion, _page

from ponos import mirror, notion_import, store, ticket_page, tickets
from ponos.ledger import Ledger
from ponos.workspace import Workspace


def _ledger(board: Any) -> tuple[Ledger, Workspace]:
    config = _config("")
    ledger = Ledger(board, config.notion)
    return ledger, ledger.workspace(config.notion)


@case
def before_the_import_the_tickets_are_still_notions(state_home: Path) -> None:
    board: Any = Notion()
    page = _page(board, "Ancien", "## Mission\n\nV1.", statut="ready")
    ledger, space = _ledger(board)
    assert [one.id for one in ledger.query(space.tickets)] == [page]
    ledger.update(space.tickets, page, {"statut": "progress"})
    assert store.read(board.pages[page], "statut") == "progress"
    assert tickets.empty(), "nothing is written to the database before the import"


@case
def an_imported_ticket_is_read_as_a_page_with_the_columns_of_the_board(state_home: Path) -> None:
    board: Any = Notion()
    page = _page(
        board, "Ajouter X", "## Mission\n\nFais X.", statut="ready", Priorité=70, Type="Code"
    )
    config = _config("")
    ledger, space = _ledger(board)
    notion_import.run(board, config, space)
    found = ledger.page(page)
    assert found.title == "Ajouter X" and found.id == page
    settings = config.notion
    assert store.read(found, settings.prop("status")) == "ready"
    assert store.read(found, settings.prop("priority")) == 70
    assert store.read(found, settings.prop("type")) == settings.kind("code")
    assert store.read(found, settings.prop("pull_request")) is None
    assert found.raw["last_edited_time"]
    assert [one.id for one in ledger.query(space.tickets)] == [page]
    ready = {"property": settings.prop("status"), "status": {"equals": "ready"}}
    assert len(ledger.query(space.tickets, ready)) == 1
    ready["status"] = {"equals": "done"}
    assert ledger.query(space.tickets, ready) == []


@case
def a_write_to_a_ticket_stays_in_the_database_and_waits_in_the_queue(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    page = _page(board, "T", "## Mission\n\nM.", statut="ready")
    ledger, space = _ledger(board)
    notion_import.run(board, config, space)
    settings = config.notion
    ledger.update(
        space.tickets,
        page,
        {settings.prop("status"): "progress", settings.prop("progress"): "écrit", "Cost": 0.5},
    )
    ledger.replace_section(page, ticket_page.DONE, "## Ce qui a été fait\n\n✅ Fait.")
    ledger.comment(page, "Une question.")
    mine = tickets.get(page)
    assert mine is not None and mine.status == "progress" and mine.progress == "écrit"
    assert mine.mission == "M." and mine.report == "✅ Fait."
    assert [one.text for one in ledger.comments(page)] == ["Une question."]
    assert ledger.blocks_text(page).startswith("## ")
    assert ticket_page.split(ledger.blocks_text(page)).done == "✅ Fait."
    assert store.read(board.pages[page], "statut") == "ready", "Notion has not been told"
    assert tickets.pending()
    assert mirror.flush(board, config, space).failed == 0
    assert store.read(board.pages[page], "statut") == "progress"
    assert "✅ Fait." in board.bodies[page] and "M." in board.bodies[page]


@case
def a_ticket_created_through_the_ledger_is_created_in_notion_by_the_mirror(
    state_home: Path,
) -> None:
    board: Any = Notion()
    config = _config("")
    _page(board, "Premier", "## Mission\n\nM.", statut="ready")
    ledger, space = _ledger(board)
    notion_import.run(board, config, space)
    settings = config.notion
    made = ledger.create_row(
        space.tickets, "Depuis la console", {settings.prop("status"): "draft", "Priorité": 80}
    )
    ledger.replace_markdown(made, "## Mission\n\nFais Y.")
    assert {one.title for one in ledger.query(space.tickets)} == {"Premier", "Depuis la console"}
    assert len(board.pages) == 1
    mirror.flush(board, config, space)
    assert len(board.pages) == 2
    record = tickets.get(made)
    assert record is not None and record.notion in board.pages
    assert "Fais Y." in board.bodies[record.notion]
    again = notion_import.rise(board, config, space, {})
    assert again.created == 0, "the page the mirror made is the ticket it came from"
    assert len(tickets.listing()) == 2


@case
def a_ticket_created_in_notion_appears_in_the_ledger_on_the_next_pass(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    _page(board, "Premier", "## Mission\n\nM.", statut="ready")
    ledger, space = _ledger(board)
    notion_import.run(board, config, space)
    fresh = _page(board, "Écrit dans Notion", "## Mission\n\nNeuve.", statut="ready")
    notion_import.rise(board, config, space, {})
    assert fresh in {one.id for one in ledger.query(space.tickets)}
    assert ledger.blocks_text(fresh).endswith("Neuve.")


@case
def the_pages_of_the_other_databases_come_from_the_last_reading_when_notion_will_not_answer(
    state_home: Path,
) -> None:
    board: Any = Notion()
    project = board.create_row("projects", "Site", {})
    config = _config("")
    ledger, space = _ledger(board)
    _page(board, "T", "## Mission\n\nM.", statut="ready")
    notion_import.run(board, config, space)
    assert ledger.page(project).title == "Site"
    fresh = Ledger(board, config.notion)
    del board.pages[project]  # the fake answers StoreError for a page it has not
    assert fresh.page(project).title == "Site"
    try:
        fresh.page("0" * 32)
    except store.StoreError:
        pass
    else:
        raise AssertionError("a page never read has nothing to fall back on")


@case
def a_workspace_that_cannot_be_resolved_is_the_one_last_seen(state_home: Path) -> None:
    board: Any = Notion()
    config = _config("")
    first = Ledger(board, config.notion)
    seen = first.workspace(config.notion)

    class Down(Notion):
        def workspace(self, settings: Any) -> Workspace:
            raise store.Unreachable("no route to Notion")

    down: Any = Down()
    later = Ledger(down, config.notion)
    space = later.workspace(config.notion)
    assert space.tickets == seen.tickets and space.projects == seen.projects
    assert space.warnings
    assert later.me() == "notion-user", "who we are is kept too"


@case
def a_ticket_trashed_through_the_ledger_is_trashed_in_notion_by_the_mirror(
    state_home: Path,
) -> None:
    board: Any = Notion()
    config = _config("")
    page = _page(board, "T", "## Mission\n\nM.", statut="ready")
    ledger, space = _ledger(board)
    notion_import.run(board, config, space)
    ledger.trash(page)
    assert tickets.get(page) is None and ledger.query(space.tickets) == []
    mirror.flush(board, config, space)
    assert board.trashed == [page]
