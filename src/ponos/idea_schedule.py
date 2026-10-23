"""Finding ideas without being asked: when, for which projects, and what a pass remembers.

`ideas.py` knows what an idea is; this is the other half of the same wish —
that they turn up on their own. It holds nothing that touches the network, for
the reason `schedules.py` does not: when a pass falls due, which projects it
covers and which it steps over are the things worth testing, and they are only
testable alone. Running the sessions is `web/planned.py`'s.

**One engine for "when".** A recurrence and a pass of ideas are the same
question — when does this fall next, strictly after now — so the answer comes
from `schedules.py` and not from a second calendar: the daily and the weekly
cadence are the recurrences' own, and the two shapes they do not have (every
N hours, a cron line) were added there, where a recurrence may use them too.

**Anacron, as recurrences are.** The next moment is written down before the
pass is done, and it is computed *from now* — a console that was off for three
days finds one pass due, not eighteen, and a second console reading the same
file finds the moment already moved. The timing keys that were in force when it
was written travel with it (`signature`): edit the frequency and the old moment
is no longer anyone's, it is drawn again from the new rule instead of firing
once more on the strength of the old one.

**Who is in.** A project says yes or no for itself (`project_settings`, kept in
`ponos.db` with the project's other decisions) and what it says wins; one that
says nothing follows the file — every project when the scope is "all", the
ones listed when it is "selected". The workspace's ideas, the ones with no
project, are a switch of their own: "all projects" has never meant the
workspace.

**What a pass remembers.** One row each, with when, how many ideas it found,
what it cost and which projects it stepped over: the Ideas page's "last pass",
and the reason a project got nothing, which otherwise would only be in a log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from . import db, schedules
from .config import Runner

# The cadence the "every four hours" preset is: not a cadence of its own.
FOUR_HOURS = 4


@dataclass(frozen=True)
class Plan:
    """What `config.toml` says about finding ideas, read once."""

    schedule: str
    at: str
    day: str
    hours: int
    cron: str
    scope: str
    projects: tuple[str, ...]
    workspace: bool
    per_batch: int
    skip_above: int
    budget_usd: float
    notify: bool

    @property
    def on(self) -> bool:
        return self.schedule != "off"


def plan(runner: Runner) -> Plan:
    return Plan(
        schedule=runner.ideas_schedule,
        at=runner.ideas_at,
        day=runner.ideas_day,
        hours=runner.ideas_every_hours,
        cron=runner.ideas_cron,
        scope=runner.ideas_scope,
        projects=tuple(
            name.strip().casefold() for name in runner.ideas_projects.split(",") if name.strip()
        ),
        workspace=runner.ideas_workspace,
        per_batch=runner.ideas_per_batch,
        skip_above=runner.ideas_skip_above,
        budget_usd=runner.ideas_budget_usd,
        notify=runner.ideas_notify,
    )


def signature(wanted: Plan) -> str:
    """The keys that say *when*, as one string: the moment stored is only good while it is the same."""
    return json.dumps(
        [wanted.schedule, wanted.at, wanted.day, wanted.hours, wanted.cron], ensure_ascii=False
    )


def next_after(wanted: Plan, after: datetime) -> datetime | None:
    """The first moment a pass falls on strictly after `after`; None when off, or unreadable."""
    kind = wanted.schedule
    if kind == "every_4h":
        return schedules.every(FOUR_HOURS, after=after)
    if kind == "hours":
        return schedules.every(wanted.hours, after=after)
    if kind == "daily":
        return schedules.next_occurrence("Daily", wanted.at, after=after)
    if kind == "weekly":
        return schedules.next_occurrence("Weekly", wanted.at, wanted.day, after=after)
    if kind == "cron":
        return schedules.cron(wanted.cron, after=after)
    return None


def problem(wanted: Plan) -> str:
    """Why the schedule cannot fire, in the words `doctor` prints; empty when it can or is off."""
    if not wanted.on:
        return ""
    if wanted.schedule == "cron":
        return schedules.cron_problem(wanted.cron)
    if next_after(wanted, datetime.now().astimezone()) is None:
        return f"“{wanted.at}” is not an hour — write it as 09:00"
    return ""


def upcoming(wanted: Plan, first: datetime, until: datetime, limit: int = 500) -> list[datetime]:
    """The passes from `first` (included) up to `until`, the way the calendar draws them."""
    found: list[datetime] = []
    current: datetime | None = first
    while current is not None and current <= until and len(found) < limit:
        found.append(current)
        current = next_after(wanted, current)
    return found


def covers(wanted: Plan, project: str, name: str, own: bool | None) -> bool:
    """Is a project part of a pass: its own word first, the file's otherwise."""
    if own is not None:
        return own
    if wanted.scope == "all":
        return True
    return (
        project.strip().casefold() in wanted.projects or name.strip().casefold() in wanted.projects
    )


# -- what is remembered -------------------------------------------------------


def due() -> tuple[str, datetime] | None:
    """The moment stored for the next pass, and the keys it was drawn from."""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute("SELECT signature, next_at FROM idea_plan").fetchone()
    except db.ERRORS:
        return None
    if not row:
        return None
    try:
        return str(row[0]), datetime.fromisoformat(row[1])
    except ValueError:
        return None


def plan_next(wanted: Plan, moment: datetime | None) -> None:
    """Write the next moment down, or forget it (None) when there is none."""
    with db.transaction() as connection:
        connection.execute("DELETE FROM idea_plan")
        if moment is not None:
            connection.execute(
                "INSERT INTO idea_plan (signature, next_at) VALUES (?, ?)",
                (signature(wanted), moment.isoformat(timespec="minutes")),
            )


@dataclass(frozen=True)
class Pass:
    """One pass, as the Ideas page reports it."""

    at: str
    found: int
    cost_usd: float
    projects: int
    skipped: dict[str, str]
    error: str = ""


def record(
    at: datetime,
    found: int,
    cost_usd: float,
    projects: int,
    skipped: dict[str, str],
    error: str = "",
) -> None:
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO idea_passes (at, found, cost_usd, projects, skipped, error)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                at.isoformat(timespec="minutes"),
                found,
                cost_usd,
                projects,
                json.dumps(skipped, ensure_ascii=False),
                error,
            ),
        )


def last() -> Pass | None:
    """The latest pass, or None before there has been one."""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT at, found, cost_usd, projects, skipped, error FROM idea_passes"
                " ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except db.ERRORS:
        return None
    if not row:
        return None
    try:
        skipped = json.loads(row[4] or "{}")
    except ValueError:
        skipped = {}
    return Pass(
        at=row[0],
        found=int(row[1]),
        cost_usd=float(row[2]),
        projects=int(row[3]),
        skipped=skipped if isinstance(skipped, dict) else {},
        error=row[5],
    )
