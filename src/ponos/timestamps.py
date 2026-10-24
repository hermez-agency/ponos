"""Reading an ISO timestamp, and what one without an offset means.

Notion always writes its offset; a person typing `edited: 2026-09-14T09:12`
into a Markdown file does not. Each reader used to decide for itself what such
an hour was — UTC for the synchronisation, the local day for the statistics —
so the same line was two hours apart depending on who read it. The choice is
now said once, by the caller, and by name:

- `naive="local"` for what a person writes: a front matter, a ticket's date. A
  bare date is the start of that day *here*, as `guide/board.md` promises;
- `naive="utc"` for what the runner and Notion write, which only ever lacks an
  offset when an older version stored it that way — and it was UTC then;
- a zone, for a reader that counts in another one than the machine's: an hour
  with no offset is then one of that zone.

A value that cannot be read is None, never an exception: a broken date in one
file must not stop a pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Literal

# The oldest moment there is, comparable with any other: where a reader that
# sorts needs a place for a value it could not read.
NEVER = datetime.min.replace(tzinfo=UTC)


def parse(stamp: object, naive: Literal["utc", "local"] | tzinfo = "utc") -> datetime | None:
    """An ISO timestamp as an aware datetime, or None for an empty or broken one."""
    try:
        moment = datetime.fromisoformat(str(stamp or ""))
        if moment.tzinfo is not None:
            return moment
        if naive == "utc":
            return moment.replace(tzinfo=UTC)
        if naive == "local":
            return moment.astimezone()
        return moment.replace(tzinfo=naive)
    except (ValueError, OverflowError, OSError):
        return None


def sortable(stamp: object, naive: Literal["utc", "local"] = "utc") -> datetime:
    """The same, for a reader that sorts or compares: a broken one is the oldest there is."""
    return parse(stamp, naive) or NEVER
