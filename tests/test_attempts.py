"""`attempts.py`: un ticket qui demande deux tentatives en reçoit un frère, une fois."""

from __future__ import annotations

from pathlib import Path

from support import case

from ponos import attempts, tickets


@case
def the_number_of_attempts_is_one_or_two() -> None:
    assert [attempts.wanted(v) for v in (1, "2", 5, 0, "", "x", None)] == [1, 2, 2, 1, 1, 1, 1]


@case
def a_ticket_asking_two_attempts_gets_a_sibling_clone(state_home: Path) -> None:
    first = tickets.create(
        "Ajouter X",
        mission="Fais X.",
        project="3ca451680af481a8",
        kind="code",
        priority=70,
        status="progress",
        attempts=2,
    )
    second = attempts.sibling(first.id)
    assert second is not None
    assert second.status == "ready" and second.attempts == 1
    assert second.mission == "Fais X." and second.project == first.project
    assert second.priority == 70 and second.kind == "code"
    assert second.twin == first.id
    assert tickets.get(first.id).twin == second.id  # type: ignore[union-attr]
    assert second.title != first.title


@case
def the_sibling_is_made_once_and_makes_none(state_home: Path) -> None:
    first = tickets.create("T", attempts=2)
    second = attempts.sibling(first.id)
    assert second is not None
    assert attempts.sibling(first.id) is None  # already has its sibling
    assert attempts.sibling(second.id) is None  # a clone is one attempt
    assert len(tickets.listing()) == 2


@case
def a_ticket_tried_once_or_unknown_gets_nothing(state_home: Path) -> None:
    once = tickets.create("T")
    assert attempts.sibling(once.id) is None
    assert attempts.sibling("f" * 32) is None
    assert len(tickets.listing()) == 1
