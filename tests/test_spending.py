"""`spending.py`: the CSV of a project's sessions, and the figure it must add up to."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date
from pathlib import Path
from typing import Any

from support import case

from ponos import spending, state
from ponos.web import statistics as web_statistics


def _session(ticket: str, at: str, cost: float, project: str = "Opoil", **more: Any) -> None:
    state.record(
        {
            "ticket": more.pop("title", f"Ticket {ticket}"),
            "id": ticket,
            "at": at,
            "status": "done",
            "project": project,
            "seconds": 90.4,
            "cost_usd": cost,
            **more,
        }
    )


def _read(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


@case
def a_projects_month_adds_up_to_the_cost_its_page_shows(state_home: Path) -> None:
    """Every session of the project in the month is a row, and the column sums to the page's cost."""
    _session("a1", "2026-10-03T10:00:00+00:00", 1.234, title="Réparer l’été, « vite »")
    _session("a1", "2026-10-04T10:00:00+00:00", 0.5, status="blocked")
    _session("b2", "2026-10-31T12:00:00+00:00", 2.0, pull_request="https://x/pull/7")
    # Out of the month, of another project, of no ticket of the board.
    _session("a1", "2026-09-30T12:00:00+00:00", 9.0)
    _session("c3", "2026-10-10T12:00:00+00:00", 4.0, project="Leadz")
    _session("z9", "2026-10-11T12:00:00+00:00", 8.0)
    tickets = [
        {"id": "a1", "project": "Opoil", "type": "Code", "subtype": "bug", "url": "https://n/a1"},
        {"id": "b2", "project": "Opoil", "type": "Code", "subtype": "", "url": "https://n/b2"},
        {"id": "c3", "project": "Leadz", "type": "Code", "subtype": "", "url": "https://n/c3"},
    ]
    first, last = spending.month_span("2026-10")
    assert (first, last) == (date(2026, 10, 1), date(2026, 10, 31))
    after, before = spending.window(first, last)
    lines = state.lines(after, before)
    table = _read(
        spending.write(
            spending.rows(lines, first, last, tickets=tickets, project="opoil", zone=UTC)
        )
    )

    assert tuple(table[0]) == spending.COLUMNS
    assert len(table) == 4, table
    assert table[1][:2] == ["2026-10-03 10:00", "Réparer l’été, « vite »"], (
        "accents and commas survive"
    )
    assert table[1][2:7] == ["https://n/a1", "Code", "bug", "", "done"]
    assert table[2][6] == "blocked" and table[3][9] == "https://x/pull/7"

    page = web_statistics.figures(tickets, state.outcomes(), first, last, UTC, project="Opoil")[
        "totals"
    ]["cost"]
    assert round(sum(float(row[8]) for row in table[1:]), 2) == page == 3.73, (page, table)


@case
def the_command_line_goes_by_the_project_each_line_carries(state_home: Path) -> None:
    """Without a board the name on the line selects, whatever its case, and the link is the console's."""
    _session("d4", "2026-10-02T08:00:00+00:00", 1.0, project="Portfolio")
    _session("e5", "2026-10-02T09:00:00+00:00", 2.0, project="Opoil")
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    after, before = spending.window(first, last)
    lines = state.lines(after, before)
    mine = spending.rows(
        lines, first, last, project="PORTFOLIO", zone=UTC, console="http://127.0.0.1:8787/"
    )
    assert [row[1] for row in mine] == ["Ticket d4"], mine
    assert mine[0][2] == "http://127.0.0.1:8787/tickets/d4", mine
    assert spending.rows(lines, first, last, project="Opoil", zone=UTC)[0][2] == (
        "ponos://ticket/e5"
    ), "no console, the ticket's own scheme"
    assert len(spending.rows(lines, first, last, zone=UTC)) == 2, "no project is every session"


@case
def a_month_that_is_not_one_is_refused() -> None:
    for wrong in ("2026", "2026-13", "octobre"):
        try:
            spending.month_span(wrong)
        except ValueError:
            continue
        raise AssertionError(wrong)
