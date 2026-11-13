"""The session logs' ceiling: `logs/` never holds more than `log_max_mb`.

Every session writes a log, and so do the `-on`, `-talk`, `-review` and `-kind`
passes beside it: on 13 November 2026 the folder held 86 000 files for 1.5 GB,
and nothing said it would stop. The daily tidy already drops what is older than
`log_retention_days`, but an age is not a size — a busy week fills a disk well
inside two weeks — so the folder has a ceiling of its own, service journal
included.

Past the ceiling, the oldest files (by modification date) go first, down to
`LOW_WATER` of it rather than to the ceiling itself: a rotation that stops right
under the line would run again at the next session. What is never taken, however
far over the folder is:

- the logs of a ticket a session is working on, or that the board says is
  running, blocked, in review or validated — a blocked ticket's log is what its
  answer is read against, and a validated one is still being delivered;
- `ponos.log`, the file the service is writing now.

When nothing but those is left above the ceiling, nothing more is removed: it is
said (a WARNING in the journal, `ponos doctor`) and left to a person, because a
log that is in use is worth more than the room it takes.

The board is read only when the folder is over the ceiling — the usual pass is
one walk of one directory. What a rotation found is kept in `logs-rotation.json`
for `ponos doctor`, which should not have to read the board to say it.

`ponos.db` is not touched: a run keeps its outcome and its cost when its file
goes (`ponos logs <id>` then says the log was removed by the rotation).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import disk, state
from .config import state_dir

logger = logging.getLogger(__name__)

# A rotation goes down to this share of the ceiling.
LOW_WATER = 0.9
# What the log of a session is called: `20261113-120000-1a2b3c4d`, then a suffix
# for the passes beside it (`-on`) and an extension or two.
_TICKET = re.compile(r"^\d{8}-\d{6}-([0-9a-f]{8})(?=[-.]|$)")
SERVICE = "ponos.log"


@dataclass
class Rotation:
    """What a rotation did, and what it found."""

    at: float = 0.0
    removed: int = 0
    freed: int = 0
    size: int = 0
    cap: int = 0
    # True when the folder is still over the ceiling and what is left is all
    # protected: nothing more could be taken.
    blocked: bool = False


def stamp_path() -> Path:
    return state_dir() / "logs-rotation.json"


def ticket_of(name: str) -> str:
    """The short id of the ticket a log belongs to, or "" for one that is nobody's."""
    found = _TICKET.match(name)
    return found.group(1) if found else ""


def size(directory: Path | None = None) -> int:
    """Bytes under the logs directory, links not followed."""
    total = 0
    for here, _, names in os.walk(directory or state.logs_dir()):
        for name in names:
            try:
                total += os.lstat(os.path.join(here, name)).st_size
            except OSError:
                continue
    return total


def rotate(cap: int, protected: set[str], directory: Path | None = None) -> Rotation:
    """Remove the oldest logs until the folder is under `LOW_WATER` of `cap` bytes.

    `protected` are the short ids of the tickets whose logs stay. Nothing is
    removed while the folder is at or under `cap`.
    """
    directory = directory or state.logs_dir()
    found = Rotation(at=time.time(), cap=cap, size=size(directory))
    if found.size <= cap:
        return found
    target = int(cap * LOW_WATER)
    files: list[tuple[float, int, Path]] = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return found
    for entry in entries:
        try:
            if not entry.is_file(follow_symlinks=False) or entry.name == SERVICE:
                continue
            if ticket_of(entry.name) in protected:
                continue
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        files.append((stat.st_mtime, stat.st_size, Path(entry.path)))
    for _, length, path in sorted(files):
        if found.size <= target:
            break
        try:
            path.unlink()
        except OSError:
            continue
        found.removed += 1
        found.freed += length
        found.size -= length
    found.blocked = found.size > cap
    return found


def keep(found: Rotation) -> None:
    """Write down what a rotation found, for `doctor` — readable by this account only."""
    try:
        path = stamp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", opener=disk.opener()) as handle:
            json.dump(asdict(found), handle)
    except OSError:
        logger.warning("the rotation's result could not be written", exc_info=True)


def last() -> Rotation | None:
    """The last rotation that ran, or None when none has."""
    try:
        raw = json.loads(stamp_path().read_text(encoding="utf-8"))
        return Rotation(**raw)
    except (OSError, ValueError, TypeError):
        return None
