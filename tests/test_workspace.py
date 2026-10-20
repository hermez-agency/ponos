"""`workspace.py`: a workspace page, and the databases the runner finds under it."""

from __future__ import annotations

from support import _FakeClient, _settings, case

from ponos import notion, workspace

# -- the workspace -----------------------------------------------------------


@case
def the_rows_of_a_workspace_become_the_runners_databases():
    client = _FakeClient(
        {"Tickets": "p-tickets", "Projects": "p-projects", "Context": "p-context"},
        text="Je suis Camille Martin.",
    )
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "Je suis Camille Martin."
    assert not space.warnings


@case
def a_row_is_found_however_its_title_is_capitalised():
    client = _FakeClient({"tickets": "p-tickets", "CONTEXT": "p-context"}, text="x")
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "x"


@case
def a_board_built_before_the_names_were_settled_still_resolves():
    """The rows shipped as "Master Tickets" and "Soul" before those names settled.

    Renaming four rows by hand is not a migration anyone should be asked to run,
    so the old titles are tried after the current ones — and only while the
    configuration itself names none, since a title someone typed is a title
    they meant.
    """
    client = _FakeClient(
        {"Master Tickets": "p-tickets", "Master project": "p-projects", "Soul": "p-soul"},
        text="who I am",
    )
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "who I am"
    assert not space.warnings

    # The new names win when a board carries both, rather than the older row.
    both = _FakeClient({"Tickets": "p-new", "Master Tickets": "p-old"})
    assert workspace.from_notion(both, _settings()).tickets == "db-of-p-new"

    # And a configuration that names a row is never second-guessed.
    named = _settings(pages={"tickets": "Backlog"})
    try:
        workspace.from_notion(_FakeClient({"Master Tickets": "p-old"}), named)
    except notion.NotionError as error:
        assert "Backlog" in str(error)
    else:
        raise AssertionError("a named row must not fall back on a legacy title")


@case
def a_missing_context_page_warns_but_never_fails_a_run():
    client = _FakeClient({"Tickets": "p-tickets"})
    space = workspace.from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "" and space.projects == ""
    assert any("Context" in warning for warning in space.warnings)

    # Present but unreadable, and present but empty, are both worth saying too.
    unreadable = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, broken={"p-context"})
    assert any(
        "unreadable" in warning
        for warning in workspace.from_notion(unreadable, _settings()).warnings
    )
    empty = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, text="   ")
    assert any("empty" in warning for warning in workspace.from_notion(empty, _settings()).warnings)


@case
def a_missing_tickets_page_is_the_one_thing_that_fails():
    client = _FakeClient({"Context": "p-context", "Projects": "p-projects"})
    try:
        workspace.from_notion(client, _settings())
    except notion.NotionError as error:
        assert "Tickets" in str(error)
        assert "Context" in str(error), "the message lists what was actually found"
    else:
        raise AssertionError("a workspace without a tickets page must not resolve")


@case
def an_explicit_database_still_wins_over_the_workspace():
    client = _FakeClient({"Tickets": "p-tickets"})
    space = workspace.from_notion(client, _settings(tickets_database="chosen"))
    assert space.tickets == "db-of-chosen"

    # And a configuration written before workspaces existed resolves the same.
    legacy = workspace.from_notion(client, _settings(workspace="", tickets_database="chosen"))
    assert legacy.tickets == "db-of-chosen"
    assert legacy.rows == {} and not legacy.warnings
