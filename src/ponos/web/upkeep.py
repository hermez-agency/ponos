"""The health of the installation, and the room it takes on this disk.

What the top of the dashboard warns about, the fixes a check offers, and the
daily tidy run on request. Both write — a fix changes the board, a tidy removes
worktrees — so both are made only once they are asked for in so many words: a
fix confirmed, a tidy under the run lock.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from .. import cleanup, health, resources, state
from .. import config as config_module
from .base import Base

# Measuring the state directory walks every file of every worktree — 25 GB of
# them on the day the console started showing it. Once in a while is plenty: it
# grows by the ticket, not by the second.
DISK_TTL = 600


class Upkeep(Base):
    def disk(self, *, fresh: bool = False) -> dict[str, Any]:
        """The room the runner takes on this machine, and what keeps it in check."""
        held = getattr(self, "_disk", None)
        if fresh or held is None or time.time() - held[0] > DISK_TTL:
            worktrees = cleanup.worktree_sizes()
            sizes = cleanup.sizes({"worktrees": sum(size for _, size in worktrees)})
            held = (time.time(), sizes, worktrees)
            self._disk = held
        measured, sizes, worktrees = held
        settings = self.config.runner
        # Read every time, unlike the sizes: it is one call, and a console that
        # says the disk has room when it just filled up is worse than none.
        room = resources.disk_mb(config_module.state_dir())
        free = room[0] if room else None
        return {
            "sizes": sizes,
            "worktrees": [{"name": name, "size": size} for name, size in worktrees[:20]],
            "free_mb": free,
            "disk_mb": room[1] if room else None,
            "min_free_disk_mb": settings.min_free_disk_mb,
            "short": resources.short_of_disk(settings.min_free_disk_mb, config_module.state_dir())
            is not None,
            "stale_worktree_days": settings.stale_worktree_days,
            "total": sum(sizes.values()),
            "measured_at": datetime.fromtimestamp(measured, UTC).isoformat(),
            "tidied_at": (
                datetime.fromtimestamp(cleanup.tidied_at(), UTC).isoformat()
                if cleanup.tidied_at()
                else ""
            ),
            "retention_days": settings.log_retention_days,
            "clean_done_worktrees": settings.clean_done_worktrees,
        }

    def health(self) -> dict[str, Any]:
        """What is wrong with the installation, for the top of the dashboard. See `health.py`."""
        checks = health.run(self.config, self.runner.client)
        return {
            "checks": [check.asdict() for check in checks],
            "problems": health.problems(checks),
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def fix_health(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One fix a check offered, once the page says it was confirmed."""
        if payload.get("confirmed") is not True:
            raise ValueError("a fix is made only once it is confirmed")
        done = health.fix(
            self.config,
            self.runner.client,
            str(payload.get("action") or ""),
            str(payload.get("target") or ""),
            confirmed=True,
        )
        # The board's shape just changed under the cache that reads it.
        self.forget_projects()
        return {"done": done, **self.health()}

    def clean(self) -> dict[str, Any]:
        """The daily tidy, now. Under the run lock, or refused while a run holds
        it — the worktrees a session stands in are the ones it would weigh."""
        try:
            with state.lock():
                tidied = self.runner.tidy(now=True)
        except state.Busy as error:
            raise RuntimeError("a run is in progress — try again once it has finished") from error
        return {
            "removed": len(tidied.removed) if tidied else 0,
            "logs": tidied.logs if tidied else 0,
            "freed": tidied.freed if tidied else 0,
            **self.disk(fresh=True),
        }
