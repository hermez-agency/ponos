"""The board as the console holds it, between two answers from Notion.

The console used to reread the whole tickets database every fifteen seconds.
That was always *right* — a full read cannot miss anything — and it was slow in
the way that shows: 366 tickets are four pages of a hundred, four seconds of
Notion, so a status changed in Notion reached the screen fifteen to twenty
seconds later, and a move made from the console was a `PATCH` the browser sat
through, lost for good if Notion answered 429 at that moment. Three things
replace it, and each is here because of something measured on the real board:

- **a read is what changed, with a window that overlaps.** Notion's
  `last_edited_time` is rounded down to the minute: four statuses written at
  :06, :22, :39 and :52 all came back as `09:32:00.000Z`. A read of "edited
  after my last read" would skip every change made in the minute of that read.
  So the window reaches `OVERLAP` seconds further back than the last read, pages
  come back more than once, and what was already held is recognised by its
  properties rather than by a timestamp that cannot tell them apart;
- **the whole board is still read, every `RECONCILE` seconds and at the start.**
  An incremental read cannot see a page leave — an archived ticket just stops
  coming back — and a window can be wrong in ways nobody thought of. The full
  read is the truth; what it finds that the reads before it had wrong is an
  *écart*, counted, shown in the console and written in the journal, which is
  how anybody will know whether the window is wide enough;
- **a move from the console is a write that waits its turn.** `Outbox` keeps it
  on disk until Notion has it: it reads the page first and refuses to overwrite
  a status somebody changed in Notion since the console showed it, retries with
  a growing wait (Notion's own `Retry-After` is honoured one layer down, in
  `notion.Client`), reads the page back to confirm, and until then the card says
  "waiting to be sent" — or, when it gave up, why.

One more thing was measured, and it is why a confirmed write is *held* for a few
seconds: a database query sees a `PATCH` one to four seconds after the `PATCH`
answered. A read in between would put the card back where it came from.

Everything written down goes to the same journal as the Markdown mirror's
reconciliation (`sync_journal` in `ponos.db`, `ponos sync --journal`): one place to ask
"when did this ticket change, and when did the other side see it?".
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import disk, store, sync

# How far behind the last read an incremental read starts. A minute would do
# for the rounding alone; the second one is for a clock that is not Notion's.
OVERLAP = 120

# How often the whole board is read again, and compared.
RECONCILE = 300

# How long a page read back after a console write outranks a query. Measured:
# a query sees a write one to four seconds after it was made.
HOLD = 15

# The waits between two tries of the same write, and how many there are before
# the card says it failed. Each try is itself up to three requests, spaced by
# `notion.Client`, which honours a 429's `Retry-After`.
BACKOFF = (2, 5, 15, 30, 60, 120, 300)

# A refusal no retry will change: the request itself is wrong.
_FINAL = re.compile(r": (400|401|403|404) ")


def _key(identifier: str) -> str:
    return str(identifier or "").replace("-", "")


def _stamp(moment: float) -> str:
    return datetime.fromtimestamp(moment, UTC).isoformat(timespec="seconds")


def _clock(moment: str) -> str:
    """`HH:MM:SS` of an ISO timestamp, for a journal line a person reads."""
    try:
        return datetime.fromisoformat(moment.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return moment or "?"


class Reader:
    """The tickets database, held, and brought up to date a window at a time."""

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        journal: Callable[[sync.Report], None] = sync.write_journal,
    ) -> None:
        self._clock = clock
        self._journal = journal
        self._lock = threading.Lock()
        self._pages: dict[str, store.Page] = {}
        self._held: dict[str, float] = {}
        self._read_at = 0.0
        self._full_at = 0.0
        self.synced_at = ""
        self.reconciled_at = ""
        # What the last full read found the incremental ones had wrong.
        self.drift: list[dict[str, Any]] = []

    def reconcile_next(self) -> None:
        """Make the next read a full one — what "Resynchronise now" asks for."""
        with self._lock:
            self._full_at = 0.0

    def get(self, page_id: str) -> store.Page | None:
        with self._lock:
            return self._pages.get(_key(page_id))

    def hold(self, page: store.Page) -> None:
        """A page read back after a write: the truth, for the next `HOLD` seconds."""
        with self._lock:
            self._pages[_key(page.id)] = page
            self._held[_key(page.id)] = self._clock() + HOLD

    def forget(self, page_id: str) -> None:
        """A page trashed from here: no longer held, and not brought back by a window.

        An incremental read cannot see a page leave, so only dropping it here
        makes it disappear before the next full read.
        """
        with self._lock:
            self._pages.pop(_key(page_id), None)
            self._held.pop(_key(page_id), None)

    def read(self, client: store.Store, database: str, status: str) -> list[store.Page]:
        """Every ticket, as current as Notion will say. Raises `StoreError`."""
        started = self._clock()
        with self._lock:
            full = not self._pages or started - self._full_at >= RECONCILE
            since = self._read_at - OVERLAP
        if full:
            fresh = client.query(database)
        else:
            fresh = client.query(
                database,
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"on_or_after": _stamp(since)},
                },
            )
        report = sync.Report()
        with self._lock:
            before = dict(self._pages)
            now = self._clock()
            self._held = {key: until for key, until in self._held.items() if until > now}
            if full:
                known = {_key(page.id): page for page in fresh}
                for key in self._held:
                    if key in before:
                        known[key] = before[key]
                if before:
                    self.drift = self._compare(before, known, status, report)
                self._pages = known
                self._full_at = started
                self.reconciled_at = _stamp(started)
            else:
                for page in fresh:
                    key = _key(page.id)
                    if key in self._held:
                        continue
                    held = before.get(key)
                    if held is not None and sync.fingerprint(held) == sync.fingerprint(page):
                        continue  # the window's overlap: already known
                    self._pages[key] = page
            if before:
                self._notice(before, self._pages, status, report, now)
            self._read_at = started
            self.synced_at = _stamp(now)
            pages = list(self._pages.values())
        self._journal(report)
        return pages

    def _compare(
        self,
        held: dict[str, store.Page],
        truth: dict[str, store.Page],
        status: str,
        report: sync.Report,
    ) -> list[dict[str, Any]]:
        """What the incremental reads had wrong, as the full read found it.

        A status that differs, or a ticket they never brought in. A ticket that
        is gone is not one: archiving a page is a thing a window cannot see by
        construction, and the full read exists to catch it.
        """
        found: list[dict[str, Any]] = []
        for key, page in truth.items():
            mine = held.get(key)
            said = store.read(mine, status) if mine is not None else None
            real = store.read(page, status)
            if mine is not None and said == real:
                continue
            found.append({"id": key, "title": page.title, "held": said or "", "truth": real or ""})
            report.note(
                "drift",
                "tickets",
                key,
                page.title,
                f"the console held {said or 'nothing'}, Notion says {real or 'nothing'}",
            )
        return found

    @staticmethod
    def _notice(
        before: dict[str, store.Page],
        after: dict[str, store.Page],
        status: str,
        report: sync.Report,
        now: float,
    ) -> None:
        """Write down every status the console has just seen change.

        The measure the ticket asked for: when the source says it changed (to
        the minute, which is all Notion keeps) and when this side saw it.
        """
        for key, page in after.items():
            old = before.get(key)
            if old is None:
                continue
            was, is_ = store.read(old, status), store.read(page, status)
            if was == is_:
                continue
            edited = str(page.raw.get("last_edited_time", ""))
            report.note(
                "seen",
                "tickets",
                key,
                page.title,
                f"{was or '—'} → {is_ or '—'} · edited {_clock(edited)} in Notion "
                f"(to the minute) · seen {_clock(_stamp(now))} by the console",
            )


@dataclass
class Write:
    """One move made from the console, until Notion has it."""

    page: str
    column: str
    status: str
    # The status the console showed when the move was made: a page that says
    # anything else by the time it is written was changed by somebody else.
    seen: str = ""
    title: str = ""
    queued: float = 0.0
    attempts: int = 0
    state: str = "pending"  # pending, failed, conflict
    error: str = ""
    next_at: float = 0.0


class Outbox:
    """The console's writes, kept on disk until Notion confirms each one.

    One per ticket: a card moved twice before the first write went out needs
    the second column in Notion, not both one after the other.
    """

    def __init__(
        self,
        path: Path | None = None,
        clock: Callable[[], float] = time.time,
        journal: Callable[[sync.Report], None] = sync.write_journal,
    ) -> None:
        self._path = path
        self._clock = clock
        self._journal = journal
        self._lock = threading.Lock()
        self._writes: dict[str, Write] = {}
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()

    # -- what is waiting ------------------------------------------------------

    def put(self, write: Write) -> None:
        write.queued = write.queued or self._clock()
        write.next_at = 0.0
        with self._lock:
            self._writes[_key(write.page)] = write
            self._save()
        self._wake.set()

    def marks(self) -> dict[str, Write]:
        """Every write not yet confirmed, by ticket — what the cards wear."""
        with self._lock:
            return {key: Write(**asdict(write)) for key, write in self._writes.items()}

    def retry(self) -> None:
        """Try the failed writes again, and let go of the conflicts.

        A conflict is the console refusing to overwrite what somebody did in
        Notion; asking for a resynchronisation is saying you have seen it.
        """
        with self._lock:
            for key, write in list(self._writes.items()):
                if write.state == "conflict":
                    del self._writes[key]
                elif write.state == "failed":
                    write.state, write.attempts, write.next_at = "pending", 0, 0.0
            self._save()
        self._wake.set()

    # -- sending --------------------------------------------------------------

    def start(
        self, send: Callable[[Write], store.Page | None], changed: Callable[[], None]
    ) -> None:
        """One thread, sending what is due, for as long as the console runs."""
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            while True:
                wait = self.flush(send, changed)
                self._wake.wait(timeout=wait)
                self._wake.clear()

        self._thread = threading.Thread(target=loop, name="tr-outbox", daemon=True)
        self._thread.start()

    def flush(
        self, send: Callable[[Write], store.Page | None], changed: Callable[[], None]
    ) -> float:
        """Send every write that is due. Returns how long until the next one is."""
        now = self._clock()
        with self._lock:
            due = [
                Write(**asdict(write))
                for write in self._writes.values()
                if write.state == "pending" and write.next_at <= now
            ]
        moved = False
        report = sync.Report()
        for write in due:
            outcome = self._attempt(write, send, report)
            with self._lock:
                current = self._writes.get(_key(write.page))
                if current is None or current.queued != write.queued:
                    continue  # moved again meanwhile: the newer write stands
                if outcome == "sent":
                    del self._writes[_key(write.page)]
                else:
                    self._writes[_key(write.page)] = write
                self._save()
            moved = True
        self._journal(report)
        if moved:
            changed()
        with self._lock:
            waiting = [w.next_at for w in self._writes.values() if w.state == "pending"]
        return max(0.5, min(waiting) - self._clock()) if waiting else 3600.0

    def _attempt(
        self, write: Write, send: Callable[[Write], store.Page | None], report: sync.Report
    ) -> str:
        """One try. `sent`, or the write is left saying why not."""
        write.attempts += 1
        try:
            send(write)
        except Conflict as conflict:
            write.state, write.error = "conflict", str(conflict)
            report.note(
                "conflict",
                "tickets",
                _key(write.page),
                write.title,
                f"moved to {write.status} from the console, but Notion already says "
                f"{conflict.found} (the console showed {write.seen}); not overwritten",
            )
            return "conflict"
        except store.StoreError as error:
            write.error = str(error).splitlines()[0]
            final = _FINAL.search(write.error) is not None
            if final or write.attempts > len(BACKOFF):
                write.state = "failed"
                report.note(
                    "write-failed",
                    "tickets",
                    _key(write.page),
                    write.title,
                    f"{write.status} not written after {write.attempts} attempt(s): {write.error}",
                )
            else:
                write.next_at = self._clock() + BACKOFF[write.attempts - 1]
            return "failed"
        report.note(
            "console→notion",
            "tickets",
            _key(write.page),
            write.title,
            f"{write.seen or '—'} → {write.status} · asked {_clock(_stamp(write.queued))} · "
            f"confirmed {_clock(_stamp(self._clock()))} · {write.attempts} attempt(s)",
        )
        return "sent"

    # -- on disk --------------------------------------------------------------

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                write = Write(**item)
            except TypeError:
                continue
            self._writes[_key(write.page)] = write

    def _save(self) -> None:
        """Whole or not at all, and never a reason for a write to fail."""
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            disk.write_atomic(
                self._path,
                json.dumps([asdict(write) for write in self._writes.values()], ensure_ascii=False),
            )
        except OSError:
            pass


class Conflict(Exception):
    """The page no longer says what the console showed when the move was made."""

    def __init__(self, found: str) -> None:
        super().__init__(f"Notion already says {found}")
        self.found = found


def send(client: store.Store, database: str, status: str, write: Write) -> store.Page:
    """Read, write, read back. What one attempt of one move is.

    Read first, because a page somebody moved in Notion since the console showed
    it must not be overwritten on the strength of an older picture. Read back,
    because an answered `PATCH` is Notion saying it heard — the page saying the
    new status is Notion saying it kept it.
    """
    page = client.page(write.page)
    found = str(store.read(page, status) or "")
    if found == write.status:
        return page
    if write.seen and found != write.seen:
        raise Conflict(found or "no status")
    client.update(database, write.page, {status: write.status})
    confirmed = client.page(write.page)
    kept = str(store.read(confirmed, status) or "")
    if kept != write.status:
        raise store.StoreError(f"written, but the page still says {kept or 'no status'}")
    return confirmed


def overlay(
    ticket: dict[str, Any], write: Write | None, column_of: Callable[[str], str]
) -> dict[str, Any]:
    """A card, as the console's own pending write leaves it.

    Pending: where it is going, and saying it has not arrived. Failed or in
    conflict: where Notion has it, and saying why the move did not happen.
    """
    if write is None:
        return ticket
    if write.state == "pending":
        return {
            **ticket,
            "status": write.status,
            "column": column_of(write.status),
            "sync": "pending",
            "sync_error": write.error,
            "sync_status": write.status,
        }
    return {**ticket, "sync": write.state, "sync_error": write.error, "sync_status": write.status}


def conflicts(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The runner's refusals to overwrite, by ticket, from the journal.

    The console shows one until the page is edited again after it — someone
    looked, and did something about it.
    """
    found: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("what") == "conflict" and entry.get("collection") == "tickets":
            found[_key(entry.get("page", ""))] = entry
    return found


