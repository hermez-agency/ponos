"""Asking the daemon to start one ticket now, and hearing what it did.

`ponos run --ticket X` and the console's « Run now » are two other processes:
the daemon is the one that holds the places, so it is the one that decides
whether there is one for X. The request is a file under the state directory,
the daemon is woken to read it (see daemon.py), and its answer is a second
file beside it — the same shape as stopping.py, for the same reason: a signal
carries no answer.

An answer is one of three words: `started` (X is in a place), `full` (no place
was free, and nothing was forced) or `refused` (X cannot be run: cancelled,
unknown, unreadable). A request nobody answers within its wait — no daemon,
or one too busy to look — is the caller's to drop.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import disk
from .config import state_dir

# A request older than this is a leftover of a caller that gave up: the next
# daemon to read it must not start a ticket nobody is waiting for any more.
STALE_SECONDS = 120


def _directory() -> Path:
    return state_dir() / "launches"


def ask(ticket: str, *, force: bool = False) -> str:
    """Write the request; its identifier, for `wait`."""
    identifier = uuid.uuid4().hex
    path = _directory() / f"{identifier}.ask"
    path.parent.mkdir(parents=True, exist_ok=True)
    disk.write_atomic(path, json.dumps({"ticket": ticket, "force": force, "at": time.time()}))
    return identifier


def pending() -> list[tuple[str, dict[str, Any]]]:
    """The requests not answered yet, oldest first — stale ones dropped on the way."""
    try:
        paths = sorted(_directory().glob("*.ask"), key=lambda path: path.stat().st_mtime)
    except OSError:
        return []
    found = []
    for path in paths:
        try:
            asked = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        if not isinstance(asked, dict) or time.time() - float(asked.get("at", 0)) > STALE_SECONDS:
            path.unlink(missing_ok=True)
            continue
        found.append((path.stem, asked))
    return found


def answer(identifier: str, status: str, message: str = "") -> None:
    directory = _directory()
    (directory / f"{identifier}.ask").unlink(missing_ok=True)
    try:
        disk.write_atomic(
            directory / f"{identifier}.answer", json.dumps({"status": status, "message": message})
        )
    except OSError:
        pass


def wait(identifier: str, seconds: float) -> dict[str, str] | None:
    """The daemon's answer, within `seconds` — None, the request withdrawn, when there is none."""
    path = _directory() / f"{identifier}.answer"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            said = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.1)
            continue
        path.unlink(missing_ok=True)
        return {"status": str(said.get("status", "")), "message": str(said.get("message", ""))}
    (_directory() / f"{identifier}.ask").unlink(missing_ok=True)
    return None
