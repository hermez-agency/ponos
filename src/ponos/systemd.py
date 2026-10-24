"""What the user's systemd says about the timer — read for its next run.

`is-enabled` answers whether the timer is installed, not whether it will ever
fire again. A timer that counts from the boot (OnBootSec) or from the service's
last activation (OnUnitActiveSec) can be enabled, active, and have no next run
at all: that is how the runner went quiet for two hours on 7 September 2026,
behind a green tick. The next run is the thing worth reading, and the timer's
own state is what tells "no next run" apart from "the run is happening now".
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass

UNIT = "ponos.timer"


@dataclass(frozen=True)
class Timer:
    enabled: str
    """What `is-enabled` says — or `no systemd`, `not installed`, `unknown`."""
    substate: str = ""
    """`waiting`, `running` while the service is, `elapsed` once nothing is left."""
    armed: bool = False
    """Whether systemd holds a next run at all."""
    row: str = ""
    """The timer's line in `list-timers`: next, left, last, passed."""
    last: float = 0.0
    """When the timer last fired, as a Unix time — 0 when it never has."""
    next: float = 0.0
    """When it fires next, as a Unix time — 0 when systemd holds no next run."""

    @property
    def running(self) -> bool:
        return self.substate == "running"

    @property
    def stalled(self) -> bool:
        """Enabled, and never going to fire: the one state a tick must not cover.

        A timer whose service is running has no next run either — it is
        computed when the service ends — and that is a run, not a fault.
        """
        return self.enabled == "enabled" and not self.running and not self.armed

    @property
    def label(self) -> str:
        return "stalled" if self.stalled else self.enabled


def read() -> Timer:
    if not shutil.which("systemctl"):
        return Timer(enabled="no systemd")
    try:
        enabled = _systemctl("is-enabled", UNIT).strip() or "not installed"
        shown = _systemctl(
            "show",
            UNIT,
            "-p",
            "SubState,NextElapseUSecRealtime,NextElapseUSecMonotonic",
        )
        listed = _systemctl("list-timers", UNIT, "--no-pager")
        # Apart from `shown`: `--timestamp` is systemd 247's, and an older one
        # refusing it must cost the two times, not the state it is read for.
        stamps = _systemctl(
            "show", UNIT, "--timestamp=unix", "-p", "LastTriggerUSec,NextElapseUSecRealtime"
        )
    except (OSError, subprocess.SubprocessError):
        return Timer(enabled="unknown")
    return describe(enabled, shown, listed, stamps)


def describe(enabled: str, shown: str, listed: str = "", stamps: str = "") -> Timer:
    """`read`, without systemd: what `is-enabled`, `show` and `list-timers` said.

    A monotonic timer reports its next run on the monotonic clock only —
    `NextElapseUSecRealtime` stays empty even while it is armed — and one with
    nothing left says `infinity` there. Either clock holding a value is a run.

    The times come as Unix times (`stamps`, `@1792743558`) rather than from the
    `list-timers` line, whose dates are written in the machine's locale and
    whose empty columns are a bare `-`. The monotonic next run is a span since
    the boot, which `time.monotonic` — the same clock — turns into a date.
    """
    fields = _fields(shown)
    realtime = fields.get("NextElapseUSecRealtime", "")
    monotonic = fields.get("NextElapseUSecMonotonic", "")
    rows = listed.strip().splitlines()
    times = _fields(stamps)
    upcoming = _unix(times.get("NextElapseUSecRealtime", ""))
    since_boot = _span(monotonic)
    if not upcoming and since_boot:
        upcoming = time.time() + since_boot - time.monotonic()
    return Timer(
        enabled=enabled,
        substate=fields.get("SubState", ""),
        armed=bool(realtime) or monotonic not in ("", "infinity"),
        row=rows[1].strip() if len(rows) > 1 else "",
        last=_unix(times.get("LastTriggerUSec", "")),
        next=upcoming,
    )


def _fields(shown: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in shown.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def _unix(value: str) -> float:
    """`@1792743558`, as `--timestamp=unix` writes a time; 0 for anything else."""
    try:
        return float(value[1:]) if value.startswith("@") else 0.0
    except ValueError:
        return 0.0


# A span as systemd writes it: `18h 48min`, `2d 3h 4min 5.123456s`.
SPAN_UNITS = {
    "y": 31557600.0,
    "month": 2629800.0,
    "w": 604800.0,
    "d": 86400.0,
    "h": 3600.0,
    "min": 60.0,
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "μs": 1e-6,
}
SPAN_PART = re.compile(r"(\d+(?:\.\d+)?)(y|month|w|d|h|min|ms|us|μs|s)")


def _span(value: str) -> float:
    """A systemd span in seconds; 0 for `infinity`, nothing, or what is not one."""
    parts = value.split()
    matched = [SPAN_PART.fullmatch(part) for part in parts]
    if not parts or not all(matched):
        return 0.0
    return sum(float(m.group(1)) * SPAN_UNITS[m.group(2)] for m in matched if m)


def _systemctl(*arguments: str) -> str:
    return subprocess.run(
        ["systemctl", "--user", *arguments], capture_output=True, text=True, timeout=5
    ).stdout
