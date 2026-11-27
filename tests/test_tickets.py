"""`tickets.py`: the ticket as `ponos.db` keeps it."""

from __future__ import annotations

from pathlib import Path

from support import case

from ponos import tickets


@case
def a_ticket_is_written_and_read_back_with_its_two_parts(state_home: Path) -> None:
    made = tickets.create(
        "Ajouter X", mission="Fais X.", project="3ca451680af481a8", priority=70, plan_first=True
    )
    assert len(made.id) == 32 and "-" not in made.id
    assert made.status == "draft" and made.priority == 70 and made.plan_first is True
    assert made.journal == "" and made.result == "" and made.created_at == made.edited_at
    assert tickets.get(made.id) == made
    assert tickets.get("0" * 32) is None


@case
def a_given_id_is_kept_without_dashes_and_not_taken_twice(state_home: Path) -> None:
    page = "41045168-0af4-81b9-9f5b-fda109a9e5f9"
    made = tickets.create("T", id=page)
    assert made.id == page.replace("-", "")
    try:
        tickets.create("T", id=page)
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("an id is taken once")


@case
def an_unknown_status_or_column_is_refused(state_home: Path) -> None:
    for values in ({"status": "finished"}, {"colour": "red"}):
        try:
            tickets.create("T", **values)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"{values} should be refused")
    assert tickets.listing() == []


@case
def a_change_moves_the_edit_date_only_when_it_changes_something(state_home: Path) -> None:
    ticket = tickets.create("T", status="ready", edited_at="2026-01-01T00:00:00+00:00")
    same = tickets.update(ticket.id, status="ready")
    assert same is not None and same.edited_at == ticket.edited_at
    moved = tickets.update(ticket.id, status="progress", cost=0.5)
    assert moved is not None and moved.edited_at != ticket.edited_at and moved.cost == 0.5
    assert tickets.update("0" * 32, title="x") is None


@case
def tickets_are_listed_by_priority_within_a_status(state_home: Path) -> None:
    low = tickets.create("low", status="ready", priority=10)
    high = tickets.create("high", status="ready", priority=90)
    tickets.create("other", status="done")
    assert [t.id for t in tickets.listing(status="ready")] == [high.id, low.id]
    assert len(tickets.listing()) == 3


@case
def what_a_ticket_comes_after_is_a_set(state_home: Path) -> None:
    first = tickets.create("first")
    second = tickets.create("second", after=[first.id])
    assert second.after == [first.id]
    updated = tickets.update(second.id, after=[])
    assert updated is not None and updated.after == []


@case
def comments_follow_their_ticket_and_leave_with_it(state_home: Path) -> None:
    ticket = tickets.create("T")
    note = tickets.comment(ticket.id, "oui", author="Léa")
    assert [(c.text, c.author) for c in tickets.comments(ticket.id)] == [("oui", "Léa")]
    assert note.id
    assert tickets.delete(ticket.id) is True
    assert tickets.comments(ticket.id) == [] and tickets.delete(ticket.id) is False
    try:
        tickets.comment(ticket.id, "x")
    except ValueError:
        pass
    else:
        raise AssertionError("no comment on a ticket that is not there")


@case
def a_ticket_cannot_come_after_itself_even_through_others(state_home: Path) -> None:
    first = tickets.create("A")
    second = tickets.create("B", after=[first.id])
    third = tickets.create("C", after=[second.id])
    for wanted in ([third.id], [second.id], [first.id]):
        try:
            tickets.update(first.id, after=wanted)
        except ValueError as error:
            said = str(error)
        else:
            raise AssertionError(f"{wanted} closes a loop")
    assert said == f"{first.public_id} cannot wait for itself", said
    try:
        tickets.update(first.id, after=[third.id])
    except ValueError as error:
        loop = f"{first.public_id} → {third.public_id} → {second.public_id} → {first.public_id}"
        assert loop in str(error), error
    assert tickets.get(first.id).after == []  # type: ignore[union-attr]
    # What is no loop is kept: two tickets waiting for the same one.
    assert tickets.update(third.id, after=[second.id, first.id]) is not None
    assert sorted(tickets.get(third.id).after) == sorted([first.id, second.id])  # type: ignore[union-attr]
