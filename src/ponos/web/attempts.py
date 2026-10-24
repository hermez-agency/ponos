"""How many times an address got the console's door wrong, and how long it waits.

The door was a `time.sleep(1)` in the thread that answered the wrong password.
`ThreadingHTTPServer` gives every request a thread of its own, so twenty
guesses sent at once all slept their second side by side and were all answered
together: a pause for the person who mistyped, nothing at all for a script.
What slows a guesser has to be shared between the requests — a count per
address, in memory, under a lock — and has to say "no" *before* the guess is
checked, not after.

So an attempt is counted when it is let in, and forgiven when it turns out
right (`admit`, `forgive`): of twenty sent at once, one is checked, and the
nineteen others are told to come back later without being looked at. Each
failure doubles the wait, from one second; the tenth locks the address out for
a quarter of an hour. Nothing is written to disk: a restart forgets, and a
restart is not something a guesser can ask for.

An address is the peer's, unless the peer is a proxy somebody declared —
`web.trusted_proxies`, this machine alone by default, where `tailscale serve`
relays from — which is the only one allowed to say who it is relaying, in the
last `X-Forwarded-For` it appended. Being on a private network is not enough:
a port Docker publishes is reached through its bridge, a neighbouring container
of Dokploy's network reaches the console without Traefik, a LAN is a LAN — and
any of them, believed, could announce a new address with every guess and never
wait. An IPv6 address counts by its /64: one machine is given a whole one.

A door that is open rather than guessed — `/oauth/register`, which any client
may call and which writes a row each time — is not slowed by failures, since
it does not fail: it is given a `Quota`, so many times per address in a window,
and refused for the rest of the window past it.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

# The tenth failure in a row is not somebody who forgot.
LOCK_AFTER = 10
LOCK_SECONDS = 15 * 60
# The longest wait before the lock: a person who mistyped five times waits this.
LONGEST_WAIT = 30
# A quiet address is forgotten after this long without a failure.
FORGET_AFTER = LOCK_SECONDS
# Past this many addresses, the forgotten ones are swept out before the next.
SWEEP_ABOVE = 4096


@dataclass
class _Record:
    failures: int
    until: float  # nothing more is checked from this address before then
    last: float


def wait_after(failures: int) -> float:
    """Seconds to wait after that many failures in a row: 1, 2, 4… then the lock."""
    if failures <= 0:
        return 0
    if failures >= LOCK_AFTER:
        return LOCK_SECONDS
    return min(2 ** (failures - 1), LONGEST_WAIT)


Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# The proxies believed when nobody declared any: this machine.
LOOPBACK: tuple[Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def network(written: str) -> Network | None:
    """An entry of `web.trusted_proxies` — an address or a network — or None for neither."""
    try:
        return ipaddress.ip_network(written.strip(), strict=False)
    except ValueError:
        return None


def proxies(written: Iterable[str]) -> tuple[Network, ...]:
    """The proxies `web.trusted_proxies` declares; an entry that is neither is left out.

    Left out rather than refused: what it would have trusted is then counted as
    one address, which is a stricter door, not a wider one — and `ponos doctor`
    says which entry it was.
    """
    return tuple(found for entry in written if (found := network(entry)))


def address_of(peer: str, forwarded: str = "", trusted: Iterable[Network] = LOOPBACK) -> str:
    """Who is knocking: the peer, or who a declared proxy says it relays."""
    try:
        direct = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if isinstance(direct, ipaddress.IPv6Address) and direct.ipv4_mapped:
        direct = direct.ipv4_mapped
    if forwarded and any(direct in proxy for proxy in trusted):
        relayed = forwarded.split(",")[-1].strip()
        try:
            direct = ipaddress.ip_address(relayed)
        except ValueError:
            return relayed or peer
    if isinstance(direct, ipaddress.IPv6Address):
        if direct.ipv4_mapped:
            return str(direct.ipv4_mapped)
        return str(ipaddress.ip_network(f"{direct}/64", strict=False))
    return str(direct)


class Quota:
    """So many uses of an open door per address in a window, counted in memory."""

    def __init__(
        self, allowed: int, seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.allowed = allowed
        self.seconds = seconds
        self.clock = clock
        self._lock = threading.Lock()
        # Per address: how many so far, and when its window closes.
        self._windows: dict[str, tuple[int, float]] = {}

    def take(self, key: str) -> float:
        """Count one use from `key`: 0 when it may go on, else the seconds left to wait."""
        with self._lock:
            now = self.clock()
            if len(self._windows) > SWEEP_ABOVE:
                self._windows = {
                    known: window for known, window in self._windows.items() if window[1] > now
                }
            used, ends = self._windows.get(key, (0, 0.0))
            if ends <= now:
                used, ends = 0, now + self.seconds
            if used >= self.allowed:
                return ends - now
            self._windows[key] = (used + 1, ends)
            return 0.0


class Attempts:
    """The count, per address, of the console's sign-in, token and code."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._records: dict[str, _Record] = {}

    def _sweep(self, now: float) -> None:
        for key in [
            key
            for key, record in self._records.items()
            if record.until <= now and now - record.last > FORGET_AFTER
        ]:
            del self._records[key]

    def _current(self, key: str, now: float) -> _Record | None:
        record = self._records.get(key)
        if record and record.until <= now and now - record.last > FORGET_AFTER:
            del self._records[key]
            return None
        return record

    def waiting(self, key: str) -> float:
        """Seconds before anything from `key` is checked again; 0 when it may try."""
        with self._lock:
            now = self.clock()
            record = self._current(key, now)
            return max(0.0, record.until - now) if record else 0.0

    def admit(self, key: str) -> float:
        """Let one attempt through, counted as failed until `forgive` says otherwise.

        Returns 0 when it may be checked, else the seconds left to wait — and
        then it was not counted: what is refused unseen tells nothing, and
        counting it would only lengthen a wait the refusal already enforces.
        """
        with self._lock:
            now = self.clock()
            if len(self._records) > SWEEP_ABOVE:
                self._sweep(now)
            record = self._current(key, now)
            if record and record.until > now:
                return record.until - now
            failures = (record.failures if record else 0) + 1
            self._records[key] = _Record(failures, now + wait_after(failures), now)
            return 0.0

    def failed(self, key: str) -> None:
        """One more failure from `key`, for a check that was made without `admit`."""
        with self._lock:
            now = self.clock()
            record = self._current(key, now)
            failures = (record.failures if record else 0) + 1
            self._records[key] = _Record(failures, now + wait_after(failures), now)

    def forgive(self, key: str) -> None:
        """`key` got it right: whatever it got wrong before is forgotten."""
        with self._lock:
            self._records.pop(key, None)
