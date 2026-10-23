"""What comes back on its own: a recipe for a ticket, and how often it is born.

A ticket leaves once. Everything that *recurs* — Monday's dependency review, the
first-of-the-month report, the weekly digest — is retyped by hand, or is not
done at all. The parti pris, and it is what keeps the rest of the runner simple:
no second execution engine beside it, only **one more source of tickets**. A
schedule creates a row in the ready column, and everything after that is the
code that already exists.

Two things live here, and neither of them touches the network — which is what
makes the calendar testable at all:

- `read`, one row of the Schedules database reduced to plain Python, with what
  makes it unreadable spelled out in `problem` rather than raised;
- `next_occurrence`, the whole calendar: four cadences, and the first moment
  *strictly after* the one you hand it.

`scheduled_for` is here too, and that is deliberate. A date written on a ticket
and a date written on a schedule mean the same thing — a moment in this
machine's timezone, a bare date being midnight here and not noon UTC — and two
readings of a Notion date that drift apart is the sort of bug nobody finds.
"""

from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import priority as priority_module
from . import store
from .config import Notion

# What a cadence may say. A select rather than free text, for the same reason as
# the model column: the point is to pick without remembering the spelling.
CADENCES = ("Hourly", "Daily", "Weekly", "Monthly")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# "09:00", "9h30", "9". Anything else is a value nobody can act on, and saying so
# is better than guessing at an hour a ticket would then be born at.
_CLOCK = re.compile(r"^(\d{1,2})\s*(?:[:hH]\s*(\d{1,2})?)?$")


@dataclass
class Schedule:
    """One row of the Schedules database, as the runner reads it.

    `problem` is what stops it being acted on — an unknown cadence, an hour
    nobody can parse, a day that is neither a weekday nor a number. A schedule
    carrying one is skipped rather than failed: `doctor` names it, and the
    others go on being born.
    """

    page: store.Page
    name: str
    cadence: str  # "" when absent or unknown
    at: str  # "09:00"
    day: str  # "Monday" | "1".."31" | ""
    active: bool
    next: datetime | None  # None = never yet computed
    last: datetime | None
    last_ticket: str  # page id, "" when there is none
    project: str
    model: str
    priority: int | None  # None when the schedule says none: its tickets are born at 50
    # What its tickets are, as the board spells it, "" for "let it be guessed":
    # copied onto each ticket, which the classifier then leaves alone.
    kind: str = ""
    subtype: str = ""
    problem: str = ""


