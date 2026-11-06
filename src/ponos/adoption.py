"""Taking back the sessions a runner before this one started.

A session is no longer a child of the runner (see tether.py): restart the
daemon, let it `exec` a new version, or let it crash, and every Claude session
it had started carries on. What it cannot carry on by itself is the ticket —
the commits pushed, the pull request opened, the status written — and that is
what adopting it is: the runner that comes next reads the session's log to its
end, as the one that started it would have, and does the rest of the ticket.

What makes that possible is written down when the session starts, in the
`sessions` table of `ponos.db`: where to follow it (`session.Handle`) and, for
the ticket's own session, the job it is part of, as JSON. JSON rather than a
pickle on purpose: the process reading it back may be a newer version, and a
field that version added is a default, not a crash.

**Only a ticket's own session is carried on.** The others a ticket goes through
— a self-review, a CI repaired, a report asked for — and those that are not a
ticket's at all — a reply, a classification — are seen to their end and let
go: their ticket is then put back where a dead runner's tickets always were,
by `sweep`, and its next attempt starts from the branch it left. They are
minutes long; the session they follow was the hour.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import agents, goals, session, state, store
from .base import Base
from .projects import Project
from .ticket import Job, Ticket

logger = logging.getLogger(__name__)

# What a job holds that is never written down: the secrets are read again from
# the vault, and the rest is what adopting it is about.
_UNWRITTEN = {"secrets", "adopted", "adoptable", "ticket"}
_PATHS = {"workdir", "log", "session_home", "reference"}


def record(job: Job) -> str:
    """The job as JSON, for whoever adopts its session — see `rebuilt`."""
    values: dict[str, Any] = {"ticket": job.ticket.id}
    for item in dataclasses.fields(job):
        if item.name in _UNWRITTEN:
            continue
        value = getattr(job, item.name)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            value = {
                key: str(part) if isinstance(part, Path) else part
                for key, part in dataclasses.asdict(value).items()
            }
        elif isinstance(value, Path):
            value = str(value)
        values[item.name] = value
    return json.dumps(values)


def _made(kind: type[Any], value: object) -> Any:
    """A dataclass out of what `record` wrote of it, unknown keys left out."""
    if not isinstance(value, dict):
        return kind()
    known = {item.name for item in dataclasses.fields(kind)}
    return kind(**{key: part for key, part in value.items() if key in known})


class Adoption(Base):
    """The sessions left by the runner before this one, taken back."""

    def rebuilt(self, written: str) -> Job | None:
        """The job `record` wrote, its ticket read afresh — None when it cannot be."""
        try:
            values = json.loads(written)
            ticket = Ticket(self.client.page(str(values["ticket"])))
        except (ValueError, KeyError, TypeError, store.StoreError):
            return None
        project_values = values.get("project") or {}
        path = project_values.get("path")
        project = _made(Project, {**project_values, "path": Path(path) if path else None})
        known = {item.name for item in dataclasses.fields(Job)}
        rest: dict[str, Any] = {}
        for key, value in values.items():
            if key not in known or key in _UNWRITTEN or key in ("project", "agent", "goal"):
                continue
            if key in _PATHS:
                value = Path(value) if value else None
            rest[key] = value
        if rest.get("workdir") is None:
            return None
        rest["agent"] = _made(agents.Agent, values.get("agent"))
        rest["goal"] = _made(goals.Goal, values.get("goal"))
        try:
            return Job(ticket=ticket, project=project, **rest)
        except TypeError:
            return None

    def orphans(self) -> list[tuple[str, str, str, Callable[[], dict[str, Any] | None]]]:
        """The sessions written down by a runner no longer here, and how to see each to its end.

        Called by whoever holds the scheduler's place, before anything else:
        nobody else can be following them. Each comes back as its ticket and a
        piece of work for the pool — the ticket carried on when its job could be
        rebuilt, the session only seen to its end otherwise — with the project
        its place counts against and its title. A session that
        ended while nobody watched is adopted all the same: its log holds its
        answer, and its code file how it ended.
        """
        found: list[tuple[str, str, str, Callable[[], dict[str, Any] | None]]] = []
        for row in state.sessions():
            try:
                handle = session.Handle.from_json(row["handle"])
            except (KeyError, TypeError, ValueError):
                state.untrack_session(row["session"])
                continue
            ticket_id = row["ticket"]
            job = self.rebuilt(row["job"]) if row["job"] else None
            if job is not None:
                job.adopted = handle
                job.adoptable = True
                self.say(
                    f"  ⇠ {job.ticket.title} — session {handle.session_id} taken back"
                    + ("" if handle.alive() else ", already ended")
                )
                found.append(
                    (
                        ticket_id,
                        job.project.name if job.project.is_code else "",
                        job.ticket.title,
                        functools.partial(self._carry_on, job),
                    )
                )
                continue
            self.say(f"  ⇠ session {handle.session_id} followed to its end, not carried on")
            found.append((ticket_id, "", "", functools.partial(self._see_out, handle)))
        return found

    def _carry_on(self, job: Job) -> dict[str, Any] | None:
        """The ticket of an adopted session, done to its end as its own runner would have."""
        result = self._guarded(job.ticket, self.execute, job)
        return result if isinstance(result, dict) else None

    def _see_out(self, handle: session.Handle) -> dict[str, Any] | None:
        """A session nobody carries on: followed to its end, reaped, and let go."""
        try:
            session.finish(handle)
        except Exception:
            logger.exception("the session %s was not seen to its end", handle.session_id)
        state.untrack_session(handle.session_id)
        return None
