"""`ticket.py`: the identifiers a ticket is known by, on disk and in a branch."""

from __future__ import annotations

from support import case

from ponos.__main__ import _names
from ponos.ticket import short_id, slugify

# -- identifiers -------------------------------------------------------------


@case
def short_ids_tell_same_day_tickets_apart():
    """Notion IDs are time-ordered, so same-day tickets share a long prefix.

    Two real tickets, created minutes apart, collided on their first eight
    characters — and would have shared one scratch directory.
    """
    a = "3ca451680af480ae9443de0b65d9abf8"
    b = "3ca451680af480beb02ac9d2cb79078c"
    assert a[:8] == b[:8], "premise: these two really do share a prefix"
    assert short_id(a) != short_id(b)
    assert short_id("3ca45168-0af4-80ae-9443-de0b65d9abf8") == short_id(a)
    assert len(short_id(a)) == 8


@case
def a_log_is_found_however_its_id_was_pasted():
    b = "3ca451680af480beb02ac9d2cb79078c"
    name = f"20260828-112441-{short_id(b)}.jsonl"
    assert _names(b, name)
    assert _names("3ca45168-0af4-80be-b02a-c9d2cb79078c", name)
    assert _names("https://www.notion.so/Ticket-" + b, name)
    assert _names(short_id(b), name)
    assert not _names("3ca451680af480ae9443de0b65d9abf8", name), "a neighbour must not match"


@case
def slugs_survive_accents_and_emptiness():
    assert slugify("Supprimer la description") == "supprimer-la-description"
    assert slugify("Corriger l'entête « à faire »") == "corriger-l-entete-a-faire"
    assert slugify("") == "ticket"
    assert len(slugify("x" * 200)) <= 40
