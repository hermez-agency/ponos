"""`public_ids.py`: `PON-142`, the id a person says out loud."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

from support import case

from ponos import db, projectless, public_ids, tickets


def _project(name: str, page: str) -> str:
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO board_pages (id, collection, title, created, edited)"
            " VALUES (?, 'projects', ?, '', '')",
            (page, name),
        )
    return page


@case
def a_prefix_is_drawn_from_the_name_and_unique_among_projects() -> None:
    assert public_ids.derive("Ponos", set()) == "PON"
    assert public_ids.derive("Brand Assets", set()) == "BA"
    assert public_ids.derive("Éléphant Rose", set()) == "ER"
    assert public_ids.derive("Ponos", {"PON"}) == "PONO"
    taken = {"PON", "PONO"}
    one = public_ids.derive("Ponos", taken)
    assert one not in taken and 2 <= len(one) <= 4 and one.isalpha() and one.isupper()
    assert public_ids.derive("", set()) not in {""}


@case
def tickets_are_numbered_per_project_and_a_project_without_one_has_the_common_prefix(
    state_home: Path,
) -> None:
    ponos = _project("Ponos", "a" * 32)
    brand = _project("Brand Assets", "b" * 32)
    first = tickets.create("un", project=ponos)
    second = tickets.create("deux", project=ponos)
    other = tickets.create("autre", project=brand)
    loose = tickets.create("libre")
    assert [first.public_id, second.public_id] == ["PON-1", "PON-2"]
    assert other.public_id == "BA-1"
    assert loose.project == projectless.ID and loose.public_id == "T-1"
    # Stored, not computed: read back as it was written.
    assert tickets.get(second.id) == second


@case
def a_ticket_that_changes_project_keeps_its_id_and_the_new_project_never_reuses_a_number(
    state_home: Path,
) -> None:
    ponos = _project("Ponos", "a" * 32)
    brand = _project("Brand Assets", "b" * 32)
    moved = tickets.create("un", project=ponos)
    tickets.update(moved.id, project=brand)
    kept = tickets.get(moved.id)
    assert kept is not None and kept.public_id == "PON-1"
    assert tickets.create("deux", project=ponos).public_id == "PON-2"
    assert tickets.create("trois", project=brand).public_id == "BA-1"
    # A number given is not given again, even once its ticket is gone.
    tickets.delete(moved.id)
    assert tickets.create("quatre", project=ponos).public_id == "PON-3"


@case
def tickets_created_at_the_same_time_all_get_their_own_number(state_home: Path) -> None:
    project = _project("Ponos", "a" * 32)
    made: list[str] = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(6):
                made.append(tickets.create("t", project=project).public_id)
        except BaseException as error:  # noqa: BLE001  # the test reports what a thread met
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    assert len(made) == 48 and len(set(made)) == 48
    assert set(made) == {f"PON-{number}" for number in range(1, 49)}


@case
def a_chosen_prefix_is_kept_and_refused_when_it_is_another_projects(state_home: Path) -> None:
    ponos = _project("Ponos", "a" * 32)
    brand = _project("Brand Assets", "b" * 32)
    assert public_ids.prefix(ponos) == "PON"
    assert public_ids.choose(ponos, " po ") == "PO"
    assert tickets.create("un", project=ponos).public_id == "PO-1"
    for wrong, why in (("PO", "taken"), ("1A", "shape"), ("T", "common")):
        try:
            public_ids.choose(brand, wrong)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{wrong} should be refused: {why}")
    # Renaming the project later does not move the prefix it was given.
    with db.transaction() as connection:
        connection.execute("UPDATE board_pages SET title = 'Autre' WHERE id = ?", (ponos,))
    assert public_ids.prefix(ponos) == "PO"


@case
def existing_tickets_are_numbered_project_by_project_in_the_order_of_their_creation() -> None:
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    names = [db.name(migration) for migration in db.MIGRATIONS]
    before = db.MIGRATIONS[: names.index("tickets_have_a_public_id")]
    old = db.open_at(location, before)
    try:
        old.execute(
            "INSERT INTO board_pages (id, collection, title, created, edited)"
            " VALUES ('a', 'projects', 'Ponos', '', '')"
        )
        for ticket, project, at in (
            ("3" * 32, "a", "2026-03-01"),
            ("1" * 32, "a", "2026-01-01"),
            ("2" * 32, "a", "2026-02-01"),
            ("4" * 32, projectless.ID, "2026-04-01"),
        ):
            old.execute(
                "INSERT INTO tickets (id, title, project, created_at, edited_at)"
                " VALUES (?, 't', ?, ?, ?)",
                (ticket, project, at, at),
            )
        old.commit()
    finally:
        old.close()
    new = db.open_at(location, db.MIGRATIONS)
    try:
        numbered = dict(new.execute("SELECT id, prefix || '-' || number FROM tickets").fetchall())
        assert numbered == {
            "1" * 32: "PON-1",
            "2" * 32: "PON-2",
            "3" * 32: "PON-3",
            "4" * 32: "T-1",
        }
        # The counters go on from there.
        assert new.execute("SELECT last FROM ticket_counters WHERE prefix = 'PON'").fetchone() == (
            3,
        )
    finally:
        new.close()


@case
def a_ticket_is_found_by_every_form_of_its_id(state_home: Path) -> None:
    project = _project("Ponos", "a" * 32)
    ticket = tickets.create("un", project=project)
    tickets.create("deux", project=project)
    dashed = "-".join(
        (ticket.id[:8], ticket.id[8:12], ticket.id[12:16], ticket.id[16:20], ticket.id[20:])
    )
    for reference in (
        "PON-1",
        "pon-1",
        " Pon-1 ",
        ticket.id,
        ticket.id.upper(),
        dashed,
        ticket.id[-8:],
        f"https://console.invalid/tickets/{ticket.id}?tab=1",
        "https://console.invalid/tickets/pon-1/",
    ):
        found = tickets.resolve(reference)
        assert found is not None and found.id == ticket.id, reference
    for reference in ("", "PON-9", "XYZ-1", "ffffffff", "not a ticket"):
        assert tickets.resolve(reference) is None, reference


@case
def the_database_refuses_two_tickets_with_one_public_id(state_home: Path) -> None:
    project = _project("Ponos", "a" * 32)
    tickets.create("un", project=project)
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO tickets (id, title, project, prefix, number, created_at, edited_at)"
                " VALUES (?, 't', ?, 'PON', 1, '', '')",
                ("8" * 32, project),
            )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("a public id is given once")
