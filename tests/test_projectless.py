"""`projectless.py`: « Sans projet », and a project named rather than pointed at."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from support import _board, _local_api, _Nudged, case

from ponos import db, projectless, store, tickets
from ponos.ledger import Ledger
from ponos.web import board as web_board
from ponos.web.api import Api

# -- reading a name -----------------------------------------------------------

PAGES = [("a" * 32, "Changer d'adresse"), ("b" * 32, "Écrire")]


@case
def a_name_is_read_whatever_its_case_and_its_accents() -> None:
    def listed() -> list[tuple[str, str]]:
        return PAGES

    assert projectless.resolve("changer D'ADRESSE", listed) == "a" * 32
    assert projectless.resolve(["ecrire"], listed) == "b" * 32
    assert projectless.resolve("  Écrire  ", listed) == "b" * 32


@case
def an_id_is_kept_and_nothing_is_sans_projet() -> None:
    def never() -> list[tuple[str, str]]:
        raise AssertionError("an id is not looked up")

    assert projectless.resolve("c" * 32, never) == "c" * 32
    dashed = "12345678-1234-1234-1234-123456789abc"
    assert projectless.resolve(dashed, never) == dashed.replace("-", "")
    assert projectless.resolve("", never) == projectless.ID
    assert projectless.resolve([], never) == projectless.ID
    assert projectless.resolve("sans projet", lambda: PAGES) == projectless.ID
    assert projectless.resolve("Unknown", lambda: PAGES) == projectless.ID


@case
def a_name_nobody_has_is_refused_with_the_names_that_exist() -> None:
    try:
        projectless.resolve("Déménager", lambda: PAGES)
    except projectless.UnknownProject as error:
        assert error.given == "Déménager"
        assert error.known == ["Changer d'adresse", "Écrire"]
        assert "Déménager" in str(error) and "Changer d'adresse, Écrire" in str(error)
        assert isinstance(error, ValueError), "the console answers a refusal, not a crash"
    else:
        raise AssertionError("an unknown name must be refused")


# -- the page -----------------------------------------------------------------


def _page() -> tuple[str, int] | None:
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            "SELECT title, trashed FROM board_pages WHERE id = ?", (projectless.ID,)
        ).fetchone()
    return (str(row[0]), int(row[1])) if row else None


@case
def the_page_is_called_in_the_runners_language_and_kept_when_renamed(state_home: Path) -> None:
    assert _page() == ("Unknown", 0), "the migration makes it"
    projectless.ensure("fr")
    assert _page() == ("Sans projet", 0)
    with db.transaction() as connection:
        connection.execute(
            "UPDATE board_pages SET title = 'Divers', trashed = 1 WHERE id = ?", (projectless.ID,)
        )
    projectless.ensure("en")
    assert _page() == ("Divers", 0), "brought back, under the name somebody gave it"


# -- through the board ----------------------------------------------------------


@case
def a_ticket_is_kept_under_its_projects_id_and_without_one_under_sans_projet(
    state_home: Path,
) -> None:
    with _board("fr") as board:
        projectless.ensure("fr")
        settings = board.settings
        space = board.workspace(settings)
        moving = board.create_row(space.projects, "Changer d'adresse")
        relation = settings.prop("project")
        named = board.create_row(space.tickets, "La poste", {relation: ["changer d’adresse"]})
        nothing = board.create_row(space.tickets, "Le passeport")
        assert tickets.get(named).project == moving  # type: ignore[union-attr]
        assert tickets.get(nothing).project == projectless.ID  # type: ignore[union-attr]
        board.update(space.tickets, nothing, {relation: ["Changer d'adresse"]})
        assert tickets.get(nothing).project == moving  # type: ignore[union-attr]
        try:
            board.create_row(space.tickets, "Ailleurs", {relation: ["Déménager"]})
        except projectless.UnknownProject as error:
            assert str(error).startswith("projet inconnu : Déménager — projets disponibles : ")
            assert "Changer d'adresse" in str(error) and "Sans projet" not in str(error)
        else:
            raise AssertionError("a project nobody has must be refused")
        assert sorted(record.title for record in tickets.listing()) == ["La poste", "Le passeport"]


@case
def the_migration_puts_names_back_into_ids_and_the_rest_in_sans_projet(state_home: Path) -> None:
    with _board():
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO board_pages (id, collection, title, created, edited)"
                " VALUES (?, 'projects', 'Changer d''adresse', 'x', 'x')",
                ("a" * 32,),
            )
        named = tickets.create("La poste", project="Changer d'adresse").id
        empty = tickets.create("Le passeport").id
        with db.transaction() as connection:
            # As a ticket written before the migration: with no project at all.
            connection.execute("UPDATE tickets SET project = '' WHERE id = ?", (empty,))
        pointed = tickets.create("Le reste", project="c" * 32).id
        lost = tickets.create("Perdu", project="Nulle part").id
        with db.transaction() as connection:
            projectless.migrate(connection)
        assert _page() == ("Unknown", 0)
        projects = {one: tickets.get(one).project for one in (named, empty, pointed, lost)}  # type: ignore[union-attr]
        assert projects == {
            named: "a" * 32,
            empty: projectless.ID,
            pointed: "c" * 32,
            lost: "Nulle part",
        }, "a name nobody has is left as it was"


def _api(board: Ledger) -> Api:
    api = _local_api(board)
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    api._outbox = web_board.Outbox(journal=lambda report: None)
    api.watch = _Nudged()  # type: ignore[assignment]  # a fake: only counts its nudges
    return api


@case
def the_console_creates_a_ticket_by_its_projects_name_and_moves_one_to_another() -> None:
    with _board() as board:
        projectless.ensure("")
        api = _api(board)
        space = board.workspace(board.settings)
        moving = board.create_row(space.projects, "Changer d'adresse")
        made = api.create_ticket("La poste", project="Changer d'adresse")
        relation = board.settings.prop("project")
        assert store.read(board.page(made["id"]), relation) == [moving]
        bare = api.create_ticket("Le passeport")
        assert store.read(board.page(bare["id"]), relation) == [projectless.ID]
        row = api.projects()[projectless.ID]
        assert row["builtin"] is True and row["kind"] == "document"
        assert "builtin" not in api.projects()[moving]

        moved = api.set_ticket_project(bare["id"], "changer d'adresse", ready=True)
        assert moved["project"] == moving and moved["project_name"] == "Changer d'adresse"
        assert moved["status"] == board.settings.state("ready")
        refusals: list[Callable[[], object]] = [
            lambda: api.save_project(projectless.ID, {"repository": "acme/site"}),
            lambda: api.save_project(projectless.ID, {"kind": "code"}),
            lambda: api.delete_project(projectless.ID, {"confirm": "Unknown"}),
            lambda: api.create_ticket("Ailleurs", project="Déménager"),
        ]
        for refused in refusals:
            try:
                refused()
            except ValueError:
                pass
            else:
                raise AssertionError("« Sans projet » keeps no repository and stays")
