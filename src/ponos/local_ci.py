"""The project's CI, run on this machine before the pull request is opened.

A red CI used to be found once the pull request was open: GitHub said so, the
ticket went back to a session that had to read the whole thing again, and the
round trip cost a second session and an hour. Run here first, a red CI goes
straight back to the session that wrote the code — its conversation still holds
every reason for every line — and the pull request opens on a branch that has
already passed once. See `Execution._local_ci`.

**Only where Docker answers.** A project's CI is services and images, and a
command run straight on this machine would be judged against whatever happens
to be installed here: a red that GitHub would never see, or a green it would
not give. So the switch is offered only when `docker info` answers, and a
runner without Docker carries on exactly as it did before the switch existed.

**What runs is the project's to say.** First the command its Settings tab
declares — `make ci`, `npm run ci` — which knows the project better than any
guess; otherwise its GitHub workflows through `act`, when `act` is installed
and there are workflows to read; otherwise nothing, and the ticket goes on as
it would have, with one line saying so.

**Named after the ticket, and gone when it ends.** Two tickets of one
repository running the same `docker compose up` would fight over the same
containers. The command is given `COMPOSE_PROJECT_NAME` and `PONOS_CI_NAME`,
both `ponos-ci-<ticket>`, `act` labels its containers with the same name, and
whatever answers to that name — a container, a network, a compose volume — is
removed once the run is over, whichever way it ended.

**A few at a time.** Each run is a set of containers, and four tickets in
flight are four of them at once: `runner.local_ci_concurrent` places, held as
locks on files so that the console and the timer count the same places, and a
run with none waits for one.

GitHub's CI is not replaced: it still runs on the pull request, and it is still
the one the merge waits for.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import disk
from .config import state_dir
from .ticket import short_id

logger = logging.getLogger(__name__)

# The label `act` is asked to put on its containers, and the prefix of every
# name the CI of a ticket is given.
LABEL = "ponos.ci"
PREFIX = "ponos-ci-"

# `docker info` is asked again after this long: the settings page is opened
# often, and a daemon started a minute ago should not wait for a restart.
CACHE_SECONDS = 60
PROBE_SECONDS = 10

# How much of a red run's output the session is shown: the end, where the
# failure is said, and enough before it to know which step it was.
TAIL_LINES = 200
TAIL_CHARACTERS = 20_000

# How often a run waiting for a place asks again.
WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class Docker:
    installed: bool
    running: bool
    version: str = ""
    error: str = ""

    @property
    def available(self) -> bool:
        return self.installed and self.running


_docker: tuple[float, Docker] | None = None
_docker_lock = threading.Lock()


def docker(*, fresh: bool = False) -> Docker:
    """Whether Docker is installed here, and whether its daemon answers — asked once a minute."""
    global _docker
    with _docker_lock:
        if not fresh and _docker and time.monotonic() - _docker[0] < CACHE_SECONDS:
            return _docker[1]
        found = _probe()
        _docker = (time.monotonic(), found)
        return found


def _probe() -> Docker:
    binary = shutil.which("docker")
    if not binary:
        return Docker(False, False)
    try:
        answered = subprocess.run(
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=PROBE_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Docker(True, False, error=str(error))
    version = answered.stdout.strip()
    if answered.returncode != 0 or not version:
        said = (answered.stderr or answered.stdout).strip().splitlines()
        return Docker(True, False, error=said[-1] if said else f"exit {answered.returncode}")
    return Docker(True, True, version=version)


def name(ticket_id: str) -> str:
    """What the containers and networks of a ticket's CI are called."""
    return f"{PREFIX}{short_id(ticket_id)}"


@dataclass(frozen=True)
class Plan:
    """What runs a project's CI: its own command, `act`, or nothing (`argv` empty)."""

    argv: list[str] = field(default_factory=list)
    source: str = ""  # project · act · ""
    shown: str = ""

    def __bool__(self) -> bool:
        return bool(self.argv)


def _workflows(workdir: Path) -> bool:
    folder = workdir / ".github" / "workflows"
    return folder.is_dir() and any(
        path.suffix in (".yml", ".yaml") for path in folder.iterdir() if path.is_file()
    )


