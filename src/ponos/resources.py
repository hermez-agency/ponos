"""What the machine has left, and whether it can still reach anybody.

Three questions a pass asks before it trusts a session, none of them about the
ticket: is there memory for one more, did the network go away under the last
one, and was it the kernel that killed it. A session that dies on exit code 137
says only that it was killed; with eight of them, `tsc`, `vitest` and PHPUnit
side by side the likeliest killer is the OOM killer, and a ticket blocked on
"killed" sends somebody looking for a bug that is not in the ticket.

Everything here answers "I do not know" rather than raising — an unreadable
`/proc/meminfo`, a machine with no `journalctl`, a firewall that eats probes —
because a guard that can itself stop the runner is worse than no guard. Linux
is the one platform the runner lives on, and the one `/proc/meminfo` exists on.
"""

from __future__ import annotations

import re
import shutil
import signal
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import notion

MEMINFO = "/proc/meminfo"

# Where "can this machine reach anybody" is asked: the board, which is the thing
# a pass cannot do without, and GitHub, which is the other half of a ticket.
# Either one answering is a network; both silent is not one.
GITHUB = ("api.github.com", 443)


def available_mb(path: str = MEMINFO) -> int | None:
    """Memory a new process can get without swapping, in MB — None when unknown.

    `MemAvailable`, not `MemFree`: the page cache is free memory the kernel
    gives back on demand, and a machine that has been up for a week has almost
    none of the second and plenty of the first.
    """
    try:
        with open(path, encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def short_of_memory(minimum_mb: int) -> int | None:
    """What is available when it is under `minimum_mb`, else None.

    Zero switches the guard off, and so does a machine that cannot say.
    """
    if minimum_mb <= 0:
        return None
    free = available_mb()
    return free if free is not None and free < minimum_mb else None


def disk_mb(path: Path) -> tuple[int, int] | None:
    """(free, total) in MB on the filesystem `path` lives on — None when unknown.

    Asked of the nearest directory that exists: the state directory is made by
    the first ticket, and a guard that cannot be asked before it must not read
    that as "full".
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return None
    return usage.free // 1_000_000, usage.total // 1_000_000


def short_of_disk(minimum_mb: int, path: Path) -> int | None:
    """What is free when it is under `minimum_mb`, else None — as `short_of_memory`."""
    if minimum_mb <= 0:
        return None
    measured = disk_mb(path)
    return measured[0] if measured is not None and measured[0] < minimum_mb else None


def _board() -> tuple[str, int]:
    parsed = urlparse(notion.endpoint())
    return parsed.hostname or "api.notion.com", parsed.port or (80 if parsed.scheme == "http" else 443)


def reachable(timeout: float = 3.0) -> bool:
    """Does a connection to the board, or to GitHub, open at all?

    A TCP connection rather than an HTTP request: it needs no token, costs
    nothing against Notion's rate limit, and says exactly what is asked — that
    the name resolves and the route is there.
    """
    for host, port in (_board(), GITHUB):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


_NETWORK = re.compile(
    r"could not resolve host|name resolution|network is unreachable|connection (?:timed out|refused|reset)"
    r"|failed to connect|unable to access|no route to host",
    re.IGNORECASE,
)


def network_error(text: str) -> bool:
    """Does what a command printed read as the network being away?"""
    return bool(_NETWORK.search(text or ""))


def signal_name(code: int) -> str:
    """A process's exit status said as the signal that ended it, or ''.

    Two spellings of the same thing: `subprocess` reports a death by signal as
    a negative number, and a shell — or a container's init — reports it as 128
    plus the signal.
    """
    number = -code if code < 0 else code - 128 if 128 < code < 160 else 0
    if not number:
        return ""
    try:
        return f"{signal.Signals(number).name} (signal {number})"
    except ValueError:
        return f"signal {number}"


_OOM = re.compile(r"out of memory|oom-kill|oom_reaper|killed process \d+", re.IGNORECASE)


def oom_killed(seconds: float = 900.0) -> str:
    """The kernel's own line about killing something for want of memory, or ''.

    `journalctl -k` where there is one, `dmesg` otherwise — the second often
    needs a privilege the first does not, which is why neither is assumed.
    Only what happened in the last `seconds`: an OOM from last week says
    nothing about this session.
    """
    since = datetime.now().astimezone() - timedelta(seconds=seconds)
    try:
        journal = subprocess.run(
            ["journalctl", "-k", "--no-pager", "-q", "-o", "short-iso",
             "--since", since.strftime("%Y-%m-%d %H:%M:%S")],
            capture_output=True, text=True, timeout=10,
        )
        if journal.returncode == 0:
            hits = [line for line in journal.stdout.splitlines() if _OOM.search(line)]
            if hits:
                return hits[-1].strip()[:300]
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        dmesg = subprocess.run(
            ["dmesg", "--time-format", "iso"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in reversed(dmesg.stdout.splitlines() if dmesg.returncode == 0 else []):
        if not _OOM.search(line):
            continue
        try:
            when = datetime.fromisoformat(line.split(" ", 1)[0].replace(",", "."))
        except ValueError:
            continue
        if when >= since:
            return line.strip()[:300]
    return ""
