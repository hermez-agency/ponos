"""What the user's systemd says about the daemon — and the timer it replaced, taken down.

The runner was a timer that started a pass every `interval_seconds`. It is now
one service that never ends (`ponos daemon`, `Restart=always`): what is worth
reading of it is whether it is enabled, whether it is running, and since when.
`is-enabled` alone is not enough — an enabled unit can be failed, or stopped by
hand — so `ActiveState` is read beside it.

`migrate` is the one-time move from the timer to the service, done by the
daemon itself the first time it starts on an installation that still has the
timer: an update installed by a version from before the daemon writes the new
service, the old timer starts it once more, and the daemon that comes up turns
the timer off and the service on. Nobody has to type anything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

SERVICE = "ponos.service"
TIMER = "ponos.timer"

# What the service's unit sets so that its sessions yield to the desktop.
PRIORITY = ("Nice", "CPUWeight", "IOSchedulingClass", "MemoryHigh")


@dataclass(frozen=True)
class Service:
    enabled: str
    """What `is-enabled` says — or `no systemd`, `not installed`, `unknown`."""
    active: str = ""
    """`ActiveState`: `active`, `inactive`, `failed`, `activating`…"""
    substate: str = ""
    restarts: int = 0
    """How many times systemd has had to start it again."""

    @property
    def running(self) -> bool:
        return self.active == "active"

    @property
    def label(self) -> str:
        """One word for the header: `running`, or why it is not."""
        if self.running:
            return "running"
        if self.enabled != "enabled":
            return self.enabled
        return self.active or "stopped"


def looping() -> bool:
    """Whether the `ponos daemon` the installer started without systemd is still there.

    Where there is no systemd the installer starts the daemon in the background
    and keeps its PID in `web/run.pid`. A restart leaves the file behind and
    may hand the number to somebody else, so the command line is read too.
    """
    try:
        pid = int((config.state_dir() / "web" / "run.pid").read_text(encoding="utf-8").strip())
        arguments = os.fsdecode(Path(f"/proc/{pid}/cmdline").read_bytes()).split("\0")
    except (OSError, ValueError):
        return False
    return "daemon" in arguments


def read() -> Service:
    if not shutil.which("systemctl"):
        return Service(enabled="no systemd")
    try:
        enabled = _systemctl("is-enabled", SERVICE).strip() or "not installed"
        shown = _systemctl("show", SERVICE, "-p", "ActiveState,SubState,NRestarts")
    except (OSError, subprocess.SubprocessError):
        return Service(enabled="unknown")
    return describe(enabled, shown)


def describe(enabled: str, shown: str) -> Service:
    """`read`, without systemd: what `is-enabled` and `show` said."""
    fields = _fields(shown)
    try:
        restarts = int(fields.get("NRestarts", "0") or 0)
    except ValueError:
        restarts = 0
    return Service(
        enabled=enabled,
        active=fields.get("ActiveState", ""),
        substate=fields.get("SubState", ""),
        restarts=restarts,
    )


def priority() -> dict[str, str]:
    """What systemd applies to the daemon's service, as `show` writes it — empty when it cannot tell.

    Read off the loaded unit rather than the file: a unit rewritten without a
    `daemon-reload` still runs its sessions at the old rank.
    """
    if not shutil.which("systemctl"):
        return {}
    try:
        return _fields(_systemctl("show", SERVICE, "-p", ",".join(PRIORITY)))
    except (OSError, subprocess.SubprocessError):
        return {}


def migrate(units: Path) -> bool:
    """Take the timer of the pass model down, and leave the service on; whether there was one.

    Only where the timer is installed in `units` — an installation `install.sh`
    made before the daemon. `--now` stops the timer, not the service it
    started: that service is the daemon asking.
    """
    timer = units / TIMER
    if not timer.exists() or not shutil.which("systemctl"):
        return False
    try:
        _systemctl("disable", "--now", TIMER)
        timer.unlink(missing_ok=True)
        _systemctl("daemon-reload")
        _systemctl("enable", SERVICE)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _fields(shown: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in shown.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def _systemctl(*arguments: str) -> str:
    return subprocess.run(
        ["systemctl", "--user", *arguments], capture_output=True, text=True, timeout=10
    ).stdout
