"""What a project has learned, kept as notes the next tickets read.

The same blocking comes back from one ticket to the next because the answer
given once serves only the ticket that got it. A session that was blocked,
answered, and then finished may say what it learned on a `LESSON:` line; it is
not believed, it is *proposed* — somebody keeps it, edits it or throws it away
on the project's page, and only a kept note reaches the prompts.

**Proposed is not kept.** A prompt that grew on its own would be the quiet way
for a wrong guess to steer every later ticket of the project, so nothing a
session wrote is read by a session until a person said yes.

**A discarded proposal never comes back.** What was thrown away is remembered
by its fingerprint (words, case and punctuation aside): the same lesson learned
again on the next blocked ticket must not ask the same question twice.

**A ceiling, so that the prompt stays short.** One note is `NOTE_LIMIT`
characters, the kept ones together `KEPT_LIMIT`, and the waiting proposals
`PROPOSED_LIMIT`: past the last, the oldest makes room. A note that does not fit
is refused by name — the person is asked to shorten something, never silently
cut.

Kept in `ponos.db` beside the project's other settings, under one key — see
project_settings.py.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import db, project_settings

NOTES = "notes"
NOTE_LIMIT = 300
KEPT_LIMIT = 2000
PROPOSED_LIMIT = 10
DROPPED_LIMIT = 200


def clean(text: str) -> str:
    """A note on one line, in single spaces, cut at the limit."""
    return " ".join(str(text or "").split())[:NOTE_LIMIT].rstrip()


def fingerprint(text: str) -> str:
    """What makes two notes the same one: the words, not the case or the punctuation."""
    words = re.sub(r"[\W_]+", " ", text.casefold()).split()
    return hashlib.sha1(" ".join(words).encode()).hexdigest()[:16]


def _held(project: str) -> dict[str, Any]:
    own = project_settings._read(project).get(NOTES)
    held = own if isinstance(own, dict) else {}
    return {
        "kept": [str(text) for text in held.get("kept", []) if isinstance(text, str)],
        "proposed": [str(text) for text in held.get("proposed", []) if isinstance(text, str)],
        "dropped": [str(text) for text in held.get("dropped", []) if isinstance(text, str)],
    }


def read(project: str) -> dict[str, list[str]]:
    """The project's notes: `kept` (read by sessions) and `proposed` (waiting). Empty when unreadable."""
    if not project_settings.key(project):
        return {"kept": [], "proposed": []}
    try:
        held = _held(project)
    except db.ERRORS:
        return {"kept": [], "proposed": []}
    return {"kept": held["kept"], "proposed": held["proposed"]}


def kept(project: str) -> list[str]:
    """The notes every ticket of the project is told, in the order they were kept."""
    return read(project)["kept"]


def _save(project: str, name: str, held: dict[str, Any]) -> None:
    def change(settings: dict[str, Any]) -> None:
        if any(held.values()):
            settings[NOTES] = {key: value for key, value in held.items() if value}
        else:
            settings.pop(NOTES, None)

    project_settings._write(project, name, change)


def _fits(kept_notes: list[str]) -> bool:
    return sum(len(text) for text in kept_notes) <= KEPT_LIMIT


def propose(project: str, name: str, text: str) -> bool:
    """Put a lesson to the person: False when it is empty, known, kept or thrown away before."""
    text = clean(text)
    if not text or not project_settings.key(project):
        return False
    try:
        held = _held(project)
        mark = fingerprint(text)
        known = [*held["kept"], *held["proposed"]]
        if mark in held["dropped"] or any(fingerprint(note) == mark for note in known):
            return False
        held["proposed"] = [*held["proposed"], text][-PROPOSED_LIMIT:]
        _save(project, name, held)
    except db.ERRORS:
        return False
    return True


def _take(held: dict[str, Any], text: str) -> str:
    """The waiting proposal that `text` names, removed from the list."""
    for index, note in enumerate(held["proposed"]):
        if note == text:
            return str(held["proposed"].pop(index))
    raise ValueError("this proposal is not waiting any more")


def keep(project: str, name: str, text: str, edited: str = "") -> None:
    """Keep a proposal, as it is or as the person rewrote it."""
    held = _held(project)
    _take(held, text)
    _add(held, edited or text)
    _save(project, name, held)


def _add(held: dict[str, Any], text: str) -> None:
    text = clean(text)
    if not text:
        raise ValueError("a note cannot be empty")
    if any(fingerprint(note) == fingerprint(text) for note in held["kept"]):
        return
    if not _fits([*held["kept"], text]):
        raise ValueError(
            f"the notes of a project hold {KEPT_LIMIT} characters at most: "
            "shorten or delete one before keeping another"
        )
    held["kept"].append(text)


def add(project: str, name: str, text: str) -> None:
    """A note written by hand, kept at once."""
    held = _held(project)
    _add(held, text)
    _save(project, name, held)


def drop(project: str, name: str, text: str) -> None:
    """Throw a proposal away, for good: its fingerprint is remembered."""
    held = _held(project)
    _take(held, text)
    mark = fingerprint(text)
    if mark not in held["dropped"]:
        held["dropped"] = [*held["dropped"], mark][-DROPPED_LIMIT:]
    _save(project, name, held)


def edit(project: str, name: str, index: int, text: str) -> None:
    """Rewrite a kept note."""
    held = _held(project)
    if not 0 <= index < len(held["kept"]):
        raise ValueError("this note does not exist any more")
    text = clean(text)
    if not text:
        raise ValueError("a note cannot be empty")
    others = [note for number, note in enumerate(held["kept"]) if number != index]
    if not _fits([*others, text]):
        raise ValueError(f"the notes of a project hold {KEPT_LIMIT} characters at most")
    held["kept"][index] = text
    _save(project, name, held)


def delete(project: str, name: str, index: int) -> None:
    """Delete a kept note. Learned again, it is proposed again: it was not refused."""
    held = _held(project)
    if not 0 <= index < len(held["kept"]):
        raise ValueError("this note does not exist any more")
    del held["kept"][index]
    _save(project, name, held)
