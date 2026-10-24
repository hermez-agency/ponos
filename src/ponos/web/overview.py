"""What the header and the statistics page say: the machine's state, and the figures.

Read off this machine — the lock, the timer, the history in `ponos.db`, the
version installed — and never off the board, except where a figure is about
its tickets. The header is drawn again at every reconnection, so nothing here
asks a remote anything: an update waiting is read from the stamp a run wrote.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import config as config_module
from .. import credits, session, state, systemd
from .. import update as update_module
from . import live, statistics
from .base import Base


class Overview(Base):
    def state(self, local: bool = True) -> dict[str, Any]:
        """Everything the header shows: the timer, the lock, the version, the spend.

        `local`: whether the page asking is on this machine, which is where an
        update can be started from — see `upgrade.Upgrade.offer`.
        """
        configuration = self.config
        held = state.running()
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
            # In a container the timer is the image's `ponos run --every`, which
            # starts with it and stops with it: on for as long as this answers.
            "timer": "enabled" if config_module.in_container() else systemd.read().label,
            "running": bool(held),
            "lock": held,
            # The sessions in flight, read from their logs: what a page that has
            # just been reloaded counts before the stream has said a word.
            "sessions": live.active(held=lambda: held),
            "credits": waiting,
            "credits_at": credits.when(waiting) if waiting else "",
            # The day's spending limit, once reached: asked of the history
            # rather than of the note a run writes, so that the banner is there
            # the moment the figure crosses the line, not at the next pass.
            "budget": budget_limit if budget_spent >= budget_limit > 0 else 0.0,
            "budget_spent": round(budget_spent, 2),
            "workspace_root": str(configuration.runner.workspace_root),
            # Which board this console is looking at. The panes read it to know
            # whether a Notion link is worth drawing, and whether the sync has
            # anything to say — in `markdown` mode neither does.
            "storage": configuration.storage.mode,
            "board_path": str(configuration.storage.path) if configuration.storage.markdown else "",
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
        tickets = self.board()["tickets"]
        return statistics.figures(
            tickets,
            state.history(1_000_000),
            first,
            last,
            project=project,
            kind_of=self.config.notion.kind_of,
        )


def _update_available() -> str:
    """The commit waiting to be installed, or an empty string for "none".

    Read from the stamp a run already writes — never by asking the remote: the
    console redraws its header on every reconnection, and a `git fetch` behind
    that would be a fetch every time a laptop wakes up.
    """
    status = update_module.waiting()
    return status.latest[:8] if status.stale else ""
