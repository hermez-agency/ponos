"""What comes back on its own: the schedules, as something you can change.

A schedule is a row of the Schedules database and the brief under it, and a
ticket is born of it at each occurrence — by the runner's pass, or by the
button that launches one now. The console writes only what a schedule is
written in, never what a pass writes back (`Next`, `Last`): one you could edit
is an occurrence you could make happen twice.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from .. import kinds as kinds_module
from .. import priority as priority_module
from .. import schedules as schedules_module
from .. import state, store, subtypes
from . import lineage
from .base import Base

logger = logging.getLogger(__name__)

# One read of the Schedules database at a time: ten pages opened together, and
# the read `serve` starts, all wait for the same one. See `Schedules.schedules`.
_READING = threading.Lock()
_BEHIND = threading.Lock()

# The rows as last read, whether the workspace has the database, and what the
# form offers for the type and the sub-type — and when that was read.
Held = tuple[float, list[schedules_module.Schedule], bool, dict[str, list[dict[str, str]]]]


class Schedules(Base):
    def save_schedule(self, page_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Change one row of the Schedules database from the console.

        Only the columns a schedule is *written* in — the cadence, the hour,
        the day, the tick, and the six a ticket inherits. Never `Next`
        or `Last`: those are what a pass writes back, and a console that let you
        edit them would let you make an occurrence happen twice.
        """
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        settings = self.config.board
        writable = {
            "cadence": settings.prop("cadence"),
            "at": settings.prop("at"),
            "day": settings.prop("day"),
            "active": settings.prop("active"),
            "model": settings.prop("model"),
            "priority": settings.prop("priority"),
        }
        written: dict[str, Any] = {}
        for key, name in writable.items():
            if key not in values:
                continue
            value = values[key]
            if key == "active":
                written[name] = bool(value)
            elif key == "priority":
                # A score, refused outside 0–100; empty is the middle one.
                written[name] = priority_module.cell(
                    priority_module.given(value), self._schedule_column(name)
                )
            else:
                written[name] = str(value or "")
        # A type and a sub-type said by their keys, as a new ticket's are, and
        # written as the board spells them: the ticket is born with that word.
        if "type" in values:
            kind = str(values["type"] or "").strip()
            if kind and kind not in kinds_module.KINDS:
                raise ValueError(f"unknown type “{kind}”")
            written[settings.prop("type")] = self.runner.kind_name(kind) if kind else ""
        if "subtype" in values:
            subtype = str(values["subtype"] or "").strip()
            if subtype and subtype not in subtypes.KEYS:
                raise ValueError(f"unknown sub-type “{subtype}”")
            written[settings.prop("subtype")] = subtypes.option(subtype) if subtype else ""
        if "project" in values:
            written[settings.prop("project")] = [values["project"]] if values["project"] else []
        # The goal its tickets serve, by its page: empty lets it go.
        if "goal" in values:
            written[settings.prop("goal")] = [values["goal"]] if values["goal"] else []
        if "name" in values and str(values["name"]).strip():
            written[self.runner.client.title_property(database)] = str(values["name"]).strip()
        if not written and "body" not in values:
            raise ValueError("nothing to change")
        if written:
            self.runner.client.update(database, page_id, written)
        # Replacing, not appending: the body is the brief every occurrence is
        # born with, a value like a project's. See `save_project`.
        if "body" in values:
            self.runner.client.replace_markdown(page_id, str(values["body"]))
        if values.get("active"):
            state.reviewed(page_id)
        self._drop_schedules()
        self.hub.publish("schedules", saved=page_id)
        if "goal" in values:
            # A goal's page lists the schedules that serve it.
            self.hub.publish("goals", saved=values["goal"] or "")
        return {"id": page_id.replace("-", "")}

    def create_schedule(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        """A new row in the Schedules database, left unticked.

        Unticked deliberately, whatever the form said: a schedule that starts
        producing tickets the second it is typed is a schedule nobody dares
        write. You look at it, then you turn it on.
        """
        name = str(name).strip()
        if not name:
            raise ValueError("a schedule needs a name")
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        page_id = self.runner.client.create_row(
            database, name, {self.config.board.prop("active"): False}
        )
        self.save_schedule(page_id, {**values, "active": False})
        return {"id": page_id.replace("-", ""), "name": name}

    def delete_schedule(self, page_id: str) -> dict[str, Any]:
        """Take a schedule off the board: into its trash, where it can be brought back.

        Trashed rather than destroyed, as a project is: the row leaves every
        query, so the pass stops reading it and nothing more is born from it,
        and a mistake is one move away from undone. The tickets it already made
        are rows of another database and are not touched.
        """
        wanted = page_id.replace("-", "")
        row = self._schedule_row(wanted)
        self.runner.client.trash(page_id)
        state.reviewed(wanted)
        self._drop_schedules()
        self.hub.publish("schedules", deleted=wanted)
        return {"id": wanted, "name": row["name"]}

    def launch_schedule(self, page_id: str) -> dict[str, Any]:
        """Run one schedule now, once however many times the button is pressed.

        A second request for a schedule already being launched is refused rather
        than queued: it is the double click, and it must not make a second ticket.
        """
        wanted = page_id.replace("-", "")
        with self._launch_guard:
            if wanted in self._launching:
                raise RuntimeError("this schedule is already being launched")
            self._launching.add(wanted)
        try:
            entry = self.runner.launch(wanted)
        except store.StoreError:
            self.forget()
            raise
        finally:
            with self._launch_guard:
                self._launching.discard(wanted)
            # `Last` and the ticket it made were written back, or may have been.
            self._drop_schedules()
        self.hub.publish("schedules", launched=wanted)
        return {"ticket": entry["id"], "title": entry["ticket"]}

    def schedules(self) -> dict[str, Any]:
        """What comes back on its own, as `ponos schedules` says it.

        Read when the page is opened rather than watched like the board: a
        schedule moves four times a day at the very most, and a console polling
        that database would be asking the board a question whose answer has not
        changed since breakfast.

        And answered from the rows the console holds, never from the board when it
        holds some: the first opening of the page was measured at nineteen
        seconds — the workspace resolved again, the database and its schema
        read behind the board's 1 800 tickets — and every later one at 350 ms,
        for two rows. Older than the watcher's period, they are read again
        behind the answer, and the page is told on the stream (`schedules`,
        `read`) when that changed something; a write from the console lets go
        of them, so the list it reads next says what was just written. `serve`
        reads them once at start (`hold_schedules`), so the first opening has
        them too.

        Two facts travel with the rows, because a list of schedules that all
        look fine explains nothing on an installation where none of them fire:
        whether the workspace has the database at all, and whether
        `runner.schedule` is on.
        """
        _, rows, database, choices = self._held_schedules()
        # The names the board has already read, and no more: a projects cache
        # gone cold is a query the rows do not have to wait for. A row whose
        # project is not in it still carries the page it points at, and the
        # console writes the name in once its list of projects arrives.
        projects = self._projects
        return {
            "enabled": self.config.runner.schedule,
            # The zone the hours are said in, for the calendar to lay them out in.
            "timezone": schedules_module.timezone_name(),
            "database": database,
            "schedules": [self._schedule(row, projects) for row in rows],
            # The passes that find ideas, drawn on the same calendar and not
            # editable from it: they are set on the Ideas page.
            "ideas_pass": self.planned.calendar(),
            # What the form offers for the type and the sub-type, only where the
            # Schedules database has the column: a value for a missing one would
            # be dropped on its way in. `ponos init` adds them.
            "choices": choices,
        }

    def hold_schedules(self) -> None:
        """Read the schedules behind `serve`'s start, so the first opening of their page waits on nothing."""
        self._schedules_behind()

    def _held_schedules(self) -> Held:
        """The schedules as last read: read there and then only when none are held."""
        held: Held | None = getattr(self, "_schedules_held", None)
        if held is None:
            # Whatever another request read while this one waited will do.
            return self._read_schedules(0.0)
        if time.monotonic() - held[0] >= self.config.web.poll_seconds:
            self._schedules_behind()
        return held

    def _read_schedules(self, wanted: float) -> Held:
        """The Schedules database read — or the read another request finished
        since `wanted`, which it waited for rather than asking the board twice."""
        with _READING:
            held: Held | None = getattr(self, "_schedules_held", None)
            if held is not None and held[0] >= wanted:
                return held
            started = time.monotonic()
            try:
                rows = self.runner.schedules()
                database = bool(self.runner.workspace.schedules)
            except store.StoreError:
                self.forget()
                raise
            fresh: Held = (started, rows, database, self._schedule_choices())
            self._schedules_held = fresh
            return fresh

    def _drop_schedules(self) -> None:
        """Read the schedules again, there and then, next time: one was just written."""
        self._schedules_held = None

    def _schedules_behind(self) -> None:
        """The schedules read again in a thread of its own, one at a time, and
        `schedules` said on the stream when that changed something."""
        with _BEHIND:
            if getattr(self, "_schedules_reading", False):
                return
            self._schedules_reading = True

        def run() -> None:
            try:
                before: Held | None = getattr(self, "_schedules_held", None)
                after = self._read_schedules(time.monotonic())
            except store.StoreError as error:
                # What is held stays, and the next answer tries again.
                logger.warning("schedules: the read behind the answer failed: %s", error)
                return
            except Exception:
                logger.exception("schedules: the read behind the answer failed")
                return
            finally:
                self._schedules_reading = False
            if before is None or _said(before) != _said(after):
                self.hub.publish("schedules", read=True)

        threading.Thread(target=run, name="ponos-schedules", daemon=True).start()

    def _schedule_row(self, wanted: str) -> dict[str, Any]:
        """One schedule as the list says it, read again when the rows held do not have it."""
        for fresh in (False, True):
            if fresh:
                self._drop_schedules()
            row: dict[str, Any] | None = next(
                (item for item in self.schedules()["schedules"] if item["id"] == wanted), None
            )
            if row is not None:
                return row
        raise LookupError(f"no schedule with id {wanted}")

    def _schedule_column(self, name: str) -> str | None:
        """The kind of one column of the Schedules database, None when it has none."""
        database = self.runner.workspace.schedules
        try:
            return self.runner.client.schema(database).get(name) if database else None
        except store.StoreError:
            return None

    def _schedule_choices(self) -> dict[str, list[dict[str, str]]]:
        database = self.runner.workspace.schedules
        try:
            schema = self.runner.client.schema(database) if database else {}
        except store.StoreError:
            return {}
        settings = self.config.board
        choices: dict[str, list[dict[str, str]]] = {}
        if settings.prop("type") in schema:
            choices["type"] = [
                {"value": key, "label": self.runner.kind_name(key)} for key in kinds_module.KINDS
            ]
        if settings.prop("subtype") in schema:
            choices["subtype"] = [
                {"value": subtype.key, "label": subtype.label} for subtype in subtypes.SUBTYPES
            ]
        return choices

    def schedule(self, page_id: str) -> dict[str, Any]:
        """One schedule, as the list says it, plus what is written on its page.

        The body is what the list leaves out, and it is the part that matters:
        it is copied under every ticket the schedule makes. Read here, once,
        rather than with every row — a list of twenty schedules would otherwise
        be twenty pages read to draw a table that shows none of them.
        """
        row = self._schedule_row(page_id.replace("-", ""))
        return {**row, "body": self.runner.client.blocks_text(page_id)}

    def schedule_activity(self, page_id: str) -> dict[str, Any]:
        """What one schedule made: its tickets, its passes, and their figures.

        Read when its page is opened, as the schedule itself is: the board is
        the console's own, and the passes are this machine's. See `lineage`.
        """
        wanted = page_id.replace("-", "")
        row = self._schedule_row(wanted)
        return lineage.of(
            row,
            # The board the watcher last drew, as the ideas take theirs: the
            # panel opened is not worth a read of every ticket.
            self.board(max_age=self.config.web.poll_seconds)["tickets"],
            state.history(1_000_000),
            state.occurrences(wanted),
        )

    def _goal_of(self, schedule: schedules_module.Schedule) -> dict[str, Any]:
        """The goal a schedule points at as the goals' index holds it; none for a goal that is gone."""
        if not schedule.goal:
            return {}
        wanted = schedule.goal.replace("-", "")
        return next((goal for goal in self._goal_index().values() if goal["id"] == wanted), {})

    def _schedule(
        self, schedule: schedules_module.Schedule, projects: dict[str, Any]
    ) -> dict[str, Any]:
        """One row of the Schedules database, as the pane reads it.

        Left in the order the board hands them over — that order is somebody's, and
        a console that sorted it would be rearranging their page for them.
        """
        next_at = schedules_module.upcoming(schedule, datetime.now().astimezone())
        review = state.schedules_to_review()
        goal = self._goal_of(schedule)
        return {
            "id": schedule.page.id.replace("-", ""),
            "name": schedule.name,
            "url": schedule.page.url,
            "cadence": schedule.cadence,
            "at": schedule.at,
            "day": schedule.day,
            "active": schedule.active,
            # When the next ticket is born, not where the pass left its
            # bookmark: a schedule turned off has none, and one that is due has
            # it now. See `schedules.upcoming`.
            "next": next_at.isoformat(timespec="minutes") if next_at else "",
            "last": schedule.last.isoformat(timespec="minutes") if schedule.last else "",
            # The ticket the last occurrence made, addressed the way the board
            # addresses one: the console links to its page, not to the board's.
            "ticket": schedule.last_ticket.replace("-", ""),
            "project": (projects.get(schedule.project) or {}).get("name", ""),
            "project_id": schedule.project.replace("-", ""),
            "model": schedule.model,
            "priority": schedule.priority,
            # By their keys, as the form sends them back: `code`, `bug`.
            "type": self.config.board.kind_of(schedule.kind),
            "subtype": subtypes.of(schedule.subtype),
            "problem": schedule.problem,
            "goal": goal.get("name", ""),
            "goal_id": schedule.goal.replace("-", ""),
            # The goal it points at is deleted or over: its tickets are born
            # without one, and the page says so.
            "goal_lost": bool(schedule.goal) and not goal.get("active", False),
            # Written by an MCP client and never turned on: a person reads it first.
            "review": schedule.page.id.replace("-", "") in review,
        }


def _said(held: Held) -> tuple[Any, ...]:
    """What of a read the page draws: two reads that say the same are not news."""
    _, rows, database, choices = held
    return ([row.page.raw for row in rows], database, choices)
