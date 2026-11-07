"""What a ticket waits for before it may start: the tickets it names under « Après ».

Born of a month of sessions that stopped on the same sentence. A series of
tickets made ready together — the eight steps of a migration, the nine tickets
behind one pull request — was run side by side, and every one but the first
paid a session to say « the ticket I need is not done yet ». Nothing on the
board could say it before: the order lived in the titles.

So a ticket names what it comes after, as a relation to other tickets of the
same board — an attribute, not a column of the board (a ticket that waits is
still ready; nothing happened to it). It is not started while one of those is
anything but done, and it starts at the first reading of the board after the
last one is: no session to wake, nothing to tick again.

One reading for the two places that ask it, the pass that would claim the
ticket and the console that draws its card, so that the card never says
« waiting » for a ticket the runner would take. They differ only in how a page
is found — the board read again by the runner, the one already read by the console —
which is `lookup`.

A ticket named that cannot be found — deleted, or never shared with the
integration — holds nothing back: it can never become done, and a ticket held
forever by a page nobody can see is worse than one started a little early.
"""

from __future__ import annotations

from collections.abc import Callable

from . import ids, store


def named(page: store.Page, column: str) -> list[str]:
    """The tickets this page says it comes after, as bare ids — itself left out.

    Anything but a relation reads as none, as for a goal: a text column under
    that name was never meant for this.
    """
    if not column:
        return []
    value = store.read(page, column)
    if not isinstance(value, list):
        return []
    own = ids.bare(page.id)
    found: list[str] = []
    for item in value:
        key = ids.bare(str(item or ""))
        if key and key != own and key not in found:
            found.append(key)
    return found


def unmet(
    page: store.Page,
    column: str,
    status: str,
    done: str,
    lookup: Callable[[str], store.Page | None],
) -> list[store.Page]:
    """The tickets named under `column` that are not done yet, in the order named.

    `lookup` hands back the page of an id, or None for one that cannot be
    found — which then holds nothing back (see the module's docstring).
    """
    waiting: list[store.Page] = []
    for key in named(page, column):
        other = lookup(key)
        if other is None:
            continue
        if str(store.read(other, status) or "") != done:
            waiting.append(other)
    return waiting


def said(pages: list[store.Page]) -> str:
    """The tickets waited for, as a card and a journal name them."""
    return ", ".join(page.title or ids.bare(page.id)[:8] for page in pages)
