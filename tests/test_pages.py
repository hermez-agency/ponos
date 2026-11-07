"""`pages.py`: the projects, agents, goals and schedules of a board kept in `ponos.db`."""

from __future__ import annotations

from datetime import UTC, datetime

from support import _board, case

from ponos import db, pages, store


@case
def a_page_is_created_read_filtered_and_changed_by_the_names_of_the_board() -> None:
    with _board() as board:
        site = board.create_row("projects", "Site", {"Repository": "user/site"})
        board.create_row("projects", "Blog", {})
        assert [page.title for page in board.query("projects")] == ["Site", "Blog"]
        page = board.page(site)
        assert store.read(page, "Repository") == "user/site"
        assert page.raw["collection"] == "projects" and page.raw["created_time"]
        found = board.query(
            "projects", {"property": "Repository", "rich_text": {"equals": "user/site"}}
        )
        assert [one.id for one in found] == [site]

        board.update("projects", site, {"Repository": "user/other", "Name": "Vitrine"})
        again = board.page(site)
        assert again.title == "Vitrine" and store.read(again, "Repository") == "user/other"
        assert again.raw["last_edited_time"] >= page.raw["last_edited_time"]


@case
def a_page_has_a_body_a_discussion_and_a_trash_that_keeps_it() -> None:
    with _board() as board:
        site = board.create_row("projects", "Site", {})
        board.append_markdown(site, "First.")
        board.append_markdown(site, "Second.")
        assert board.blocks_text(site) == "First.\n\nSecond."
        board.replace_markdown(site, "Only this.")
        assert board.blocks_text(site) == "Only this."

        board.comment(site, "One")
        board.comment(site, "Two")
        assert [remark.text for remark in board.comments(site)] == ["One", "Two"]
        assert {remark.created_by for remark in board.comments(site)} == {"ponos"}

        board.trash(site)
        assert board.query("projects") == []
        try:
            board.page(site)
        except store.Missing:
            pass
        else:
            raise AssertionError("a trashed page is off the board")
        with db.transaction(immediate=False) as connection:
            assert connection.execute("SELECT trashed FROM board_pages").fetchone() == (1,)


@case
def the_standing_context_is_a_page_of_its_own() -> None:
    with _board() as board:
        space = board.workspace(board.settings)
        assert space.context == "" and space.warnings
        board.replace_markdown(pages.CONTEXT_PAGE, "We are small.")
        board.append_markdown(pages.CONTEXT_PAGE, "Be plain.")
        assert board.workspace(board.settings).context == "We are small.\n\nBe plain."
        assert board.blocks_text(pages.CONTEXT_PAGE) == "We are small.\n\nBe plain."


@case
def a_date_is_written_as_the_iso_text_it_is_read_back_from() -> None:
    with _board() as board:
        schedule = board.create_row(
            "schedules", "Weekly", {"Next": datetime(2026, 11, 9, 9, tzinfo=UTC)}
        )
        assert store.read(board.page(schedule), "Next") is not None


@case
def a_relation_to_a_ticket_is_kept_as_it_is() -> None:
    """A schedule's last ticket is the ticket's own id: there is no page of the board to name instead."""
    with _board() as board:
        ticket = board.create_row("tickets", "Un ticket", {"statut": "ready"})
        schedule = board.create_row("schedules", "Weekly", {"Last ticket": [ticket]})
        assert store.read(board.page(schedule), "Last ticket") == [ticket]
