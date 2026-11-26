"""Waiting for the credits to come back, instead of failing on them.

A Claude subscription is metered in windows: a few hours of work, then the CLI
answers "usage limit reached" to everything until the window rolls over. To a
runner nobody is watching that reads like every other broken session — the
ticket comes back as failed, its worktree is kept for a post-mortem there is
nothing to post-mortem, and by the time the credits return there is nobody left
to put it back in the queue. One exhausted quota costs a whole board.

So the three facts a run needs are here.

**What an exhausted quota looks like**, read off what the CLI said, because that
is the only place it is ever said. **How much of the window is already spent**,
read off the endpoint `/usage` asks, with the sign-in the CLI already keeps —
which is what lets a runner stop *before* the wall rather than against it, and
leave you enough of your own subscription to open a terminal with. And **the moment it comes back**, written
into the state directory: a run is a process the timer starts, not a loop, so
what this one learned only reaches the next one by being on disk. The runs in
between find the note and do nothing at all — no session started, no ticket
claimed, nothing to report.

The message carries its own answer when it can: `Claude AI usage limit
reached|1758031200` is the CLI saying "not before this timestamp". When it says
only that the limit is reached, the wait is a short one — `BLIND_WAIT` — and a
run that finds the limit still standing simply writes a new note. Guessing a
five-hour window would be the expensive mistake: what was hit is the *end* of a
window, and it may well be a minute away.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import db, http

# How long to wait when the refusal does not say when it lifts. Short on
# purpose: the cost of waking up too early is one session that dies in a second
# and writes a new note, and the cost of waiting too long is a board that sits
# idle for hours.
BLIND_WAIT = 15 * 60

# And the ceiling on any of it. A window lasts hours, not days, so a moment
# further off than this is not a moment: a timestamp in milliseconds, a clock
# that disagrees, a message whose format changed. None of those is allowed to
# put a runner to sleep for good — it waits this long, tries, and is told again.
LONGEST_WAIT = 6 * 3600

# What Claude Code says when there is nothing left to spend. Both spellings are
# here because both happen: a subscription hits a usage limit, an API key runs
# its balance down. Anything else — a timeout, a crash, a refusal — is a failure
# and is reported as one.
_SPENT = re.compile(r"usage limit reached|credit balance is too low", re.IGNORECASE)
# What Claude Code says when the account it was signed in with is gone: an
# OAuth sign-in that expired and could not be refreshed. Not a quota — nothing
# comes back by waiting, somebody has to run `claude login` — so it is a wait of
# its own, `login`, which `claude auth status` answering signed in again lifts.
# Read the same way as the two above, on a failure only, and for the
# subscription only: a key that is refused is a failure like any other.
_SIGNED_OUT = re.compile(
    r"failed to authenticate|oauth session expired|oauth token has expired", re.IGNORECASE
)
# The timestamp the CLI appends to the first of them, in seconds since the epoch
# — or in milliseconds, which is the same moment written longer.
_UNTIL = re.compile(r"limit reached\s*\|\s*(\d{9,})")
# Above this a timestamp is read in milliseconds: in seconds it is the year
# 5138, in milliseconds March 1973 — no reset is either, and the second is the
# one a format change produces.
_MILLISECONDS = 10**11


def reached(text: str) -> float:
    """When the credits come back, if this is a session that ran out of them.

    Zero when it is not, which is every other way a session can end. The moment
    may be in the past — a window that rolled over while the session was dying —
    and that is still an exhausted quota: the ticket it was working on goes back
    in the queue either way, there is simply nothing to wait for. It is never
    further off than `LONGEST_WAIT`, whatever the message says.
    """
    text = str(text or "")
    if not _SPENT.search(text):
        return 0.0
    found = _UNTIL.search(text)
    if not found:
        return time.time() + BLIND_WAIT
    until = float(found.group(1))
    if until > _MILLISECONDS:
        until /= 1000
    return min(until, time.time() + LONGEST_WAIT)


def signed_out(text: str) -> bool:
    """Is this a session that died on a sign-in that is no longer valid?"""
    return bool(_SIGNED_OUT.search(str(text or "")))


# The two waits, and they are not the same wait. `spent` is the wall: the CLI
# has refused, and no session can run. `reserve` is the line drawn short of it —
# there is credit left, we are simply not spending the last of it. A pass meets
# both the same way: it still merges what you validated and only declines to
# *start* anything. Two rows rather than one field, because a
# run reads each of them to answer a different question. They live in the
# `waits` table of `ponos.db`, which replaced `credits.json` and `reserve.json`.


def hold(until: float, *, what: str = "spent") -> None:
    """Write down that there is nothing to run before `until`.

    Never a reason to fail a run. A note nobody could write only means the next
    run tries a session and is told the same thing again — the old behaviour,
    one wasted session at a time.
    """
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO waits (what, until, since) VALUES (?, ?, ?)",
                (what, float(until), time.time()),
            )
    except db.ERRORS:
        pass


def hold_once(until: float, *, what: str) -> bool:
    """`hold`, unless that wait is already standing. True when this one wrote it.

    In one transaction, because the sessions of a pass end on their own
    threads: two that die on the same sentence must not both say it.
    """
    try:
        with db.transaction() as connection:
            row = connection.execute("SELECT until FROM waits WHERE what = ?", (what,)).fetchone()
            if row and float(row[0]) > time.time():
                return False
            connection.execute(
                "INSERT OR REPLACE INTO waits (what, until, since) VALUES (?, ?, ?)",
                (what, float(until), time.time()),
            )
            return True
    except db.ERRORS:
        return False


def held(*, what: str = "spent") -> float:
    """The moment being waited for, or 0.0 when nothing is being waited for.

    A note whose moment has passed is no wait at all: it is `release` that
    removes it, so that the run which finds the credits back can say so.
    """
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute("SELECT until FROM waits WHERE what = ?", (what,)).fetchone()
    except db.ERRORS:
        return 0.0
    until = float(row[0]) if row else 0.0
    return until if until > time.time() else 0.0


def release(*, what: str = "spent") -> bool:
    """Forget the wait. True when there was one to forget."""
    try:
        with db.transaction() as connection:
            return connection.execute("DELETE FROM waits WHERE what = ?", (what,)).rowcount > 0
    except db.ERRORS:
        return False


def when(until: float) -> str:
    """The hour a wait ends, as a clock reads it."""
    return datetime.fromtimestamp(until).astimezone().strftime("%H:%M")


def moment(at: float) -> str:
    """A reading's date and hour, as a clock reads it: `19/11 15:44`."""
    return datetime.fromtimestamp(at).astimezone().strftime("%d/%m %H:%M")