def settled(ticket: dict[str, Any], entry: dict[str, Any] | None) -> dict[str, Any]:
    """A card, with the runner's last refusal on it if nothing happened since."""
    if entry is None or ticket.get("sync"):
        return ticket
    edited = _moment(str(ticket.get("edited", "")))
    at = _moment(str(entry.get("at", "")))
    # Notion's edit is to the minute: an edit in the minute of the refusal is
    # the runner's own write of the other columns, not somebody answering it.
    if edited is not None and at is not None and edited.replace(second=0, microsecond=0) > at:
        return ticket
    return {**ticket, "sync": "conflict", "sync_error": str(entry.get("detail", ""))}


def _moment(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def describe(reader: Reader, tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """The line over the board: when it last agreed with Notion, and what does not.

    Counted off the cards rather than off the outbox, so that the runner's own
    refusals — read from the journal — are counted with the console's.
    """
    marks = [ticket.get("sync", "") for ticket in tickets]
    return {
        "synced_at": reader.synced_at,
        "reconciled_at": reader.reconciled_at,
        "drift": len(reader.drift),
        "pending": marks.count("pending"),
        "failed": marks.count("failed"),
        "conflicts": marks.count("conflict"),
    }


def held(
    ticket: dict[str, Any],
    noted: dict[str, tuple[str, str]],
    *,
    passing: bool,
    timer: bool,
    waits: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Why a ready card is still in its column — or nothing, for any other card.

    A ready column that stays full with nothing to say why reads as a broken
    runner, and for half an hour it was one. So every ready card says what it is
    waiting for, from the first of these that holds: its date, the credit, the
    reserve or the day's limit (`waits`: what each has written down, as a
    clock reads it), what the pass under way wrote down about it (`noted`, see
    `Board.explain` — read only while a pass holds the lock, since a pass that
    died leaves its record behind), and otherwise the next reading of the board:
    the pass's own if one is under way, the timer's if it is on.
    """
    if ticket.get("column") != "ready":
        return {}
    moment = _moment(str(ticket.get("scheduled") or ""))
    if moment is not None and moment > (now or datetime.now(UTC)):
        return {"reason": "date", "detail": str(ticket["scheduled"])}
    for what, until in (waits or {}).items():
        if until:
            return {"reason": what, "detail": until}
    if passing:
        reason, detail = noted.get(_key(ticket.get("id", "")), ("pass", ""))
        return {"reason": reason, "detail": detail}
    return {"reason": "next" if timer else "timer", "detail": ""}
