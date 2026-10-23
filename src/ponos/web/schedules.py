"""What comes back on its own: the schedules, as something you can change.

A schedule is a row of the Schedules database and the brief under it, and a
ticket is born of it at each occurrence — by the runner's pass, or by the
button that launches one now. The console writes only what a schedule is
written in, never what a pass writes back (`Next`, `Last`): one you could edit
is an occurrence you could make happen twice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import kinds as kinds_module
from .. import priority as priority_module
from .. import schedules as schedules_module
from .. import state, store, subtypes
from . import lineage
from .base import Base


class Schedules(Base):
    def save_schedule(self, page_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Change one row of the Schedules database from the console.

        Only the columns a schedule is *written* in — the cadence, the hour,
        the day, the tick, and the five a ticket inherits. Never `Next`
        or `Last`: those are what a pass writes back, and a console that let you
        edit them would let you make an occurrence happen twice.
        """
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        settings = self.config.notion
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
        self.hub.publish("schedules", saved=page_id)
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
            database, name, {self.config.notion.prop("active"): False}
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
        row = next((item for item in self.schedules()["schedules"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no schedule with id {wanted}")
        self.runner.client.trash(page_id)
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
        self.hub.publish("schedules", launched=wanted)
        return {"ticket": entry["id"], "title": entry["ticket"]}

    def schedules(self) -> dict[str, Any]:
        """What comes back on its own, as `ponos schedules` says it.

        Read when the page is opened rather than watched like the board: a
        schedule moves four times a day at the very most, and a console polling
        that database would be asking Notion a question whose answer has not
        changed since breakfast.

        Two facts travel with the rows, because a list of schedules that all
        look fine explains nothing on an installation where none of them fire:
        whether the workspace has the database at all, and whether
        `runner.schedule` is on.
        """
        try:
            rows = self.runner.schedules()
            database = bool(self.runner.workspace.schedules)
        except store.StoreError:
            self.forget()
            raise
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
            "page": self.config.notion.page("schedules"),
            # Which board: "a row in the database" is Notion's sentence, and a
            # Markdown board has files.
            "storage": self.config.storage.mode,
            "schedules": [self._schedule(row, projects) for row in rows],
            # The passes that find ideas, drawn on the same calendar and not
            # editable from it: they are set on the Ideas page.
            "ideas_pass": self.planned.calendar(),
            # What the form offers for the type and the sub-type, only where the
            # Schedules database has the column: a value for a missing one would
            # be dropped on its way in. `ponos init` adds them.
            "choices": self._schedule_choices(),
        }

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
        settings = self.config.notion
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
        wanted = page_id.replace("-", "")
        row = next((item for item in self.schedules()["schedules"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no schedule with id {wanted}")
        return {**row, "body": self.runner.client.blocks_text(page_id)}

    def schedule_activity(self, page_id: str) -> dict[str, Any]:
        """What one schedule made: its tickets, its passes, and their figures.

        Read when its page is opened, as the schedule itself is: the board is
        the console's own, and the passes are this machine's. See `lineage`.
        """
        wanted = page_id.replace("-", "")
        row = next((item for item in self.schedules()["schedules"] if item["id"] == wanted), None)
        if row is None:
            raise LookupError(f"no schedule with id {wanted}")
        return lineage.of(
            row,
            self.board()["tickets"],
            state.history(1_000_000),
            state.occurrences(wanted),
        )

    def _schedule(
        self, schedule: schedules_module.Schedule, projects: dict[str, Any]
    ) -> dict[str, Any]:
        """One row of the Schedules database, as the pane reads it.

        Left in the order Notion hands them over — that order is somebody's, and
        a console that sorted it would be rearranging their page for them.
        """
        next_at = schedules_module.upcoming(schedule, datetime.now().astimezone())
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
            # addresses one: the console links to its page, not to Notion's.
            "ticket": schedule.last_ticket.replace("-", ""),
            "project": (projects.get(schedule.project) or {}).get("name", ""),
            "project_id": schedule.project.replace("-", ""),
            "model": schedule.model,
            "priority": schedule.priority,
            # By their keys, as the form sends them back: `code`, `bug`.
            "type": self.config.notion.kind_of(schedule.kind),
            "subtype": subtypes.of(schedule.subtype),
            "problem": schedule.problem,
        }
