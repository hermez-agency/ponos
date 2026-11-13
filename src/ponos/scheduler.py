"""The daemon's loop: a place frees, the next ready ticket takes it.

What it replaces is the pass. A pass was a process the timer started, that
claimed what was ready, kept `max_concurrent` places filled, and ended — and
on 6 November 2026 that shape kept tickets in « Ready » for half an hour twice,
places free: the pass had run its span (`PASS_SPAN`, gone with it), took
nothing more, and held the run lock until its last session ended, so that no
other pass could start either. The span was there for a good reason — a pass
that never ends never loads new code — and that reason is kept another way:
the daemon `exec`s itself onto a new version, and adopts the sessions it
leaves running (see daemon.py and adoption.py).

So there is no pass any more, only places. `serve` holds them for as long as
the daemon lives, and fills each one the moment it is free: from the board as
it is *now*, by priority, a ticket waiting for another left where it is, a
project at its own limit passed over for the next one. It looks at the board
when a place frees, when somebody asks (`ponos run`, the console, the MCP — a
signal, see daemon.py), whenever the set of ready tickets in `ponos.db` changes
— a local read, every `LOOK_SECONDS` — and every `interval_seconds` whatever
happens, the safety net the timer used to be.

**Everything else goes on beside it, in a thread of its own** (`_upkeep`): the
mirror, the answers typed on a phone, the « On » prompts, the sweep, the merged
pull requests closed, their CI and their reviews followed, the validated ones
merged, the recurring tickets born, the daily tidy. A pass did those at its top
and nowhere else: a merge validated at 14:20 waited for a session started at
14:04. Here they come round every `interval_seconds`, or as soon as somebody
asks — and a publication, which is a session, is handed to the places rather
than started on the side.

What is written down for `status` and the console, every time it changes, is
the places — which ticket holds each, per project — and the queue, each ticket
with why it waits (see `snapshot`).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import adoption, board, launches, state, store
from . import update as update_module
from . import voice as voice_module
from .projects import Project
from .ticket import Job, Ticket

logger = logging.getLogger(__name__)

# How often the ready tickets in `ponos.db` are counted, to start one made
# ready by whoever did not say so — a local read of one column, not a look.
LOOK_SECONDS = 2.0

# How long a stopping daemon waits for the work that cannot be carried on —
# a push, a merge, a reply — before it goes anyway. Under systemd's own 90 s.
STOP_GRACE_SECONDS = 60.0

# More threads than places on purpose: forcing a ticket past the limit takes a
# place the limit did not count, and an adopted session needs a thread to be
# followed in whatever the limit now says.
THREADS = 64
# How often the upkeep looks at the size of logs/ — see rotation.py.
LOG_ROTATION_SECONDS = 3600


@dataclass
class Signals:
    """What reaches the scheduler from outside, as events — see daemon.py."""

    wake: threading.Event = field(default_factory=threading.Event)
    upkeep: threading.Event = field(default_factory=threading.Event)
    reload: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)

    def nudge(self) -> None:
        self.wake.set()
        self.upkeep.set()


@dataclass
class Place:
    """One place taken, and by what."""

    kind: str  # "ticket", "publication", "replies", "session"
    ticket: str = ""
    title: str = ""
    project: str = ""
    since: float = field(default_factory=time.time)


class Scheduler(adoption.Adoption):
    """The places, filled for as long as the daemon lives."""

    def serve(self, signals: Signals, *, upkeep: bool = True) -> str:
        """Run until asked to stop or to reload; which of the two it was.

        Returns once nothing is in flight that a restart could not carry on:
        what is left are sessions, which go on without this process and are
        adopted by the next one.
        """
        self._places: dict[Future[dict[str, Any] | None], Place] = {}
        self._hand = board.InHand()
        self._carried = board.InHand()
        self._publishing: list[tuple[Ticket, Project]] = []
        self._lock = threading.Lock()
        self._said: list[dict[str, Any]] = []
        self._queued: list[Ticket] = []
        self._dated: list[tuple[Ticket, datetime]] = []
        self._past_limit = 0
        self._snapshot: dict[str, Any] = {}
        self._claimed = set()
        self._ready_seen: frozenset[str] | None = None
        self._stalled = ""
        self._parked: set[str] = set()
        self._credit_read = 0.0
        self._projects: dict[str, str] = {}
        self._talked_at = 0.0
        self._heard = -1
        self._ending_at: tuple[str, float] | None = None
        self._upkeeping = threading.Lock()
        self._rotated_at = 0.0
        pool = ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix="tr-place")
        for ticket_id, project, title, work in self.orphans():
            self._occupy(pool, Place("ticket", ticket_id, title, project), work)
        # `upkeep` False is for the tests of the places alone.
        beside = threading.Thread(
            target=self._upkeep, args=(signals,), name="tr-upkeep", daemon=True
        )
        if upkeep:
            beside.start()
        look_at = 0.0
        counted_at = 0.0
        try:
            while True:
                freed = self._land()
                ending = (
                    "stop" if signals.stop.is_set() else "reload" if signals.reload.is_set() else ""
                )
                if ending:
                    since = self._ending_since(ending)
                    if self._quiet(beside) or (
                        ending == "stop" and time.time() - since > STOP_GRACE_SECONDS
                    ):
                        return ending
                elif self._update_due():
                    signals.reload.set()
                    continue
                if not ending:
                    now = time.time()
                    asked = signals.wake.is_set()
                    signals.wake.clear()
                    if now - counted_at >= LOOK_SECONDS:
                        counted_at = now
                        if self._ready_changed():
                            asked = True
                    if freed or asked or now - look_at >= self.config.runner.interval_seconds:
                        look_at = now
                        self._look()
                    self._launches(pool)
                    self._fill(pool)
                    self._keep_snapshot()
                waiting = set(self._places)
                if waiting:
                    wait(waiting, timeout=0.5, return_when=FIRST_COMPLETED)
                else:
                    signals.wake.wait(0.5)
        finally:
            signals.upkeep.set()
            pool.shutdown(wait=False, cancel_futures=True)

    # -- the places -------------------------------------------------------------

    @property
    def width(self) -> int:
        return max(1, self.config.runner.max_concurrent)

    def _occupy(
        self,
        pool: ThreadPoolExecutor,
        place: Place,
        work: Callable[..., dict[str, Any] | None],
        *arguments: object,
    ) -> None:
        if place.ticket:
            self._hand.take(place.ticket, place.project if place.kind == "ticket" else "")
            self._claimed.add(place.ticket)
        future = pool.submit(work, *arguments)
        if place.ticket:
            self._hand.carry(future, place.ticket)
        self._places[future] = place

    def _land(self) -> bool:
        """The places whose work is over: their results recorded, and whether any freed."""
        done = {future for future in self._places if future.done()}
        for future in done:
            place = self._places.pop(future)
            try:
                result = future.result()
            except Exception:
                logger.exception("a place ended on an exception")
                result = None
            if place.kind == "publication" and place.ticket:
                self._carried.leave(place.ticket)
            if place.ticket:
                self._claimed.discard(place.ticket)
            if result:
                state.record_all([result])
        with self._lock:
            said, self._said = self._said, []
        if said:
            state.record_all(said)
        self._hand.land(done)
        return bool(done)

    def _free(self) -> bool:
        return len(self._places) - self._past_limit < self.width

    def _fill(self, pool: ThreadPoolExecutor) -> None:
        """Every free place, given work: publications first, then the queue, then the answers."""
        self._past_limit = max(0, min(self._past_limit, len(self._places) - self.width))
        with self._lock:
            publishing = list(self._publishing)
        # A comment arrived since the answers were last looked at — a read of
        # the file, every loop — or the safety look is due.
        heard = self.threads.last()
        talk = heard != self._heard or (
            time.time() - self._talked_at >= self.config.runner.interval_seconds
        )
        if not self._free() or not (publishing or self._queued or talk):
            self.explain(self._queued, self.width)
            return
        if self._held_by_credit():
            # Each ticket once: the queue is the board as last read, and a
            # ticket ticked since would read unticked until the next look.
            fresh = [ticket for ticket in self._queued if ticket.id not in self._parked]
            if fresh:
                state.record_all(self.park(fresh))
                self._parked |= {ticket.id for ticket in fresh}
            return
        self._parked.clear()
        while publishing and self._free() and self.room_for_a_session():
            ticket, project = publishing.pop(0)
            with self._lock:
                self._publishing.remove((ticket, project))
            self._occupy(
                pool,
                Place("publication", ticket.id, ticket.title),
                self._guarded,
                ticket,
                self._carry_out,
                ticket,
                project,
            )
        while self._queued and self._free() and self.room_for_a_session():
            picked = self.pick(self._queued, self._hand)
            if picked is None:
                break
            self._start(pool, picked)
        if talk and self._free() and self.room_for_a_session() and not self._talking():
            self._talked_at, self._heard = time.time(), heard
            self._occupy(pool, Place("replies"), self._talk)
        self.explain(self._queued, self.width)

    def _start(self, pool: ThreadPoolExecutor, ticket: Ticket) -> bool:
        """Claim a ticket picked off the queue and start its work — in the loop's thread.

        `pick` has put it in hand already. Claimed here, in the one thread that
        does it, so that two tickets never race over the same repository index.
        """
        self._claimed.add(ticket.id)
        job = self._guarded(ticket, self.prepare, ticket)
        if not isinstance(job, Job):
            if job:
                state.record_all([job])
            self._hand.leave(ticket.id)
            self._claimed.discard(ticket.id)
            return False
        project = self.in_repository(ticket)
        self._occupy(
            pool,
            Place("ticket", ticket.id, ticket.title, project),
            self._guarded,
            ticket,
            self.execute,
            job,
        )
        return True

    def _talking(self) -> bool:
        return any(place.kind == "replies" for place in self._places.values())

    def _talk(self) -> dict[str, Any] | None:
        said: list[dict[str, Any]] = []
        self.talk(said)
        with self._lock:
            self._said += said
        return None

    # -- what the loop reads ------------------------------------------------------

    def _look(self) -> None:
        """The queue, read afresh: what is ready now, by priority, less what is in hand."""
        try:
            tickets, dated = self.queue()
        except store.StoreError as error:
            self.say(f"  ! the board could not be read: {voice_module.line(error)}")
            return
        known = {ticket.id for ticket in self._queued}
        fresh = [ticket for ticket in tickets if ticket.id not in self._hand]
        self._projects = {ticket.id: self.in_repository(ticket) for ticket in fresh}
        new = [ticket for ticket in fresh if ticket.id not in known]
        self._holding = {
            ticket.id: (ticket, "running") for ticket in tickets if ticket.id in self._hand
        }
        self._queued = fresh
        self._dated = dated
        # Queued or held for later, both are work about to happen: `converse`
        # leaves them alone, because their comments are going into a prompt.
        # Read afresh rather than added to: a ticket that left the queue since
        # is spoken to again.
        self._claimed = (
            {place.ticket for place in self._places.values() if place.ticket}
            | {ticket.id for ticket in fresh}
            | {ticket.id for ticket, _ in dated}
            | set(self._waiting_on)
        )
        if new:
            self.say(f"↺ {len(new)} ticket(s) ready — {len(fresh)} in the queue")

    def _ready_changed(self) -> bool:
        """Whether the ready column of `ponos.db` holds other tickets than at the last count."""
        try:
            pages = self.client.query(self.database, self._ready_filter())
        except store.StoreError:
            return False
        seen = frozenset(page.id.replace("-", "") for page in pages)
        changed = self._ready_seen is not None and seen != self._ready_seen
        self._ready_seen = seen
        return changed

    def _held_by_credit(self) -> str:
        """Why nothing new may start — the reserve, the credit — or "" when it may.

        Asked again every `LOOK_SECONDS` at most: the loop turns twice a second.
        """
        if time.time() - self._credit_read < LOOK_SECONDS:
            return self._stalled
        self._credit_read = time.time()
        why = ""
        if self.waiting_for_credits():
            why = "credits"
        elif self.under_reserve():
            why = "reserve"
        if why != self._stalled:
            self._stalled = why
            if why:
                self.say("  ⏸ out of credit — nothing new is started until it is back")
        return why

    def _launches(self, pool: ThreadPoolExecutor) -> None:
        """The tickets somebody asked to start now — `ponos run --ticket`, « Run now »."""
        for identifier, asked in launches.pending():
            reference = str(asked.get("ticket") or "")
            force = bool(asked.get("force"))
            try:
                tickets = self.requested(reference)
            except store.StoreError as error:
                launches.answer(identifier, "refused", voice_module.line(error))
                continue
            if not tickets:
                launches.answer(identifier, "refused", "cancelled — not run")
                continue
            ticket = tickets[0]
            if ticket.id in self._hand:
                launches.answer(identifier, "started", "already running")
                continue
            project = self.in_repository(ticket)
            limit = max(1, self.config.runner.max_concurrent_per_project)
            crowded = bool(project) and self._hand.holding(project) >= limit
            if not force and (not self._free() or crowded):
                launches.answer(identifier, "full", self._fullness(project, crowded))
                continue
            if not self._free() or crowded:
                # Past the limit, once: the place it takes is not counted.
                self._past_limit += 1
                self.say(f"  ⇡ {ticket.title} — started past the limit, as asked")
            self._queued = [one for one in self._queued if one.id != ticket.id]
            self._hand.take(ticket.id, project)
            if self._start(pool, ticket):
                launches.answer(identifier, "started")
            else:
                launches.answer(identifier, "refused", "it could not be claimed — see its card")

    def _fullness(self, project: str, crowded: bool) -> str:
        if crowded:
            limit = max(1, self.config.runner.max_concurrent_per_project)
            return f"{project} already holds {limit} place(s)"
        return f"all {self.width} place(s) are taken"

    # -- beside the places ------------------------------------------------------------

    def _upkeep(self, signals: Signals) -> None:
        """Everything that is not a ticket's session, round after round, in a thread of its own."""
        while not (signals.stop.is_set() or signals.reload.is_set()):
            with self._upkeeping:
                try:
                    self._upkeep_once()
                except store.Unreachable as error:
                    self.say(f"offline — the board is looked at again later ({error})")
                except Exception:
                    logger.exception("the upkeep round stopped")
            # What the round brought up — a ticket made ready elsewhere, born of
            # a schedule, put back by the sweep — is looked at straight away.
            signals.wake.set()
            signals.upkeep.wait(self.config.runner.interval_seconds)
            signals.upkeep.clear()

    def _upkeep_once(self) -> None:
        self._comments.clear()
        self.answers()
        self.digest()
        results = self.transitions()
        if not self.dry_run:
            self.sweep()
            self.close_merged()
            self.tidy()
            self._rotate_logs()
        results += self.born()
        settled, fresh = self.delivering(self._carried)
        results += settled
        for entry in settled:
            self._carried.leave(entry["id"])
        for ticket, _ in fresh:
            self._carried.take(ticket.id)
        with self._lock:
            self._publishing += fresh
            self._said += results
        if fresh:
            self.say(f"  ↺ {len(fresh)} ticket(s) validated — carried out at the next free place")

    def _rotate_logs(self) -> None:
        """The logs' ceiling, at the start and then once an hour — in the upkeep, never in a place."""
        if time.time() - self._rotated_at < LOG_ROTATION_SECONDS:
            return
        self._rotated_at = time.time()
        try:
            self.rotate_logs()
        except Exception:
            logger.exception("the logs could not be rotated")

    def _quiet(self, upkeep: threading.Thread) -> bool:
        """Whether all that is in flight is sessions a restart carries on, and the upkeep idle."""
        if upkeep.is_alive():
            if not self._upkeeping.acquire(blocking=False):
                return False
            self._upkeeping.release()
        following: set[str] = getattr(self, "_following", set())
        return all(place.ticket in following for place in self._places.values())

    def _ending_since(self, ending: str) -> float:
        """When the daemon began to end this way — said once, on the first ask."""
        if self._ending_at is None or self._ending_at[0] != ending:
            self._ending_at = (ending, time.time())
            if ending == "reload":
                self.say("↻ restarting on the code on disk once the work in flight allows it")
            else:
                self.say("■ stopping — the sessions in flight carry on, and are taken back later")
        return self._ending_at[1]

    def _update_due(self) -> bool:
        """Whether a newer version was installed, here, now — see `update.install_newer`."""
        settings = self.config.runner
        if self.dry_run or not settings.auto_update:
            return False
        if not update_module.due(settings.update_interval_seconds):
            return False
        return update_module.install_newer(settings, say=self.say, notify=self._notify)

    def _keep_snapshot(self) -> None:
        """Write down the places and the queue when they changed — see `snapshot`."""
        snapshot = self.snapshot()
        if snapshot != self._snapshot and not self.dry_run:
            self._snapshot = snapshot
            state.keep_places({**snapshot, "pid": os.getpid()})

    def snapshot(self) -> dict[str, Any]:
        """The places — which ticket holds each, per project — and the queue, each with why it waits."""
        limit = max(1, self.config.runner.max_concurrent_per_project)
        busy = [
            {
                "ticket": place.ticket,
                "title": place.title,
                "project": place.project,
                "kind": place.kind,
                "since": round(place.since),
                "adoptable": place.ticket in getattr(self, "_following", ()),
            }
            for place in sorted(self._places.values(), key=lambda place: place.since)
        ]
        projects: dict[str, dict[str, int]] = {}
        for place in self._places.values():
            if place.project:
                projects.setdefault(place.project, {"busy": 0, "limit": limit})["busy"] += 1
        queue: list[dict[str, str]] = []
        for ticket in self._queued:
            project = self._projects.get(ticket.id, "")
            why = (
                self._stalled
                or ("project" if project and self._hand.holding(project) >= limit else "")
                or "places"
            )
            queue.append(
                {"ticket": ticket.id, "title": ticket.title, "project": project, "why": why}
            )
        for ticket, waits in getattr(self, "_waiting_on", {}).values():
            queue.append(
                {
                    "ticket": ticket.id,
                    "title": ticket.title,
                    "project": "",
                    "why": "after",
                    "detail": waits,
                }
            )
        for ticket, moment in self._dated:
            queue.append(
                {
                    "ticket": ticket.id,
                    "title": ticket.title,
                    "project": "",
                    "why": "date",
                    "detail": moment.isoformat(timespec="minutes"),
                }
            )
        return {
            "width": self.width,
            "per_project": limit,
            "busy": busy,
            "free": max(0, self.width - (len(self._places) - self._past_limit)),
            "projects": projects,
            "queue": queue,
        }
