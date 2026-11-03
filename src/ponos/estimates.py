"""What a ticket is likely to cost, and how long it is likely to take, before it starts.

The daily limit and the per-ticket budget stop a session once it has spent; a
ticket put in Ready says nothing of whether it will cost thirty cents or ten
dollars. The journal (journal.py) already holds the answer for the tickets
that came before, so the estimate is read off them rather than asked of a
model: it costs nothing, and gives the same answer twice.

**Tickets, not runs.** A ticket stopped on a question and taken again is two
runs and one bill: its runs are added up, and it is filed under its last run's
project, type, sub-type and model.

**The closest tickets there are enough of.** The same project, type, sub-type
and model first — the model only when the ticket names one, since an empty one
is the runner's to choose; then the same project and type; then the type
alone. At each step `LEAST` tickets at least, or the next one is tried: a
median of two is an anecdote.

**Two numbers each: the median and the 80th centile.** The median is what a
ticket usually costs; the centile is what one in five goes past, which is the
part a mean would hide — a handful of long sessions are a third of the bill.

**Nothing rather than a zero.** Too few tickets to compare with, or no type to
compare on, and there is no estimate: the console then says nothing at all.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import journal, models

# How many tickets an estimate stands on, at the least.
LEAST = 5


@dataclass(frozen=True)
class Done:
    """One ticket that ran, as an estimate compares it: its last run's terms, its whole bill."""

    ticket: str
    project: str
    kind: str
    subtype: str
    model: str
    cost: float
    seconds: float


def _seconds(start: object, end: object) -> float:
    try:
        lasted = datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
    except (TypeError, ValueError):
        return 0.0
    return max(lasted.total_seconds(), 0.0)


def tickets(runs: Iterable[dict[str, Any]] | None = None) -> list[Done]:
    """Every ticket that ran and was paid for, from `journal.ended` unless `runs` are given.

    A ticket none of whose runs reported a cost is left out: it would count as
    free, and pull every median down.
    """
    found: dict[str, dict[str, Any]] = {}
    for run in journal.ended() if runs is None else runs:
        ticket = str(run.get("ticket") or "")
        held = found.setdefault(ticket, {"cost": None, "seconds": 0.0})
        held.update(
            project=str(run.get("project") or ""),
            kind=str(run.get("kind") or ""),
            subtype=str(run.get("subtype") or ""),
            model=models.label(str(run.get("model") or "")),
        )
        if isinstance(run.get("cost_usd"), (int, float)):
            held["cost"] = (held["cost"] or 0.0) + float(run["cost_usd"])
        held["seconds"] += _seconds(run.get("started_at"), run.get("ended_at"))
    return [
        Done(ticket=ticket, **held)
        for ticket, held in found.items()
        if ticket and held["cost"] is not None
    ]


def _centile(values: list[float]) -> float:
    """The 80th centile, interpolated between the two values around it."""
    return statistics.quantiles(values, n=5, method="inclusive")[3]


def estimate(
    project: str,
    kind: str,
    subtype: str = "",
    model: str = "",
    *,
    ticket: str = "",
    done: list[Done] | None = None,
) -> dict[str, Any] | None:
    """The estimate for a ticket of this project, type, sub-type and model — None for none.

    `ticket` is left out of what it is compared with: a ticket taken again is
    not its own precedent. `done` is `tickets()`, read once by a caller that
    estimates a whole column.
    """
    if not kind:
        return None
    wanted = models.label(model)
    key = ticket.replace("-", "")
    alike = [one for one in (tickets() if done is None else done) if one.ticket != key]
    levels: list[tuple[str, Callable[[Done], bool]]] = []
    if project:
        levels.append(
            (
                "subtype",
                lambda one: (
                    one.project == project
                    and one.kind == kind
                    and one.subtype == subtype
                    and (not wanted or one.model == wanted)
                ),
            )
        )
        levels.append(("project", lambda one: one.project == project and one.kind == kind))
    levels.append(("type", lambda one: one.kind == kind))
    for basis, matches in levels:
        kept = [one for one in alike if matches(one)]
        if len(kept) < LEAST:
            continue
        costs = [one.cost for one in kept]
        seconds = [one.seconds for one in kept]
        return {
            "cost": round(statistics.median(costs), 2),
            "cost_high": round(_centile(costs), 2),
            "seconds": round(statistics.median(seconds)),
            "seconds_high": round(_centile(seconds)),
            "tickets": len(kept),
            "basis": basis,
        }
    return None
