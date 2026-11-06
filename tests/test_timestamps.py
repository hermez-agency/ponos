"""`timestamps.py`: one reading of an ISO timestamp, and of an hour with no offset."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

from support import case

from ponos import timestamps


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
def an_offset_is_taken_as_written() -> None:
    paris = timezone(timedelta(hours=2))
    for naive in ("utc", "local"):
        assert timestamps.parse("2026-09-14T09:12:00+02:00", naive) == datetime(
            2026, 9, 14, 9, 12, tzinfo=paris
        )
        assert timestamps.parse("2026-09-14T07:12:00.000Z", naive) == datetime(
            2026, 9, 14, 7, 12, tzinfo=UTC
        )


@case
def an_hour_without_an_offset_is_read_as_the_caller_says() -> None:
    with _paris():
        assert timestamps.parse("2026-09-14T09:12") == datetime(2026, 9, 14, 9, 12, tzinfo=UTC)
        assert timestamps.parse("2026-09-14T09:12", naive="local") == datetime(
            2026, 9, 14, 7, 12, tzinfo=UTC
        )
        assert timestamps.parse("2026-09-14", naive="local") == datetime(
            2026, 9, 13, 22, 0, tzinfo=UTC
        )
    # A zone named by the caller, whatever the machine's: an hour of that zone.
    tokyo = timezone(timedelta(hours=9))
    assert timestamps.parse("2026-09-14T09:12", naive=tokyo) == datetime(
        2026, 9, 14, 0, 12, tzinfo=UTC
    )


@case
def a_broken_timestamp_is_none_or_the_oldest_there_is() -> None:
    for broken in ("", None, "hier", "2026-13-01", 12):
        assert timestamps.parse(broken) is None
        assert timestamps.parse(broken, naive="local") is None
        assert timestamps.sortable(broken) == timestamps.NEVER
    assert timestamps.sortable("2026-09-14") > timestamps.NEVER