def plan(declared: str, workdir: Path, ticket_id: str) -> Plan:
    """The command the project declared, else its workflows through `act`, else nothing."""
    declared = declared.strip()
    if declared:
        return Plan(["sh", "-c", declared], "project", declared)
    act = shutil.which("act")
    if act and _workflows(workdir):
        # `--rm`: the job containers go when their job does, red or green. The
        # label is what finds the ones a killed run left behind.
        argv = [act, "--rm", "--container-options", f"--label {LABEL}={name(ticket_id)}"]
        return Plan(argv, "act", "act")
    return Plan()


@dataclass(frozen=True)
class Run:
    ok: bool
    code: int
    tail: str
    seconds: float
    log: Path
    timed_out: bool = False


def _tail(log: Path) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = "\n".join(text.splitlines()[-TAIL_LINES:])
    return text[-TAIL_CHARACTERS:]


def environment(ci_name: str, secrets: dict[str, str] | None = None) -> dict[str, str]:
    """The command's environment: the runner's, the project's keys, and the ticket's names."""
    return {
        **os.environ,
        **(secrets or {}),
        # Read by most test runners as "nobody is watching": no watch mode, no
        # prompt, no colours waiting for a terminal.
        "CI": "true",
        "COMPOSE_PROJECT_NAME": ci_name,
        "PONOS_CI_NAME": ci_name,
    }


def run(
    chosen: Plan,
    workdir: Path,
    ci_name: str,
    log: Path,
    *,
    timeout_minutes: int,
    secrets: dict[str, str] | None = None,
) -> Run:
    """The CI run once, its output into `log`; a timeout kills the whole process group."""
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    timed_out = False
    with disk.open_private(log) as output:
        try:
            process = subprocess.Popen(
                chosen.argv,
                cwd=str(workdir),
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=environment(ci_name, secrets),
                start_new_session=True,
            )
        except OSError as error:
            output.write(f"{chosen.shown}: {error}\n")
            return Run(False, 127, str(error), 0.0, log)
        try:
            code = process.wait(timeout=max(1, timeout_minutes) * 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            code = process.wait()
            output.write(f"\n[ponos] local CI stopped after {timeout_minutes} minutes\n")
    return Run(
        code == 0 and not timed_out,
        code,
        _tail(log),
        time.monotonic() - started,
        log,
        timed_out,
    )


def _docker_lines(*arguments: str) -> list[str]:
    binary = shutil.which("docker")
    if not binary:
        return []
    try:
        answered = subprocess.run(
            [binary, *arguments],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("docker %s: %s", " ".join(arguments), error)
        return []
    return [line.strip() for line in answered.stdout.splitlines() if line.strip()]


def clean(ci_name: str) -> int:
    """Remove every container, network and compose volume of one ticket's CI; how many went.

    Found three ways, since a command may start them three ways: by the
    label `act` was given, by the compose project the environment named, and
    by a name that starts with the ticket's.
    """
    labels = (f"label={LABEL}={ci_name}", f"label=com.docker.compose.project={ci_name}")
    containers = {
        found
        for given in (*labels, f"name=^/?{ci_name}")
        for found in _docker_lines("ps", "-aq", "--filter", given)
    }
    removed = 0
    if containers:
        removed += len(_docker_lines("rm", "-f", "-v", *sorted(containers)))
    networks = {
        found
        for given in (*labels, f"name=^{ci_name}")
        for found in _docker_lines("network", "ls", "-q", "--filter", given)
    }
    if networks:
        removed += len(_docker_lines("network", "rm", *sorted(networks)))
    volumes = set(_docker_lines("volume", "ls", "-q", "--filter", labels[1]))
    if volumes:
        removed += len(_docker_lines("volume", "rm", "-f", *sorted(volumes)))
    return removed


@contextmanager
def place(places: int, waiting: Callable[[], None] | None = None) -> Iterator[int]:
    """One of `places` places for a local CI, held for as long as the block lasts.

    A file lock per place, so that every process of this machine counts the
    same ones — `flock`, held by an open file rather than by a process, so
    that two threads of one runner count as two. `waiting` is called once,
    the first time none is free.
    """
    folder = state_dir() / "local-ci"
    folder.mkdir(parents=True, exist_ok=True)
    said = False
    while True:
        for index in range(max(1, places)):
            handle = open(folder / f"place-{index}.lock", "a")  # noqa: SIM115 — held across the yield
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                continue
            try:
                yield index
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()
            return
        if not said and waiting:
            waiting()
        said = True
        time.sleep(WAIT_SECONDS)
