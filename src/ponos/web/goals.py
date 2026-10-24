"""The goals: what a ticket is done for, and how far each one has gone.

A goal is a row of the Objectifs database, written by hand in Notion as a
project's is, so its columns are found under the names they are written with.
How far it has gone is counted from the board rather than read from Notion's
rollup: a board of Markdown files has none, and the tickets the console already
holds say it column by column.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import time
from typing import Any

from .. import goals as goals_module
from .. import priority as priority_module
from .. import store
from ..ticket import short_id
from .base import Base
from .projects import PROJECT_TTL, _first, _relation
from .tickets import _columns

logger = logging.getLogger(__name__)

# The columns `goals.resolve` and `goals.active` read too, under the same names.
GOAL_COLUMNS = goals_module.GOAL_COLUMNS


def _active(status: str) -> bool:
    """Whether a goal's `Statut` says it is still worked toward, as `goals.active` reads it.

    No status is active there too: a database that never had the column is
    not one whose goals are all over.
    """
    return not status.strip() or status.strip().lower() in goals_module.ACTIVE


def _pointing(page: store.Page, column: str, goal_id: str) -> store.Page:
    """A ticket's page as held, now pointing at this goal — or at none: what a read back would say."""
    cell = {**page.properties.get(column, {}), "type": "relation"}
    cell["relation"] = [{"id": goal_id}] if goal_id else []
    return dataclasses.replace(page, properties={**page.properties, column: cell})


