"""`estimates.py`: what a ticket is likely to cost and take, from the tickets that ran."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import _bare_api, _TalkClient, case

from ponos import db, estimates, store
from ponos.web import api as web_api

# Ten Code/Bug tickets of one project: the costs and the minutes each took.
COSTS = (0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 10.0)
MINUTES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def _ran(
    ticket: str,
    *,
    project: str = "Ponos",
    kind: str = "code",
    subtype: str = "bug",
    model: str = "opus",
    cost: float | None = 1.0,
    minutes: float = 5,
) -> None:
    """One run that ended, written into the journal as a session would have left it."""
    start = datetime(2026, 10, 23, 9, tzinfo=UTC)
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO runs (ticket, project, kind, subtype, model, started_at, ended_at,"
            " status, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, 'done', ?)",
            (
                ticket,
                project,
                kind,
                subtype,
                model,
                start.isoformat(timespec="seconds"),
                (start + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
                cost,
            ),
        )


def _basis(*asked: str) -> str:
    """Which tickets an estimate was drawn from: there must be one."""
    found = estimates.estimate(*asked)
    assert found is not None, asked
    return str(found["basis"])


def _ten_bugs() -> None:
    for number, (cost, minutes) in enumerate(zip(COSTS, MINUTES, strict=True)):
        _ran(f"{number:032d}", cost=cost, minutes=minutes)


@case
def a_new_bug_is_estimated_from_the_ten_bugs_of_its_project(state_home: Path) -> None:
    _ten_bugs()
    found = estimates.estimate("Ponos", "code", "bug", "claude-opus-5-5")
    assert found == {
        "cost": 1.1,
        "cost_high": 1.64,
        "seconds": 330,
        "seconds_high": 492,
        "tickets": 10,
        "basis": "subtype",
    }, found


@case
def fewer_than_five_tickets_alike_make_no_estimate(state_home: Path) -> None:
    for number in range(4):
        _ran(f"{number:032d}")
    assert estimates.estimate("Ponos", "code", "bug") is None
    assert estimates.estimate("Ponos", "", "bug") is None, "no type, nothing to compare on"


@case
def an_estimate_falls_back_on_the_project_and_type_then_on_the_type(state_home: Path) -> None:
    for number in range(3):
        _ran(f"a{number:031d}", subtype="bug")
    for number in range(3):
        _ran(f"b{number:031d}", subtype="feature")
    assert _basis("Ponos", "code", "bug") == "project"
    for number in range(4):
        _ran(f"c{number:031d}", project="Leadz", subtype="bug")
    found = estimates.estimate("Leadz", "code", "bug")
    assert found is not None
    assert found["basis"] == "type" and found["tickets"] == 10, found
    assert estimates.estimate("Leadz", "writing") is None


@case
def a_ticket_is_its_runs_added_up_and_never_its_own_precedent(state_home: Path) -> None:
    _ten_bugs()
    # Taken twice: the second run is the same ticket, its bill and its time added.
    _ran(f"{9:032d}", cost=2.0, minutes=20)
    # Paid for by nobody: it would count as free.
    _ran("f" * 32, cost=None)
    done = {one.ticket: one for one in estimates.tickets()}
    assert done[f"{9:032d}"].cost == 12.0 and done[f"{9:032d}"].seconds == 1800
    assert "f" * 32 not in done
    found = estimates.estimate("Ponos", "code", "bug", ticket=f"{0:032d}")
    assert found is not None
    assert found["tickets"] == 9, found


@case
def an_estimate_compares_the_model_only_when_the_ticket_names_one(state_home: Path) -> None:
    _ten_bugs()
    assert _basis("Ponos", "code", "bug", "haiku") == "project"
    assert _basis("Ponos", "code", "bug", "") == "subtype"


class _BugClient(_TalkClient):
    """A ready Code/Bug ticket of the project Ponos."""

    def __init__(self, status: str = "ready") -> None:
        super().__init__([])
        self._status = status

    def page(self, page_id: str) -> store.Page:
        return store.Page(
            id="1a2b3c4d-0000-0000-0000-000000000000",
            url="https://board.invalid/p",
            title="Le bandeau ne se ferme pas",
            properties={
                "statut": {"type": "status", "status": {"name": self._status}},
                "Type": {"type": "select", "select": {"name": "Code"}},
                "Sous-type": {"type": "select", "select": {"name": "Bug"}},
                "Project": {"type": "relation", "relation": [{"id": "p" * 32}]},
            },
            raw={"created_time": "2026-11-01T09:00:00.000Z"},
        )

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        return "Le bandeau reste affiché."


def _api(client: _TalkClient) -> web_api.Api:
    api = _bare_api(client)
    assert api._runner is not None
    api._runner._workspace = type("W", (), {"goals": "", "projects": ""})()
    api._projects = {"p" * 32: {"id": "p" * 32, "name": "Ponos", "kind": "code"}}
    api._projects_at = time.time()
    return api


@case
def the_page_of_a_ready_bug_says_what_it_is_likely_to_cost(state_home: Path) -> None:
    _ten_bugs()
    found = _api(_BugClient()).ticket("1a2b3c4d000000000000000000000000")["estimate"]
    assert found["cost"] == 1.1 and found["cost_high"] == 1.64, found
    assert "estimate" not in _api(_BugClient("done")).ticket("1a2b3c4d000000000000000000000000")


@case
def the_page_of_a_ticket_without_history_has_no_estimate(state_home: Path) -> None:
    for number in range(4):
        _ran(f"{number:032d}")
    page = _api(_BugClient()).ticket("1a2b3c4d000000000000000000000000")
    assert page["estimate"] is None, "nothing rather than a zero"


@case
def the_new_ticket_form_asks_for_the_estimate_of_what_it_holds(state_home: Path) -> None:
    _ten_bugs()
    api = _api(_BugClient())
    assert api.estimate("p" * 32, "code", "bug")["estimate"]["basis"] == "subtype"
    # The type left to the runner: compared on the project's kind.
    assert api.estimate("p" * 32, "", "")["estimate"]["basis"] == "project"
    assert api.estimate("", "writing")["estimate"] is None
