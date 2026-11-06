"""The machine group: what this computer gives a session.

Tools, disk, memory, load, the daemon that holds the places and the priority
sessions run at. What Ponos's own installation says — its channels, version,
database, leftovers — is `installation`, apart for its length only.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

from .. import browser, cleanup, disk, git, leftovers, local_ci, resources, state, systemd
from .. import config as config_module
from .check import ERROR, INFO, OK, WARN, Check, _check, _fix, _installing


def _machine(config: config_module.Config) -> list[Check]:
    return [
        *_tools(),
        *_docker(config),
        *_browser(config),
        *_disk(config),
        *_private_state(),
        *_memory(config),
        *_load(config),
        *_runner(config),
    ]


DOCKER_INSTALL = "https://docs.docker.com/engine/install/"


def _docker(config: config_module.Config) -> list[Check]:
    """Whether Docker answers, which is what the local CI before a pull request needs.

    A warning only when `runner.local_ci` asks for it: a runner that never
    turned it on has lost nothing, and the line says what Docker would offer.
    """
    found = local_ci.docker(fresh=True)
    wanted = config.runner.local_ci
    if found.available:
        return [
            _check(
                "machine.docker",
                OK,
                "Docker",
                "Docker {{version}} answers: the local CI runs before every pull request."
                if wanted
                else "Docker {{version}} answers: the local CI before pull requests can be turned on.",
                params={"version": found.version},
            )
        ]
    said = (
        "Docker is installed, but its daemon does not answer."
        if found.installed
        else "Docker is not installed."
    )
    return [
        _check(
            "machine.docker",
            WARN if wanted else INFO,
            "Docker",
            said,
            cause="runner.local_ci is on: tickets go on without their local CI until Docker answers."
            if wanted
            else "The local CI before pull requests needs it, and stays off until it answers.",
            evidence=found.error,
            url=DOCKER_INSTALL,
            steps=[
                "Start its daemon (`sudo systemctl start docker`), and let this account use it (the `docker` group)."
                if found.installed
                else "Install Docker Engine, then check again."
            ],
        )
    ]


def _browser(config: config_module.Config) -> list[Check]:
    """Ponos's browser: Playwright and its Chromium, and the command that installs them.

    A warning when `[browser] default` sends external tickets to it — they
    fall back on Claude in Chrome until it is there — and a note otherwise.
    """
    title = "Ponos's browser"
    wanted = config.browser.default == browser.PONOS
    if not browser.available():
        said = "Playwright is not installed: external tickets use Claude in Chrome."
    elif not browser.chromium():
        said = (
            "Playwright is installed, but not its Chromium: external tickets use Claude in Chrome."
        )
    else:
        return [
            _check(
                "machine.browser",
                OK,
                title,
                "Playwright and its Chromium are installed: external tickets can sign in with the vault."
                if wanted
                else "Playwright and its Chromium are installed; browser.default sends external tickets to Claude in Chrome.",
            )
        ]
    commands = browser.install_commands()
    return [
        _check(
            "machine.browser",
            WARN if wanted else INFO,
            title,
            said,
            cause="browser.default is ponos: every external ticket falls back on Claude in Chrome."
            if wanted
            else "",
            steps=["Install it into Ponos's Python: `{{install}}`, then `{{chromium}}`."],
            params={"install": commands[0], "chromium": commands[1]},
        )
    ]


def _tools() -> list[Check]:
    """git, without which nothing runs, and ffmpeg, without which a video is not looked at."""
    found: list[Check] = []
    if shutil.which("git"):
        found.append(
            _check(
                "machine.git",
                OK,
                "git",
                "{{version}}.",
                params={"version": (git.run(["git", "--version"]).out.splitlines() or [""])[0]},
            )
        )
    else:
        found.append(
            _check(
                "machine.git",
                ERROR,
                "git",
                "git is not installed.",
                cause="Every ticket works in a git worktree.",
                **_installing("git"),
            )
        )
    if shutil.which("ffmpeg"):
        found.append(
            _check(
                "machine.ffmpeg",
                OK,
                "ffmpeg",
                "A video sent to the workspace is looked at through its frames.",
            )
        )
    elif _video_sent():
        found.append(
            _check(
                "machine.ffmpeg",
                WARN,
                "ffmpeg",
                "ffmpeg is missing: a video sent to the workspace cannot be looked at.",
                **_installing("ffmpeg"),
            )
        )
    else:
        found.append(
            _check(
                "machine.ffmpeg",
                INFO,
                "ffmpeg",
                "Optional: with ffmpeg, a video sent to the workspace can be looked at through its frames.",
            )
        )
    return found


def _has_display() -> bool:
    """A graphical session to notify on: always true off Linux, where notify-send is not the way."""
    if not sys.platform.startswith("linux"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _video_sent() -> bool:
    """Whether a video was ever dropped in the workspace: only then is a missing ffmpeg a loss."""
    root = config_module.state_dir() / "web" / "attachments"
    try:
        return any(
            path.suffix.lower().lstrip(".") in ("mp4", "webm", "mov") for path in root.glob("*/*")
        )
    except OSError:
        return False


def _disk(config: config_module.Config) -> list[Check]:
    found: list[Check] = []
    runner = config.runner
    state = config_module.state_dir()
    found.append(
        _check(
            "machine.disk",
            INFO,
            "Disk space",
            "{{state}} holds {{sizes}}.",
            params={
                "state": str(state),
                "sizes": ", ".join(
                    f"{place} {cleanup.human(size)}"
                    for place, size in {**cleanup.sizes(), "tmp": cleanup.tmp_size()}.items()
                ),
            },
        )
    )
    reclaimable = leftovers.docker_reclaimable() if runner.docker_prune else ""
    if reclaimable:
        found.append(
            _check(
                "machine.disk",
                INFO,
                "Disk space",
                "Docker could give back {{reclaimable}}; the daily tidy prunes it.",
                params={"reclaimable": reclaimable},
            )
        )
    days = {"days": str(runner.log_retention_days)}
    if runner.log_retention_days <= 0:
        found.append(
            _check(
                "machine.tidy",
                WARN,
                "Tidying",
                "runner.log_retention_days = 0: nothing is ever tidied on its own.",
            )
        )
    elif runner.clean_done_worktrees:
        found.append(
            _check(
                "machine.tidy",
                OK,
                "Tidying",
                "Tidied once a day: logs, and the worktrees of tickets done, older than {{days}} days.",
                params=days,
            )
        )
    else:
        found.append(
            _check(
                "machine.tidy",
                OK,
                "Tidying",
                "Logs older than {{days}} days are dropped once a day.",
                params=days,
            )
        )
        found.append(
            _check(
                "machine.tidy",
                INFO,
                "Tidying",
                "runner.clean_done_worktrees = false: worktrees stay until `ponos clean --force`.",
            )
        )
    room = resources.disk_mb(state)
    minimum = runner.min_free_disk_mb
    if room is None:
        found.append(
            _check(
                "machine.disk",
                WARN,
                "Disk space",
                "The free disk space cannot be read here: the disk guard cannot tell.",
            )
        )
    elif minimum <= 0:
        found.append(
            _check(
                "machine.disk",
                INFO,
                "Disk space",
                "runner.min_free_disk_mb = 0: no disk guard; {{free}} MB free.",
                params={"free": str(room[0])},
            )
        )
    elif room[0] < minimum:
        found.append(
            _check(
                "machine.disk",
                ERROR,
                "Disk space",
                "{{free}} MB free, under the {{minimum}} MB a ticket needs to start.",
                params={"free": str(room[0]), "minimum": str(minimum)},
                cause="Worktrees and logs of past tickets fill the disk; no ticket is started until it has room.",
                steps=[
                    "Free some room: Settings › Disk tidies the logs and the finished worktrees."
                ],
            )
        )
    else:
        found.append(
            _check(
                "machine.disk",
                OK,
                "Disk space",
                "{{free}} MB free (a ticket starts above {{minimum}} MB).",
                params={"free": str(room[0]), "minimum": str(minimum)},
            )
        )
    leftover = git.residues(state / "worktrees")
    if leftover:
        found.append(
            _check(
                "machine.residue",
                WARN,
                "Worktrees",
                "{{count}} worktree directories are only residue (no .git: files a container created).",
                params={"count": str(len(leftover))},
                steps=["Run `ponos clean --force` to empty them."],
            )
        )
    else:
        found.append(
            _check("machine.residue", OK, "Worktrees", "No residue in the worktrees directory.")
        )
    if last := cleanup.tidied_at():
        found.append(
            _check(
                "machine.tidy",
                INFO,
                "Tidying",
                "Last tidied {{at}}.",
                params={"at": f"{datetime.fromtimestamp(last):%Y-%m-%d %H:%M}"},
            )
        )
    return found


# Clones of somebody's repository, not what Ponos keeps: their files are the
# project's, with the modes git gave them, and walking them is a node_modules.
CHECKOUTS = ("worktrees", "scratch", git.LEFTOVERS)


def _private_state() -> list[Check]:
    """What under the state directory another account could read.

    The directory is closed at each launch (`config.private_state`), which is
    what protects the rest; what was written inside it with the umask — chat
    screenshots, transcripts — is said here, and tightened by the fix.
    """
    state = config_module.state_dir()
    title = "State directory"
    loose = disk.open_to_others(state, CHECKOUTS)
    if not loose:
        return [
            _check(
                "machine.private",
                OK,
                title,
                "Nothing in {{state}} can be read by other accounts.",
                params={"state": str(state)},
            )
        ]
    shown = ", ".join(str(path.relative_to(state)) for path in loose[:3])
    shown += "…" if len(loose) > 3 else ""
    return [
        _check(
            "machine.private",
            ERROR if state in loose else WARN,
            title,
            "{{count}} entries in {{state}} can be read by other accounts ({{shown}}).",
            params={"count": str(len(loose)), "state": str(state), "shown": shown},
            cause="Written with the umask: chat attachments, screenshots, transcripts.",
            steps=["Run `chmod -R go-rwx {{state}}`."],
            fix=_fix(
                "state_private",
                "Tighten",
                "Make what is in {{state}} readable by this account only?",
                [],
            ),
        )
    ]


def _memory(config: config_module.Config) -> list[Check]:
    free, minimum = resources.available_mb(), config.runner.min_free_memory_mb
    params = {"free": str(free), "minimum": str(minimum)}
    if free is None:
        return [
            _check(
                "machine.memory",
                INFO,
                "Memory",
                "/proc/meminfo is unreadable here: the memory guard cannot tell.",
            )
        ]
    if minimum <= 0:
        return [
            _check(
                "machine.memory",
                INFO,
                "Memory",
                "runner.min_free_memory_mb = 0: no memory guard; {{free}} MB available.",
                params=params,
            )
        ]
    if free < minimum:
        return [
            _check(
                "machine.memory",
                WARN,
                "Memory",
                "{{free}} MB available, under runner.min_free_memory_mb ({{minimum}} MB): no session is started until it is back.",
                params=params,
            )
        ]
    return [
        _check(
            "machine.memory",
            OK,
            "Memory",
            "{{free}} MB available (a session starts above {{minimum}} MB).",
            params=params,
        )
    ]


def _load(config: config_module.Config) -> list[Check]:
    measured, per_core = resources.load(), config.runner.max_load_per_core
    if measured is None:
        return [
            _check(
                "machine.load",
                INFO,
                "Load",
                "The load average is unreadable here: the load guard cannot tell.",
            )
        ]
    load, cores = measured
    params = {
        "load": f"{load:.1f}",
        "cores": str(cores),
        "per_core": f"{per_core:g}",
        "ceiling": f"{per_core * cores:g}",
    }
    if per_core <= 0:
        return [
            _check(
                "machine.load",
                INFO,
                "Load",
                "runner.max_load_per_core = 0: no load guard; load {{load}} on {{cores}} cores.",
                params=params,
            )
        ]
    if load > per_core * cores:
        return [
            _check(
                "machine.load",
                WARN,
                "Load",
                "Load {{load}} on {{cores}} cores, above runner.max_load_per_core ({{per_core}}, so {{ceiling}}): no session is started until it comes down.",
                params=params,
            )
        ]
    return [
        _check(
            "machine.load",
            OK,
            "Load",
            "Load {{load}} on {{cores}} cores (a session starts at {{ceiling}} or below).",
            params=params,
        )
    ]


def _runner(config: config_module.Config) -> list[Check]:
    """What holds the places, how many there are, and how a session is let loose."""
    runner = config.runner
    every = {
        "interval": str(runner.interval_seconds),
        "places": str(runner.max_concurrent),
        "per_project": str(runner.max_concurrent_per_project),
    }
    found: list[Check] = []
    if config_module.in_container():
        found.append(
            _check(
                "machine.runner",
                OK,
                "Runner",
                "The daemon starts with the container (`ponos daemon`): {{places}} place(s), the board looked at again every {{interval}}s at the latest.",
                params=every,
            )
        )
    elif not shutil.which("systemctl"):
        if state.scheduler():
            found.append(
                _check(
                    "machine.runner",
                    OK,
                    "Runner",
                    "No systemd here: `ponos daemon` runs in the background, {{places}} place(s).",
                    params=every,
                )
            )
        else:
            found.append(
                _check(
                    "machine.runner",
                    WARN,
                    "Runner",
                    "No systemd here and no daemon: no ticket is taken until `ponos daemon` is started (`ponos run` for a single run).",
                )
            )
    else:
        found.append(
            _check(
                "machine.places",
                INFO,
                "Runner",
                "{{places}} place(s), {{per_project}} per project; the board is looked at again every {{interval}}s at the latest.",
                params=every,
            )
        )
        found.append(_service(systemd.read()))
        priority = _priority(systemd.priority())
        if priority:
            found.append(priority)
    found.append(
        _check(
            "settings.permissions",
            INFO,
            "Sessions",
            "permission_mode = {{mode}}.",
            params={"mode": runner.permission_mode},
        )
    )
    found.append(_workers(runner))
    if runner.progress:
        found.append(
            _check(
                "settings.progress",
                INFO,
                "Sessions",
                "Live steps are written into the ticket every {{every}}s.",
                params={"every": str(runner.progress_interval_seconds)},
            )
        )
    else:
        found.append(
            _check(
                "settings.progress",
                INFO,
                "Sessions",
                "runner.progress = false: the ticket says nothing until the end.",
            )
        )
    return found


def _workers(runner: config_module.Runner) -> Check:
    """How many test workers a session is given — see resources.share."""
    count = resources.share(runner.session_workers, runner.max_concurrent)
    params = {
        "workers": str(count),
        "cores": str(resources.cores()),
        "concurrent": str(runner.max_concurrent),
    }
    if runner.session_workers > 0:
        return _check(
            "settings.workers",
            INFO,
            "Sessions",
            "runner.session_workers = {{workers}}: each session's tests take {{workers}} workers at most.",
            params=params,
        )
    return _check(
        "settings.workers",
        INFO,
        "Sessions",
        "Each session's tests take {{workers}} workers at most: {{cores}} cores shared by runner.max_concurrent ({{concurrent}}).",
        params=params,
    )


def _service(service: systemd.Service) -> Check:
    """The daemon's unit, and an error while it is not running.

    `enabled` is what `is-enabled` says, and it says nothing of a unit that
    failed or was stopped by hand: `ActiveState` is what tells.
    """
    if service.enabled != "enabled":
        return _check(
            "machine.runner",
            ERROR,
            "Runner",
            "The runner's daemon is {{state}}: no ticket is picked up.",
            params={"state": service.enabled},
            cause="`ponos service on` was never run, or ponos.service was disabled.",
            steps=["In a terminal on this machine, run `ponos service on`."],
        )
    if not service.running:
        return _check(
            "machine.runner",
            ERROR,
            "Runner",
            "The runner's daemon is enabled but not running ({{state}}).",
            params={"state": service.active or "stopped"},
            cause="ponos.service stopped, or keeps failing to start.",
            steps=[
                "In a terminal on this machine, run `ponos service on`.",
                "If it stops again, read why: `journalctl --user -u ponos.service -n 50`.",
            ],
        )
    return _check("machine.runner", OK, "Runner", "The runner's daemon is running.")


# `IOSchedulingClass` as `show` writes it: the kernel's number for the class.
IO_CLASSES = {"0": "none", "1": "realtime", "2": "best-effort", "3": "idle"}


def _priority(shown: dict[str, str]) -> Check | None:
    """The rank the runner's sessions run at, and a warning while it is the desktop's.

    Five sessions at nice 0 shared the machine with the browser they drive, as
    equals, until the desktop stopped answering. A unit written before
    `ponos.service.in` lowered them keeps them there until `ponos service on`.
    """
    if not shown.get("Nice"):
        return None
    memory = shown.get("MemoryHigh", "")
    params = {
        "nice": shown["Nice"],
        "weight": shown.get("CPUWeight", "") or "[not set]",
        "io": IO_CLASSES.get(shown.get("IOSchedulingClass", ""), "best-effort"),
        "memory": f"{int(memory) / 2**30:.1f} GB" if memory.isdigit() else memory or "infinity",
    }
    said = "nice {{nice}}, CPUWeight {{weight}}, I/O {{io}}, MemoryHigh {{memory}}."
    if params["nice"] == "0" and params["io"] != "idle":
        return _check(
            "machine.priority",
            WARN,
            "Priority",
            "The sessions run at the desktop's priority: " + said,
            params=params,
            cause="The runner's unit was written before it ran its sessions in the background.",
            steps=["In a terminal on this machine, run `ponos service on` to rewrite it."],
        )
    return _check(
        "machine.priority", OK, "Priority", "Sessions in the background: " + said, params=params
    )
