"""Updating the installation from the console, without cutting anything short.

The runner already updates itself between two runs (`update.between_runs`);
what the console adds is *now*, on a click, with somebody watching. The rules
are the same ones, and for the same reason: the update takes **the run lock**.
Every Claude session a ticket starts runs inside a pass that holds it, so
holding it is the one guarantee that no session is running — and that none
starts while the code is being swapped: the timer's next run finds it busy,
claims nothing, and leaves every ticket where it was. A click while a ticket is
running is therefore not refused, it is *queued*: the update waits for the
lock, says so, and can be called off while it waits.

Nothing the page sends chooses what runs. The endpoint takes no command, no
revision and no path: it asks the remote again, under the lock, what the
channel in the configuration says is the newest, and installs that with the
same `update.install` a run uses — which takes the installation back to the
commit it replaced if the new one does not start.

The console is the one process that has to go: it is restarted last, once the
lock is released and "restarting" has been said, and the page reconnects on its
own to whichever version answers. Under its systemd unit that is the unit's
restart; started by hand, the process replaces itself with the same command
line. What was going on is written down first, so the process that comes back
knows it came back from an update.

The console also asks on its own, when it starts and every quarter of an hour
(`watch`): a run asks once an hour at most, and only when the timer is on —
the button would otherwise appear an hour after the commit it offers, or never.
It is one `git fetch` per quarter, from one process, whatever the number of
pages open; a page that loads reads what the last look found.

In a container there is nothing of the kind to do: the header says that a new
version is a new image, and gives the command that pulls it — see `update.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import disk, environment, state
from .. import update as update_module
from ..config import Runner, in_container, state_dir

# The steps a page draws, in order. `waiting` is the lock; `failed` and `done`
# are where it ends.
PHASES = ("idle", "waiting", "downloading", "installing", "restarting", "done", "failed")
UNDER_WAY = ("waiting", "downloading", "installing", "restarting")

# How often a queued update asks for the lock again. A pass lasts minutes; a
# few seconds late is nothing, and a second is a busy loop on a laptop.
POLL_SECONDS = 5.0

# How often the console asks the remote itself — see `watch`.
CHECK_SECONDS = 15 * 60

# What somebody types when the console cannot do it — the CLI does the same thing.
COMMAND = "ponos update"

UNIT = "ponos-web.service"


def log_path() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path / "update.log"


def _marker() -> Path:
    return state_dir() / "web" / "upgrade.json"


def restart() -> None:
    """Put this console on the code now on disk: its unit, or its own command line.

    The unit only when it is *this* process: a console started by hand on
    another port while the unit's one also runs must restart itself, not the
    other one. `--no-block`, because systemd stops this process — and whatever
    it is waiting on — as part of the job.
    """
    if shutil.which("systemctl"):
        shown = subprocess.run(
            ["systemctl", "--user", "show", "--property", "MainPID", "--value", UNIT],
            capture_output=True, text=True, timeout=10,
        )
        if shown.returncode == 0 and shown.stdout.strip() == str(os.getpid()):
            subprocess.run(["systemctl", "--user", "--no-block", "restart", UNIT], timeout=10)
            return
    # The launcher put the version it found on PYTHONPATH, resolved; the same
    # command line would come back on it. The version the link names now is the
    # one to come back on.
    app = update_module.app_dir()
    python = sys.executable
    if app.is_symlink():
        running = str(Path(update_module.__file__).resolve().parents[2] / "src")
        landed = str(app.resolve() / "src")
        parts = os.environ.get("PYTHONPATH", "").split(os.pathsep)
        os.environ["PYTHONPATH"] = os.pathsep.join(
            landed if part == running else part for part in parts
        )
        # And on its environment: the one this process runs in belongs to the
        # version it replaced.
        python = environment.interpreter(app.resolve())
    os.execv(python, [python, *sys.orig_argv[1:]])


class Upgrade:
    """One update at a time, told to every page as it goes."""

    def __init__(
        self,
        publish: Callable[..., None],
        settings: Callable[[], Runner],
        busy: Callable[[], str] = lambda: "",
        *,
        app: Path | None = None,
        reboot: Callable[[], None] = restart,
        poll: float = POLL_SECONDS,
    ) -> None:
        self.publish = publish
        self.settings = settings
        # What else would be cut by a restart — a chat turn, a command — named,
        # or "" when nothing is.
        self.busy = busy
        self.app = app or update_module.app_dir()
        self.reboot = reboot
        self.poll = poll
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self.phase = "idle"
        self.detail = ""
        self.error = ""
        self.target = ""
        self.lines: list[str] = []
        self._page: str | None = None
        self._arrived()

    # -- what the header reads ------------------------------------------------

    def offer(self, local: bool = True) -> dict:
        """What the version in the header says, and whether it can act on it.

        `local` is whether the page asking is on this machine: the endpoint only
        answers there, so a console opened from elsewhere is shown the command
        rather than a button that would be refused.
        """
        why = ""
        if in_container():
            why = update_module.CONTAINER
        elif not local:
            why = "an update is started from the machine the runner is on"
        elif not os.access(self.app.parent, os.W_OK):
            # A version is written beside the one in use, not over it.
            why = f"{self.app.parent} is not writable by the console"
        return {
            **self.known(),
            "automatic": not why,
            "manual": why,
            "command": update_module.PULL if in_container() else COMMAND,
            **self.progress(),
        }

    def known(self) -> dict:
        """What the last check found — the same for every page, near or far."""
        status = update_module.waiting(self.app)
        if self._page is None:
            self._page = update_module.repository_page(self.app)
        return {
            "available": status.stale,
            "current": status.current[:8],
            "latest": status.latest[:8],
            "tag": status.tag,
            # How far behind, and what is coming: the button's number and its tooltip.
            "behind": status.behind if status.stale else 0,
            "commits": status.commits if status.stale else [],
            "notes": update_module.notes(status, self._page) or (
                f"{self._page}/blob/main/CHANGELOG.md" if self._page else ""
            ),
        }

    def progress(self) -> dict:
        return {
            "phase": self.phase,
            "detail": self.detail,
            "error": self.error,
            "target": self.target,
            "log": list(self.lines[-40:]),
            "log_path": str(log_path()),
        }

    # -- asking on its own ----------------------------------------------------

    def watch(self, every: float = CHECK_SECONDS) -> None:
        """Ask the remote now, then every `every` seconds, for as long as the console runs."""
        def loop() -> None:
            while True:
                try:
                    self.look()
                except Exception:  # noqa: BLE001 — a thread that dies stops looking for good
                    pass
                time.sleep(every)

        threading.Thread(target=loop, name="upgrade-check", daemon=True).start()

    def look(self) -> None:
        """One check, said to every page when it changes what the header offers.

        Not while an update is under way — it asks the remote itself, under the
        lock — and not with `runner.auto_update` off: whoever turned it off
        updates with `ponos update`, and asked for no fetch behind their back.
        The run's clock is left alone (`update.remember`).
        """
        settings = self.settings()
        if not settings.auto_update or self.phase in UNDER_WAY:
            return
        before = self.known()
        update_module.check(self.app, settings.update_channel, clock=False)
        after = self.known()
        if after != before:
            self.publish("upgrade", **after, **self.progress())

    # -- what a click does ----------------------------------------------------

    def start(self) -> dict:
        """Queue the update. Refused while one is under way, or with nothing to install."""
        with self._lock:
            if in_container():
                raise RuntimeError(update_module.CONTAINER)
            if self.phase in UNDER_WAY:
                raise RuntimeError("an update is already under way")
            if not update_module.waiting(self.app).stale:
                raise RuntimeError("this is already the newest version known")
            self._cancelled.clear()
            self.error = ""
            self.target = ""
            self.lines = []
            self._set("waiting", "")
            threading.Thread(target=self._work, name="upgrade", daemon=True).start()
        return self.progress()

    def cancel(self) -> dict:
        """Call off an update still waiting for the lock. Past that, it goes on."""
        with self._lock:
            if self.phase != "waiting":
                raise RuntimeError("the update is no longer waiting — it cannot be called off now")
            self._cancelled.set()
        return self.progress()

    # -- the work -------------------------------------------------------------

    def _work(self) -> None:
        try:
            self._run()
        except Exception as error:  # noqa: BLE001 — a thread that dies says nothing
            self._fail(f"the update stopped: {error}")

    def _run(self) -> None:
        said = ""
        while True:
            if self._cancelled.is_set():
                self._say("called off before it started")
                self._set("idle", "")
                return
            other = self.busy()
            if not other:
                try:
                    with state.lock():
                        if self._installed():
                            break
                        return
                except state.Busy:
                    other = "a ticket is running"
            if other != said:
                self._say(f"waiting: {other}")
                self._set("waiting", other)
                said = other
            self._cancelled.wait(self.poll)
        self._set("restarting", "")
        self._say("restarting the console")
        try:
            disk.write_atomic(
                _marker(), json.dumps({"target": self.target, "at": time.time()})
            )
        except OSError:
            pass
        # A moment for the stream to carry "restarting" to the page before the
        # process it is carried by goes away.
        time.sleep(1.0)
        self.reboot()

    def _installed(self) -> bool:
        """Under the lock: ask again, install, and say whether to restart."""
        settings = self.settings()
        self._set("downloading", "")
        self._say(f"asking the remote for the newest version ({settings.update_channel})")
        status = update_module.check(self.app, settings.update_channel)
        if status.reason:
            self._fail(status.reason)
            return False
        if not status.stale:
            self._say("already the newest version — nothing to install")
            self._set("idle", "")
            return False
        self.target = status.tag or status.latest[:8]
        self._say(update_module.describe(status))
        self._set("installing", self.target)
        error = update_module.install(status, settings.interval_seconds, self.app)
        if error:
            self._fail(error)
            return False
        self._say(f"installed {self.target}")
        return True

    # -- saying it ------------------------------------------------------------

    def _set(self, phase: str, detail: str) -> None:
        self.phase = phase
        self.detail = detail
        self.publish("upgrade", **self.progress())

    def _fail(self, error: str) -> None:
        self.error = error
        self._say(f"failed: {error}")
        self._set("failed", "")

    def _say(self, line: str) -> None:
        stamped = f"{datetime.now().strftime('%H:%M:%S')}  {line}"
        self.lines.append(stamped)
        try:
            with open(log_path(), "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().date().isoformat()} {stamped}\n")
        except OSError:
            pass

    def _arrived(self) -> None:
        """Back from an update this console restarted for: say it landed."""
        try:
            said = json.loads(_marker().read_text(encoding="utf-8"))
            _marker().unlink()
        except (OSError, ValueError):
            return
        self.target = str(said.get("target") or "")
        self._say(f"restarted on {self.target}")
        self._set("done", self.target)
