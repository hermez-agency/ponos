"""What a ticket waits for before it may start: the tickets it names under « Après ».

Born of a month of sessions that stopped on the same sentence. A series of
tickets made ready together — the eight steps of a migration, the nine tickets
behind one pull request — was run side by side, and every one but the first
paid a session to say « the ticket I need is not done yet ». Nothing on the
board could say it before: the order lived in the titles.

So a ticket names what it comes after, as a relation to other tickets of the
same board. It is not started while one of those is anything but done or
validated — validated is a review already passed, whose merge is the
runner's to do — and a ticket that names unfinished ones is put in the
waiting column, which the runner leaves to `Board.release`: that moves it to
ready once the last one is finished, or to blocked when one of them was
cancelled, since a ticket given up on never finishes and only a person can say
what the ones after it become.

A ticket somebody moves to ready anyway is still held there while one is
unfinished, its card saying so: that reading (`unmet`) is the older one, kept
as the net under the column.

Refused when it loops: a ticket cannot wait, even through others, for itself —
see `tickets.cycle`.

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

from collections.abc import Callable, Collection

from . import ids, store

# The statuses, as keys of `config.STATUS`, a ticket waited for counts as
# finished in. Validated rather than only done: the person has said yes, and
# what is left — a merge — is the runner's.
FINISHED = ("done", "validated")


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
    done: str | Collection[str],
    lookup: Callable[[str], store.Page | None],
) -> list[store.Page]:
    """The tickets named under `column` that are not finished yet, in the order named.

    `done` is the status, or the statuses, a ticket counts as finished in.
    `lookup` hands back the page of an id, or None for one that cannot be
    found — which then holds nothing back (see the module's docstring).
    """
    finished = {done} if isinstance(done, str) else set(done)
    waiting: list[store.Page] = []
    for key in named(page, column):
        other = lookup(key)
        if other is None:
            continue
        if str(store.read(other, status) or "") not in finished:
            waiting.append(other)
    return waiting


def given_up(pages: list[store.Page], status: str, cancelled: str) -> list[store.Page]:
    """Those of `pages` that were cancelled: they will never be finished."""
    if not cancelled:
        return []
    return [page for page in pages if str(store.read(page, status) or "") == cancelled]


def said(pages: list[store.Page]) -> str:
    """The tickets waited for, as a card and a journal name them: `PON-36`, else the title."""
    return ", ".join(
        str(page.raw.get("public_id") or "") or page.title or ids.bare(page.id)[:8]
        for page in pages
    )