def _config_dir() -> Path:
    """Claude Code's own directory, which `CLAUDE_CONFIG_DIR` moves as a whole."""
    directory = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(directory).expanduser() if directory else Path.home() / ".claude"


def _store() -> Path:
    """Where Claude Code leaves what `/usage` last showed.

    The CLI's own store, not ours — read, never written, and never a reason to
    fail: a shape that changed under us has to read as "nobody knows", not as a
    runner that stops working. `CLAUDE_CONFIG_DIR` moves the whole of it, so it
    is looked for there before the home directory.
    """
    directory = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if directory:
        return Path(directory).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


# The two windows a subscription is actually metered in, and the two `/usage`
# puts on screen: the session, which lasts hours, and the week. The others in
# that payload are scoped to a model or a surface and would stop a runner over
# a quota its sessions are not even spending.
_WINDOWS = ("five_hour", "seven_day")

# What `/usage` asks, and the header that lets a subscription's OAuth token in.
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA = "oauth-2025-04-20"

# How old a reading may be and still be one. Past this the figure is *unknown*,
# never 0 %: Claude Code only refreshes its cache inside an interactive session
# that shows the usage, and the headless sessions of this runner never do — the
# cache sat at its 19 November values for a week while the limit it was meant to
# enforce read every window as already rolled over. A quarter of an hour is a
# few missed reads of `FETCH_EVERY`, and short of the time a window takes to
# fill from the reserve to the wall.
STALE_AFTER = 15 * 60

# How often the endpoint is asked, and how soon after a failure. A free place
# asks every few seconds; the subscription does not move that fast.
FETCH_EVERY = 3 * 60
RETRY_AFTER = 60


@dataclass(frozen=True)
class Window:
    """One metered window: how much of it is spent, and when it rolls over (0.0: not said)."""

    name: str
    percent: float
    resets_at: float


@dataclass(frozen=True)
class Reading:
    """What the subscription said, and when it said it."""

    windows: tuple[Window, ...]
    read_at: float

    def worst(self) -> tuple[float, float]:
        """The most constraining window, as `used` answers it."""
        return max((window.percent, window.resets_at) for window in self.windows)


