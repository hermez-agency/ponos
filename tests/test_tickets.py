"""`tickets.py`: the ticket as `ponos.db` keeps it, and the queue the mirror reads."""

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
    assert made.report == "" and made.created_at == made.edited_at
    assert tickets.get(made.id) == made
    assert tickets.get("0" * 32) is None


@case
def a_given_id_is_kept_without_dashes_and_not_taken_twice(state_home: Path) -> None:
    page = "41045168-0af4-81b9-9f5b-fda109a9e5f9"
    made = tickets.create("T", id=page, notion="https://notion/x")
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
def every_change_is_queued_once_and_only_when_it_changes(state_home: Path) -> None:
    ticket = tickets.create("T", status="ready")
    assert [c.what for c in tickets.pending()] == ["created"]
    tickets.update(ticket.id, status="progress")
    tickets.update(ticket.id, status="progress")
    tickets.update(ticket.id, cost=0.5, progress="écrit")
    queue = tickets.pending()
    assert [c.what for c in queue] == ["created", "status", "fields"]
    assert queue[2].payload == {"fields": ["cost", "progress"]}
    assert tickets.update("0" * 32, title="x") is None


@case
def a_ticket_born_from_a_page_is_not_queued_as_created(state_home: Path) -> None:
    tickets.create("T", id="a" * 32, notion="https://notion/a")
    assert tickets.pending() == []


@case
def the_queue_keeps_what_notion_did_not_take(state_home: Path) -> None:
    ticket = tickets.create("T")
    (first,) = tickets.pending()
    tickets.failed(first.id, "502")
    (again,) = tickets.pending()
    assert (again.tries, again.error) == (1, "502")
    tickets.sent(first.id)
    assert tickets.pending() == []
    assert tickets.get(ticket.id) is not None, "the ticket does not depend on Notion"


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
    assert note.id and tickets.pending()[-1].what == "comment"
    assert tickets.delete(ticket.id) is True
    assert tickets.comments(ticket.id) == [] and tickets.delete(ticket.id) is False
    try:
        tickets.comment(ticket.id, "x")
    except ValueError:
        pass
    else:
        raise AssertionError("no comment on a ticket that is not there")
