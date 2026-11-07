"""`ledger.py`: the tickets served from `ponos.db`, the other pages beside them."""

from __future__ import annotations

from pathlib import Path

from support import _board, _config, case

from ponos import pages, store, tickets
from ponos.ledger import Ledger


@case
def a_ticket_is_read_as_a_page_with_the_columns_of_the_board(state_home: Path) -> None:
    settings = _config("").board
    with _board() as ledger:
        space = ledger.workspace(settings)
        made = tickets.create(
            "Ajouter X", mission="Fais X.", status="ready", priority=70, kind="code"
        )
        found = ledger.page(made.id)
        assert found.title == "Ajouter X" and found.id == made.id
        assert store.read(found, settings.prop("status")) == "ready"
        assert store.read(found, settings.prop("priority")) == 70
        assert store.read(found, settings.prop("type")) == settings.kind("code")
        assert store.read(found, settings.prop("pull_request")) is None
        assert found.raw["last_edited_time"]
        assert "Fais X." in ledger.blocks_text(made.id)
        assert [one.id for one in ledger.query(space.tickets)] == [made.id]
        ready = {"property": settings.prop("status"), "select": {"equals": "ready"}}
        assert len(ledger.query(space.tickets, ready)) == 1
        ready["select"] = {"equals": "done"}
        assert ledger.query(space.tickets, ready) == []


@case
def a_ticket_written_and_created_through_the_ledger_is_a_row(state_home: Path) -> None:
    settings = _config("").board
    with _board() as ledger:
        space = ledger.workspace(settings)
        made = ledger.create_row(space.tickets, "Ajouter Y", {settings.prop("status"): "draft"})
        ledger.replace_markdown(made, "## Mission\n\nFais Y.")
        ledger.update(space.tickets, made, {settings.prop("status"): "ready"})
        ledger.comment(made, "Une question ?")
        record = tickets.get(made)
        assert record is not None and record.status == "ready" and record.mission == "Fais Y."
        assert [remark.text for remark in tickets.comments(made)] == ["Une question ?"]
        assert ledger.comments(made)[0].created_by == ledger.me() == "ponos"
        ledger.trash(made)
        assert tickets.get(made) is None


@case
def the_pages_that_are_not_tickets_are_the_board_s_own(state_home: Path) -> None:
    settings = _config("").board
    with _board() as ledger:
        space = ledger.workspace(settings)
        project = ledger.create_row(space.projects, "Site", {"Repository": "acme/site"})
        assert ledger.page(project).title == "Site"
        assert [page.id for page in ledger.query(space.projects)] == [project]
        assert tickets.get(project) is None, "a project is not a ticket"


@case
def a_ticket_is_addressed_by_the_console_and_a_dashed_id_still_names_it(
    state_home: Path,
) -> None:
    settings = _config("").board
    with _board():
        ledger = Ledger(pages.Pages(settings), settings, "en", "https://ponos.example/")
        made = tickets.create("Ancien", mission="V1.", status="ready")
        found = ledger.page(made.id)
        assert found.url == f"https://ponos.example/tickets/{made.id}"
        page = made.id
        dashed = f"{page[:8]}-{page[8:12]}-{page[12:16]}-{page[16:20]}-{page[20:]}"
        assert ledger.page(dashed).id == page
