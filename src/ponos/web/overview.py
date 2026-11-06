"""What the header and the statistics page say: the machine's state, and the figures.

Read off this machine — the daemon and its places, the history in `ponos.db`, the
version installed — and never off the board, except where a figure is about
its tickets. The header is drawn again at every reconnection, so nothing here
asks a remote anything: an update waiting is read from the stamp a run wrote.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import Any

from .. import config as config_module
from .. import credits, journal, session, spending, state, systemd
from .. import update as update_module
from . import live, statistics
from .base import Base


class Overview(Base):
    def state(self, local: bool = True) -> dict[str, Any]:
        """Everything the header shows: the daemon, its places, the version, the spend.

        `local`: whether the page asking is on this machine, which is where an
        update can be started from — see `upgrade.Upgrade.offer`.
        """
        configuration = self.config
        holder = state.scheduler()
        places = state.places() if holder else {}
        if places and places.get("pid") != holder.get("pid"):
            places = {}
        handled, spend = state.totals()
        # A timer that is on and a board that does not move is the one state
        # somebody would open a terminal for. `credits` is 0 the rest of the
        # time, which is how the header knows to say nothing.
        # The reserve counts as being out of credit here, and deliberately so:
        # to whoever is looking at the header, "nothing is being started and
        # here is when that changes" is one state, not two.
        waiting = (
            credits.held() or credits.held(what="reserve")
            if configuration.runner.wait_for_credits
            else 0.0
        )
        budget_limit = configuration.budget.daily_usd
        budget_spent = state.spent_today() if budget_limit > 0 else 0.0
        version = update_module.running()
        return {
            # The daemon: running while a scheduler holds the places — in a
            # container or without systemd that is all there is to read; under
            # systemd, why it is not otherwise.
            "daemon": "running"
            if holder
            else "stopped"
            if config_module.in_container() or not shutil.which("systemctl")
            else systemd.read().label,
            "running": bool(places.get("busy")) or bool(state.sessions()),
            "places": _places(places, configuration),
            # The sessions in flight, read from their logs: what a page that has
            # just been reloaded counts before the stream has said a word.
            "sessions": live.active(held=live.in_flight),
            "credits": waiting,
            "credits_at": credits.when(waiting) if waiting else "",
            # The day's spending limit, once reached: asked of the history
            # rather than of the note a run writes, so that the banner is there
            # the moment the figure crosses the line, not at the next pass.
            "budget": budget_limit if budget_spent >= budget_limit > 0 else 0.0,
            "budget_spent": round(budget_spent, 2),
            "workspace_root": str(configuration.runner.workspace_root),
            # Whether there is a Notion behind this board: the panes read it to
            # know whether a Notion link is worth drawing.
            "notion": not configuration.standalone,
            "interval_seconds": configuration.runner.interval_seconds,
            "model": configuration.runner.model or "default",
            "permission_mode": configuration.runner.permission_mode,
            "claude": bool(session.available()),
            "version": version["version"],
            # What the version's tooltip says: the commit it was made of.
            "commit": {key: version[key] for key in ("commit", "date", "subject")},
            "update": _update_available(),
            "upgrade": self.upgrade.offer(local),
            "spend": round(spend, 2),
            "handled": handled,
            "chat": self.chat.state(),
            "commands": sorted(self.commands.allowed),
            "busy": self.commands.busy,
        }

    def statistics(
        self, start: str = "", end: str = "", project: str | None = None
    ) -> dict[str, Any]:
        """The statistics page: the board, dated with the runner's history.

        See `statistics` for which of the two says when a ticket closed. With a
        `project`, its page's: the same figures over that project's tickets.
        """
        first, last = statistics.period(start, end, datetime.now().date())
        # The board the watching thread last read, rather than a Notion query
        # of its own: changing the period redraws the page, not the board.
        tickets = self.watch.recent(2 * self.watch.interval)["tickets"]
        return statistics.figures(
            tickets,
            state.outcomes(),
            first,
            last,
            project=project,
            kind_of=self.config.notion.kind_of,
        )

    def spending_csv(
        self, start: str = "", end: str = "", month: str = "", project: str | None = None
    ) -> str:
        """Every session of a period, one CSV row each — see `spending`.

        `month` (`2026-10`) is a period of its own; otherwise `start` and `end`
        are the statistics' and default to the same thirty days. `project` is a
        project's id or its name, "" for the tickets of none, None for the whole
        history; an unknown one is refused rather than exported empty, which
        would read as a project that cost nothing.
        """
        if month:
            first, last = spending.month_span(month)
        else:
            first, last = statistics.period(start, end, datetime.now().date())
        name = project
        if project:
            known = self.all_projects()["projects"]
            found = next(
                (
                    item
                    for item in known
                    if project.replace("-", "") == item["id"]
                    or project.casefold() == item["name"].casefold()
                ),
                None,
            )
            if found is None:
                raise LookupError(f"no project {project!r}")
            name = found["name"]
        tickets = self.watch.recent(2 * self.watch.interval)["tickets"]
        after, before = spending.window(first, last)
        return spending.write(
            spending.rows(
                state.lines(after, before),
                first,
                last,
                tickets=tickets,
                project=name,
                models=journal.models(),
            )
        )


def _places(written: dict[str, Any], configuration: config_module.Config) -> dict[str, Any]:
    """What the daemon last wrote of its places, in the shape the header reads.

    Its own figures when it is there; the configured ones, all free, when not.
    """
    width = int(written.get("width") or configuration.runner.max_concurrent)
    return {
        "width": width,
        "per_project": int(
            written.get("per_project") or configuration.runner.max_concurrent_per_project
        ),
        "free": int(written.get("free", width)),
        "busy": [
            {
                "ticket": str(place.get("ticket", "")),
                "title": str(place.get("title", "")),
                "project": str(place.get("project", "")),
                "kind": str(place.get("kind", "")),
                "since": float(place.get("since") or 0),
            }
            for place in written.get("busy") or []
        ],
        "projects": [
            {
                "name": name,
                "busy": int(counted.get("busy", 0)),
                "limit": int(counted.get("limit", 0)),
            }
            for name, counted in sorted((written.get("projects") or {}).items())
        ],
        "queue": [
            {
                "ticket": str(waiting.get("ticket", "")),
                "title": str(waiting.get("title", "")),
                "project": str(waiting.get("project", "")),
                "why": str(waiting.get("why", "")),
                "detail": str(waiting.get("detail", "")),
            }
            for waiting in written.get("queue") or []
        ],
    }


def _update_available() -> str:
    """The commit waiting to be installed, or an empty string for "none".

    Read from the stamp a run already writes — never by asking the remote: the
    console redraws its header on every reconnection, and a `git fetch` behind
    that would be a fetch every time a laptop wakes up.
    """
    status = update_module.waiting()
    return status.latest[:8] if status.stale else ""
