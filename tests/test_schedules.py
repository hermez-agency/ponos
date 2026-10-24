"""`schedules.py`: the next moment of a schedule, across clock changes."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime

from support import case

from ponos import notion, schedules, store

# -- scheduling --------------------------------------------------------------


@case
def a_bare_date_means_the_start_of_that_day_here():
    """Not midnight UTC: a ticket dated "30 August" starts on the 30th, locally."""
    from datetime import datetime

    from ponos.schedules import scheduled_for

    moment = scheduled_for("2026-08-30")
    assert moment is not None and moment.tzinfo is not None
    assert (moment.year, moment.month, moment.day, moment.hour) == (2026, 8, 30, 0)
    assert moment.utcoffset() == datetime(2026, 8, 30).astimezone().utcoffset()


@case
def a_date_with_a_time_keeps_its_offset():
    from ponos.schedules import scheduled_for

    moment = scheduled_for("2026-08-30T14:30:00.000+02:00")
    assert moment is not None
    assert (moment.hour, moment.minute) == (14, 30)
    assert moment.utcoffset().total_seconds() == 7200


@case
def an_unreadable_date_never_holds_a_ticket_back():
    """A value the runner cannot parse must not silently freeze a ticket."""
    from ponos.schedules import scheduled_for

    assert scheduled_for(None) is None
    assert scheduled_for("") is None
    assert scheduled_for("bientôt") is None


@case
def notion_truncates_a_datetime_to_the_minute():
    """Not our doing, but it decides how precise scheduling can be.

    Sending 14:48:27 stores 14:48:00, so a ticket fires at the top of the minute
    it names. Worth pinning: a future change here would look like the runner
    firing early.
    """
    from ponos.schedules import scheduled_for

    stored = scheduled_for("2026-08-28T14:48:00.000+02:00")
    assert stored is not None and (stored.hour, stored.minute, stored.second) == (14, 48, 0)


@contextmanager
def _paris():
    """The machine in Paris for a moment: what a schedule's hours are said in."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Paris"
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()


def _walk(cadence: str, at: str, day: str, start: str, count: int) -> list[str]:
    """`count` occurrences in a row, each computed from the one before — the calendar's walk."""
    found: list[str] = []
    after = datetime.fromisoformat(start).astimezone()
    for _ in range(count):
        after = schedules.next_occurrence(cadence, at, day, after=after)
        found.append(after.strftime("%Y-%m-%d %H:%M %Z"))
    return found


@case
def a_schedule_keeps_its_wall_clock_hour_across_the_change_to_winter_time():
    """The clocks go back on 25 October 2026: nine in the morning stays nine."""
    with _paris():
        assert schedules.timezone_name() == "Europe/Paris"
        assert _walk("Daily", "09:00", "", "2026-10-23T12:00:00+02:00", 4) == [
            "2026-10-24 09:00 CEST",
            "2026-10-25 09:00 CET",
            "2026-10-26 09:00 CET",
            "2026-10-27 09:00 CET",
        ]
        # An hour that does not exist (02:30 on 29 March) lands after the jump.
        assert _walk("Daily", "02:30", "", "2026-03-28T12:00:00+01:00", 2) == [
            "2026-03-29 03:30 CEST",
            "2026-03-30 02:30 CEST",
        ]
        # An hourly one reads the wall clock too: the repeated 02:30 is not a launch of its own.
        assert _walk("Hourly", "00:30", "", "2026-10-25T00:00:00+02:00", 5) == [
            "2026-10-25 00:30 CEST",
            "2026-10-25 01:30 CEST",
            "2026-10-25 02:30 CEST",
            "2026-10-25 03:30 CET",
            "2026-10-25 04:30 CET",
        ]


@case
def the_same_moment_in_any_offset_gives_the_same_occurrence():
    """A Last run from Notion comes in UTC, an offset may predate the change of time: same instant, same answer."""
    with _paris():
        here = datetime.fromisoformat("2026-10-26T07:30:00+01:00")
        for after in (
            here,
            datetime.fromisoformat("2026-10-26T06:30:00+00:00"),
            datetime.fromisoformat("2026-10-26T08:30:00+02:00"),
        ):
            hourly = schedules.next_occurrence("Hourly", "00:00", after=after)
            assert hourly is not None and hourly.isoformat() == "2026-10-26T08:00:00+01:00", (
                after,
                hourly,
            )
            daily = schedules.next_occurrence("Daily", "07:45", after=after)
            assert daily is not None and daily.isoformat() == "2026-10-26T07:45:00+01:00", (
                after,
                daily,
            )
            line = schedules.cron("0 * * * *", after=after)
            assert line is not None and line.isoformat() == "2026-10-26T08:00:00+01:00", (
                after,
                line,
            )


@case
def weekly_and_monthly_schedules_walk_their_day_in_a_row():
    with _paris():
        assert _walk("Weekly", "09:00", "Monday", "2026-10-14T12:00:00+02:00", 3) == [
            "2026-10-19 09:00 CEST",
            "2026-10-26 09:00 CET",
            "2026-11-02 09:00 CET",
        ]
        assert _walk("Monthly", "07:00", "31", "2027-01-01T00:00:00+01:00", 3) == [
            "2027-01-31 07:00 CET",
            "2027-02-28 07:00 CET",
            "2027-03-31 07:00 CEST",
        ]


@case
def a_paused_or_unreadable_schedule_has_no_upcoming_moment():
    """The calendar draws from `upcoming`: a schedule that is off is a schedule nothing is due from."""
    now = datetime.fromisoformat("2026-10-14T21:00:00+02:00")
    page = store.Page(id="a" * 32, title="Whisper Desk", properties={}, url="")
    due = schedules.Schedule(
        page=page,
        name="Whisper Desk",
        cadence="Daily",
        at="09:00",
        day="",
        active=True,
        next=datetime.fromisoformat("2026-10-09T09:00:00+02:00"),
        last=None,
        last_ticket="",
        project="",
        model="",
        priority="",
    )
    assert schedules.upcoming(due, now) == now, "due: it fires on the next pass, never in the past"
    due.active = False
    assert schedules.upcoming(due, now) is None
    due.active, due.problem = True, "no cadence the runner knows"
    assert schedules.upcoming(due, now) is None


@case
def a_date_range_schedules_on_its_end():
    """Notion dates may be ranges; the runner reads the moment work is due."""
    page = notion.Page(
        id="x",
        url="u",
        title="t",
        properties={
            "Due": {"type": "date", "date": {"start": "2026-08-30", "end": "2026-09-02"}},
            "Single": {"type": "date", "date": {"start": "2026-08-30", "end": None}},
            "Empty": {"type": "date", "date": None},
        },
    )
    assert notion.read(page, "Due") == "2026-09-02"
    assert notion.read(page, "Single") == "2026-08-30"
    assert notion.read(page, "Empty") is None
