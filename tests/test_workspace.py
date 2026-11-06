"""`workspace.py`: a workspace page, and the databases the runner finds under it."""

from __future__ import annotations

from support import _FakeClient, _settings, case

from ponos import config as C
from ponos import notion, workspace


def _from_notion(client: _FakeClient, settings: C.Notion) -> workspace.Workspace:
    return workspace.from_notion(client, settings)  # type: ignore[arg-type]  # a fake: rows and text only


# -- the workspace -----------------------------------------------------------


@case
def the_rows_of_a_workspace_become_the_runners_databases() -> None:
    client = _FakeClient(
        {
            "Tickets": "p-tickets",
            "Projects": "p-projects",
            "Context": "p-context",
            "Objectifs": "p-goals",
        },
        text="Je suis Camille Martin.",
    )
    space = _from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "Je suis Camille Martin."
    assert not space.warnings


@case
def a_row_is_found_however_its_title_is_capitalised() -> None:
    client = _FakeClient({"tickets": "p-tickets", "CONTEXT": "p-context"}, text="x")
    space = _from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "x"


@case
def rows_under_other_titles_are_found_by_the_names_the_configuration_gives() -> None:
    """A board whose rows carry other titles names them under `[notion.pages]`.

    Nothing is guessed past the configured title, nor past the default one: the
    titles the runner used to ship with ("Master Tickets", "Soul") are no
    longer tried on their own.
    """
    rows = {
        "Master Tickets": "p-tickets",
        "Master project": "p-projects",
        "Soul": "p-soul",
        "Objectifs": "p-goals",
    }
    named = _settings(
        pages={"tickets": "Master Tickets", "projects": "Master project", "context": "Soul"}
    )
    space = _from_notion(_FakeClient(rows, text="who I am"), named)
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "who I am"
    assert not space.warnings

    try:
        _from_notion(_FakeClient(rows), _settings())
    except notion.NotionError as error:
        assert "Tickets" in str(error)
    else:
        raise AssertionError("an old title must not stand in for the default one")


@case
def a_missing_context_page_warns_but_never_fails_a_run() -> None:
    client = _FakeClient({"Tickets": "p-tickets"})
    space = _from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "" and space.projects == ""
    assert any("Context" in warning for warning in space.warnings)

    # Present but unreadable, and present but empty, are both worth saying too.
    unreadable = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, broken={"p-context"})
    assert any(
        "unreadable" in warning for warning in _from_notion(unreadable, _settings()).warnings
    )
    empty = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, text="   ")
    assert any("empty" in warning for warning in _from_notion(empty, _settings()).warnings)


@case
def a_missing_tickets_page_is_the_one_thing_that_fails() -> None:
    client = _FakeClient({"Context": "p-context", "Projects": "p-projects"})
    try:
        _from_notion(client, _settings())
    except notion.NotionError as error:
        assert "Tickets" in str(error)
        assert "Context" in str(error), "the message lists what was actually found"
    else:
        raise AssertionError("a workspace without a tickets page must not resolve")


@case
def an_explicit_database_still_wins_over_the_workspace() -> None:
    client = _FakeClient({"Tickets": "p-tickets"})
    space = _from_notion(client, _settings(tickets_database="chosen"))
    assert space.tickets == "db-of-chosen"

    # And a configuration written before workspaces existed resolves the same.
    legacy = _from_notion(client, _settings(workspace="", tickets_database="chosen"))
    assert legacy.tickets == "db-of-chosen"
    assert legacy.rows == {} and not legacy.warnings


@case
def a_missing_goals_page_warns_but_never_fails_a_run() -> None:
    client = _FakeClient({"Tickets": "p-tickets", "Context": "p-context"}, text="x")
    space = _from_notion(client, _settings())
    assert space.tickets == "db-of-p-tickets" and space.goals == ""
    assert [warning for warning in space.warnings if "Objectifs" in warning], space.warnings

    present = _FakeClient({"Tickets": "p-t", "Context": "p-c", "Objectifs": "p-goals"}, text="x")
    found = _from_notion(present, _settings())
    assert found.goals == "db-of-p-goals" and not found.warnings

    unreadable = _FakeClient(
        {"Tickets": "p-t", "Context": "p-c", "Objectifs": "p-goals"}, text="x", broken={"p-goals"}
    )
    space = _from_notion(unreadable, _settings())
    assert space.tickets == "db-of-p-t" and space.goals == ""
    assert any("goals database unreadable" in warning for warning in space.warnings)
