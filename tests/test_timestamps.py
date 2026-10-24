"""`timestamps.py`: one reading of an ISO timestamp, and of an hour with no offset."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone

from support import case

from ponos import sync, timestamps
from ponos.web import statistics


@contextmanager
def _paris() -> Iterator[None]:
    """The machine in Paris for a moment, two hours ahead of UTC in September."""
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


@case
def an_offset_is_taken_as_written():
    paris = timezone(timedelta(hours=2))
    for naive in ("utc", "local"):
        assert timestamps.parse("2026-09-14T09:12:00+02:00", naive) == datetime(
            2026, 9, 14, 9, 12, tzinfo=paris
        )
        assert timestamps.parse("2026-09-14T07:12:00.000Z", naive) == datetime(
            2026, 9, 14, 7, 12, tzinfo=UTC
        )


@case
def an_hour_without_an_offset_is_read_as_the_caller_says():
    with _paris():
        assert timestamps.parse("2026-09-14T09:12") == datetime(2026, 9, 14, 9, 12, tzinfo=UTC)
        assert timestamps.parse("2026-09-14T09:12", naive="local") == datetime(
            2026, 9, 14, 7, 12, tzinfo=UTC
        )
        assert timestamps.parse("2026-09-14", naive="local") == datetime(
            2026, 9, 13, 22, 0, tzinfo=UTC
        )


@case
def a_broken_timestamp_is_none_or_the_oldest_there_is():
    for broken in ("", None, "hier", "2026-13-01", 12):
        assert timestamps.parse(broken) is None
        assert timestamps.parse(broken, naive="local") is None
        assert timestamps.sortable(broken) == timestamps.NEVER
    assert timestamps.sortable("2026-09-14") > timestamps.NEVER


@case
def a_front_matter_hour_is_the_same_hour_for_the_sync_and_the_statistics():
    """`edited: 2026-09-14T23:30`, typed by hand: local, for both readers.

    Read in UTC by one and locally by the other, the same line was two hours
    apart in Paris — here, a ticket edited on the 14th by the synchronisation
    and closed on the 15th by the statistics.
    """
    typed = "2026-09-14T23:30"
    with _paris():
        assert statistics.day_of(typed) == date(2026, 9, 14)
        assert sync._minute(typed) == datetime(2026, 9, 14, 21, 30, tzinfo=UTC)
        assert sync._minute(typed).astimezone().date() == statistics.day_of(typed)
        # Notion's 21:45 UTC is 23:45 in Paris: after the hour typed, not before.
        assert sync._newer("2026-09-14T21:45:00.000Z", typed)
        assert not sync._newer(typed, "2026-09-14T21:45:00.000Z")
