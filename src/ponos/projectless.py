"""« Sans projet »: the project of a ticket that has none, and a project named rather than pointed at.

Two ways a ticket used to lose its project, and both ended the same way.

A ticket written with a project's **name** where its identifier belongs —
`"project": "Changer d'adresse"` sent to the console's API — was kept as
written, and blocked at its first pass on « no such page »: every other door
writes an identifier, and the runner only knows how to follow one. So the name
is read here, once, for every door at once: `ledger.Ledger` writes a ticket's
project through `resolve`, which takes a name (whatever its case and accents)
or an identifier and keeps the identifier, and refuses a name nobody has with
the list of those that exist — a refusal said to whoever is creating the
ticket, rather than a ticket blocked later for somebody else to read.

A ticket written with **no project at all** already ran, as the plainest of
document tickets, but nothing on the board said so: no filter found it, no
list counted it, and somebody wanting to run "renew my passport" invented a
project for it. So it has one: a page of the projects collection, under a
fixed identifier (`ID`), made by a migration, that never has a repository and
cannot be deleted. Every ticket created without a project is written into it,
and the runner reads it as it read no project — a scratch directory under the
state, the answer in the page, no worktree, no pull request. A code ticket in
it is not run in a guessed repository: it asks which one (see
`preparation.py`).

Its name is the runner's language's (`NAMES`), written when the runner starts
(`ensure`) — the migration that makes the page has no configuration to read
one from — and only over one of its own names: a page somebody renamed stays
renamed.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

from . import db, ids

# Thirty-two hexadecimal characters, as every page id: `short_id` and the
# routes that read `{id:page}` take it like any other.
ID = "00000000000000000000000000000001"

NAMES = {"en": "Unknown", "fr": "Sans projet"}


class UnknownProject(ValueError):
    """A project named that no page answers to, and the names that do."""

    def __init__(self, message: str, given: str, known: list[str]) -> None:
        super().__init__(message)
        self.given = given
        self.known = known


def name(language: str) -> str:
    """What the page is called in that language."""
    from . import voice

    return NAMES[voice.understood(language)]


def is_it(page_id: object) -> bool:
    """Whether a page id is « Sans projet »'s."""
    return ids.bare(page_id).lower() == ID


def is_identifier(value: object) -> bool:
    """Thirty-two hexadecimal characters, dashes left aside: a page id, not a name."""
    text = ids.bare(value)
    return len(text) == 32 and all(char in "0123456789abcdefABCDEF" for char in text)


def fold(text: object) -> str:
    """A name as two spellings of it compare: no case, no accents, single spaces.

    And one apostrophe: a phone types "’" where a keyboard types "'".
    """
    typed = str(text or "").replace("’", "'").replace("‘", "'")
    decomposed = unicodedata.normalize("NFKD", " ".join(typed.split()))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def first(value: object) -> str:
    """The one project a relation names, whatever shape the caller wrote it in."""
    related = value if isinstance(value, (list, tuple)) else [value]
    return next((str(one).strip() for one in related if str(one or "").strip()), "")


def match(given: str, pages: Iterable[tuple[str, str]]) -> str:
    """The id of the page a name or an id designates among (id, title) — "" when none."""
    wanted = fold(given)
    if not wanted:
        return ""
    if wanted in {fold(word) for word in NAMES.values()}:
        return ID
    for page_id, title in pages:
        if fold(title) == wanted or ids.bare(page_id).lower() == ids.bare(given).lower():
            return ids.bare(page_id)
    return ""


def resolve(
    given: object,
    pages: Callable[[], Iterable[tuple[str, str]]],
    refusal: Callable[[str, list[str]], str] | None = None,
) -> str:
    """The identifier a ticket keeps for the project it was given.

    Nothing is « Sans projet ». An identifier is kept as it is, even one no
    page answers to any more: a project deleted since is the deletion's to deal
    with, not a reason to refuse every later write of the ticket. A name is
    the page it names; a name nobody has raises `UnknownProject`, said by
    `refusal(given, known)` when the caller has words for it. `pages` gives the
    (id, title) of every project, and is only asked when a name has to be read.
    """
    text = first(given)
    if not text:
        return ID
    if is_identifier(text):
        return ids.bare(text)
    listed = list(pages())
    found = match(text, listed)
    if found:
        return found
    known = [title for page_id, title in listed if not is_it(page_id)]
    message = (
        refusal(text, known)
        if refusal
        else f"unknown project: {text} — projects available: {', '.join(known) or '—'}"
    )
    raise UnknownProject(message, text, known)


def ensure(language: str) -> None:
    """The page there, untrashed, and called in the runner's language.

    Renamed only from one of its own names: a page somebody called otherwise
    keeps what they called it. A database that cannot be written is left as it
    is — the page is a convenience of the board, never a reason to stop.
    """
    wanted = name(language)
    try:
        with db.transaction() as connection:
            row = connection.execute(
                "SELECT title, trashed FROM board_pages WHERE id = ?", (ID,)
            ).fetchone()
            if row is None:
                _insert(connection, wanted)
                return
            title, trashed = str(row[0]), int(row[1])
            if trashed or (title != wanted and title in NAMES.values()):
                connection.execute(
                    "UPDATE board_pages SET title = ?, trashed = 0 WHERE id = ?",
                    (wanted if title in NAMES.values() else title, ID),
                )
    except db.ERRORS:
        return


def _insert(connection: Any, title: str) -> None:
    """The page itself: a project with no repository, no path, nothing but a name."""
    from .pages import now

    stamp = now()
    connection.execute(
        "INSERT OR IGNORE INTO board_pages (id, collection, title, properties, body, created, edited)"
        " VALUES (?, 'projects', ?, '{}', '', ?, ?)",
        (ID, title, stamp, stamp),
    )


def migrate(connection: Any) -> None:
    """Make the page, put every ticket without a project in it, and names back into ids.

    Run once, by `db._projectless`. A name that matches no project is left as
    it was: guessing which project somebody meant is not a migration's to do.
    """
    _insert(connection, NAMES["en"])
    pages = [
        (str(page_id), str(title))
        for page_id, title in connection.execute(
            "SELECT id, title FROM board_pages WHERE collection = 'projects' AND trashed = 0"
        )
    ]
    named = [
        str(project)
        for (project,) in connection.execute(
            "SELECT DISTINCT project FROM tickets WHERE project != ''"
        )
        if not is_identifier(project)
    ]
    for written in named:
        found = match(written, pages)
        if found:
            connection.execute("UPDATE tickets SET project = ? WHERE project = ?", (found, written))
    connection.execute("UPDATE tickets SET project = ? WHERE project = ''", (ID,))