def scheduled_for(value: object) -> datetime | None:
    """A Notion date, read in this machine's timezone.

    A bare date means the start of that day here: a ticket due "30 August"
    becomes eligible at midnight, not at noon UTC. A date with a time is taken
    as written, offset included. Anything unparseable is treated as no date at
    all — nothing is ever held back by a value the runner failed to read.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo is None else moment


def timezone_name() -> str:
    """The IANA name of this machine's timezone, or "" when it cannot be told.

    Every hour a schedule says is a wall-clock hour *here*: 09:00 is nine in
    Paris whatever the browser reading the calendar sits in, and it stays nine
    when the clocks change. The console draws its calendar from the cadence, so
    it needs the zone by name — an offset would be right on one side of the
    change and an hour off on the other.
    """
    named = os.environ.get("TZ", "").lstrip(":")
    if not named:
        # Where the system keeps it: /etc/localtime points into the zoneinfo tree.
        target = os.path.realpath("/etc/localtime")
        named = target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""
    try:
        ZoneInfo(named)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return ""
    return named


def read(page: store.Page, settings: Notion) -> Schedule:
    """One schedule, and what — if anything — makes it unreadable.

    Never raises. A row somebody half filled in is a row the pass steps over,
    not a pass that stops: one broken schedule must not take the others with it.
    """

    def value(key: str) -> object:
        return store.read(page, settings.prop(key))

    def first(key: str) -> str:
        related = value(key) or []
        return str(related[0]) if isinstance(related, list) and related else ""

    cadence = str(value("cadence") or "").strip()
    known = next((name for name in CADENCES if name.lower() == cadence.lower()), "")
    at = str(value("at") or "").strip()
    day = str(value("day") or "").strip()

    schedule = Schedule(
        page=page,
        name=page.title.strip() or "(untitled schedule)",
        cadence=known,
        at=at,
        day=day,
        active=bool(value("active")),
        next=scheduled_for(value("next_run")),
        last=scheduled_for(value("last_run")),
        last_ticket=first("last_ticket"),
        project=first("project"),
        model=str(value("model") or "").strip(),
        priority=(
            priority_module.score(value("priority"))
            if str(value("priority") or "").strip()
            else None
        ),
        kind=str(value("type") or "").strip(),
        subtype=str(value("subtype") or "").strip(),
    )
    schedule.problem = _problem(schedule)
    return schedule


def _problem(schedule: Schedule) -> str:
    """Why this schedule cannot be acted on, in the words `doctor` prints."""
    if not schedule.cadence:
        return f"no cadence the runner knows — one of: {', '.join(CADENCES)}"
    if _clock(schedule.at) is None:
        return f"“{schedule.at}” is not an hour — write it as 09:00"
    if schedule.cadence == "Weekly" and schedule.day.strip() and _weekday(schedule.day) is None:
        return f"“{schedule.day}” is not a day of the week"
    if schedule.cadence == "Monthly" and _day_of_month(schedule.day) is None:
        return f"“{schedule.day}” is not a day of the month — 1 to 31"
    return ""


def next_occurrence(
    cadence: str, at: str = "", day: str = "", *, after: datetime
) -> datetime | None:
    """The first moment this cadence falls on, strictly after `after`.

    - **Hourly** — on the minute of `at`, so 09:35 means every hour at :35;
      an empty `at` means :00.
    - **Daily** — at `at`, tomorrow when the hour is already behind us.
    - **Weekly** — the next `day` at `at`. No day named means the weekday
      `after` itself falls on.
    - **Monthly** — the `day` of the month at `at`, clipped to the last day
      there is: the 31st in February is the 28th, or the 29th.

    `None` — never an exception — for a cadence nobody declared, an hour nobody
    can read, a day that means nothing. A schedule the runner cannot understand
    is one it leaves alone, and `doctor` is where that is said out loud.

    Aware in, aware out: the moment comes back in this machine's timezone, which
    is the one `scheduled_for` reads dates in.
    """
    clock = _clock(at)
    if clock is None:
        return None
    hour, minute = clock
    name = cadence.strip().lower()
    base = after.replace(tzinfo=None) if after.tzinfo else after

    if name == "hourly":
        moment = base.replace(minute=minute, second=0, microsecond=0)
        if moment <= base:
            moment += timedelta(hours=1)
    elif name == "daily":
        moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= base:
            moment += timedelta(days=1)
    elif name == "weekly":
        # No day named is not a mistake: it means "whichever day this is", which
        # is what a schedule written on a Tuesday with nothing else said meant.
        wanted = base.weekday() if not day.strip() else _weekday(day)
        if wanted is None:
            return None
        moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        moment += timedelta(days=(wanted - moment.weekday()) % 7)
        if moment <= base:
            moment += timedelta(days=7)
    elif name == "monthly":
        wanted = _day_of_month(day)
        if wanted is None:
            return None
        moment = _in_month(base.year, base.month, wanted, hour, minute)
        if moment <= base:
            year, month = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
            moment = _in_month(year, month, wanted, hour, minute)
    else:
        return None

    return _local(moment) if after.tzinfo else moment


def every(hours: int, *, after: datetime) -> datetime:
    """`hours` hours after `after`, to the minute.

    An interval rather than a calendar: "every four hours" is four hours from
    the last time, not the next multiple of four on the clock, which would give
    a pass started at 10:30 a second one at 12:00. The caller keeps the moment
    it fired at and hands it back, so the spacing holds across a restart.
    """
    return after.replace(second=0, microsecond=0) + timedelta(hours=max(1, hours))


# The five fields of a crontab line and what each may hold. Day of week takes
# 0 and 7 for Sunday, as cron does.
_CRON_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _cron_field(text: str, low: int, high: int) -> set[int] | None:
    """One field of a cron line as the values it stands for, None if it is not one."""
    values: set[int] = set()
    for part in text.split(","):
        body, _, step_text = part.partition("/")
        if step_text and not step_text.isdigit():
            return None
        step = int(step_text) if step_text else 1
        if step < 1:
            return None
        if body == "*":
            start, stop = low, high
        elif re.fullmatch(r"\d+", body):
            start = stop = int(body)
            if step_text:
                stop = high
        elif re.fullmatch(r"\d+-\d+", body):
            start, stop = (int(number) for number in body.split("-"))
        else:
            return None
        if not low <= start <= stop <= high:
            return None
        values.update(range(start, stop + 1, step))
    return values


def _cron(expression: str) -> tuple[list[set[int]], bool, bool] | None:
    """A cron line as its five sets, and whether the day of month and of week are restricted."""
    fields = expression.split()
    if len(fields) != 5:
        return None
    sets: list[set[int]] = []
    for text, (low, high) in zip(fields, _CRON_FIELDS, strict=True):
        found = _cron_field(text, low, high)
        if not found:
            return None
        sets.append(found)
    sets[4] = {day % 7 for day in sets[4]}
    return sets, fields[2] != "*", fields[4] != "*"


def cron_problem(expression: str) -> str:
    """Why this is not a cron line the runner reads, in the words `doctor` prints; empty if it is one."""
    if _cron(expression) is None:
        return f"“{expression}” is not a cron line — five fields: minute hour day month weekday"
    return ""


def cron(expression: str, *, after: datetime) -> datetime | None:
    """The first moment a cron line falls on, strictly after `after`.

    The usual five fields with `*`, lists, ranges and steps, no names. As in
    cron, a day of the month and a day of the week that are both given mean
    either of them. `None` for a line nobody can read, and for one that never
    falls — the 31st of February.
    """
    parsed = _cron(expression)
    if parsed is None:
        return None
    (minutes, hours, days, months, weekdays), dated, weekly = parsed
    base = (after.replace(tzinfo=None) if after.tzinfo else after).replace(
        second=0, microsecond=0
    ) + timedelta(minutes=1)
    for offset in range(366 * 8):
        day = (base + timedelta(days=offset)).date()
        if day.month not in months:
            continue
        in_month, in_week = day.day in days, (day.weekday() + 1) % 7 in weekdays
        if not (in_month or in_week if dated and weekly else in_month and in_week):
            continue
        for hour in sorted(hours):
            for minute in sorted(minutes):
                moment = datetime(day.year, day.month, day.day, hour, minute)
                if moment >= base:
                    return _local(moment) if after.tzinfo else moment
    return None


def _local(moment: datetime) -> datetime:
    """A wall-clock moment read in this machine's timezone, the same on every Python.

    An hour that does not exist (02:30 when the clocks jump to 03:00) is read
    after the jump on 3.12 and later, and before it on 3.11, which swaps what
    `fold` means in a gap. Both are tried and the later one kept, so the
    launch lands after the change rather than an hour early.
    """
    first = moment.astimezone()
    if first.replace(tzinfo=None) == moment:
        return first
    return max(first, moment.replace(fold=1 - moment.fold).astimezone())


def upcoming(schedule: Schedule, now: datetime) -> datetime | None:
    """When the next ticket is born, as somebody reading the list understands it.

    `next` is the runner's bookmark, not an answer: it stays where the last pass
    left it. A schedule turned off keeps the date it had then — weeks old by the
    time anybody looks — and nothing is born from it at all, so it has none. A
    schedule nobody can read is the same. One that is on and already due fires
    on the very next pass: *now*, never a moment in the past.
    """
    if not schedule.active or schedule.problem or schedule.next is None:
        return None
    return max(schedule.next, now)


def _in_month(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """That day of that month, or the last one the month has.

    The 31st exists in seven months out of twelve. A monthly schedule set on it
    is not a schedule that skips February — it is one that lands on the 28th.
    """
    return datetime(year, month, min(day, calendar.monthrange(year, month)[1]), hour, minute)


def _clock(at: str) -> tuple[int, int] | None:
    """ "09:35" → (9, 35). Empty is midnight; anything unreadable is None."""
    text = at.strip()
    if not text:
        return (0, 0)
    match = _CLOCK.match(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    return (hour, minute) if hour < 24 and minute < 60 else None


def _weekday(day: str) -> int | None:
    """Monday → 0, and a shortened “Mon” too. None when it names no day at all.

    An empty day is read by the caller, which is the only place that knows what
    “whichever day it is” means.
    """
    text = day.strip().lower()
    if not text:
        return None
    for index, name in enumerate(_WEEKDAYS):
        if name.lower().startswith(text):
            return index
    return None


def _day_of_month(day: str) -> int | None:
    """ "1".."31", and nothing said means the first of the month."""
    text = day.strip()
    if not text:
        return 1
    return int(text) if text.isdigit() and 1 <= int(text) <= 31 else None
