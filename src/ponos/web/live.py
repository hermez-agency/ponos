"""What the console shows without being asked: the board, and the sessions.

One stream reaches the browser, and everything travels on it — the board, the
steps of a running ticket, the chat, the output of a command. A page that opened
three connections would have to reconnect three times after a suspend, and would
still have to put the events back in order at the far end.

Two rules keep it honest:

- **nobody watching, nothing polled.** The board is read from Notion only while
  a browser is connected. A console left open in a tab is one reader; a console
  nobody opened must cost the integration nothing at all;
- **the logs are the live feed, not Notion.** A running ticket already writes its
  session to disk, ten events a second. Tailing that file is free and instant,
  where asking Notion what it is doing would be neither.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from .. import log, notifications, progress, state, store

logger = logging.getLogger(__name__)

# What a browser connecting mid-flight is given to catch up with. Enough to
# rebuild a running session's steps, small enough to send in one go.
BACKLOG = 300

# A log stops being live this long after its last write. Past that the session is
# over — the runner has moved on and nothing more will be appended.
IDLE_SECONDS = 180

# What is kept as a *state* rather than as an event (see `Hub`): a browser that
# connects wants the board as it is and the sessions running now, not the last
# twenty versions of either.
STATES = ("board", "state", "sessions", "sync", "upgrade", "notifications")

# How much of a log is read at a time, from its end, to find its last line —
# which is enough, nearly always, to find it in one read.
ENDING_BYTES = 64 * 1024


@dataclass
class Event:
    kind: str
    payload: dict
    id: int = 0
    at: float = field(default_factory=time.time)

    def encode(self) -> str:
        body = json.dumps({"kind": self.kind, "at": self.at, **self.payload}, ensure_ascii=False)
        return f"id: {self.id}\nevent: {self.kind}\ndata: {body}\n\n"


class Hub:
    """Fan-out to every connected browser, plus a backlog for the next one."""

    def __init__(self, backlog: int = BACKLOG) -> None:
        self._lock = threading.Lock()
        self._clients: set[queue.Queue] = set()
        self._backlog: deque[Event] = deque(maxlen=backlog)
        # Every event is numbered, and the number is the SSE id. A browser
        # reconnecting after a suspend hands back the last one it saw, and gets
        # what it missed — rather than the whole backlog a second time.
        self._sequence = 0
        # The board and the run's state are *states*, not events: a browser
        # connecting wants the current one, not the last twenty. They are kept
        # aside, by kind, and replayed after the backlog.
        self._latest: dict[str, Event] = {}

    def publish(self, kind: str, **payload: object) -> None:
        with self._lock:
            self._sequence += 1
            event = Event(kind, dict(payload), id=self._sequence)
            if kind in STATES:
                self._latest[kind] = event
            else:
                self._backlog.append(event)
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(event)
            except queue.Full:
                # A browser that stopped reading is a browser that went away.
                # Dropping the event beats blocking the runner behind it.
                pass

    def publish_board(self, board: dict, changes: dict | None = None) -> None:
        """The board, kept whole for the next browser, sent as what changed.

        Sent whole, a board of five hundred tickets weighs a third of a
        megabyte, and a ticket in flight moves it every few seconds — for one
        card. So the browsers already watching are given `changes` when there
        are any, and the whole board only when there are not; the board kept
        for the next one is always whole, under the same id. Changes go to no
        backlog: a browser that missed one is given the board again instead
        (see `subscribe`).
        """
        with self._lock:
            self._sequence += 1
            whole = Event("board", dict(board), id=self._sequence)
            self._latest["board"] = whole
            event = whole if changes is None else Event("changes", dict(changes), id=self._sequence)
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(event)
            except queue.Full:
                # The next changes will not follow on from what this browser
                # holds, and it asks for the board again — see `use-console`.
                pass

    def subscribe(self, after: int = 0, board: bool = False) -> queue.Queue:
        """A channel, primed with what this browser has not seen.

        A first connection (`after` is zero) is given the current board and
        nothing else: its transcript comes from `/api/chat`, and replaying the
        backlog on top of that would show every message twice. A reconnection
        names the last event it saw, and gets exactly what came after it — the
        board included only if it moved since, or if the browser says (`board`)
        that what it holds no longer follows from what it was sent.
        """
        channel: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            replay = [
                event
                for event in self._latest.values()
                if event.kind != "board" or not after or board or event.id > after
            ]
            if after:
                replay += [event for event in self._backlog if event.id > after]
            for event in sorted(replay, key=lambda event: event.id):
                try:
                    channel.put_nowait(event)
                except queue.Full:
                    break
            self._clients.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(channel)

    @property
    def watchers(self) -> int:
        with self._lock:
            return len(self._clients)


class Tail:
    """The session logs, read forward, turned into steps as they are written.

    Position is kept per file, so a log already half-read when the console opens
    does not replay from its first line — except once, on the first pass, which
    is what puts a session already in flight on the screen.
    """

    def __init__(
        self,
        hub: Hub,
        directory: Path | None = None,
        held: Callable[[], str] | None = None,
    ) -> None:
        self.hub = hub
        self.directory = directory or state.logs_dir()
        self.held = held or state.running
        self._offsets: dict[str, int] = {}
        self._seen: set[str] = set()
        # The sessions last announced, so that a pass which changes nothing
        # says nothing. `None` until the first pass, which always speaks: a
        # browser connecting must be told "none" as much as "these two".
        self._running: list[dict] | None = None

    def pass_once(self) -> int:
        published = 0
        for path in _live_logs(self.directory):
            published += self._read(path)
        self._announce()
        return published

    def _announce(self) -> None:
        """Say which sessions are running, whenever that changes.

        A `step` says a session is alive; nothing in the log says, as a step,
        that it is over — the last line is the answer, and after it there is
        silence. Without this, a console counts every session it ever saw as
        running until the tab is closed, and a tab opened later counts none.
        """
        running = active(self.directory, self.held)
        if running == self._running:
            return
        self._running = running
        self.hub.publish("sessions", sessions=running)

    def _read(self, path: Path) -> int:
        key = path.name
        first = key not in self._seen
        self._seen.add(key)
        offset = self._offsets.get(key, 0)
        try:
            size = path.stat().st_size
            if size < offset:  # truncated or replaced: start over
                offset = 0
            if first:
                # A session already running when the console opened: give it its
                # last few steps rather than its first, so the panel opens on
                # where the work *is*.
                offset = max(0, size - 200_000)
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                lines = handle.readlines()
                self._offsets[key] = handle.tell()
        except OSError:
            return 0

        published = 0
        for line in lines:
            if not line.endswith("\n"):  # a half-written line: next pass has it
                self._offsets[key] -= len(line.encode("utf-8", "replace"))
                break
            for step in steps(line):
                self.hub.publish(
                    "step",
                    source=_ticket(key),
                    log=key,
                    label=step.label,
                    detail=step.detail,
                    said=step.said,
                )
                published += 1
        return published


def _live_logs(directory: Path) -> Iterator[Path]:
    """The logs written to recently enough to belong to a session in flight."""
    cutoff = time.time() - IDLE_SECONDS
    try:
        paths = sorted(directory.glob("*.jsonl"))
    except OSError:
        return
    for path in paths:
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        yield path


def answered(path: Path) -> bool:
    """Has this session said its last word? — a `result` line, at the end.

    Read from the end of the file rather than followed: the question is asked
    of every recent log on every pass, and by a page reload that has not seen
    any of them go by.
    """
    try:
        with path.open("rb") as handle:
            last = _last_line(handle)
    except OSError:
        return False
    try:
        return json.loads(last).get("type") == "result"
    except (ValueError, AttributeError):
        # Still being written: the type is the first thing on the line, and
        # the opening of it is enough to tell.
        return re.search(rb'^\s*\{\s*"type"\s*:\s*"result"', last[:256]) is not None


def lasted(ticket: str, directory: Path | None = None) -> float | None:
    """How long a ticket's last finished session took, in minutes — or None.

    The board says it where it has a duration column, and most boards made by
    hand have none: 475 tickets on one of them, not one duration, while every
    session's log ends on a `result` line that carries it. Read from the newest
    log that has said its last word, so a run in progress shows the one before.
    """
    directory = directory or state.logs_dir()
    for path in sorted(directory.glob(f"*-{ticket}.jsonl"), reverse=True):
        try:
            with path.open("rb") as handle:
                event = json.loads(_last_line(handle))
        except (OSError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        milliseconds = event.get("duration_ms")
        if isinstance(milliseconds, (int, float)) and milliseconds > 0:
            return round(milliseconds / 60_000, 1)
    return None


def _last_line(handle: BinaryIO) -> bytes:
    """The last line of a file, read backwards a block at a time.

    Blocks rather than a fixed tail: the final `result` line carries the whole
    answer, and a tail shorter than it would cut off the one part that says
    what the line is.
    """
    handle.seek(0, 2)
    position = handle.tell()
    tail = b""
    while position > 0:
        step = min(ENDING_BYTES, position)
        position -= step
        handle.seek(position)
        tail = handle.read(step) + tail
        body = tail.rstrip(b"\r\n")
        cut = body.rfind(b"\n")
        if cut >= 0:
            return body[cut + 1 :]
    return tail.rstrip(b"\r\n")


def active(directory: Path | None = None, held: Callable[[], str] | None = None) -> list[dict]:
    """The sessions running now, newest first, as `[{source, log}]`.

    Three things have to agree. The log was written in the last few minutes; its
    last line is not the session's answer; and a run holds the lock — a runner
    killed mid-session leaves a log that looks alive for `IDLE_SECONDS`, and the
    lock is what the kernel drops the moment the process goes.
    """
    directory = directory or state.logs_dir()
    if not (held or state.running)():
        return []
    found: list[tuple[float, dict]] = []
    for path in _live_logs(directory):
        if answered(path):
            continue
        try:
            written = path.stat().st_mtime
        except OSError:
            continue
        found.append((written, {"source": _ticket(path.name), "log": path.name}))
    # Ordered by the last write, but not carrying it: it moves with every line,
    # and a list that changed each second would be announced each second.
    found.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in found]


def steps(line: str) -> list[progress.Step]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return []
    return progress.describe(event)


def _ticket(filename: str) -> str:
    """The ticket a log belongs to: `20260830-120000-1a2b3c4d.jsonl` → `1a2b3c4d`."""
    return filename.removesuffix(".jsonl").rsplit("-", 1)[-1]


class Watch:
    """One thread, running only while somebody is looking.

    The board is asked of Notion every `interval` seconds; the logs are tailed
    every second, because that is where "live" actually happens and it costs a
    stat call. Both stop the moment the last browser disconnects.
    """

    def __init__(
        self,
        hub: Hub,
        board: Callable[[], dict],
        *,
        interval: int = 15,
        directory: Path | None = None,
        held: Callable[[], str] | None = None,
        status: Callable[[], dict] | None = None,
    ) -> None:
        self.hub = hub
        self.board = board
        # When the board last agreed with Notion. Published after every read,
        # on its own: it changes every time, and the board must not be
        # redrawn for a clock that moved.
        self.status = status
        self.interval = max(5, interval)
        self.tail = Tail(hub, directory, held)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # The board last published, ticket by ticket, to tell what changed.
        self._fingerprint = ""
        self._sent: dict[str, Any] | None = None
        self._version = 0
        # The board last read, and when: what `recent` hands out again.
        self._read: tuple[float, dict] | None = None
        self._nudged = threading.Event()
        # How many writes from the console asked for a read: a board read
        # before the last of them is not one to hand out again (`Tickets.board`).
        self.nudges = 0
        # The bell last published: a pass that finds the same says nothing.
        self._bell = ""

    def ensure_running(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="tr-watch", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def nudge(self) -> None:
        """Ask for a board read on the next tick, without waiting for it here.

        A ticket created or moved from the console should show up at once — but
        the browser must not sit through a Notion round trip to be told the
        write it just made succeeded. The watching thread does it, a second
        later, and the board arrives on the stream like any other.
        """
        self.nudges += 1
        self._nudged.set()

    def recent(self, age: float) -> dict:
        """The board as last read, when that is under `age` seconds ago; read again otherwise.

        For what asks for the whole board and can live with it a few seconds
        old — the statistics, at every change of period or project. While a
        page is open this thread has just read it, and a second Notion query
        would only say the same thing again.
        """
        held = self._read
        if held is not None and time.monotonic() - held[0] < age:
            return held[1]
        board = self.board()
        self._read = (time.monotonic(), board)
        return board

    def remember(self, at: float, board: dict) -> None:
        """Hold a board read elsewhere — `/api/board` — as if this thread had read it."""
        self._read = (at, board)

    def ring(self) -> None:
        """Publish the bell when it changed — a read of a small table, once a second.

        The runner writes notifications from another process, so there is nothing
        to be told: the file is looked at, and only a change reaches the stream.
        """
        heard = notifications.recent()
        fingerprint = json.dumps(heard, sort_keys=True)
        if fingerprint == self._bell:
            return
        self._bell = fingerprint
        self.hub.publish("notifications", **heard)

    def refresh(self, *, force: bool = False) -> None:
        """Read the board and publish what it says that is new.

        A fingerprint rather than a timestamp: the board is polled on a clock,
        but a board that has not moved is not news, and a console that redrew
        itself every fifteen seconds would lose your scroll position for nothing.
        What did move is sent as `changes`, numbered so that a browser can tell
        it missed some; `force` — a write from the console — sends the whole
        board when nothing moved, to put back a card the page drew ahead.
        """
        try:
            payload = self.board()
        except Exception as error:
            # A board that does not answer is said, once a refresh, without a
            # trace: that is the network, not the code.
            if isinstance(error, store.StoreError):
                logger.warning("live: the board could not be read: %s", error, extra=log.FILE_ONLY)
            else:
                logger.exception("live: the board could not be read", extra=log.FILE_ONLY)
            message = str(error).splitlines()[0]
            self.hub.publish("notice", where="board", message=message)
            if self.status is not None:
                self.hub.publish("sync", **self.status(), error=message)
            return
        self._read = (time.monotonic(), payload)
        if self.status is not None:
            self.hub.publish("sync", **self.status(), error="")
        # Every read, moved or not: a bell just rung is only let go of a moment
        # later, by a board that may be the same as the last.
        notifications.settle(payload.get("tickets") or ())
        fingerprint = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        same = fingerprint == self._fingerprint
        if same and not force:
            return
        self._fingerprint = fingerprint
        base = self._version
        self._version += 1
        found = None if same else difference(self._sent, payload)
        self._sent = payload
        board = {**payload, "version": self._version}
        if found is None:
            self.hub.publish_board(board)
        else:
            self.hub.publish_board(board, {**found, "base": base, "version": self._version})

    def _loop(self) -> None:
        next_board = 0.0
        while not self._stop.is_set():
            if self.hub.watchers == 0:
                # Idle rather than dead: a browser reconnecting after a suspend
                # finds the thread already there, and its board one second later.
                if self._stop.wait(2):
                    return
                next_board = 0.0
                continue
            now = time.monotonic()
            asked = self._nudged.is_set()
            if asked or now >= next_board:
                self._nudged.clear()
                next_board = now + self.interval
                self.refresh(force=asked)
            try:
                self.tail.pass_once()
                self.ring()
            except Exception as error:
                logger.exception(
                    "live: the session logs could not be followed", extra=log.FILE_ONLY
                )
                self.hub.publish("notice", where="logs", message=str(error).splitlines()[0])
            if self._stop.wait(1):
                return


def difference(before: dict | None, after: dict) -> dict | None:
    """What a page holding `before` needs to be told to hold `after`.

    The tickets that changed or appeared, each with the one it now follows —
    the board is sorted by column and title, and a card that moved column moves
    in the list too — and the ids of the ones gone. `None` when only the whole
    board will do: the first one, or one whose columns changed.

    The page applies it in one way only (`applyChanges` in `board-store.ts`),
    and that is replayed here: changes that would not give back exactly
    `after`, in its order, are not sent.
    """

    def frame(board: dict) -> dict:
        return {key: value for key, value in board.items() if key != "tickets"}

    if before is None or frame(before) != frame(after):
        return None
    held = {ticket["id"]: ticket for ticket in before["tickets"]}
    now = [ticket["id"] for ticket in after["tickets"]]
    if len(held) != len(before["tickets"]) or len(set(now)) != len(now):
        return None
    removed = sorted(set(held) - set(now))
    changed: list[dict] = []
    previous = ""
    for ticket in after["tickets"]:
        if held.get(ticket["id"]) != ticket:
            changed.append({"after": previous, "ticket": ticket})
        previous = ticket["id"]

    gone = set(removed) | {entry["ticket"]["id"] for entry in changed}
    order = [identifier for identifier in held if identifier not in gone]
    for entry in changed:
        if entry["after"] and entry["after"] not in order:
            return None
        order.insert(
            order.index(entry["after"]) + 1 if entry["after"] else 0, entry["ticket"]["id"]
        )
    if order != now:
        return None
    return {"changed": changed, "removed": removed}
