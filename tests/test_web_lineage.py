"""`web/lineage.py`: which tickets a schedule made, and what they came to."""

from __future__ import annotations

from datetime import date

from support import case

from ponos.web import lineage

SCHEDULE = {"id": "s1", "name": "Whisper Desk — rattraper Wispr Flow", "ticket": "t4"}


def _ticket(id: str, title: str, created: str, column: str, cost=None, duration=None) -> dict:
    return {
        "id": id,
        "short": id,
        "title": title,
        "url": "",
        "status": column,
        "column": column,
        "created": created,
        "cost": cost,
        "duration": duration,
        "pull_request": "",
    }


@case
def a_title_is_a_schedules_when_it_is_its_name_and_a_date():
    name = SCHEDULE["name"]
    assert lineage.titled(name, f"{name} — 2026-10-12") == date(2026, 10, 12)
    assert lineage.titled(name, f"{name} — 2026-10-12 09:00") == date(2026, 10, 12)
    assert lineage.titled(name, f"{name} — à revoir") is None
    assert lineage.titled(name, "Whisper Desk — 2026-10-12") is None
    assert lineage.titled("", "— 2026-10-12") is None


@case
def the_tickets_are_found_by_their_line_their_history_their_row_and_their_title():
    name = SCHEDULE["name"]
    tickets = [
        _ticket("t1", "Renamed by hand", "2026-10-05T07:00:00Z", "done", 1.5, 30),
        _ticket("t2", "Also renamed", "2026-10-06T07:00:00Z", "failed", 0.5, 10),
        _ticket("t3", f"{name} — 2026-10-07", "2026-10-07T07:00:00Z", "cancelled"),
        _ticket("t4", "The last one", "2026-10-14T07:00:00Z", "running", 2.0),
        # A title of its but a week away from the day it says: somebody's copy.
        _ticket("t5", f"{name} — 2026-09-01", "2026-10-08T07:00:00Z", "done", 9.0),
        _ticket("t6", "Somebody else's", "2026-10-07T07:00:00Z", "done", 4.0),
    ]
    history = [
        {"status": "scheduled", "id": "t2", "from": name},
        {"status": "scheduled", "id": "t6", "from": "Another", "schedule": "s9"},
    ]
    occurrences = [
        {
            "at": "2026-10-13T07:00:00+00:00",
            "outcome": "skipped",
            "ticket": "",
            "title": "",
            "reason": "open",
        },
        {
            "at": "2026-10-05T07:00:00+00:00",
            "outcome": "born",
            "ticket": "t1",
            "title": "x",
            "reason": "",
        },
    ]
    found = lineage.of(SCHEDULE, tickets, history, occurrences)

    assert [ticket["id"] for ticket in found["tickets"]] == ["t4", "t3", "t2", "t1"], "newest first"
    assert {ticket["id"]: ticket["linked"] for ticket in found["tickets"]}["t3"] == "title"
    assert found["matched"] == 1
    assert found["since"] == "2026-10-05T07:00:00+00:00"

    totals = found["totals"]
    assert totals["tickets"] == 4 and totals["cost"] == 4.0
    assert totals["average_cost"] == round(4.0 / 3, 2), "over the tickets that have a cost"
    assert totals["average_duration"] == 20.0
    assert totals["success"] == round(1 / 3, 4), "done over done, failed and cancelled"
    assert {row["key"]: row["count"] for row in found["statuses"]} == {
        "cancelled": 1,
        "done": 1,
        "failed": 1,
        "running": 1,
    }

    # The passes: the two kept, and the births before the lines were kept,
    # said from their tickets.
    runs = found["runs"]
    assert [(run["outcome"], run["ticket"], run["inferred"]) for run in runs] == [
        ("born", "t4", True),
        ("skipped", "", False),
        ("born", "t3", True),
        ("born", "t2", True),
        ("born", "t1", False),
    ]
    assert runs[-1]["column"] == "done"


@case
def the_weeks_run_from_the_first_ticket_to_the_last_with_none_left_out():
    tickets = [
        _ticket("t1", "a", "2026-09-29T10:00:00Z", "done", 1.0),
        _ticket("t2", "b", "2026-10-01T10:00:00Z", "review", 2.0),
        _ticket("t3", "c", "2026-10-15T10:00:00Z", "failed"),
    ]
    weeks = lineage.weeks(tickets)
    assert [week["week"] for week in weeks] == ["2026-09-28", "2026-10-05", "2026-10-12"]
    assert weeks[0] == {"week": "2026-09-28", "tickets": 2, "done": 1, "open": 1, "cost": 3.0}
    assert weeks[1]["tickets"] == 0
    assert weeks[2] == {"week": "2026-10-12", "tickets": 1, "done": 0, "open": 0, "cost": 0.0}
    assert lineage.weeks([]) == []


@case
def a_schedule_that_made_nothing_says_so_rather_than_dividing_by_zero():
    found = lineage.of({"id": "s1", "name": "Rien", "ticket": ""}, [], [], [])
    assert found["tickets"] == [] and found["runs"] == [] and found["weeks"] == []
    assert found["totals"] == {
        "tickets": 0,
        "cost": 0,
        "average_cost": None,
        "average_duration": None,
        "success": None,
    }
    assert found["since"] == "" and found["matched"] == 0
