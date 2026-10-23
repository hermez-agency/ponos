"""The journals: the runner's history, the session logs, and the runs of one ticket.

Read off this machine only — `ponos.db`, the logs directory and `ponos.log` —
and never written: what a session did is what it did. A log is always named,
never given as a path, so that nothing outside the logs directory is read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import journal, log, models, state
from . import live
from .base import Base


class Journals(Base):
    def history(self, limit: int = 30) -> dict[str, Any]:
        return {"entries": list(reversed(state.history(limit)))}

    def logs(self, ticket: str = "") -> dict[str, Any]:
        """The newest session logs — of one ticket, when it is named.

        Named by its short id, as the file is: a ticket opened on the console
        finds its last session here, however many others ran since.
        """
        paths = sorted(state.logs_dir().glob("*.jsonl"), reverse=True)
        if ticket:
            paths = [path for path in paths if path.stem.rsplit("-", 1)[-1] == ticket]
        paths = paths[:40]
        return {
            "logs": [
                {
                    "name": path.name,
                    "ticket": path.name.removesuffix(".jsonl").rsplit("-", 1)[-1],
                    "at": path.stat().st_mtime,
                    "size": path.stat().st_size,
                }
                for path in paths
                if path.exists()
            ]
        }

    def log(self, name: str) -> dict[str, Any]:
        """One session, as the steps it was made of. Never as a path from outside."""
        target = state.logs_dir() / Path(name).name
        if not target.exists() or target.suffix != ".jsonl":
            raise LookupError(f"no such log: {name}")
        steps = []
        with target.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                for step in live.steps(line):
                    steps.append({"label": step.label, "detail": step.detail, "said": step.said})
        # The count is of the whole session, the steps only of its end: a card
        # says how far a run has come, and a thousand lines is enough to read.
        return {"name": target.name, "count": len(steps), "steps": steps[-1000:]}

    def service_log(self, lines: int = 500) -> dict[str, Any]:
        """The end of ponos.log — the runner's and the console's own journal, masked.

        What `ponos logs --service` prints, for whoever has no terminal at hand:
        the last lines, never the whole file. See log.py.
        """
        return {"path": str(log.path()), "lines": log.tail(max(1, min(lines, 2000)))}

    def runs(self, page_id: str) -> dict[str, Any]:
        """Every run of one ticket the local journal holds, newest first.

        Read from the database, not from the page: the page keeps what the
        agent said, the journal every step — and every run, where the page
        and the logs only ever knew the last one by name. See journal.py.
        """
        return {
            "runs": [
                {**run, "model_label": models.label(run.get("reported") or run.get("model") or "")}
                for run in journal.runs(page_id)
            ]
        }

    def run_steps(
        self, identifier: int, before: int = 0, after: int = 0, limit: int = journal.PAGE
    ) -> dict[str, Any]:
        """One page of a run's steps: its end, what came before `before`, or after `after`."""
        found = journal.run(identifier)
        if found is None:
            raise LookupError(f"no such run: {identifier}")
        return {
            **journal.steps(identifier, before=before, after=after, limit=limit),
            "ended": bool(found["ended_at"]),
        }
