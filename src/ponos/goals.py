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


# What a goal's `Statut` says while it is still being worked toward. A goal
# that is on hold, met or given up is not a cap: proposing work for it is
# proposing work nobody is waiting on.
ACTIVE = ("actif", "active", "en cours")


def active(
    backend: store.Store,
    database_id: str,
    project: str = "",
    status_property: str = "Statut",
    projects_property: str = "Projets",
    criterion_property: str = "Critère",
    due_property: str = "Échéance",
) -> list[Goal]:
    """The goals being worked toward now — those of a project, or all of them.

    A goal with no status counts as active: a database that never had the
    column is not one whose goals are all over. `project` keeps the goals whose
    `Projets` relation holds it. An unreadable database is no goal at all, for
    the same reason `resolve` gives: ideas are an accessory of the goals, not
    the other way round.
    """
    if not database_id:
        return []
    try:
        pages = backend.query(database_id)
    except store.StoreError:
        return []
    wanted = project.replace("-", "")
    found: list[Goal] = []
    for page in pages:
        name = page.title.strip()
        status = str(store.read(page, status_property) or "").strip().lower()
        if not name or (status and status not in ACTIVE):
            continue
        if wanted:
            linked = store.read(page, projects_property)
            if not isinstance(linked, list) or wanted not in (
                str(item or "").replace("-", "") for item in linked
            ):
                continue
        found.append(
            Goal(
                name,
                criterion=str(store.read(page, criterion_property) or "").strip(),
                due=str(store.read(page, due_property) or "").strip(),
            )
        )
    return found