def _window(raw: object) -> tuple[float, float] | None:
    """One window of a reading, as a percentage and the moment it rolls over.

    Nothing spent when its moment has *passed*: the reading is fresh (see
    `STALE_AFTER`), so a window that rolled over since is empty now, whatever
    the figure beside it says.

    `None` is the other answer entirely — this window says nothing usable — and
    it is what lets a payload whose shape changed read as "nobody knows" rather
    than as a subscription nobody has touched.
    """
    if not isinstance(raw, dict):
        return None
    percent = raw.get("utilization")
    if not isinstance(percent, (int, float)) or isinstance(percent, bool):
        return None
    moment = 0.0
    stated = raw.get("resets_at")
    if isinstance(stated, str) and stated.strip():
        try:
            moment = datetime.fromisoformat(stated.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
        if moment <= time.time():
            return 0.0, 0.0
    return float(percent), moment


def _parse(windows: object, read_at: float) -> Reading | None:
    if not isinstance(windows, dict):
        return None
    found = []
    for name in _WINDOWS:
        reading = _window(windows.get(name))
        if reading is not None:
            found.append(Window(name, *reading))
    # Not one window said anything a percentage could be read off. That is the
    # shape having changed, not a subscription nobody has touched.
    return Reading(tuple(found), read_at) if found else None


def _cached() -> tuple[Reading | None, float]:
    """Claude Code's cache: the reading in it if it is fresh, and when it was taken (0.0: never)."""
    try:
        cache = json.loads(_store().read_text(encoding="utf-8"))["cachedUsageUtilization"]
        windows = cache["utilization"]
        fetched = cache.get("fetchedAtMs")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None, 0.0
    if not isinstance(fetched, (int, float)) or isinstance(fetched, bool):
        return None, 0.0
    taken = fetched / 1000
    if time.time() - taken > STALE_AFTER:
        return None, taken
    return _parse(windows, taken), taken


def _token() -> str:
    """The subscription's OAuth token, as the CLI keeps it. Read only — refreshing it is the CLI's."""
    try:
        oauth = json.loads((_config_dir() / ".credentials.json").read_text(encoding="utf-8"))[
            "claudeAiOauth"
        ]
        token = oauth["accessToken"]
        expires = oauth.get("expiresAt")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return ""
    if isinstance(expires, (int, float)) and expires / 1000 <= time.time():
        return ""
    return token if isinstance(token, str) else ""


def _fetch() -> Reading | None:
    """Ask the subscription itself, as `/usage` does. `None` on any failure: the caller says "unknown"."""
    token = _token()
    if not token:
        return None
    try:
        answer = http.send(
            "anthropic-usage",
            "GET",
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": USAGE_BETA,
                "Accept": "application/json",
            },
            timeout=10,
            attempts=1,
            limit=1_000_000,
        )
        if answer.status != 200:
            return None
        return _parse(json.loads(answer.body), time.time())
    except (http.Unanswered, ValueError):
        return None


_lock = threading.Lock()
_fetched: Reading | None = None
_next_fetch = 0.0


def forget() -> None:
    """Drop what was read and the pause after it: the next `read` asks again."""
    global _fetched, _next_fetch
    with _lock:
        _fetched, _next_fetch = None, 0.0


def read() -> Reading | None:
    """A reading no older than `STALE_AFTER`, or `None` when nobody knows.

    The endpoint first, at most every `FETCH_EVERY`; Claude Code's own cache is
    the fallback, and only while it is fresh — an interactive session that
    showed `/usage` a minute ago is as good a source as our own request.
    """
    global _fetched, _next_fetch
    now = time.time()
    with _lock:
        if now >= _next_fetch:
            got = _fetch()
            _next_fetch = now + (FETCH_EVERY if got else RETRY_AFTER)
            if got:
                _fetched = got
        mine = _fetched if _fetched and now - _fetched.read_at <= STALE_AFTER else None
    cached, _ = _cached()
    return max((r for r in (mine, cached) if r), key=lambda r: r.read_at, default=None)


def last_read() -> float:
    """When the subscription was last read at all, however long ago — 0.0 when it never was."""
    with _lock:
        mine = _fetched.read_at if _fetched else 0.0
    return max(mine, _cached()[1])


def used() -> tuple[float, float] | None:
    """How much of the subscription is spent, and when that lets up.

    A percentage between 0 and 100, and a moment in seconds since the epoch —
    the **most constraining** of the two windows, because being at 20 % of the
    week and 97 % of the session means there is nothing to start either way. The
    moment is the one belonging to that window, so the wait it justifies ends
    exactly when the thing that caused it does; 0.0 when the reading names none.

    `None` is "nobody knows": no sign-in, an endpoint that did not answer, a
    cache older than `STALE_AFTER`, a shape that changed. The runner carries on
    on it — one that stopped working because a lookup failed would be a far
    worse failure than the one this guards against — but says so, loudly.
    """
    reading = read()
    return reading.worst() if reading else None
