"""`ponos daemon`: the process that holds the places, for as long as the machine is up.

What the systemd timer used to be, and what `ponos run --every` was in a
container, in one process that never ends of its own accord: `ponos.service`
runs it with `Restart=always`, the image runs it beside the console, and
`install.sh` starts it in the background where there is no systemd. The loop
itself is `scheduler.Scheduler.serve`; this module is what is around it — the
scheduler's place on the machine, the signals, the configuration read again
when it changes, and the `exec` that puts the daemon on a new version.

**Signals are how the rest of Ponos talks to it.** SIGUSR1 is « look now »: a
ticket made ready from the console or the MCP, a `ponos run`, a launch asked
for (see launches.py) — `nudge` sends it. SIGHUP is « restart on the code on
disk »: the console's update button sends it once the new version is in place
(`reload`). SIGTERM and SIGINT stop it — the sessions in flight do not stop
with it: they are not its children (tether.py), and the next daemon adopts
them (adoption.py). Nothing a signal does is done in its handler: each only
sets an event the loop reads.

**A restart is an `exec`.** Same pid, so systemd sees nothing but a process
that carries on; the launcher is read again, so the version is the one `app`
points at now; and the tethers started by the old image are still children
of this pid, which is what lets the new image reap them.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from types import FrameType
from typing import TYPE_CHECKING

from . import __version__, state, systemd
from . import config as config_module
from . import update as update_module

if TYPE_CHECKING:
    from .scheduler import Signals

logger = logging.getLogger(__name__)

# How often the configuration file is looked at for a change.
CONFIG_GLANCE = 5.0


def holder() -> int:
    """The pid holding the scheduler's place, or 0 when nobody does."""
    return int(state.scheduler().get("pid") or 0)


def _send(number: signal.Signals) -> int:
    pid = holder()
    if not pid or pid == os.getpid():
        return 0
    try:
        os.kill(pid, number)
    except (ProcessLookupError, PermissionError):
        return 0
    return pid


def nudge() -> int:
    """Ask the scheduler to look at the board now; its pid, or 0 when nobody holds the place."""
    return _send(signal.SIGUSR1)


def reload() -> int:
    """Ask the daemon to restart on the code on disk, once its work in flight allows it."""
    return _send(signal.SIGHUP)


def listen(signals: Signals) -> None:
    """Turn the signals into the events the loop reads — and nothing more, in a handler."""

    def woken(number: int, frame: FrameType | None) -> None:
        signals.nudge()

    def reloaded(number: int, frame: FrameType | None) -> None:
        signals.reload.set()
        signals.wake.set()

    def stopped(number: int, frame: FrameType | None) -> None:
        if signals.stop.is_set():
            # Asked twice: whoever asked does not want to wait for the grace.
            os._exit(0)
        signals.stop.set()
        signals.wake.set()

    signal.signal(signal.SIGUSR1, woken)
    signal.signal(signal.SIGHUP, reloaded)
    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGINT, stopped)


def _stamp() -> float:
    try:
        return config_module.config_path().stat().st_mtime
    except OSError:
        return 0.0


def serve(*, dry_run: bool = False) -> int:
    """The daemon, until it is stopped; 0 unless it could not start."""
    from .runner import Runner

    try:
        with state.scheduling():
            ending = _serve(Runner, dry_run=dry_run)
    except state.Busy as error:
        print(f"{error} — this one leaves it there", flush=True)
        return 0
    if ending == "reload":
        _restart()
    return 0


def _serve(runner_class: type, *, dry_run: bool) -> str:
    from .scheduler import Signals

    signals = Signals()
    listen(signals)
    if not config_module.in_container() and update_module.app_dir().is_symlink():
        if systemd.migrate(update_module.units_dir()):
            print("the timer is gone: ponos.service runs the daemon from now on", flush=True)
    waiting = False
    while not _usable():
        # A container's first minutes, or a fresh install: the console is up,
        # nobody has given it a board yet. Said once, rather than every minute.
        if not waiting:
            print("no board configured yet — the daemon starts once there is one", flush=True)
            waiting = True
        seen = _stamp()
        while _stamp() == seen:
            if signals.stop.wait(CONFIG_GLANCE):
                return "stop"
            if signals.reload.is_set():
                return "reload"
    configuration = config_module.load()
    runner = runner_class(configuration, dry_run=dry_run)
    print(
        f"ponos {__version__} — daemon on pid {os.getpid()}, "
        f"{configuration.runner.max_concurrent} place(s)",
        flush=True,
    )
    watcher = threading.Thread(
        target=_watch_config, args=(runner, signals), name="tr-config", daemon=True
    )
    watcher.start()
    ending: str = runner.serve(signals)
    return ending


def _usable() -> bool:
    try:
        config_module.load()
    except config_module.ConfigError:
        return False
    return True


def _watch_config(runner: object, signals: Signals) -> None:
    """Read the configuration again when its file changes — the console edits it.

    Most of it is read off `runner.config` at the moment it is needed, so the
    new one is swapped in and that is all. What `reconfigure` cannot swap
    under the sessions using it restarts the daemon instead, as on an update.
    """
    seen = _stamp()
    while not (signals.stop.is_set() or signals.reload.is_set()):
        time.sleep(CONFIG_GLANCE)
        stamp = _stamp()
        if stamp == seen:
            continue
        seen = stamp
        try:
            fresh = config_module.load()
        except config_module.ConfigError as error:
            print(f"  ! the configuration was not read again: {error}", flush=True)
            continue
        if getattr(runner, "reconfigure", None) is None or not runner.reconfigure(fresh):  # type: ignore[attr-defined]
            print("the board's settings changed — restarting on them", flush=True)
            signals.reload.set()
        signals.nudge()


def command() -> list[str]:
    """What the daemon `exec`s: the launcher when installed, this Python otherwise."""
    if update_module.app_dir().is_symlink():
        binary = update_module.launcher()
        if binary.exists():
            return [str(binary), "daemon", *sys.argv[2:]]
    return [sys.executable, "-m", "ponos", "daemon", *sys.argv[2:]]


def _restart() -> None:
    """Become the daemon of the code on disk: same pid, new image."""
    arguments = command()
    print(f"↻ restarting: {' '.join(arguments)}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    source = str(update_module.app_dir() / "src")
    if not update_module.app_dir().is_symlink():
        os.environ["PYTHONPATH"] = os.pathsep.join(
            part for part in (source, os.environ.get("PYTHONPATH", "")) if part
        )
    os.execv(arguments[0], arguments)
