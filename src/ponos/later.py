"""When a ticket is to run: a moment as somebody types it, and whether it may hold a ticket.

The console sends an ISO date with its offset, worked out in the browser's
timezone; a terminal does not have a date picker. `ponos schedule <ticket>
"demain 9h"` is what a person, or an `On` prompt writing a follow-up, actually
types — so the few shapes people say are read here, once, for the CLI, the API
and the MCP alike, and anything else is refused with what *is* understood
rather than guessed at. A date the runner misreads is a ticket that runs a day
early, or never; a refusal costs one more try.

Every hour said without an offset is one of this machine's, as everywhere the
runner reads a ticket's date (`schedules.scheduled_for`): "9h" is nine o'clock
where the daemon runs, which is where the ticket is held.

A moment already past is refused rather than written: on a ready ticket it
would mean "now", which is what no date says more plainly, and a date typed a
day wrong would start the work without anybody noticing the mistake. The one
way back to "now" is the empty value, which removes the date.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import timestamps

# The hour a day said alone starts at: "demain" is tomorrow morning, not midnight.
MORNING = (9, 0)

_CLOCK = re.compile(r"^(\d{1,2})\s*(?:(?:[:h])\s*(\d{2})?)?$")
_OFFSET = re.compile(r"^\+\s*(\d+)\s*(min|m|h|d|j|w)$")
_UNITS = {"m": "minutes", "min": "minutes", "h": "hours", "d": "days", "j": "days", "w": "weeks"}

_DAYS = {
    "today": 0,
    "aujourd'hui": 0,
    "aujourdhui": 0,
    "tomorrow": 1,
    "demain": 1,
    "après-demain": 2,
    "apres-demain": 2,
    "après demain": 2,
    "apres demain": 2,
}
_WEEKDAYS = (
    ("monday", "lundi"),
    ("tuesday", "mardi"),
    ("wednesday", "mercredi"),
    ("thursday", "jeudi"),
    ("friday", "vendredi"),
    ("saturday", "samedi"),
    ("sunday", "dimanche"),
)

FORMS = '"2026-11-21 09:00", "demain 9h", "tomorrow 14:30", "lundi 9h", "+2h", "+2d"'


def _clock(text: str) -> tuple[int, int] | None:
    match = _CLOCK.match(text.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    return (hour, minute) if hour < 24 and minute < 60 else None


def _day(text: str, now: datetime) -> datetime | None:
    """The day a word names, at midnight here: "demain", "lundi" (the next one, never today)."""
    word = text.strip().lower().removeprefix("next ").removesuffix(" prochain")
    if word in _DAYS:
        return (now + timedelta(days=_DAYS[word])).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    for index, names in enumerate(_WEEKDAYS):
        if word in names:
            ahead = (index - now.weekday()) % 7 or 7
            return (now + timedelta(days=ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def parse(text: str, now: datetime | None = None) -> datetime | None:
    """The moment `text` names, aware and in this machine's zone; None when it names none.

    ISO first — what the console sends, and "2026-11-21 09:00" typed by hand.
    Then "+2h", "+30m", "+3d" from now; a day ("demain", "lundi", "après-demain")
    with an hour or without one (then `MORNING`); an hour alone, today or, once
    it has passed, tomorrow.
    """
    now = (now or datetime.now()).astimezone()
    said = " ".join(text.strip().split())
    if not said:
        return None
    moment = timestamps.parse(said, naive="local")
    if moment is not None:
        return moment
    lowered = said.lower()
    if offset := _OFFSET.match(lowered):
        unit = _UNITS[offset.group(2)]
        return (now + timedelta(**{unit: int(offset.group(1))})).replace(second=0, microsecond=0)
    if clock := _clock(lowered):
        moment = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        return moment if moment > now else moment + timedelta(days=1)
    words = lowered.replace(" à ", " ").replace(" at ", " ").split(" ")
    # The day is what comes before the hour, if the last word is one.
    clock = _clock(words[-1]) if len(words) > 1 else None
    day = _day(" ".join(words[:-1] if clock else words), now)
    if day is None:
        return None
    hour, minute = clock or MORNING
    return day.replace(hour=hour, minute=minute)


def written(value: object, now: datetime | None = None) -> str:
    """The date a ticket is to carry, as the board keeps it; "" to remove it.

    Raises `ValueError` — in words a person can act on — for a moment nobody
    can read and for one already past.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    current = (now or datetime.now()).astimezone()
    moment = parse(text, current)
    if moment is None:
        raise ValueError(f"unreadable date “{text}”: write it like {FORMS}")
    if moment <= current:
        raise ValueError(
            f"{moment.isoformat(timespec='minutes')} has already passed: "
            "choose a later moment, or remove the date to run the ticket now"
        )
    return moment.isoformat(timespec="minutes")