class Goals(Base):
    def _goal_index(self) -> dict[str, dict[str, Any]]:
        """{page id: {id, name, status, active, project_ids}} — the goals, one query kept as the projects are.

        A card names its goal from this, so the board reads the goals database
        once every few minutes rather than a page per ticket. A workspace with
        no goals, or one that cannot be read, is an empty index: the cards
        lose their goal, never the board. The status and the projects are what
        a new ticket's choice of goal is sorted by (`Tickets._choices`).
        """
        held: dict[str, dict[str, Any]] = getattr(self, "_goals", {})
        # Kept empty too: a workspace whose goals are none is not asked again
        # at every reading of the board.
        if time.time() - getattr(self, "_goals_at", 0.0) < PROJECT_TTL:
            return held
        try:
            return self._remember_goals(self._goal_pages())
        except store.StoreError:
            return held

    def _goal_pages(self) -> list[store.Page]:
        database = self.runner.workspace.goals
        return self.runner.client.query(database) if database else []

    def _remember_goals(self, pages: list[store.Page]) -> dict[str, dict[str, Any]]:
        self._goals = {}
        for page in pages:
            if not page.title:
                continue
            status = _first(page, *GOAL_COLUMNS["status"])
            self._goals[page.id] = {
                "id": page.id.replace("-", ""),
                "name": page.title,
                "status": status,
                "active": _active(status),
                "project_ids": [
                    one.replace("-", "") for one in _relation(page, *GOAL_COLUMNS["projects"])
                ],
            }
        self._goals_at = time.time()
        return self._goals

    def goals(self) -> dict[str, Any]:
        """Every goal, and how far its tickets have gone.

        How far is counted, not read: Notion's rollup is not a column `store`
        reads, and a board of Markdown files has none. The tickets the board
        lists already say it — their column, and the goal they point at — so
        a goal's progress is the same data the dashboard draws, column by
        column, on either board.
        """
        pages = self._goal_pages()
        # Read here, so the cards that follow name a goal created a minute ago.
        self._remember_goals(pages)
        projects = self.projects()
        counts: dict[str, dict[str, int]] = {}
        serving: dict[str, list[dict[str, str]]] = {}
        for ticket in self._goal_tickets():
            if ticket.get("goal_id"):
                column = counts.setdefault(ticket["goal_id"], {})
                column[ticket["column"]] = column.get(ticket["column"], 0) + 1
                serving.setdefault(ticket["goal_id"], []).append(
                    {
                        "id": ticket["id"].replace("-", ""),
                        "short": ticket.get("short", ""),
                        "title": ticket.get("title", ""),
                        "column": ticket["column"],
                    }
                )
        rows = []
        for page in pages:
            if not page.title:
                continue
            bare = page.id.replace("-", "")
            linked = _relation(page, *GOAL_COLUMNS["projects"])
            # A score whatever the column holds: a select still says "High".
            ranked = _first(page, *GOAL_COLUMNS["priority"])
            rows.append(
                {
                    "id": bare,
                    "name": page.title,
                    "url": page.url,
                    "description": _first(page, *GOAL_COLUMNS["description"]),
                    "criterion": _first(page, *GOAL_COLUMNS["criterion"]),
                    "due": _first(page, *GOAL_COLUMNS["due"]),
                    "status": _first(page, *GOAL_COLUMNS["status"]),
                    "active": _active(_first(page, *GOAL_COLUMNS["status"])),
                    "priority": priority_module.score(ranked) if ranked else None,
                    "projects": [projects[one]["name"] for one in linked if one in projects],
                    "project_ids": [one.replace("-", "") for one in linked if one in projects],
                    "tickets": counts.get(bare, {}),
                    "linked": serving.get(bare, []),
                }
            )
        return {
            "goals": rows,
            "statuses": self._goal_statuses(),
            "configured": bool(self.runner.workspace.goals),
            # Which board: "Notion's trash" and its link are Notion's, and a
            # Markdown board has files under goals/.
            "storage": self.config.storage.mode,
        }

    def _goal_statuses(self) -> list[str]:
        """The options of the goals' status column, as the database spells them.

        Offered by the form rather than a word list of its own: a status column
        refuses a name it does not offer, and a select makes a second option of
        one spelled otherwise.
        """
        database = self.runner.workspace.goals
        if not database:
            return []
        try:
            return self.runner.client.options(
                database, self._goal_column(database, *GOAL_COLUMNS["status"])
            )
        except store.StoreError:
            return []

    def _goal_tickets(self) -> list[dict[str, str]]:
        """Every ticket as a goal counts it: its column, and the goal it points at.

        Read off the pages the console already holds (`Reader.pages`), with its
        own moves still on their way, as the cards wear them: the whole of
        `board` — the journal, the systemd calls of `_hold` — only to count
        columns, at every opening of the list and after every write, was most
        of what a goal cost. A console that has not read the board yet reads it
        once, as `board` would.
        """
        settings = self.config.notion
        pages = self.reader.pages() or self.reader.read(
            self.runner.client, self.runner.database, settings.prop("status")
        )
        names = _columns(settings)
        writes = self.outbox.marks()
        tickets = []
        for page in pages:
            bare = page.id.replace("-", "")
            status = str(store.read(page, settings.prop("status")) or "")
            write = writes.get(bare)
            if write is not None and write.state == "pending":
                status = write.status
            tickets.append(
                {
                    "id": bare,
                    "short": short_id(page.id),
                    "title": page.title,
                    "column": names.get(status, "draft"),
                    "goal_id": goals_module.pointed(page, settings.prop("goal")).replace("-", ""),
                }
            )
        return tickets

    def create_goal(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        """A new row in the Goals database, written with the rest of its form."""
        name = str(name).strip()
        if not name:
            raise ValueError("a goal needs a name")
        database = self.runner.workspace.goals
        if not database:
            raise ValueError("this workspace has no goals database")
        page_id = self.runner.client.create_row(database, name)
        try:
            saved = self.save_goal(page_id, {**values, "name": name})
        except (store.StoreError, ValueError, LookupError):
            # The row is made before its columns: one whose columns were
            # refused would stay, and the form sent again would make a second.
            with contextlib.suppress(store.StoreError):
                self.runner.client.trash(page_id)
            raise
        return {**saved, "name": name}

    def save_goal(self, page_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Change one row of the Goals database, and the tickets it serves.

        Nothing but the columns a goal is written in: `Avancement`, `Faits` and
        `Total` are Notion's rollups of the tickets, and they recompute on their
        own once the tickets point here — which is why `tickets` writes the
        ticket's side of the relation, the one a Markdown board has too.
        """
        database = self.runner.workspace.goals
        if not database:
            raise ValueError("this workspace has no goals database")
        written: dict[str, Any] = {}
        columns = GOAL_COLUMNS
        for key in ("description", "criterion", "due", "status"):
            if key in values:
                written[self._goal_column(database, *columns[key])] = str(values[key] or "")
        # The form sends every field back: an empty priority is one nobody
        # gave, not the 50 `given` would make of it.
        if str(values.get("priority") or "").strip():
            name = self._goal_column(database, *columns["priority"])
            kind = self.runner.client.schema(database).get(name)
            written[name] = priority_module.cell(priority_module.given(values["priority"]), kind)
        if "projects" in values:
            written[self._goal_column(database, *columns["projects"])] = [
                str(one) for one in values["projects"] or [] if one
            ]
        if "name" in values:
            name = str(values["name"] or "").strip()
            if not name:
                raise ValueError("a goal needs a name")
            written[self.runner.client.title_property(database)] = name
        if not written and "tickets" not in values:
            raise ValueError("nothing to change")
        wanted = page_id.replace("-", "")
        if written:
            self.runner.client.update(database, page_id, written)
        served: dict[str, list[Any]] = {"written": [], "failed": []}
        if "tickets" in values:
            served = self._serve_goal(
                wanted, [str(one).replace("-", "") for one in values["tickets"] or []]
            )
        # The cards name their goal: read the board again, under its new name.
        self._goals_at = 0.0
        self.watch.nudge()
        self.hub.publish("goals", saved=wanted)
        return {"id": wanted, **served}

    def _goal_column(self, database: str, *names: str) -> str:
        """The column of the goals database a field is written to, as it is spelled there."""
        try:
            schema = self.runner.client.schema(database)
        except store.StoreError:
            return names[0]
        lookup = {key.lower(): key for key in schema}
        for name in names:
            if name.lower() in lookup:
                return lookup[name.lower()]
        return names[0]

    def _serve_goal(self, goal_id: str, tickets: list[str]) -> dict[str, list[Any]]:
        """Make exactly these tickets the ones that point at the goal: what was written, what failed.

        A ticket that pointed elsewhere is moved, and one that is no longer
        listed is released only if it still points here — a ticket pointed at
        another goal meanwhile is not this goal's to untie.

        One write per ticket, and nothing else: the column and the goal are
        checked once for the lot, and a page is not read back — the console
        holds it already, and is told the relation it now has. Forty tickets
        were once more than eighty requests in a row, any of which could end
        the lot halfway with nobody told; a ticket Notion refuses now is set
        down beside the others, and the rest are still written.
        """
        # A goal made a moment ago is not in the index yet: read it again.
        self._goals_at = 0.0
        column = self._goal_relation(goal_id)
        client = self.runner.client
        # The goal as a page read back would name it: the index's own id, which
        # is how a card finds its goal there (`Tickets._ticket`).
        named = next(
            (one for one in self._goal_index() if one.replace("-", "") == goal_id), goal_id
        )
        wanted = set(tickets)
        pointing = {ticket["id"]: ticket["goal_id"] for ticket in self._goal_tickets()}
        held = {page.id.replace("-", ""): page for page in self.reader.pages()}
        changes = [
            (ticket, goal_id) for ticket in sorted(wanted) if pointing.get(ticket) != goal_id
        ]
        changes += [
            (ticket, "")
            for ticket, pointed in sorted(pointing.items())
            if pointed == goal_id and ticket not in wanted
        ]
        written: list[str] = []
        failed: list[dict[str, str]] = []
        for ticket, target in changes:
            try:
                client.update(self.runner.database, ticket, {column: [target] if target else []})
            except store.StoreError as error:
                logger.warning("goal %s: ticket %s not written: %s", goal_id, ticket, error)
                failed.append({"id": ticket, "error": str(error)})
                continue
            written.append(ticket)
            page = held.get(ticket)
            if page is not None:
                self.reader.hold(_pointing(page, column, named if target else ""))
        return {"written": written, "failed": failed}

    def _goal_relation(self, goal_id: str) -> str:
        """The tickets' column that points at a goal, once this one is known to exist."""
        column = self.config.notion.prop("goal")
        if column not in self.runner.client.schema(self.runner.database):
            raise ValueError(f"this board has no “{column}” column to point a ticket at a goal")
        if goal_id and goal_id.replace("-", "") not in {
            one.replace("-", "") for one in self._goal_index()
        }:
            raise LookupError(f"no goal with id {goal_id}")
        return column

    def set_ticket_goal(self, ticket_id: str, goal_id: str) -> dict[str, Any]:
        """Point a ticket at a goal, or at none when `goal_id` is empty."""
        column = self._goal_relation(goal_id)
        client = self.runner.client
        client.update(self.runner.database, ticket_id, {column: [goal_id] if goal_id else []})
        self.reader.hold(client.page(ticket_id))
        self.watch.nudge()
        self.hub.publish("goals", saved=goal_id.replace("-", ""))
        return {"id": ticket_id.replace("-", ""), "goal_id": goal_id.replace("-", "")}

    def delete_goal(self, page_id: str) -> dict[str, Any]:
        """Take a goal off the board: into Notion's trash, where it can be brought back.

        The tickets that served it keep a relation to a page that no longer
        answers a query, and read as serving none.
        """
        wanted = page_id.replace("-", "")
        row = next((item for item in self.goals()["goals"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no goal with id {wanted}")
        self.runner.client.trash(page_id)
        self._goals_at = 0.0
        self.watch.nudge()
        self.hub.publish("goals", deleted=wanted)
        return {"id": wanted, "name": row["name"]}
