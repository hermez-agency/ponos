"""`dependencies.py`: the tickets one comes after, and which of them are not done."""

from __future__ import annotations

from typing import Any

from support import case

from ponos import dependencies, store
from ponos.web import board as board_module


def _ticket(key: str, title: str, status: str, after: list[str] | None = None) -> store.Page:
    properties: dict[str, Any] = {
        "statut": {"type": "status", "status": {"name": status}},
    }
    if after is not None:
        properties["Après"] = {"type": "relation", "relation": [{"id": one} for one in after]}
    return store.Page(key, f"https://board.invalid/{key}", title, properties)


def _unmet(page: store.Page, board: dict[str, store.Page]) -> list[str]:
    return [found.title for found in dependencies.unmet(page, "Après", "statut", "done", board.get)]


@case
def a_ticket_waits_for_every_ticket_it_comes_after_that_is_not_done() -> None:
    board = {
        "aaaa": _ticket("aaaa", "Migration 1", "progress"),
        "bbbb": _ticket("bbbb", "Migration 2", "done"),
        "cccc": _ticket("cccc", "Migration 3", "ready"),
    }
    waiting = _ticket("dddd", "Migration 4", "ready", ["aa-aa", "bbbb", "cccc"])
    assert _unmet(waiting, board) == ["Migration 1", "Migration 3"]
    found = dependencies.unmet(waiting, "Après", "statut", "done", board.get)
    assert dependencies.said(found) == "Migration 1, Migration 3"


@case
def a_ticket_that_names_nothing_or_nothing_to_be_found_waits_for_nothing() -> None:
    board = {"aaaa": _ticket("aaaa", "Fait", "done")}
    # No column, an empty one, a column that is not a relation, the setting off.
    assert _unmet(_ticket("dddd", "seul", "ready"), board) == []
    assert _unmet(_ticket("dddd", "seul", "ready", []), board) == []
    texted = _ticket("dddd", "seul", "ready")
    texted.properties["Après"] = {"type": "rich_text", "rich_text": []}
    assert _unmet(texted, board) == []
    named = _ticket("dddd", "seul", "ready", ["zzzz"])
    assert dependencies.unmet(named, "", "statut", "done", board.get) == []
    # A page nobody can find never becomes done: it holds nothing back.
    assert _unmet(named, board) == []
    # Nor does a ticket that names itself.
    assert _unmet(_ticket("dddd", "seul", "ready", ["dddd"]), board) == []


@case
def a_ready_card_says_which_tickets_it_waits_for_after_its_date() -> None:
    card = {"id": "dddd", "column": "ready", "scheduled": ""}
    held = board_module.held(card, {}, scheduling=True, after="Migration 1")
    assert held == {"reason": "after", "detail": "Migration 1"}, held
    # A date still to come is said first, as it is everywhere a card waits.
    dated = {**card, "scheduled": "2999-01-01T09:00+00:00"}
    assert board_module.held(dated, {}, scheduling=True, after="M1")["reason"] == "date"
    assert board_module.held(card, {}, scheduling=True)["reason"] == "next"
