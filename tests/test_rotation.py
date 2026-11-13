"""`rotation.py`: the ceiling of the logs folder."""

from __future__ import annotations

import os
import time
from pathlib import Path

from support import case

from ponos import rotation


def _log(directory: Path, name: str, size: int, age: float) -> Path:
    """A file of `size` bytes last written `age` seconds ago."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"x" * size)
    moment = time.time() - age
    os.utime(path, (moment, moment))
    return path


@case
def the_oldest_logs_go_first_down_to_ninety_percent(state_home: Path) -> None:
    logs = state_home / "logs"
    names = [f"20261101-00000{n}-0000000{n}.jsonl" for n in range(1, 8)]
    # 7 files of 100 bytes, the first the oldest: 700 bytes against a ceiling of 600.
    files = [_log(logs, name, 100, 1000 - n * 100) for n, name in enumerate(names)]
    found = rotation.rotate(600, set())
    # 90 % of 600 is 540: two files out (500), not one (600 is still over).
    assert found.removed == 2 and found.freed == 200 and found.size == 500
    assert [path.exists() for path in files] == [False, False, True, True, True, True, True]
    assert not found.blocked


@case
def a_folder_under_its_ceiling_is_left_alone(state_home: Path) -> None:
    kept = _log(state_home / "logs", "20261101-000001-00000001.jsonl", 100, 50)
    found = rotation.rotate(100, set())
    assert found.removed == 0 and kept.exists() and found.size == 100


@case
def protected_tickets_and_the_service_journal_stay(state_home: Path) -> None:
    logs = state_home / "logs"
    service = _log(logs, "ponos.log", 300, 5000)
    blocked = _log(logs, "20261101-000001-aaaaaaaa.jsonl", 300, 4000)
    blocked_on = _log(logs, "20261101-000002-aaaaaaaa-on.jsonl", 100, 3900)
    free = _log(logs, "20261101-000003-bbbbbbbb.jsonl", 100, 3000)
    older_service = _log(logs, "ponos.log.1", 100, 6000)
    found = rotation.rotate(500, {"aaaaaaaa"})
    assert service.exists() and blocked.exists() and blocked_on.exists()
    assert not free.exists() and not older_service.exists()
    assert found.size == 700 and found.blocked, "only protected files remain, over the ceiling"


@case
def a_ticket_is_read_from_the_name_of_its_logs(state_home: Path) -> None:
    assert rotation.ticket_of("20261101-120000-1a2b3c4d.jsonl") == "1a2b3c4d"
    assert rotation.ticket_of("20261101-120000-1a2b3c4d-on.jsonl.gz") == "1a2b3c4d"
    assert rotation.ticket_of("20261101-120000-1a2b3c4d.setup.log") == "1a2b3c4d"
    assert rotation.ticket_of("ponos.log") == ""
    assert rotation.ticket_of("20261101-120000-ideas-1a2b3c4d.jsonl") == ""


@case
def the_last_rotation_is_remembered_for_the_doctor(state_home: Path) -> None:
    assert rotation.last() is None
    rotation.keep(rotation.Rotation(at=1.0, removed=3, freed=30, size=7, cap=10, blocked=True))
    found = rotation.last()
    assert found is not None and found.removed == 3 and found.blocked
