"""A ticket written from a phone: « /ticket <project> <what to do> ».

An idea that comes in the street should not wait for a console. The same
channels that carry a question carry the other way round too: a message that
opens with `/ticket` (Telegram) or `ticket:` (either) is a ticket, not an answer.

This module only reads the sentence — the pure part, which is why it knows no
board. Which projects exist, and where the ticket is written, is `reports.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `/ticket`, `/ticket@my_bot` (what Telegram writes in a group) or `ticket:`;
# a `!` before the colon, or right after the slash command, means « Ready ».
_COMMAND = re.compile(r"^\s*(?:/ticket(?:@\w+)?(!?)|ticket(!?)\s*:)(?=\s|$)\s*(.*)$", re.I | re.S)

# Under two letters a first word is a coincidence, not an abbreviation.
PREFIX = 2

# A title is a line, not a paragraph; the rest of the message is the body.
TITLE = 100


@dataclass
class Command:
    """What a message asked for, before any project is looked up."""

    ready: bool
    text: str


def parse(text: str) -> Command | None:
    """The command a message is, or None when it is anything else."""
    found = _COMMAND.match(text or "")
    if not found:
        return None
    return Command(ready=bool(found.group(1) or found.group(2)), text=found.group(3).strip())


def project(text: str, names: list[str]) -> tuple[str, str]:
    """(project, what is left) — the first word looked up among `names`.

    Case does not count, and a prefix does: « /ticket pon … » is Ponos, unless
    two projects start that way, in which case the word is part of the text
    rather than a guess. No project recognised is `("", text)`.
    """
    word, _, rest = text.partition(" ")
    folded = word.casefold()
    if len(folded) < PREFIX:
        return "", text
    exact = [name for name in names if name.casefold() == folded]
    near = [name for name in names if name.casefold().startswith(folded)]
    chosen = exact or (near if len(near) == 1 else [])
    return (chosen[0], rest.strip()) if chosen else ("", text)


def title_of(text: str) -> tuple[str, str]:
    """(title, body): the first line, cut at a word, and the whole text when it said more."""
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    title = first
    if len(title) > TITLE:
        title = title[:TITLE].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return title, text.strip() if title != text.strip() else ""
