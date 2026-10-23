"""Asking the run that holds a ticket's session to let go of it.

The console and the run are two processes: the session is a child of the second,
and the first has no handle on it. A signal sent from outside would also be read
for what `session.signalled` calls a kill nobody on our side sent — and the
ticket would be blocked on it, then relaunched once. So the request is a file
under the state directory, which the run reads while the session is going:
`session.run` already ends its whole process group when its `stop` event is set,
and a stop it was asked for comes back as `Outcome.stopped`, not as a failure.

The run answers with a second file once the session is gone, which is what the
console waits for before it touches the worktree. A request nobody answers —
the session was already dead, no run is going — is the console's to clear.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import disk
from .config import state_dir

# A request older than this is a leftover of a console that died before it
# cleared it, not a wish: the next session of that ticket must not be born stopped.
STALE_SECONDS = 300

POLL_SECONDS = 0.5


def _file(ticket_id: str, suffix: str) -> Path:
    return state_dir() / "stops" / f"{ticket_id.replace('-', '')}.{suffix}"


def _write(ticket_id: str, suffix: str, text: str) -> None:
    path = _file(ticket_id, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    disk.write_atomic(path, text)


def request(ticket_id: str, action: str) -> None:
    """Ask for the ticket's session to end, for `action` (`pause` or `abandon`)."""
    _write(ticket_id, "ask", action)


def requested(ticket_id: str) -> str:
    """The action asked for on this ticket, or "" when none is — or none is still fresh."""
    path = _file(ticket_id, "ask")
    try:
        if time.time() - path.stat().st_mtime > STALE_SECONDS:
            return ""
        return path.read_text().strip()
    except OSError:
        return ""


def acknowledge(ticket_id: str) -> None:
    """Say that the session is gone and the ticket's worktree is nobody's but the console's."""
    _write(ticket_id, "done", "")


def wait(ticket_id: str, seconds: float) -> bool:
    """Whether the run acknowledged the request, within `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        if _file(ticket_id, "done").exists():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS / 5)


def held(ticket_id: str) -> bool:
    """Whether a run is on this ticket's session right now.

    The run writes its pid beside the session and removes it when the session
    ends; a run killed with the session leaves the file, hence the look at the
    pid. Only then is the acknowledgement waited for.
    """
    try:
        pid = int(_file(ticket_id, "live").read_text())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def clear(ticket_id: str) -> None:
    for suffix in ("ask", "done"):
        _file(ticket_id, suffix).unlink(missing_ok=True)


def watch(ticket_id: str, over: threading.Event) -> threading.Event:
    """An event set as soon as this ticket is asked to stop, until `over` is set.

    Handed to `session.run` as its `stop`. A request made before the session
    began is seen at the first look, and ends it as it starts.
    """
    asked = threading.Event()
    try:
        _write(ticket_id, "live", str(os.getpid()))
    except OSError:
        pass  # only the console's wait depends on it, and it does without

    def look() -> None:
        try:
            while not over.is_set():
                if requested(ticket_id):
                    asked.set()
                    # Kept until the session has ended, which is when `over` is set.
                    over.wait()
                    return
                over.wait(POLL_SECONDS)
        finally:
            _file(ticket_id, "live").unlink(missing_ok=True)

    threading.Thread(target=look, name="tr-asked", daemon=True).start()
    return asked
