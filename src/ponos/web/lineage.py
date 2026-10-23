"""Which tickets a schedule made, and what they came to — for a schedule's page in the console.

A schedule's own row says one ticket: the last one, in the column a pass
writes back so that it knows whether the previous occurrence is still open.
Everything before it was forgotten as the next one was born. So the runner now
keeps a line per occurrence in `ponos.db` (`state.occurred`): the ticket made,
or why none was — skipped because the last one was still open, or refused by
the board. That is the link, and it starts the day it was put in place.

What came before it is attached by what can still be read, the surer first:

- the runner's history, where every birth since that history exists is a line
  naming the schedule (by its page since the link, by its name before it);
- the ticket the row itself points at;
- and the title, last: a schedule names every ticket `<name> — <date>`, the
  date being the day it was born. A ticket of that title created within a day
  of that date is taken for one of its own. A schedule renamed since loses
  those, and only those: the others are linked by id.

How many were attached by their title alone is handed back, so the page can say
that part of the history was rebuilt rather than recorded. The passes that
made no ticket before the link existed are lost: nothing kept them.

The figures are computed here rather than in the browser for the reason
`statistics.py` gives: this is where the tests are.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

from .statistics import day_of

# The columns a ticket stops in. The rate of success is done over all three:
# a ticket still in review or blocked has not said yet how it ends.
FINISHED = ("done", "failed", "cancelled")

# What a schedule writes after its name: the day, and the hour for an hourly one.
STAMP = re.compile(r" — (\d{4}-\d{2}-\d{2})(?: \d{2}:\d{2})?$")


def _moment(stamp: str) -> datetime:
    """An ISO timestamp, to sort on; the oldest there is where it cannot be read."""
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def titled(name: str, title: str) -> date | None:
    """The day in a title a schedule called `name` would have written, or None."""
    if not name or not title.startswith(name):
        return None
    found = STAMP.fullmatch(title[len(name) :])
    if not found:
        return None
    try:
        return date.fromisoformat(found.group(1))
    except ValueError:
        return None


def _bare(ticket: str) -> str:
    return ticket.replace("-", "")


def linked(
    schedule: dict[str, Any],
    tickets: list[dict[str, Any]],
    history: list[dict[str, Any]],
    occurrences: list[dict[str, Any]],
) -> dict[str, str]:
    """{ticket id: how it is known to be this schedule's — `recorded` or `title`}."""
    known: set[str] = {_bare(str(row.get("ticket") or "")) for row in occurrences}
    for entry in history:
        if entry.get("status") != "scheduled":
            continue
        said = _bare(str(entry.get("schedule") or ""))
        if said == schedule["id"] or (not said and entry.get("from") == schedule["name"]):
            known.add(_bare(str(entry.get("id") or "")))
    known.add(_bare(str(schedule.get("ticket") or "")))
    known.discard("")
    found: dict[str, str] = {}
    for ticket in tickets:
        key = _bare(str(ticket.get("id") or ""))
        if key in known:
            found[key] = "recorded"
            continue
        stamped = titled(schedule["name"], str(ticket.get("title") or ""))
        born = day_of(str(ticket.get("created") or ""))
        if stamped and born and abs((born - stamped).days) <= 1:
            found[key] = "title"
    return found


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weeks(tickets: list[dict[str, Any]], zone: tzinfo | None = None) -> list[dict[str, Any]]:
    """The tickets by the week they were born in, every week from the first to the last."""
    counted: dict[date, dict[str, Any]] = {}
    for ticket in tickets:
        day = day_of(str(ticket.get("created") or ""), zone)
        if not day:
            continue
        week = counted.setdefault(_monday(day), {"tickets": 0, "done": 0, "open": 0, "cost": 0.0})
        week["tickets"] += 1
        if ticket.get("column") == "done":
            week["done"] += 1
        elif ticket.get("column") not in FINISHED:
            week["open"] += 1
        week["cost"] += float(ticket.get("cost") or 0)
    if not counted:
        return []
    first, last = min(counted), max(counted)
    filled = []
    monday = first
    while monday <= last:
        week = counted.get(monday, {"tickets": 0, "done": 0, "open": 0, "cost": 0.0})
        filled.append({"week": monday.isoformat(), **week, "cost": round(week["cost"], 2)})
        monday += timedelta(days=7)
    return filled


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def of(
    schedule: dict[str, Any],
    tickets: list[dict[str, Any]],
    history: list[dict[str, Any]],
    occurrences: list[dict[str, Any]],
    zone: tzinfo | None = None,
) -> dict[str, Any]:
    """What a schedule made, its passes, and the figures over them.

    `schedule` is a row as `Api._schedule` says it, `tickets` the board's cards,
    `occurrences` the schedule's own lines from `state.occurrences`.
    """
    how = linked(schedule, tickets, history, occurrences)
    mine = sorted(
        (ticket for ticket in tickets if _bare(str(ticket.get("id") or "")) in how),
        key=lambda ticket: _moment(str(ticket.get("created") or "")),
        reverse=True,
    )
    by_id = {_bare(str(ticket["id"])): ticket for ticket in mine}

    runs = [
        {
            **row,
            "column": (by_id.get(row["ticket"]) or {}).get("column", ""),
            "inferred": False,
        }
        for row in occurrences
    ]
    # A ticket with no line of its own was born before the lines were kept:
    # its pass is said from the ticket, and marked as such.
    told = {row["ticket"] for row in occurrences}
    for ticket in mine:
        key = _bare(str(ticket["id"]))
        if key in told:
            continue
        runs.append(
            {
                "at": str(ticket.get("created") or ""),
                "outcome": "born",
                "ticket": key,
                "title": str(ticket.get("title") or ""),
                "reason": "",
                "column": ticket.get("column", ""),
                "inferred": True,
            }
        )
    runs.sort(key=lambda row: _moment(str(row["at"])), reverse=True)

    columns: dict[str, int] = {}
    for ticket in mine:
        column = str(ticket.get("column") or "")
        columns[column] = columns.get(column, 0) + 1
    finished = sum(columns.get(column, 0) for column in FINISHED)
    costs = [float(ticket["cost"]) for ticket in mine if ticket.get("cost") is not None]
    durations = [float(ticket["duration"]) for ticket in mine if ticket.get("duration") is not None]
    return {
        "tickets": [
            {
                "id": _bare(str(ticket["id"])),
                "short": str(ticket.get("short") or ""),
                "title": str(ticket.get("title") or ""),
                "url": str(ticket.get("url") or ""),
                "status": str(ticket.get("status") or ""),
                "column": ticket.get("column", "draft"),
                "created": str(ticket.get("created") or ""),
                "cost": ticket.get("cost"),
                "duration": ticket.get("duration"),
                "pull_request": str(ticket.get("pull_request") or ""),
                "linked": how[_bare(str(ticket["id"]))],
            }
            for ticket in mine
        ],
        "runs": runs,
        "statuses": [{"key": key, "count": count} for key, count in sorted(columns.items())],
        "totals": {
            "tickets": len(mine),
            "cost": round(sum(costs), 2),
            "average_cost": _average(costs),
            "average_duration": _average(durations),
            "success": round(columns.get("done", 0) / finished, 4) if finished else None,
        },
        "weeks": weeks(mine, zone),
        # The oldest line kept: before it, only the births were known.
        "since": occurrences[-1]["at"] if occurrences else "",
        "matched": sum(1 for kind in how.values() if kind == "title"),
    }
