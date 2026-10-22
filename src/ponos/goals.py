"""The goal a ticket serves.

A project says *where* the work happens, an agent says *who* does it. Neither
says **what for** — and "add a column" reads differently when the point is a
launch next month than when it is a cleanup nobody is waiting on.

So a ticket may point at a goal, and the goal is a page: its body is the brief
of the goal, exactly as a project's page is its brief. Its row adds the two
things a session cannot guess — the criterion that says the goal is met, and
the date it is due by.

Everything here is optional twice over: a database without the relation column
behaves as it always has, and a ticket that names no goal gets the prompt it
always got, to the character. A goal is the intent of the task, never its
rules: it is read before the role, which keeps the last word.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import store


@dataclass
class Goal:
    name: str = ""
    brief: str = ""
    criterion: str = ""
    due: str = ""

    def __bool__(self) -> bool:
        return bool(self.name)


def pointed(page: store.Page, relation_property: str) -> str:
    """The goal a ticket points at, or "" — the first of the relation, if any.

    Anything but a relation reads as none: a column of another type under that
    name is a column that was never meant for this, and its first character is
    not a page to ask Notion for.
    """
    goals = store.read(page, relation_property)
    if not isinstance(goals, list) or not goals:
        return ""
    return str(goals[0] or "")


def resolve(
    backend: store.Store,
    page_id: str,
    criterion_property: str = "Critère",
    due_property: str = "Échéance",
) -> Goal:
    """The goal a ticket points at. An unreadable page is no goal at all.

    Failing a ticket because the page saying what it serves could not be
    fetched would trade a whole run for an accessory — the same call the
    project brief and the agent already make.
    """
    try:
        page = backend.page(page_id)
    except store.StoreError:
        return Goal()
    name = page.title.strip()
    if not name:
        return Goal()
    try:
        brief = backend.blocks_text(page_id, live=False)
    except store.StoreError:
        brief = ""
    return Goal(
        name,
        brief,
        str(store.read(page, criterion_property) or "").strip(),
        str(store.read(page, due_property) or "").strip(),
    )
