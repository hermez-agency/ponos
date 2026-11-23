"""The id a person says out loud: `PON-142`.

A ticket's own id is thirty-two hexadecimal characters, and the eight it was
shortened to (`ticket.short_id`) are no easier to read out. The public id is a
project's prefix and a number that follows: `PON-142`, `BA-37`.

**Numbered per project, by prefix.** The prefix already says the project, so a
global counter would only give gaps nobody can explain (BA-37, then BA-52). The
counter is the *prefix's* (`ticket_counters`), not the project's: a ticket that
moves to another project keeps the id it was given, and the project it joins
never hands out a number that was already given — nor does a prefix that
changes hands after a rename, since the number goes on from where the prefix
stopped.

**Stored, never computed.** The prefix and the number are written with the
ticket, in the same transaction that takes the number: `BEGIN IMMEDIATE`
(`db.transaction`) is the lock that makes two tickets created at once — console,
CLI, a recurrence, an import, two processes — draw two numbers. A unique index
on (prefix, number) is the net under it.

**A prefix is a project's setting**, kept in `ticket_prefixes`. Unless somebody
chose one, it is drawn from the project's name the first time a ticket needs
it — two to four capital letters, unique among projects — and written down, so
that renaming the project later does not move it.
"""

from __future__ import annotations

import re
import sqlite3
import string
import unicodedata

from . import db, projectless

# What a ticket of « Sans projet » is numbered under: `T-12`.
COMMON = "T"

# A chosen prefix: letters first, then letters or digits, as long as is readable.
SHAPE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
# A public id as typed, whatever its case.
PUBLIC = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-([0-9]+)$")


class PrefixTaken(ValueError):
    """The prefix is another project's."""


def typed(text: object) -> str:
    """A prefix as it is kept: no spaces, capitals."""
    return str(text or "").strip().upper()


def parse(reference: object) -> tuple[str, int] | None:
    """(prefix, number) of `pon-142`, or None for anything else."""
    found = PUBLIC.match(str(reference or "").strip())
    return (found.group(1).upper(), int(found.group(2))) if found else None


def derive(name: str, taken: set[str]) -> str:
    """Two to four capital letters out of a project's name, not in `taken`.

    The initials of several words (`Brand Assets` → `BA`), the first letters of
    one (`Ponos` → `PON`); the next candidate when that one is used, and at last
    letters walked through one after the other, which cannot run out.
    """
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z]+", plain.upper())
    letters = "".join(words)
    initials = "".join(word[0] for word in words)[:4]
    candidates = []
    if len(initials) >= 2:
        candidates.append(initials)
    for size in (3, 4, 2):
        if len(letters) >= size:
            candidates.append(letters[:size])
    for candidate in candidates:
        if candidate not in taken:
            return candidate
    stem = (letters + "XX")[:2]
    for one in string.ascii_uppercase:
        for two in string.ascii_uppercase:
            if (candidate := stem + one + two) not in taken:
                return candidate
    raise AssertionError("no prefix left")  # pragma: no cover  # 676 per stem


def _name(connection: sqlite3.Connection, project: str) -> str:
    row = connection.execute(
        "SELECT title FROM board_pages WHERE collection = 'projects' AND id = ?", (project,)
    ).fetchone()
    return str(row[0]) if row else ""


def prefix_of(connection: sqlite3.Connection, project: str) -> str:
    """The project's prefix — drawn from its name and written down if it has none yet."""
    if projectless.is_it(project):
        return COMMON
    row = connection.execute(
        "SELECT prefix FROM ticket_prefixes WHERE project = ?", (project,)
    ).fetchone()
    if row:
        return str(row[0])
    taken = {str(one) for (one,) in connection.execute("SELECT prefix FROM ticket_prefixes")}
    taken.add(COMMON)
    prefix = derive(_name(connection, project), taken)
    connection.execute(
        "INSERT INTO ticket_prefixes (project, prefix) VALUES (?, ?)", (project, prefix)
    )
    return prefix


def take(connection: sqlite3.Connection, project: str) -> tuple[str, int]:
    """The next public id of a project, as (prefix, number) — inside the caller's transaction."""
    prefix = prefix_of(connection, project)
    connection.execute(
        "INSERT INTO ticket_counters (prefix, last) VALUES (?, 1) "
        "ON CONFLICT (prefix) DO UPDATE SET last = last + 1",
        (prefix,),
    )
    (number,) = connection.execute(
        "SELECT last FROM ticket_counters WHERE prefix = ?", (prefix,)
    ).fetchone()
    return prefix, int(number)


def set_prefix(connection: sqlite3.Connection, project: str, prefix: str) -> str:
    """Give a project the prefix it is to number its next tickets under.

    Raises `ValueError` for a shape that is not a prefix and `PrefixTaken` for
    one that is another project's. The tickets already numbered keep their ids.
    """
    wanted = typed(prefix)
    if projectless.is_it(project):
        raise ValueError(f"the tickets without a project are always numbered {COMMON}-…")
    if not SHAPE.match(wanted) or wanted == COMMON:
        raise ValueError(
            f"{prefix!r} is not a prefix: two to six capitals or digits, a letter first"
        )
    owner = connection.execute(
        "SELECT project FROM ticket_prefixes WHERE prefix = ?", (wanted,)
    ).fetchone()
    if owner and owner[0] != project:
        raise PrefixTaken(f"{wanted} is already another project's prefix")
    connection.execute(
        "INSERT INTO ticket_prefixes (project, prefix) VALUES (?, ?) "
        "ON CONFLICT (project) DO UPDATE SET prefix = excluded.prefix",
        (project, wanted),
    )
    return wanted


def prefix(project: str) -> str:
    """The project's prefix, in a transaction of its own — what a page of settings shows."""
    with db.transaction() as connection:
        return prefix_of(connection, project)


def choose(project: str, wanted: str) -> str:
    """`set_prefix`, in a transaction of its own."""
    with db.transaction() as connection:
        return set_prefix(connection, project, wanted)


def backfill(connection: sqlite3.Connection) -> None:
    """Number the tickets that have no id yet, project by project, oldest first."""
    rows = connection.execute(
        "SELECT id, project FROM tickets WHERE number = 0 ORDER BY created_at, id"
    ).fetchall()
    for ticket, project in rows:
        prefix, number = take(connection, project)
        connection.execute(
            "UPDATE tickets SET prefix = ?, number = ? WHERE id = ?", (prefix, number, ticket)
        )
