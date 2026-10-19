"""A ticket's priority: a score from 0 to 100, highest first.

It used to be four words — Urgent, High, Normal, Low — and four words said
little: two tickets both "High" were tied, and the step between "Normal" and
"High" was as wide as the board's whole middle. A number says how much, and
leaves room between two tickets to put a third.

**The words are still read.** A board built before the number has a select
column full of them, and a board somebody has not migrated yet must keep its
queue in order rather than flatten it to one score: each word is the score its
migration gives it (`WORDS`). Written the other way too — a score lands on a
select column as the nearest word — so a runner updated before its board is
migrated neither stops nor fills the column with options named "75".

**Read leniently, taken strictly.** A cell somebody typed 150 into is a ticket
that wants to go first, and is read as 100; a cell that says nothing is 50, the
middle, and waits its turn. A score *given* to the runner — by the console, by
a tool — out of 0 to 100 is refused instead: the person typing it is there to
be told.
"""

from __future__ import annotations

import math
from typing import Any

LOWEST = 0
HIGHEST = 100

# What an empty cell is worth: the middle, so a ticket nobody ranked goes after
# the urgent ones and before the ones somebody said could wait.
DEFAULT = 50

# The four words of the select it replaces, and the score each one migrates to.
WORDS = {"Urgent": 100, "High": 75, "Normal": 50, "Low": 25}

# From this score up, a ticket is never run on the lightest model (see `models`).
URGENT = 75


def _number(value: Any) -> float | None:
    """The number a cell or a field holds, a word turned into its score; None for none."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if math.isnan(value) else float(value)
    text = str(value).strip()
    if not text:
        return None
    for word, score in WORDS.items():
        if text.casefold() == word.casefold():
            return float(score)
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    return None if math.isnan(number) else number


def score(value: Any) -> int:
    """What a board's cell is worth: clamped to 0–100, `DEFAULT` when it says nothing."""
    number = _number(value)
    if number is None:
        return DEFAULT
    return int(min(max(round(number), LOWEST), HIGHEST))


def given(value: Any) -> int:
    """A score somebody gave: `DEFAULT` when empty, `ValueError` outside 0–100."""
    if value is None or not str(value).strip():
        return DEFAULT
    number = _number(value)
    if number is None or not LOWEST <= number <= HIGHEST:
        raise ValueError(f"a priority is a number from {LOWEST} to {HIGHEST}, not “{value}”")
    return int(round(number))


def word(value: int) -> str:
    """The word nearest a score, for a board whose column is still a select."""
    return min(WORDS, key=lambda name: abs(WORDS[name] - value))


def cell(value: int, kind: str | None) -> int | str:
    """A score as a column of that kind takes it: a word in a select, else the number."""
    return word(value) if kind == "select" else value
