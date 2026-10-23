"""Finding ideas on a schedule, from the console's own process.

`idea_schedule.py` knows when a pass falls due and who is in it; this is what
carries one out. It lives in the console and not in the runner's pass for the
reason `ideas.py` is here: the session that proposes ten ideas is built from
what the console already holds — the project index, the board it keeps warm,
the lock that stops two batches for one scope — and a second way to build the
same prompt would be a second thing to keep in step. The cost is that nothing
is found while the console is not running, which the unit that serves it
(`ponos-web`, or the container's `serve`) makes the ordinary case; `doctor`
says so where the schedule is on and nothing serves.

**A thread that looks once a minute, and fires at most once per moment.** The
moment is written down before the pass is done (`idea_schedule.plan_next`), so
a console restarted in the middle of one does not run it twice, and one that
was off for a week runs one pass when it comes back.

**A project is skipped, never failed.** A pass goes through its scopes one by
one and a scope that cannot be done — too many ideas still unsorted, a board
that does not answer, the budget spent — is said in the journal, remembered on
the pass, and stepped over. The ceiling in dollars is read between two scopes:
a session that has started is not stopped for it, since one stopped halfway is
paid for and gives nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import idea_schedule, ideas, log, project_settings, schedules
from ..config import IDEAS_SCHEDULES

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .api import Api

# How often the thread looks at the clock. A pass is never earlier than the
# minute it was written for, so a finer look would only be a busier thread.
LOOK_SECONDS = 60.0

# How far ahead the calendar is laid out, and the most it is given: an every
# four hours pass is six a day, and the page folds a day's worth into one.
HORIZON_DAYS = 90
MOST_SHOWN = 600

# What the dialog calls each key, against the file's: the table is `runner`,
# and they all begin with `ideas_`.
KEYS = (
    "schedule",
    "at",
    "day",
    "every_hours",
    "cron",
    "scope",
    "workspace",
    "per_batch",
    "skip_above",
    "notify",
)


class Planned:
    def __init__(self, api: Api) -> None:
        self._api = api
        self._lock = threading.Lock()
        self._passing = False

    # -- when -----------------------------------------------------------------

    def watch(self, every: float = LOOK_SECONDS) -> None:
        """Look now, then every `every` seconds, for as long as the console runs."""

        def loop() -> None:
            while True:
                try:
                    self.look()
                except Exception:  # a thread that dies stops finding for good
                    logger.exception("ideas: the scheduled pass failed")
                time.sleep(every)

        threading.Thread(target=loop, name="ponos-idea-pass", daemon=True).start()

    def look(self, now: datetime | None = None) -> idea_schedule.Pass | None:
        """One look at the clock: a pass if one is due, else nothing.

        The first moment of a schedule that has just been written is drawn
        and waited for, never fired: choosing "every day at 9" at ten past nine
        must not set a pass off at once.
        """
        now = now or datetime.now().astimezone()
        wanted = idea_schedule.plan(self._api.config.runner)
        upcoming = (
            idea_schedule.next_after(wanted, now) if not idea_schedule.problem(wanted) else None
        )
        stored = idea_schedule.due()
        if upcoming is None:
            if stored is not None:
                idea_schedule.plan_next(wanted, None)
            return None
        if stored is None or stored[0] != idea_schedule.signature(wanted):
            idea_schedule.plan_next(wanted, upcoming)
            logger.info("ideas: first pass %s", upcoming.strftime("%Y-%m-%d %H:%M"))
            return None
        if stored[1] > now:
            return None
        # Taken before it is done: a crash in the middle loses one pass, where
        # the other order would run it twice and pay for both.
        idea_schedule.plan_next(wanted, upcoming)
        return self.run(wanted, now)

    # -- doing ----------------------------------------------------------------

    def run(self, wanted: idea_schedule.Plan, now: datetime) -> idea_schedule.Pass | None:
        """One pass over the projects that are in it. None when one is already going."""
        with self._lock:
            if self._passing:
                return None
            self._passing = True
        try:
            return self._run(wanted, now)
        finally:
            with self._lock:
                self._passing = False

    def _scopes(self, wanted: idea_schedule.Plan) -> list[tuple[str, str]]:
        """(project id, name) of every scope the pass covers: the workspace, then the projects."""
        scopes: list[tuple[str, str]] = [("", "")] if wanted.workspace else []
        scopes += [(row["id"], row["name"]) for row in self._covered(wanted)]
        return scopes

    def _covered(self, wanted: idea_schedule.Plan) -> list[dict[str, Any]]:
        said = project_settings.every_ideas()
        return [
            row
            for row in self._api.all_projects()["projects"]
            if row["id"]
            and idea_schedule.covers(
                wanted, row["id"], row["name"], said.get(project_settings.key(row["id"]))
            )
        ]

    def _run(self, wanted: idea_schedule.Plan, now: datetime) -> idea_schedule.Pass:
        api = self._api
        found, cost, covered = 0, 0.0, 0
        skipped: dict[str, str] = {}
        by_scope: dict[str, int] = {}
        error = ""
        try:
            scopes = self._scopes(wanted)
        except Exception as failure:  # the board is not answering: nothing to cover
            logger.exception("ideas: the projects could not be read", extra=log.FILE_ONLY)
            scopes, error = [], f"the projects could not be read: {failure}"
        waiting = api.runner.waiting_for_credits()
        if waiting and scopes:
            scopes, error = [], "out of credit"
            logger.info("ideas: pass given up — out of credit")
        for project, name in scopes:
            label = name or "the workspace"
            if wanted.budget_usd and cost >= wanted.budget_usd:
                skipped[label] = f"the budget of ${wanted.budget_usd:.2f} is spent"
                logger.info("ideas: %s skipped — %s", label, skipped[label])
                continue
            unsorted = len(ideas.listed(project))
            if wanted.skip_above and unsorted >= wanted.skip_above:
                skipped[label] = f"{unsorted} new ideas waiting (limit {wanted.skip_above})"
                logger.info("ideas: %s skipped — %s", label, skipped[label])
                continue
            try:
                batch = api.generate_ideas(project, wanted.per_batch)
            except RuntimeError as failure:  # already being found, or out of credit
                skipped[label] = str(failure)
                logger.info("ideas: %s skipped — %s", label, failure)
                if "credit" in str(failure):
                    error = "out of credit"
                    break
                continue
            except Exception as failure:  # one project must not take the others down
                logger.exception("ideas: finding ideas for %s failed", label, extra=log.FILE_ONLY)
                skipped[label] = f"{type(failure).__name__}: {failure}"
                continue
            covered += 1
            cost += float(batch.get("cost_usd") or 0)
            count = len(batch["ideas"])
            found += count
            if count:
                by_scope[label] = count
        done = idea_schedule.Pass(
            at=now.isoformat(timespec="minutes"),
            found=found,
            cost_usd=round(cost, 6),
            projects=covered,
            skipped=skipped,
            error=error,
        )
        idea_schedule.record(now, found, done.cost_usd, covered, skipped, error)
        logger.info(
            "ideas: pass done — %d ideas for %d scope(s), $%.4f, %d skipped",
            found,
            covered,
            cost,
            len(skipped),
        )
        api.hub.publish("ideas", planned=found)
        if wanted.notify and found:
            self._tell(found, by_scope)
        return done

    def _tell(self, found: int, by_scope: dict[str, int]) -> None:
        """“n new ideas” on the channels you are reachable on. Never a reason to fail a pass."""
        lines = [f"{label}: {count}" for label, count in by_scope.items()]
        title = f"Ponos — {found} new idea{'s' if found != 1 else ''}"
        try:
            self._api.runner._announce(title, "\n".join(lines))
        except Exception:
            logger.exception("ideas: the notification was not sent", extra=log.FILE_ONLY)

    # -- saying ---------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """The schedule, the projects in it and the last pass: the dialog and the banner's."""
        api = self._api
        runner = api.config.runner
        wanted = idea_schedule.plan(runner)
        said = project_settings.every_ideas()
        projects = [
            {
                "id": project_settings.key(row["id"]),
                "name": row["name"],
                "enabled": idea_schedule.covers(
                    wanted, row["id"], row["name"], said.get(project_settings.key(row["id"]))
                ),
                "own": said.get(project_settings.key(row["id"])),
            }
            for row in api.all_projects()["projects"]
            if row["id"]
        ]
        last = idea_schedule.last()
        return {
            "settings": {
                "schedule": runner.ideas_schedule,
                "at": runner.ideas_at,
                "day": runner.ideas_day,
                "every_hours": runner.ideas_every_hours,
                "cron": runner.ideas_cron,
                "scope": runner.ideas_scope,
                "workspace": runner.ideas_workspace,
                "per_batch": runner.ideas_per_batch,
                "skip_above": runner.ideas_skip_above,
                "budget_usd": runner.ideas_budget_usd,
                "notify": runner.ideas_notify,
                "model": runner.ideas_model,
            },
            "projects": projects,
            "problem": idea_schedule.problem(wanted),
            "next": self._next(wanted),
            "last": None
            if last is None
            else {
                "at": last.at,
                "found": last.found,
                "cost_usd": last.cost_usd,
                "projects": last.projects,
                "skipped": [{"name": name, "reason": why} for name, why in last.skipped.items()],
                "error": last.error,
            },
            "running": self._passing,
            "timezone": schedules.timezone_name(),
        }

    def _refuse_unreadable(self, payload: dict[str, Any]) -> None:
        """A cron line or an hour that could never fire is refused, rather than saved to be named by `doctor`."""
        current = idea_schedule.plan(self._api.config.runner)
        merged = replace(
            current,
            schedule=str(payload.get("schedule", current.schedule) or "").strip(),
            at=str(payload.get("at", current.at) or "").strip(),
            day=str(payload.get("day", current.day) or "").strip(),
            cron=str(payload.get("cron", current.cron) or "").strip(),
        )
        if merged.on:
            if merged.schedule not in IDEAS_SCHEDULES:
                raise ValueError(f"How often: one of {', '.join(IDEAS_SCHEDULES)}")
            if cause := idea_schedule.problem(merged):
                raise ValueError(cause)

    def _next(self, wanted: idea_schedule.Plan) -> str:
        """When the next pass falls — now, if it is due — or "" when none will."""
        if not wanted.on or idea_schedule.problem(wanted):
            return ""
        now = datetime.now().astimezone()
        stored = idea_schedule.due()
        if stored is not None and stored[0] == idea_schedule.signature(wanted):
            return max(stored[1], now).isoformat(timespec="minutes")
        found = idea_schedule.next_after(wanted, now)
        return found.isoformat(timespec="minutes") if found else ""

    def calendar(self) -> dict[str, Any]:
        """The passes to come, as the recurrences' calendar draws them — read only."""
        wanted = idea_schedule.plan(self._api.config.runner)
        first = self._next(wanted)
        last = idea_schedule.last()
        coming = (
            idea_schedule.upcoming(
                wanted,
                datetime.fromisoformat(first),
                datetime.now().astimezone() + timedelta(days=HORIZON_DAYS),
                MOST_SHOWN,
            )
            if first
            else []
        )
        return {
            "active": wanted.on and not idea_schedule.problem(wanted),
            "next": first,
            "last": last.at if last else "",
            "upcoming": [moment.isoformat(timespec="minutes") for moment in coming],
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write what the dialog sent into `config.toml`, and the projects into their own settings.

        Through `settings.save`, so that every value is checked by the rules the
        loader applies and the file is loaded again before the save stands. The
        projects ticked are the file's when the scope is "selected", and they
        replace what each project said on its own page: the dialog shows every
        project as it stands, so what it sends back is the whole truth.
        """
        api = self._api
        self._refuse_unreadable(payload)
        values: dict[str, object] = {}
        for key in KEYS:
            if key in payload:
                offered = payload[key]
                # The weekdays are spelled with a capital in the file.
                values[f"runner.ideas_{key}"] = (
                    offered.strip().capitalize()
                    if key == "day" and isinstance(offered, str)
                    else offered
                )
        if "model" in payload:
            values["runner.ideas_model"] = payload["model"]
        if "budget_usd" in payload:
            budget = payload["budget_usd"]
            try:
                amount = float(str(budget).strip() or 0)
            except ValueError:
                raise ValueError(f"The budget: “{budget}” is not an amount") from None
            if amount < 0:
                raise ValueError("The budget: 0 or more")
            values["runner.ideas_budget_usd"] = f"{amount:g}" if amount else None
        chosen = payload.get("projects")
        if chosen is not None:
            if not isinstance(chosen, list):
                raise ValueError("The projects: a list")
            values["runner.ideas_projects"] = (
                ", ".join(project_settings.key(str(item)) for item in chosen) or None
            )
        saved = api.save_settings({"settings": values}) if values else {"saved": []}
        scope = api.config.runner.ideas_scope
        if chosen is not None and scope == "selected":
            names = {
                project_settings.key(row["id"]): row["name"]
                for row in api.all_projects()["projects"]
                if row["id"]
            }
            for project in project_settings.every_ideas():
                project_settings.set_ideas(project, names.get(project, ""), None)
        api.hub.publish("ideas", settings=True)
        return {**self.describe(), "saved": saved["saved"]}
