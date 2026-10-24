"""How many tickets came in, how many went out, and when — for the console's statistics.

The board says where every ticket is now; it does not say when it got there.
Notion keeps a page's `created_time` and its `last_edited_time`, and nothing in
between — a status change is not dated anywhere the API reaches. So the day a
ticket closed is read from two places, the better one first:

- the runner's own history, where every move to `done` it makes itself is a
  line with its timestamp: a pull request merged from the validated column, a
  document written, a publication published. That is the exact minute;
- the page's `last_edited_time` for everything else — a ticket you dragged to
  done yourself, or one closed because its pull request was merged by hand
  (`board.close_merged` writes no history line). Nothing moves a ticket once it
  is done, so its last edit is its closing, unless somebody touched it since.

The history comes first because it cannot drift: a done ticket edited a week
later keeps the day it was closed. How many closings each source dated is
handed back too, so a curve built mostly on the second one says so.

Days are this machine's days, not UTC's: a ticket closed at 23:30 in Paris
closed that evening, not the next morning.

The series are computed here rather than in the browser because this is where
the tests are: the page only draws what it is handed.

The sub-types are the board's: every code ticket closed in the period, by its
sub-type (subtypes.py) and by the week it closed in, and what one of each cost
and lasted on average — all its sessions counted, as for the average above.

The tickets created are counted once more, by type, sub-type and project, and
by day — by week past a month, where daily bars would be hairs. They are handed
over as cells rather than as a chart because the console filters them by type
and by project on the spot, and works out how much of a project's work is
fixing what it broke (`lib/made.ts`): the same cells for the period before, of
the same length, are what its trend is measured against. A code ticket nobody
gave a sub-type yet is a cell with none, drawn as unclassified rather than
left out — leaving it out would make a board half sorted look all features.

The blocks are the history's too: every line that ended blocked or failed,
counted by the cause it carries (blocks.py) and by the week it fell in.

A project's figures are the same computation over its tickets alone, and over
the history lines of those tickets: a history line knows its ticket's id, not
the project's name as the board spells it today, so the board is what says
whose a session was. That is also why the projects' costs add up to the
global one only up to the lines of tickets with no project — or no longer on
the board, which nobody can say a project for.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta, tzinfo

from .. import blocks, subtypes, timestamps

# The runner's history lines that are a ticket reaching `done`. A plain "done"
# status is not one: a session that opened a pull request reports "done" and
# leaves the ticket in review.
CLOSING_KINDS = ("document", "delivery")

# Where a ticket stops being open: done, or validated — approved, and left to
# the runner to merge. A cancelled ticket leaves the open ones too, but it is
# not counted closed: see `figures`.
CLOSED = ("done", "validated")

# Up to this many days the tickets created are drawn day by day; past it, week by week.
DAILY = 31

# A period longer than this is refused rather than drawn: two years of points
# is already more than a screen has pixels for.
LONGEST = 731


def day_of(stamp: str, zone: tzinfo | None = None) -> date | None:
    """The local day an ISO timestamp falls on, or None for an empty or broken one."""
    # A date with no time — what a board of files may carry — is that day here,
    # and an hour with no offset is read here too, as the synchronisation does.
    moment = timestamps.parse(stamp, naive="local")
    return None if moment is None else moment.astimezone(zone).date()


def closings(history: list[dict], zone: tzinfo | None = None) -> dict[str, date]:
    """{ticket id: the last day the runner itself moved it to done}."""
    closed: dict[str, date] = {}
    for entry in history:
        if not (entry.get("merged") or entry.get("kind") in CLOSING_KINDS):
            continue
        if entry.get("status") != "done":
            continue
        day = day_of(str(entry.get("at", "")), zone)
        key = str(entry.get("id", "")).replace("-", "")
        if day and key and (key not in closed or day > closed[key]):
            closed[key] = day
    return closed


def period(start: str, end: str, today: date) -> tuple[date, date]:
    """The days asked for, the last thirty by default, refused when they make no sense."""
    last = date.fromisoformat(end) if end else today
    first = date.fromisoformat(start) if start else last - timedelta(days=29)
    if first > last:
        raise ValueError("the period ends before it starts")
    if (last - first).days >= LONGEST:
        raise ValueError(f"a period is at most {LONGEST} days")
    return first, last


def figures(
    tickets: list[dict],
    history: list[dict],
    first: date,
    last: date,
    zone: tzinfo | None = None,
    project: str | None = None,
    kind_of: Callable[[str], str] = lambda option: "",
) -> dict:
    """The cards, the curves and the breakdowns of one period.

    `tickets` are the board's, as `Api.board` builds them, with `edited`.
    With a `project` (its name, "" for the tickets that have none) only its
    tickets are counted, and only what its sessions spent. `kind_of` says
    which of the four types a board's Type option is (`Notion.kind_of`).
    A ticket is open on a day if it was created by the end of it and not yet
    closed: that is every status but done and validated (`CLOSED`), failed and
    blocked included — they are still somebody's to deal with. A validated
    ticket is dated by its last edit, moving it there, until the runner merges
    it and the history says when it was done. A cancelled ticket is neither: it leaves
    the open ones on its last edit without being counted closed — nothing got
    done — and what its sessions spent stays in the spending, which is money
    gone all the same.
    """
    if project is not None:
        tickets = [ticket for ticket in tickets if (ticket.get("project") or "") == project]
        mine = {str(ticket.get("id", "")) for ticket in tickets}
        history = [entry for entry in history if str(entry.get("id", "")).replace("-", "") in mine]
    dated = closings(history, zone)
    known = {}
    # The day each cancelled ticket left the open ones — see above.
    dropped_on_day: dict[str, date] = {}
    from_history = from_edit = 0
    for ticket in tickets:
        created = day_of(ticket.get("created", ""), zone)
        closed = None
        if ticket.get("column") in CLOSED:
            closed = (
                dated.get(str(ticket.get("id", ""))) if ticket.get("column") == "done" else None
            )
            if closed:
                from_history += 1
            else:
                # Done with no date at all: closed before anything is drawn.
                closed = day_of(ticket.get("edited", ""), zone) or created or date.min
                from_edit += 1
            # An edit is never before the page existed; a history line about a
            # page that was since recreated could be.
            if closed and created and closed < created:
                closed = created
        elif ticket.get("column") == "cancelled":
            dropped = day_of(ticket.get("edited", ""), zone) or created or date.min
            dropped_on_day[ticket.get("id", "")] = max(dropped, created) if created else dropped
        known[ticket.get("id", "")] = (ticket, created, closed)

    created_on: Counter[date] = Counter()
    closed_on: Counter[date] = Counter()
    dropped_on: Counter[date] = Counter(dropped_on_day.values())
    for _, created, closed in known.values():
        if created:
            created_on[created] += 1
        if closed:
            closed_on[closed] += 1

    # What was open the evening before the period: the curve starts from the
    # board as it stood, not from zero.
    def open_on(day: date) -> int:
        ended = {key: closed or dropped_on_day.get(key) for key, (_, _, closed) in known.items()}
        return sum(
            1
            for key, (_, created, _) in known.items()
            if (created is None or created <= day) and (ended[key] is None or ended[key] > day)
        )

    spent_on: Counter[date] = Counter()
    for entry in history:
        day = day_of(str(entry.get("at", "")), zone)
        if day and first <= day <= last:
            spent_on[day] += float(entry.get("cost_usd") or 0)

    days = []
    stock = open_on(first - timedelta(days=1))
    spent = 0.0
    day = first
    while day <= last:
        stock += created_on[day] - closed_on[day] - dropped_on[day]
        spent += spent_on[day]
        days.append(
            {
                "day": day.isoformat(),
                "created": created_on[day],
                "closed": closed_on[day],
                "open": stock,
                "cost": round(spent, 2),
            }
        )
        day += timedelta(days=1)

    # What the tickets closed in the period cost in all, sessions from before
    # the period included: a ticket is not cheaper for having been started
    # last month.
    cost_of: Counter[str] = Counter()
    for entry in history:
        cost_of[str(entry.get("id", "")).replace("-", "")] += float(entry.get("cost_usd") or 0)
    shut = [
        str(ticket.get("id", ""))
        for ticket, _, closed in known.values()
        if closed and first <= closed <= last
    ]
    average = round(sum(cost_of[key] for key in shut) / len(shut), 2) if shut else None

    stops = blocked(history, first, last, zone)
    seconds_of: Counter[str] = Counter()
    for entry in history:
        seconds_of[str(entry.get("id", "")).replace("-", "")] += float(entry.get("seconds") or 0)
    kinds_of_work = subtyped(
        [
            (ticket, closed)
            for ticket, _, closed in known.values()
            if closed and first <= closed <= last
        ],
        cost_of,
        seconds_of,
        first,
        last,
    )

    born = [ticket for ticket, created, _ in known.values() if created and first <= created <= last]
    made = created_by_kind(
        [(ticket, created) for ticket, created, _ in known.values() if created],
        first,
        last,
        kind_of,
    )
    statuses = Counter(str(ticket.get("column") or "draft") for ticket in born)
    projects = Counter(str(ticket.get("project") or "") for ticket in born)
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "totals": {
            "open": days[-1]["open"],
            "closed": sum(item["closed"] for item in days),
            "created": sum(item["created"] for item in days),
            "cost": days[-1]["cost"],
        },
        "days": days,
        "statuses": [{"key": key, "count": count} for key, count in statuses.most_common()],
        "projects": [{"name": name, "count": count} for name, count in projects.most_common()],
        "dated": {"history": from_history, "edited": from_edit},
        "average": average,
        "blocks": stops,
        "subtypes": kinds_of_work,
        "made": made,
    }


def created_by_kind(
    tickets: list[tuple[dict, date]],
    first: date,
    last: date,
    kind_of: Callable[[str], str],
) -> dict:
    """The tickets created in a period, as cells: bucket, type, sub-type, project, count.

    A bucket is a day, or a week named by its Monday past `DAILY` days; every
    bucket the period touches is listed, empty ones included. `before` holds
    the same cells, bucket left out, for the period of the same length that
    ends the day before this one starts. A sub-type the table does not know is
    none: the ticket is unclassified, still counted.
    """
    weekly = (last - first).days + 1 > DAILY
    start = (lambda day: day - timedelta(days=day.weekday())) if weekly else (lambda day: day)
    buckets = []
    bucket = start(first)
    while bucket <= last:
        buckets.append(bucket.isoformat())
        bucket += timedelta(days=7 if weekly else 1)
    length = last - first + timedelta(days=1)
    now: Counter[tuple[str, str, str, str]] = Counter()
    before: Counter[tuple[str, str, str]] = Counter()
    for ticket, created in tickets:
        subtype = str(ticket.get("subtype") or "")
        cell = (
            kind_of(str(ticket.get("type") or "")),
            subtype if subtype in subtypes.BY_KEY else "",
            str(ticket.get("project") or ""),
        )
        if first <= created <= last:
            now[(start(created).isoformat(), *cell)] += 1
        elif first - length <= created < first:
            before[cell] += 1
    return {
        "unit": "week" if weekly else "day",
        "buckets": buckets,
        "cells": [
            {"bucket": bucket, "kind": kind, "subtype": subtype, "project": name, "count": count}
            for (bucket, kind, subtype, name), count in sorted(now.items())
        ],
        "before": [
            {"kind": kind, "subtype": subtype, "project": name, "count": count}
            for (kind, subtype, name), count in sorted(before.items())
        ],
    }


def subtyped(
    closed: list[tuple[dict, date]],
    cost_of: Counter[str],
    seconds_of: Counter[str],
    first: date,
    last: date,
) -> dict:
    """The tickets closed in a period, by sub-type and by week, and what each kind took.

    A ticket's duration is its sessions' (the history's seconds), and the
    board's own Duration when the history has none — a ticket closed before
    the runner kept it. An average is over the tickets that say something:
    `None` when none of them does, rather than a zero nobody spent.
    """
    weeks: dict[date, Counter[str]] = {}
    monday = first - timedelta(days=first.weekday())
    while monday <= last:
        weeks[monday] = Counter()
        monday += timedelta(days=7)
    count: Counter[str] = Counter()
    costs: dict[str, list[float]] = {}
    minutes: dict[str, list[float]] = {}
    for ticket, day in closed:
        key = str(ticket.get("subtype") or "")
        if key not in subtypes.BY_KEY:
            continue
        weeks[day - timedelta(days=day.weekday())][key] += 1
        count[key] += 1
        identifier = str(ticket.get("id", ""))
        if cost_of[identifier]:
            costs.setdefault(key, []).append(cost_of[identifier])
        lasted = seconds_of[identifier] / 60 or float(ticket.get("duration") or 0)
        if lasted:
            minutes.setdefault(key, []).append(lasted)

    def mean(values: list[float] | None, digits: int) -> float | None:
        return round(sum(values) / len(values), digits) if values else None

    return {
        "total": sum(count.values()),
        "weeks": [
            {"week": week.isoformat(), "counts": dict(counts)} for week, counts in weeks.items()
        ],
        "subtypes": [
            {
                **subtypes.BY_KEY[key].as_dict(),
                "count": count[key],
                "cost": mean(costs.get(key), 2),
                "duration": mean(minutes.get(key), 1),
            }
            for key in subtypes.KEYS
            if count[key]
        ],
    }


def blocked(history: list[dict], first: date, last: date, zone: tzinfo | None = None) -> dict:
    """The stops of a period, by cause and by week — see blocks.py.

    A week is named by its Monday, and every week the period touches is there,
    empty ones included: a week without a block is the thing the chart is for.
    A line written before codes existed, and not migrated, is read back from
    its sentence the way the migration would have.
    """
    weeks: dict[date, Counter[str]] = {}
    monday = first - timedelta(days=first.weekday())
    while monday <= last:
        weeks[monday] = Counter()
        monday += timedelta(days=7)
    total: Counter[str] = Counter()
    for entry in history:
        if entry.get("status") not in ("blocked", "failed"):
            continue
        day = day_of(str(entry.get("at", "")), zone)
        if not day or not first <= day <= last:
            continue
        code = blocks.known(entry.get("code")) or blocks.classify(str(entry.get("reason") or ""))
        weeks[day - timedelta(days=day.weekday())][code] += 1
        total[code] += 1
    return {
        "total": sum(total.values()),
        "weeks": [
            {"week": week.isoformat(), "counts": dict(counts)} for week, counts in weeks.items()
        ],
        "causes": [
            {**blocks.cause(code).as_dict(), "count": count} for code, count in total.most_common()
        ],
    }
