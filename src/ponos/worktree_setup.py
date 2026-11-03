"""The project's preparation of a fresh worktree, run before the session starts.

A worktree cut a minute ago has no `node_modules`, no `.venv`, no local `.env`:
every session began by guessing what to install and running it at its own
expense — in time, in tokens, sometimes with the wrong package manager, and
with three to fifteen sessions in flight, as many installs at once. The
project says it once instead, and it runs here, in the worktree, before Claude
is started.

**Two places to say it, the project's own word first.** The `setup` its
Settings tab holds (`project_settings.py`) wins; otherwise `.ponos/setup.sh`,
read from the worktree itself, so that a repository can carry its preparation
with its code. Neither: nothing runs, and a ticket goes on as it always did.

**A failure stops the ticket, before it costs a session.** A session started
on a worktree whose install failed would find the failure by itself, later and
dearer. The last lines of the output are what the ticket shows; the whole of
it is in the log.

**A reused worktree is prepared again.** The command is meant to be idempotent
(`npm ci`, `uv sync`): a branch picked up from an earlier attempt may well have
changed its lockfile since.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import disk

# The file a repository carries its own preparation in, relative to the worktree.
SCRIPT = Path(".ponos") / "setup.sh"

# How much of the output reaches the ticket: the end of it is where it failed.
TAIL_LINES = 40
TAIL_CHARACTERS = 4_000


@dataclass(frozen=True)
class Plan:
    """What to run: `argv` for `shown`, from `source` ("project" or "repository")."""

    argv: tuple[str, ...] = ()
    shown: str = ""
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.argv)


@dataclass(frozen=True)
class Run:
    ok: bool
    code: int
    tail: str
    seconds: float
    log: Path
    timed_out: bool = False


def plan(command: str, workdir: Path) -> Plan:
    """The project's own command, else the repository's `.ponos/setup.sh`, else nothing."""
    command = command.strip()
    if command:
        return Plan(("sh", "-c", command), command, "project")
    script = workdir / SCRIPT
    if script.is_file() and script.read_text(encoding="utf-8", errors="replace").strip():
        return Plan(("sh", str(SCRIPT)), str(SCRIPT), "repository")
    return Plan()


def run(
    chosen: Plan,
    workdir: Path,
    log: Path,
    *,
    timeout_minutes: int,
    secrets: dict[str, str] | None = None,
) -> Run:
    """The preparation run once, its output into `log`; a timeout kills the whole process group."""
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    timed_out = False
    with disk.open_private(log) as output:
        output.write(f"$ {chosen.shown}\n")
        output.flush()
        try:
            process = subprocess.Popen(
                chosen.argv,
                cwd=str(workdir),
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                # "Nobody is watching": no prompt, no watch mode, no colours.
                env={**os.environ, **(secrets or {}), "CI": "true", "PONOS_SETUP": "1"},
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
            output.write(f"\n[ponos] setup stopped after {timeout_minutes} minutes\n")
    return Run(
        code == 0 and not timed_out,
        code,
        _tail(log),
        time.monotonic() - started,
        log,
        timed_out,
    )


def _tail(log: Path) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = "\n".join(text.splitlines()[-TAIL_LINES:])
    return text[-TAIL_CHARACTERS:]
