"""How long Ponos worked on a ticket, with the clock stopped while it waited.

The time since a ticket was made says little: it holds the wait in *Ready*, the
hours a question stood unanswered, and the days a pull request sat in review —
which is the reviewer's time, not the runner's. So the figure is built from the
runs the journal already keeps (journal.py): each has the moment its session
opened and the moment the ticket's outcome was known, and that interval is the
work. Nothing new is written for it, which is also why it survives a restart
and why a ticket from before this module has its time — a ticket with no run
has none, and says so rather than showing a zero.

**A pause is the gap after a run**, and what the run came to names it: a
question left to answer, a ticket blocked or failed, credit to wait for. The
gap after a run that ended in a pull request is review, and is not counted
anywhere. A run the runner never closed — killed mid-session — is cut at its
last step: the time after it is unknown, and a clock that kept running on a
dead session would be the false figure this is here to avoid.

Pure: the spans and the instant are given, so that a test can say what the
clock read at any moment without waiting for it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import blocks

# An unclosed run on a ticket still in progress is live while its last step is
# this recent. Past it the runner is taken to be gone, whatever the column says.
STALE_SECONDS = 30 * 60

# The columns a ticket can sit in while the clock is stopped on a pause. In
# review, done or cancelled it is somebody else's time, or nobody's.
_WAITING = ("blocked", "failed", "ready", "draft", "progress")

PAUSES = ("question", "blocked", "credit")


def _instant(stamp: str | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def pause_of(span: dict) -> str:
    """Why the clock stops after this run: `question`, `blocked`, `credit`, or "" for none."""
    status = span.get("status") or ""
    if status == "waiting":
        return "credit"
    if status in ("blocked", "failed"):
        code = blocks.known(span.get("code"))
        return "question" if code and blocks.CAUSES[code].family == "question" else "blocked"
    return ""


def measure(spans: list[dict], column: str, now: datetime | None = None) -> dict | None:
    """What the clock of a ticket reads, or None when no run was ever made for it.

    `spans` are the ticket's runs as `journal.spans` reads them; `column` is
    where the board draws it now. `work` and `paused` are seconds, as of `now`;
    `running` says the clock is going, `pause` why it is stopped, if it is.
    """
    now = now or datetime.now(UTC)
    runs = []
    for span in spans:
        start = _instant(span.get("start"))
        if start is None:
            continue
        runs.append((start, span))
    if not runs:
        return None
    runs.sort(key=lambda one: one[0])

    work = paused = 0.0
    running = False
    reached: datetime | None = None
    last_span: dict = {}
    for start, span in runs:
        last = _instant(span.get("last")) or start
        closed = _instant(span.get("end"))
        live = (
            closed is None
            and column == "progress"
            and (now - last).total_seconds() < STALE_SECONDS
        )
        end = now if live else max(closed or last, start)
        if reached is not None:
            if start > reached and pause_of(last_span):
                paused += (start - reached).total_seconds()
            # Two runs that overlap are one stretch of work, not two.
            start = max(start, reached)
            end = max(end, start)
        work += (end - start).total_seconds()
        running = live
        reached = end
        last_span = span

    pause = ""
    if not running and column in _WAITING and reached is not None:
        pause = pause_of(last_span)
        if pause and now > reached:
            paused += (now - reached).total_seconds()
    return {
        "work": round(work),
        "paused": round(paused),
        "sessions": len(runs),
        "running": running,
        "pause": pause,
    }
