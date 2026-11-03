"""The week on one screen: what was delivered, what it cost, what is waiting for you.

The figures exist in the console, and nobody opens the console on a Friday
evening. So the runner says them, once a period, to the channel that is already
in your pocket — and says them without a session: everything here is read off
`ponos.db` and the board's two columns that wait for a person, at no cost.

**A period is named by the moment it ends.** "Weekly on Monday at 9" means the
seven days that closed on the last Monday 9:00 that has passed, whatever time it
is when a pass looks. That moment is also the key of the row `state.claim_digest`
writes *before* the message goes: two passes, a run and the console's, a retry
after a crash — one of them takes the period and the others find it taken.
A period no channel took is given back, and tried again at the next pass.

**A late pass still delivers, an old one does not.** A laptop closed at 9:00
sends its digest when it wakes at 9:40, but a digest enabled on a Wednesday does
not send Monday's: `GRACE` is how late a period may still be sent.

**Delivered** is what the statistics call closed by the runner itself: a pull
request opened, a merge, a document. A ticket counts once, whatever number of
history lines it left. The merge rate is merged over opened — it moves with the
week a pull request waits, not with the quality of the work.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from . import blocks, channels, state, store
from . import voice as voice_module
from .base import Base
from .config import DIGEST_DAYS, Notify
from .ticket import Ticket

# How long after its end a period may still be sent.
GRACE = timedelta(hours=24)

# The history lines that are a ticket delivered without a pull request.
DELIVERIES = ("document", "delivery")

# The tickets listed under "waiting for a decision" — the rest are counted.
LISTED = 15


@dataclass
class Figures:
    """One period, counted."""

    delivered: Counter[str] = field(default_factory=Counter)
    cost: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    opened: int = 0
    merged: int = 0
    stops: Counter[str] = field(default_factory=Counter)
    sessions: int = 0


def period(settings: Notify, now: datetime) -> tuple[datetime, datetime] | None:
    """`(start, end)` of the latest period that is over, or None when the digest is off.

    `now` is aware, and the days are this machine's: a Monday 9:00 is the one on
    the wall, daylight saving included.
    """
    if settings.digest not in ("daily", "weekly"):
        return None
    now = now.astimezone()
    length = 1 if settings.digest == "daily" else 7
    back = 0
    if settings.digest == "weekly":
        back = (now.weekday() - DIGEST_DAYS.index(settings.digest_day)) % 7

    def at(days_back: int) -> datetime:
        day = now.date() - timedelta(days=days_back)
        return datetime.combine(day, time(settings.digest_hour)).astimezone()

    end = at(back)
    if end > now:
        end = at(back + length)
    return at_back(end, length), end


def at_back(end: datetime, days: int) -> datetime:
    """The same wall-clock hour `days` earlier — not 24 hours times `days`, across a clock change."""
    return datetime.combine(end.date() - timedelta(days=days), end.time()).astimezone()


def due(settings: Notify, now: datetime) -> tuple[datetime, datetime] | None:
    """The period to send now, if one is over and still within `GRACE`."""
    found = period(settings, now)
    if found is None or now.astimezone() - found[1] > GRACE:
        return None
    return found


def count(entries: list[dict[str, Any]]) -> Figures:
    """The figures of a period, from the history lines written during it."""
    figures = Figures()
    seen: dict[str, str] = {}
    opened: set[str] = set()
    merged: set[str] = set()
    for entry in entries:
        project = str(entry.get("project") or "")
        figures.sessions += 1
        figures.cost[project] += float(entry.get("cost_usd") or 0.0)
        status = entry.get("status")
        ticket = str(entry.get("id") or entry.get("ticket") or "").replace("-", "")
        if status in ("blocked", "failed"):
            code = blocks.known(entry.get("code")) or blocks.classify(
                str(entry.get("reason") or "")
            )
            figures.stops[code] += 1
        elif status == "done" and ticket:
            if entry.get("merged"):
                merged.add(ticket)
                opened.add(ticket)
            elif entry.get("pull_request"):
                opened.add(ticket)
            if entry.get("merged") or entry.get("pull_request") or entry.get("kind") in DELIVERIES:
                seen[ticket] = project
    for project in seen.values():
        figures.delivered[project] += 1
    figures.opened, figures.merged = len(opened), len(merged)
    return figures


def compose(
    said: voice_module.Voice,
    figures: Figures,
    waiting: list[tuple[str, str, str]],
    start: datetime,
    end: datetime,
    weekly: bool,
) -> str:
    """The message: `waiting` is `(project, title, link)` per ticket that needs a decision."""
    nobody = said.say("digest-no-project")

    def named(counts: dict[str, Any], show: Any = str) -> str:
        return ", ".join(
            f"{project or nobody} {show(value)}"
            for project, value in sorted(counts.items(), key=lambda pair: -pair[1])
            if value
        )

    lines = [
        said.say("digest-weekly", since=_day(start), until=_day(end))
        if weekly
        else said.say("digest-daily", day=_day(start))
    ]
    if not figures.sessions and not waiting:
        return "\n".join([*lines, said.say("digest-quiet"), said.say("digest-nothing-waiting")])
    delivered = sum(figures.delivered.values())
    lines.append(said.say("digest-delivered", count=delivered))
    lines += [
        f"  · {project or nobody} {number}" for project, number in figures.delivered.most_common()
    ]
    total = sum(figures.cost.values())
    lines.append(
        said.say("digest-cost", total=said.money(total))
        + (f" — {named(figures.cost, said.money)}" if total else "")
    )
    if figures.opened:
        lines.append(
            said.say(
                "digest-merge",
                rate=round(100 * figures.merged / figures.opened),
                merged=figures.merged,
                opened=figures.opened,
            )
        )
    if figures.stops:
        causes = ", ".join(
            f"{blocks.cause(code).label[said.language]} {number}"
            for code, number in figures.stops.most_common()
        )
        lines.append(said.say("digest-stops", count=sum(figures.stops.values()), causes=causes))
    if not waiting:
        lines.append(said.say("digest-nothing-waiting"))
        return "\n".join(lines)
    lines.append(said.say("digest-waiting", count=len(waiting)))
    for project, title, link in waiting[:LISTED]:
        lines += [f"  · {project or nobody} — {title}", f"    {link}"]
    if len(waiting) > LISTED:
        lines.append(said.say("digest-more", count=len(waiting) - LISTED))
    return "\n".join(lines)


def _day(moment: datetime) -> str:
    return f"{moment.day}/{moment.month}"


class Digest(Base):
    """The runner telling you how the period went."""

    def digest(self, *, now: bool = False, at: datetime | None = None) -> bool:
        """Send the digest that is due, or with `now` the one of the period under way. `at` is the clock.

        Returns whether a channel took it. Never a reason to fail a pass: a
        board that does not answer, or no channel at all, leaves the period to
        the next one.
        """
        settings = self.config.notify
        moment = (at or datetime.now()).astimezone()
        if now:
            weekly = settings.digest != "daily"
            end, length = moment, 7 if weekly else 1
            window = (at_back(end, length), end)
        else:
            if self.dry_run or not settings.remote:
                return False
            found = due(settings, moment)
            if found is None:
                return False
            window, weekly = found, settings.digest == "weekly"
        key = f"{settings.digest}:{window[1].isoformat(timespec='minutes')}"
        if not now and not state.claim_digest(key):
            return False
        try:
            text = compose(
                self.voice,
                count(state.between(*window)),
                self._decisions(),
                *window,
                weekly,
            )
        except (store.StoreError, OSError) as error:
            if not now:
                state.release_digest(key)
            self.say(f"  ! the digest could not be written: {error}")
            return False
        sent = channels.announce(settings, text) > 0
        if not sent and not now:
            state.release_digest(key)
        return sent

    def _decisions(self) -> list[tuple[str, str, str]]:
        """The tickets waiting for a person: in review, blocked, failed — with their link."""
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        columns = dict.fromkeys(
            self.config.notion.state(key) for key in ("review", "blocked", "failed")
        )
        waiting = []
        for column in columns:
            for page in self.client.query(
                self.database, {"property": status_property, kind: {"equals": column}}
            ):
                ticket = Ticket(page)
                waiting.append((self._project_of(ticket).name, ticket.title, ticket.url))
        return waiting
