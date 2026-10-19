"""How long a sign-in lasts, and how every one of them is taken back at once.

The cookie a sign-in left used to be an HMAC of the email and the password,
and nothing else: good until the password changed, which in practice meant
forever — a cookie copied off a laptop opened the console a year later. It now
says when it was given, and is good for thirty days from the last time it was
used: a browser that comes back is given a fresh one, a day at a time, and one
left in a drawer runs out by itself.

Still nothing kept per browser. The cookie carries its date, signed, and what
signs it is a key drawn once and kept in `web/sessions` beside the token. That
is the whole of "sign out everywhere" (`revoke`): a new key, and every cookie
signed with the old one is a stranger — read again from the file whenever it
changes, so `ponos serve --sign-out-everywhere` reaches a console already
running. A restart still signs nobody out, and a new password still signs
everybody out, because what is signed includes it (`SignIn.proof`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path

from ..config import state_dir

# Thirty days from the last request, and renewed at most once a day — a
# `Set-Cookie` on every answer of the API would be noise for no gain.
LIFETIME = 30 * 24 * 3600
RENEW_AFTER = 24 * 3600

_lock = threading.Lock()
_cached: tuple[tuple[int, int], str] | None = None


def key_path() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path / "sessions"


def _draw(path: Path) -> str:
    from ..disk import write_private  # 0600 from its first byte, as the token

    fresh = secrets.token_urlsafe(32)
    write_private(path, fresh + "\n")
    return fresh


def key() -> str:
    """The key the sessions are signed with: the one kept, or one drawn now."""
    global _cached
    path = key_path()
    with _lock:
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if _cached and _cached[0] == stamp:
                return _cached[1]
            kept = path.read_text(encoding="utf-8").strip()
        except OSError:
            kept, stamp = "", (0, 0)
        if not kept:
            kept = _draw(path)
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        _cached = (stamp, kept)
        return kept


def revoke() -> None:
    """Sign every browser out: the sessions given so far are signed by nobody now."""
    global _cached
    with _lock:
        _draw(key_path())
        _cached = None


def _signature(proof: str, issued: int) -> str:
    return hmac.new(key().encode(), f"{proof}\n{issued}".encode(), hashlib.sha256).hexdigest()


def issue(proof: str, now: float | None = None) -> str:
    """A session for the sign-in `proof` stands for, given now."""
    issued = int(time.time() if now is None else now)
    return f"{issued}.{_signature(proof, issued)}"


def issued(proof: str, cookie: str, now: float | None = None) -> int | None:
    """When `cookie` was given, if it is a session of `proof` still alive — else None."""
    stamp, _, signature = cookie.partition(".")
    if not stamp.isdigit() or not signature:
        return None
    given = int(stamp)
    moment = time.time() if now is None else now
    # Compared as bytes: what is offered came from a browser, and may hold
    # anything — `compare_digest` refuses a string outside ASCII.
    if not hmac.compare_digest(signature.encode(), _signature(proof, given).encode()):
        return None
    if moment - given > LIFETIME or given - moment > 60:
        return None
    return given
