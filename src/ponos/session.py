"""Running a Claude Code session on a ticket, and knowing what it did.

The session runs in `--print` mode with `stream-json` output: the raw stream is
written to a log as-is, which lets you follow a ticket live
(`ponos logs -f`) and read back afterwards why it failed.

`on_event` sees every event of that stream as it arrives, which is what lets
the runner write the steps into the ticket while they happen.

The session ID is **drawn before** launching and passed as `--session-id`. So we
know it even if the session dies halfway, and `claude --resume <id>` reopens the
conversation exactly where it stopped — which is what makes a failure something
to repair by hand rather than something to redo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any
from urllib.parse import parse_qs, quote, urlparse

from . import config, credits, disk, leftovers, vault
from .question import Question, caveats, lesson, memories, parse

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    ok: bool
    blocked: bool
    session_id: str
    summary: str
    log: Path
    answer: str = ""
    error: str = ""
    cost_usd: float = 0.0
    turns: int = 0
    seconds: float = 0.0
    # The subscription's quota, spent: a session that never got to start rather
    # than one that went wrong. `resets_at` is when it comes back, in seconds
    # since the epoch. See credits.py, and what the runner does with it.
    exhausted: bool = False
    resets_at: float = 0.0
    # Of those, the one whose wait no clock ends: the CLI's sign-in expired.
    # `exhausted` too, so that the ticket goes back where it came from; what
    # lifts the wait is a sign-in, not `resets_at`.
    signed_out: bool = False
    # Ended by whoever started it, on purpose: not a failure, and not an answer.
    # `answer` is what it had said by then; the conversation is still on disk.
    stopped: bool = False
    # Ended by the CLI because it spent what `--max-budget-usd` allowed. Always
    # `blocked` too: the work is unfinished and somebody has to decide.
    over_budget: bool = False
    # What a blocked session asked, in the parts it was told to hand over —
    # see question.py. None when it wrote only its RESULT line.
    question: Question | None = None
    # What a session that ended ok could not check, for whoever reviews it —
    # its CAVEAT lines. Written on the report, and read back by the console.
    caveats: list[str] = field(default_factory=list)
    # What it says it learned about the project, for the notes — see notes.py.
    lesson: str = ""
    # The facts it proposes to remember — its MEMORY lines, see memory.py.
    memories: list[str] = field(default_factory=list)
    # How the process ended, as `subprocess` says it (negative: a signal), and
    # whether it got as far as its own last event. A session with no result is
    # one that was cut, not one that failed — what `killed` tells apart.
    code: int = 0
    resulted: bool = True
    timed_out: bool = False
    # Why it is believed to have been killed from outside, once the runner has
    # looked and given it its one more try: empty for every other ending.
    killed: str = ""

    @property
    def concluded(self) -> bool:
        """Did it end on a RESULT line, whichever way? Not when it just stopped."""
        return bool(_verdict(self.answer))

    @property
    def resume_command(self) -> str:
        return f"claude --resume {self.session_id}"


# What the CLI says when it is asked to carry on a conversation it does not
# have: pruned, filed elsewhere, or never on this machine. Narrow on purpose —
# `lost` decides whether a run is worth doing over, and reading an ordinary
# failure as a missing session would quietly run every failing ticket twice.
_LOST = re.compile(
    r"no conversation found|session .{0,80}not found|could not (?:be )?(?:find|found|resume)",
    re.IGNORECASE,
)


# The prompt never goes on the command line: the session reads it on its
# standard input, which `--print` does when it is given none. Two reasons, and
# the second is the one that killed sessions. Linux refuses any single argument
# over 128 KiB (MAX_ARG_STRLEN) with E2BIG, before the session exists. And
# argv is public: `ps` shows it to every user of the machine — a brief can hold
# a secret — and `pkill -f` matches it. A ticket whose page quotes the last
# run's `vite --port 5199` made its own session's command line contain that
# text, so the session's `pkill -f "vite --port 5199"` killed the session
# itself (exit 137), and any other one carrying the same words. What stays in
# argv is short and the runner's own: options, an identifier, a model name.


def available() -> str:
    return shutil.which("claude") or ""


def lost(outcome: Outcome) -> bool:
    """Did this session fail because there was no conversation to resume?

    The one failure a fresh session repairs. Everything else a resumed session
    can do — ask a question, time out, crash — it would do again, so redoing it
    costs a second full session and loses whatever the first one had to say.
    """
    return bool(_LOST.search(outcome.error or ""))


def signalled(outcome: Outcome) -> bool:
    """Was the session ended by a signal nobody on our side sent?

    SIGKILL is 137 once a shell has relayed it and -9 straight from the
    process; SIGTERM is 143 and -15. Not the watchdog's, not the console's
    Stop: those return before anybody asks.
    """
    if outcome.ok or outcome.blocked or outcome.stopped or outcome.timed_out:
        return False
    return outcome.code < 0 or outcome.code in (137, 143)


def new_id() -> str:
    """A session identifier, drawn before the session exists.

    The runner draws it at claim time so the ticket can point at the work
    from the moment it starts, not only once it is finished.
    """
    return str(uuid.uuid4())


@dataclass
class Handle:
    """A session started detached, as much of it as a later runner needs to follow it.

    `pid` is the tether's (see tether.py), which is also the process group the
    CLI runs in; `code` is where the tether writes how the CLI ended. Stored in
    `ponos.db` while the session runs (`state.track_session`), so that a runner
    started after this one — an update's `exec`, a restart, a crash — reads the
    same log to its end rather than killing the session or starting it over.
    """

    session_id: str
    pid: int
    log: Path
    stderr: Path
    code: Path
    cwd: Path
    started: float
    timeout_minutes: int = 30
    tmp: Path | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "log": str(self.log),
            "stderr": str(self.stderr),
            "code": str(self.code),
            "cwd": str(self.cwd),
            "started": self.started,
            "timeout_minutes": self.timeout_minutes,
            "tmp": str(self.tmp) if self.tmp else "",
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> Handle:
        return cls(
            session_id=str(value["session_id"]),
            pid=int(value["pid"]),
            log=Path(value["log"]),
            stderr=Path(value["stderr"]),
            code=Path(value["code"]),
            cwd=Path(value["cwd"]),
            started=float(value.get("started") or time.time()),
            timeout_minutes=int(value.get("timeout_minutes") or 30),
            tmp=Path(value["tmp"]) if value.get("tmp") else None,
        )

    @property
    def deadline(self) -> float:
        return self.started + self.timeout_minutes * 60

    def alive(self) -> bool:
        """Whether the tether is still there — and is this session's, not a pid reused."""
        return tethered(self.pid, self.session_id)

    def ended(self) -> bool:
        """Whether the CLI has ended: its code written, or nobody left to write it."""
        return self.code.exists() or not self.alive()


def tethered(pid: int, session_id: str) -> bool:
    """Whether `pid` is a live tether holding `session_id`.

    A child of this process is reaped on the way — a tether that ended under a
    runner that `exec`ed is still its child, and would otherwise stay a zombie
    that `kill(pid, 0)` calls alive. Anybody else's is read in /proc, whose
    command line names the session: a pid reused by an unrelated process is not
    a session going.
    """
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        return False
    try:
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()[0]
    except (OSError, IndexError):
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True
    return state != "Z" and session_id.encode() in arguments


def run(
    prompt: str,
    *,
    cwd: Path,
    log: Path,
    model: str = "",
    permission_mode: str = "bypassPermissions",
    timeout_minutes: int = 30,
    session_id: str = "",
    resume: bool = False,
    environment: dict[str, str] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    stop: threading.Event | None = None,
    max_budget_usd: float = 0.0,
    chrome: bool = True,
    mcp_config: Path | None = None,
    attribution: bool = False,
    adopted: Handle | None = None,
    track: Callable[[Handle], None] | None = None,
) -> Outcome:
    """One session, from its start to what it came to.

    Started detached (see tether.py) and followed through its log; `track` is
    told its handle the moment it exists, which is how the runner writes it down
    for whoever comes after. `adopted` is a session a runner before this one
    started: nothing is launched, it is followed from where it is.
    """
    if adopted is not None:
        handle = adopted
        # What the runner before this one already reported is not reported
        # again: the steps are in the journal and on the card.
        try:
            skip = handle.log.stat().st_size
        except OSError:
            skip = 0
    else:
        handle = launch(
            prompt,
            cwd=cwd,
            log=log,
            model=model,
            permission_mode=permission_mode,
            timeout_minutes=timeout_minutes,
            session_id=session_id,
            resume=resume,
            environment=environment,
            max_budget_usd=max_budget_usd,
            chrome=chrome,
            mcp_config=mcp_config,
            attribution=attribution,
        )
        skip = 0
        if track is not None:
            try:
                track(handle)
            except Exception:
                logger.exception("    ! the session was not written down for a restart")
    return finish(handle, on_event=on_event, stop=stop, skip=skip)


def launch(
    prompt: str,
    *,
    cwd: Path,
    log: Path,
    model: str = "",
    permission_mode: str = "bypassPermissions",
    timeout_minutes: int = 30,
    session_id: str = "",
    resume: bool = False,
    environment: dict[str, str] | None = None,
    max_budget_usd: float = 0.0,
    chrome: bool = True,
    mcp_config: Path | None = None,
    attribution: bool = False,
) -> Handle:
    """Start a session detached from this process, and say where to follow it."""
    binary = available()
    if not binary:
        raise FileNotFoundError("claude not found in PATH")

    session_id = session_id or new_id()
    command = _command(
        binary,
        session_id,
        resume=resume,
        permission_mode=permission_mode,
        model=model,
        max_budget_usd=max_budget_usd,
        chrome=chrome,
        mcp_config=mcp_config,
        attribution=attribution,
    )

    # What the caller adds comes last: an OpenRouter key configured for the
    # runner is meant to win over one that happens to be in this shell. See
    # openrouter.py.
    scratch_tmp = leftovers.make_tmp(session_id)
    inherited = {
        **inheritable(os.environ),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        **leftovers.environment(cwd),
        **({"TMPDIR": str(scratch_tmp)} if scratch_tmp else {}),
        **(environment or {}),
    }
    leftovers.warn_pinned(cwd)
    log.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = log.with_suffix(".err")
    code_path = log.with_name(log.name + ".code")
    code_path.unlink(missing_ok=True)
    # The transcript is private from its first byte: the tether opens it so.
    with disk.open_private(log), disk.open_private(stderr_path):
        pass
    source = str(Path(__file__).resolve().parents[1])
    tether_environment = {
        **inheritable(os.environ),
        "PYTHONPATH": os.pathsep.join(
            part for part in (source, os.environ.get("PYTHONPATH", "")) if part
        ),
    }
    spec = {
        "command": command,
        "cwd": str(cwd),
        "log": str(log),
        "stderr": str(stderr_path),
        "code": str(code_path),
        "environment": inherited,
        "prompt": prompt,
        # Masked before anything reads it: the transcript, the steps written
        # into the ticket, the answer — see vault.py.
        "forms": list(vault.forms()),
    }
    started = time.time()
    tether = subprocess.Popen(
        [sys.executable, "-m", "ponos.tether", session_id],
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=tether_environment,
        # Its own session, so that neither this process's end nor a signal sent
        # to its group reaches it — and its own group, so we can end it all.
        start_new_session=True,
    )
    assert tether.stdin is not None
    try:
        tether.stdin.write(json.dumps(spec).encode())
        tether.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    _CHILDREN[tether.pid] = tether
    return Handle(
        session_id=session_id,
        pid=tether.pid,
        log=log,
        stderr=stderr_path,
        code=code_path,
        cwd=cwd,
        started=started,
        timeout_minutes=timeout_minutes,
        tmp=scratch_tmp,
    )


# The tethers this process started, kept so that `Popen` reaps them itself: a
# `waitpid` of ours on a pid `subprocess` also watches would take its status.
_CHILDREN: dict[int, subprocess.Popen[bytes]] = {}

# How often a session's log is looked at for new lines.
FOLLOW_SECONDS = 0.1


def finish(
    handle: Handle,
    *,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    stop: threading.Event | None = None,
    skip: int = 0,
) -> Outcome:
    """Follow a session to its end, then clean up after it and say what it came to.

    `skip` is how many bytes of the log were already reported by whoever
    followed it before: read for the answer, not handed to `on_event` again.
    """
    final, texts, code, interrupted, timed_out = follow(
        handle, on_event=on_event, stop=stop, skip=skip
    )
    # Whatever the way out — a result, a timeout, a Stop, an exception —
    # nothing the session started stays behind it.
    reap(handle.pid)
    _CHILDREN.pop(handle.pid, None)
    leftovers.stop_processes(handle.cwd)
    leftovers.sweep(handle.cwd)
    leftovers.drop_tmp(handle.tmp)
    # Written by the CLI itself, so masked once it has let go of it.
    vault.scrub(handle.stderr)
    return _outcome(
        final,
        texts,
        session_id=handle.session_id,
        log=handle.log,
        stderr_path=handle.stderr,
        seconds=time.time() - handle.started,
        code=code,
        interrupted=interrupted,
        timed_out=timed_out,
        timeout_minutes=handle.timeout_minutes,
    )


def follow(
    handle: Handle,
    *,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    stop: threading.Event | None = None,
    skip: int = 0,
) -> tuple[dict[str, Any], list[str], int, bool, bool]:
    """Read a session's log as it is written, until the session has ended.

    Its last event, what it said, its exit code, and whether it was stopped or
    timed out on the way. The deadline is the session's own, counted from when
    it started — a runner that adopts it an hour in does not give it an hour more.
    """
    final: dict[str, Any] = {}
    texts: list[str] = []
    interrupted = timed_out = False
    consumed = 0  # the bytes of the complete lines read so far
    buffer = b""
    child = _CHILDREN.get(handle.pid)
    reading: IO[bytes] | None = None
    try:
        while True:
            ended = handle.code.exists() or (
                child.poll() is not None if child is not None else not handle.alive()
            )
            if reading is None:
                try:
                    reading = handle.log.open("rb")
                except OSError:
                    reading = None
            chunk = reading.read() if reading is not None else b""
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                consumed += len(line) + 1
                event = _parse(line.decode("utf-8", errors="replace"))
                if event is None:
                    continue
                if on_event is not None and consumed > skip:
                    on_event = _listen(on_event, event)
                if event.get("type") == "result":
                    final = event
                elif event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
            if ended and not chunk:
                last = _parse(buffer.decode("utf-8", errors="replace")) if buffer.strip() else None
                if last is not None and last.get("type") == "result":
                    final = last
                break
            if not ended and stop is not None and stop.is_set() and not interrupted:
                interrupted = True
                halt(handle.pid)
                continue
            if not ended and not timed_out and time.time() >= handle.deadline:
                timed_out = True
                halt(handle.pid)
                continue
            if not chunk:
                time.sleep(FOLLOW_SECONDS)
    finally:
        if reading is not None:
            reading.close()
    return final, texts, _code(handle, child), interrupted, timed_out


def _parse(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _listen(
    on_event: Callable[[dict[str, Any]], None], event: dict[str, Any]
) -> Callable[[dict[str, Any]], None] | None:
    """Hand one event over; a listener that raises is dropped, never the session."""
    try:
        on_event(event)
    except Exception as error:
        # Whoever watches the session is never allowed to stop it: a reporter
        # that throws is dropped, and the ticket runs to its end unwatched.
        logger.exception("    ! live report dropped: %s", error)
        return None
    return on_event


def _code(handle: Handle, child: subprocess.Popen[bytes] | None) -> int:
    """How the CLI ended, as the tether wrote it; a killed tether wrote nothing."""
    deadline = time.monotonic() + 2
    while not handle.code.exists() and time.monotonic() < deadline:
        if child is not None and child.poll() is not None:
            break
        if child is None and not handle.alive():
            break
        time.sleep(0.05)
    try:
        return int(handle.code.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -signal.SIGKILL


def inheritable(environ: Mapping[str, str]) -> dict[str, str]:
    """The runner's environment, less the secrets that are the runner's own.

    In a container every one of them is a variable — the console's password and
    token, the channels', the providers' keys — and a session handed
    the whole environment had them all, for an `env` to print into its
    transcript and the ticket. A session is given what `[vault]` grants its
    project and what its provider needs, by the caller: the rest stays here.
    """
    withheld = set(config.SECRETS.values()) | {config.VAULT_KEY_ENV}
    return {name: value for name, value in environ.items() if name not in withheld}


# What the usual test runners and builds read for how many workers to start.
# Vitest from 4 on reads the first, 1 to 3 the next two; pytest-xdist reads its
# own for `-n auto`, Cargo and Go theirs. Playwright and Jest read nothing:
# PLAYWRIGHT_WORKERS and JEST_WORKERS are for a configuration that asks for
# them (Ponos's own playwright.config.ts does), and the prompt names their
# flags. MAKEFLAGS is left out on purpose: `make` runs one job when nobody says
# otherwise, and `-j` would raise that rather than cap it.
WORKERS = (
    "VITEST_MAX_WORKERS",
    "VITEST_MAX_THREADS",
    "VITEST_MAX_FORKS",
    "PLAYWRIGHT_WORKERS",
    "JEST_WORKERS",
    "PYTEST_XDIST_AUTO_NUM_WORKERS",
    "CARGO_BUILD_JOBS",
    "GOMAXPROCS",
)


def workers(count: int) -> dict[str, str]:
    """The environment that holds a session's tests to `count` workers — see resources.share."""
    return dict.fromkeys(WORKERS, str(max(1, count)))


# What turns Claude Code's own signature off: no `Co-Authored-By` trailer under
# a commit, no « Generated with Claude Code » under a pull request. Given on the
# command line rather than left to the machine's `~/.claude/settings.json`, which
# says what it says, and merged over it by the CLI. `attribution` is the setting
# of today's versions; `includeCoAuthoredBy` the one older ones read instead —
# a key a version does not know it ignores.
UNSIGNED = json.dumps(
    {"attribution": {"commit": "", "pr": ""}, "includeCoAuthoredBy": False},
    separators=(",", ":"),
)


def _command(
    binary: str,
    session_id: str,
    *,
    resume: bool,
    permission_mode: str,
    model: str,
    max_budget_usd: float,
    chrome: bool = True,
    mcp_config: Path | None = None,
    attribution: bool = False,
) -> list[str]:
    """The CLI's command line for one session.

    `chrome` false leaves Claude in Chrome out: the session browses with
    Ponos's own browser instead, the `ponos-browser` server `mcp_config`
    names (browser.py) — added to the servers Claude Code already has.
    `attribution` false is `[claude] attribution` off: see `UNSIGNED`.
    """
    command = [
        binary,
        "--print",
        # Claude in Chrome, so a ticket can be handled in the browser the way a
        # person would. `--print` turns it off by default and only the flag
        # overrides that, so the setting alone would never reach us here. It
        # attaches to the Chrome already running — it cannot start one — and it
        # needs the OAuth session of the CLI: an ANTHROPIC_API_KEY session gets
        # `user:inference` alone and the integration refuses to load — which is
        # also what a session routed through OpenRouter is, see openrouter.py.
        *(["--chrome"] if chrome else []),
        *(["--mcp-config", str(mcp_config)] if mcp_config else []),
        # `--resume` continues a conversation that already exists, and refuses
        # to be given an identifier to create: the console's chat is one long
        # session, drawn once and carried on turn after turn, which is what
        # makes it a conversation rather than a series of strangers.
        *(["--resume", session_id] if resume else ["--session-id", session_id]),
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        permission_mode,
        *([] if attribution else ["--settings", UNSIGNED]),
    ]
    if model:
        command += ["--model", model]
    # The CLI stops itself at the limit, between two steps, and says so in its
    # last line: a clean end, with the cost of what was done.
    if max_budget_usd > 0:
        command += ["--max-budget-usd", f"{max_budget_usd:.2f}"]
    return command


def _outcome(
    final: dict[str, Any],
    texts: list[str],
    *,
    session_id: str,
    log: Path,
    stderr_path: Path,
    seconds: float,
    code: int,
    interrupted: bool,
    timed_out: bool,
    timeout_minutes: int,
) -> Outcome:
    """What a session that has ended did, read from its last event and its stderr."""
    # A stop that crossed the session's last word is no stop: the answer had
    # arrived, and it is what is kept.
    if interrupted and not final:
        return Outcome(
            ok=False,
            blocked=False,
            session_id=session_id,
            summary="",
            log=log,
            answer="\n".join(texts).strip(),
            error="stopped",
            cost_usd=float(final.get("total_cost_usd") or 0.0),
            turns=int(final.get("num_turns") or 0),
            seconds=seconds,
            stopped=True,
            code=code,
            resulted=False,
        )
    if timed_out:
        return Outcome(
            ok=False,
            blocked=False,
            session_id=session_id,
            summary="",
            log=log,
            answer="",
            error=f"session killed after {timeout_minutes} min",
            # Cut or not, what it spent was spent: the last event, when it
            # came, still says how much.
            cost_usd=float(final.get("total_cost_usd") or 0.0),
            turns=int(final.get("num_turns") or 0),
            seconds=seconds,
            code=code,
            resulted=bool(final),
            timed_out=True,
        )

    answer = str(final.get("result") or "\n".join(texts)).strip()
    over_budget = final.get("subtype") == "error_max_budget_usd"
    failed = not over_budget and (bool(final.get("is_error")) or (code != 0 and not interrupted))
    blocked = over_budget or _verdict(answer) == "blocked"
    error = ""
    resets_at = 0.0
    signed_out = False
    if failed:
        tail = _tail(stderr_path)
        error = answer[-800:] or tail or f"claude exited with code {code}"
        # Read on a failure only: a session that *talks* about usage limits must
        # not put the runner to sleep. And out of both the answer and stderr,
        # because the CLI says it in whichever of the two it was writing to.
        said = f"{answer}\n{tail}"
        signed_out = credits.signed_out(said)
        # As far off as any wait may be: a sign-in is what ends this one, and
        # the moment is only there for a runner that never hears of one.
        resets_at = time.time() + credits.LONGEST_WAIT if signed_out else credits.reached(said)

    return Outcome(
        ok=not failed and not blocked,
        blocked=blocked,
        session_id=str(final.get("session_id") or session_id),
        summary=_summary(answer),
        log=log,
        answer=answer,
        error=error,
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        turns=int(final.get("num_turns") or 0),
        seconds=seconds,
        exhausted=bool(resets_at),
        signed_out=signed_out,
        question=parse(answer) if blocked and not over_budget else None,
        caveats=caveats(answer) if not failed and not blocked else [],
        lesson=lesson(answer) if not failed and not blocked else "",
        memories=memories(answer) if not failed and not blocked else [],
        resets_at=resets_at,
        over_budget=over_budget,
        code=code,
        resulted=bool(final),
    )


# How long a stopped session is given to end on SIGTERM before its group is killed.
GRACE_SECONDS = 5


def halt(target: subprocess.Popen[str] | int) -> None:
    """End a session's whole process group: asked first, then made to.

    By the group id, which with `start_new_session` is the leader's pid and
    outlives it: a command the session started is still in it once the CLI
    itself has exited, and it is the one that has to go.
    """
    pid = target if isinstance(target, int) else target.pid
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    if not isinstance(target, int):
        try:
            target.wait(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    else:
        _gone(pid, GRACE_SECONDS)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _gone(group: int, seconds: float) -> bool:
    """Whether the group is empty within `seconds` — its tether reaped on the way."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        child = _CHILDREN.get(group)
        if child is not None:
            child.poll()
        try:
            os.killpg(group, 0)
        except (ProcessLookupError, PermissionError):
            return True
        time.sleep(0.1)
    return False


def reap(target: subprocess.Popen[str] | int) -> None:
    """End what is left of a session's process group once its leader is gone.

    `halt` is for a session still running; this is for the one that ended, and
    whose `pnpm dev` did not. Nothing to wait for when the group is empty, so a
    session that cleaned up after itself costs nothing.
    """
    pid = target if isinstance(target, int) else target.pid
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    if _gone(pid, GRACE_SECONDS):
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


PROJECTS = Path.home() / ".claude" / "projects"


def exists(session_id: str) -> bool:
    """Has Claude Code filed this conversation anywhere — can it be resumed?

    A session stopped in its first second may not have written a line yet, and
    `--resume` on an identifier it never kept fails before saying a word.
    """
    try:
        return any(PROJECTS.glob(f"*/{session_id}.jsonl"))
    except OSError:
        return False


def project_key(path: Path) -> str:
    """The folder Claude Code files a session under, for a given directory.

    It slugifies the working directory: every `/` and `.` becomes `-`. So
    /home/me/work/app is `-home-me-work-app`, and a session started inside a
    disposable worktree is filed under the worktree, not the repository — which
    is why `/resume` in the repository never shows it.
    """
    return re.sub(r"[/.]", "-", str(path))


def relocate(session_id: str, destination: Path) -> Path | None:
    """Move a finished session's transcript under `destination`'s project folder.

    A ticket runs in a worktree that is deleted afterwards, so its session ends
    up filed under a directory that no longer exists — resumable by ID, but
    invisible in the repository's session picker. Moving the transcript puts it
    where you would look for it: `claude --resume` inside the repository lists
    it beside your own sessions.

    This reaches into Claude Code's own storage, so it is written to fail
    quietly: the transcript is located by globbing rather than by guessing where
    it was, and anything unexpected leaves the session exactly where it is,
    still resumable by its identifier.
    """
    try:
        matches = list(PROJECTS.glob(f"*/{session_id}.jsonl"))
        if not matches:
            return None
        source = matches[0]
        target_dir = PROJECTS / project_key(destination)
        if source.parent == target_dir:
            return source
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.move(str(source), str(target))
        try:
            source.parent.rmdir()  # only if the ticket left nothing else behind
        except OSError:
            pass
        return target
    except (OSError, ValueError):
        return None


SCHEME = "ponos"
TERMINALS: tuple[tuple[str, Callable[[str, list[str]], list[str]]], ...] = (
    (
        "gnome-terminal",
        lambda cwd, args: ["gnome-terminal", f"--working-directory={cwd}", "--", *args],
    ),
    ("konsole", lambda cwd, args: ["konsole", "--workdir", str(cwd), "-e", *args]),
    (
        "xfce4-terminal",
        lambda cwd, args: ["xfce4-terminal", f"--working-directory={cwd}", "-e", " ".join(args)],
    ),
    ("kitty", lambda cwd, args: ["kitty", "--directory", str(cwd), *args]),
    ("alacritty", lambda cwd, args: ["alacritty", "--working-directory", str(cwd), "-e", *args]),
    ("foot", lambda cwd, args: ["foot", "--working-directory", str(cwd), *args]),
    ("x-terminal-emulator", lambda cwd, args: ["x-terminal-emulator", "-e", *args]),
)


def deep_link(session_id: str, cwd: Path | str | None = None, host: str = "") -> str:
    """A clickable link that reopens this session, wherever it ran.

    The console draws any scheme as a link, and `install.sh` registers
    `ponos://` with the desktop. Clicking the session of a ticket
    therefore opens a terminal already inside the conversation — which beats
    copying a UUID into a command by some distance.

    When the runner is on a server, the session's transcript is on that server
    too, and a link that opened a local terminal would find nothing. `host` puts
    the ssh destination in the link, so the click opens the session **over ssh**
    from whichever machine you clicked on. That is what keeps the Session column
    useful once the runner moves off your laptop.

    Claude Code registers a `claude-cli://` scheme of its own, but its query
    parameters are undocumented and a wrong guess would produce a link that
    silently does nothing; ours does exactly what this file says it does.
    """
    query = []
    if cwd:
        query.append(f"cwd={quote(str(cwd), safe='/')}")
    if host:
        query.append(f"host={quote(host, safe='@.:-')}")
    link = f"{SCHEME}://session/{session_id}"
    return f"{link}?{'&'.join(query)}" if query else link


# What a session identifier and an ssh destination may be made of, and nothing
# more. A link is something anybody can put in a ticket or a web page, and
# clicking it hands both words to a command line: `host=-oProxyCommand=…` is an
# ssh *option*, not a machine, and runs whatever it says before any connection
# is attempted. So the two are checked against their shape rather than escaped
# — a word that cannot begin with a dash cannot become an option. Claude Code
# names its sessions with UUIDs, and `new_id` draws them the same way.
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_HOST = re.compile(r"^[A-Za-z0-9_.@:\[\]-]{1,255}$")


def resume_command(uri: str) -> tuple[str, list[str]]:
    """The directory and the command a ponos:// link means.

    Kept apart from `open_link` so that what a link is allowed to run can be
    checked without a terminal opening. Raises ValueError for anything that is
    not a link this module wrote: an unknown action, an identifier that is not
    one, a host that is not a host.
    """
    parsed = urlparse(uri)
    if parsed.scheme != SCHEME:
        raise ValueError(f"not a {SCHEME}:// link: {uri}")
    action = parsed.netloc or parsed.path.lstrip("/").split("/")[0]
    if action != "session":
        raise ValueError(f"unknown action “{action}” — expected {SCHEME}://session/<id>")
    session_id = parsed.path.strip("/").split("/")[-1]
    if not session_id:
        raise ValueError("no session identifier in the link")
    if not _SESSION_ID.match(session_id):
        raise ValueError(
            f"“{session_id}” is not a session identifier — letters, digits and dashes, "
            "not starting with a dash"
        )
    query = parse_qs(parsed.query)
    cwd = (query.get("cwd") or [str(Path.home())])[0]
    host = (query.get("host") or [""])[0]

    if host:
        if host.startswith("-") or not _HOST.match(host):
            raise ValueError(
                f"“{host}” is not an ssh destination — user@host, with letters, digits "
                "and . _ : @ [ ] - only, and never a leading dash"
            )
        # The session lives on another machine, so resuming means going there.
        # No local claude is needed — only ssh, and an account that has one.
        if not shutil.which("ssh"):
            raise FileNotFoundError(f"ssh not found — cannot reach {host}")
        remote = f"cd {shlex.quote(cwd)} 2>/dev/null; claude --resume {shlex.quote(session_id)}"
        # `--` before the destination: whatever it is, ssh reads it as one.
        return str(Path.home()), ["ssh", "-t", "--", host, remote]
    if not Path(cwd).is_dir():
        cwd = str(Path.home())
    binary = available()
    if not binary:
        raise FileNotFoundError("claude not found in PATH")
    return cwd, [binary, "--resume", session_id]


def open_link(uri: str) -> int:
    """Handle a ponos:// URI by opening a terminal on that session."""
    cwd, command = resume_command(uri)

    preferred = os.environ.get("PONOS_TERMINAL", "")
    candidates = list(TERMINALS)
    if preferred:
        candidates.insert(0, (preferred, lambda cwd, args: [preferred, "-e", *args]))
    for name, build in candidates:
        if shutil.which(name):
            # Detached: the click must not keep the desktop handler alive.
            subprocess.Popen(build(cwd, command), start_new_session=True)
            return 0
    raise FileNotFoundError("no terminal emulator found — set PONOS_TERMINAL to the one you use")


# A pull request's address, as `gh pr create` prints it on its last line.
_PULL_REQUEST = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")


def pull_requests(log: Path) -> list[str]:
    """The pull requests a session opened itself, read from its log, in order.

    Only what `gh pr create` printed: a URL met anywhere else — a `git log`,
    a `gh pr list`, a page read — is a pull request somebody else opened, and
    attaching it to the ticket would be lying. Nothing when the log cannot be
    read: this is a net under the board, never a reason to fail a ticket.
    """
    creating: set[str] = set()
    found: list[str] = []
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        # Not every event's `message` is a turn: a `permission_denied` carries
        # a sentence there.
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                given = block.get("input")
                command = str(given.get("command") or "") if isinstance(given, dict) else ""
                if re.search(r"\bgh\s+pr\s+create\b", command):
                    creating.add(str(block.get("id")))
            elif block.get("type") == "tool_result" and str(block.get("tool_use_id")) in creating:
                printed = block.get("content")
                if isinstance(printed, list):
                    printed = " ".join(
                        str(part.get("text") or "") for part in printed if isinstance(part, dict)
                    )
                for url in _PULL_REQUEST.findall(str(printed or "")):
                    if url not in found:
                        found.append(url)
    return found


def _verdict(answer: str) -> str:
    for line in reversed(answer.splitlines()):
        stripped = line.strip().lstrip("*# ").rstrip("*")
        if stripped.upper().startswith("RESULT:"):
            value = stripped[len("RESULT:") :].strip().lower()
            if value.startswith("blocked"):
                return "blocked"
            if value.startswith("ok"):
                return "ok"
    return ""


def _summary(answer: str) -> str:
    """The RESULT line without its verdict, else the tail of the answer.

    "RESULT: ok — removed the header" becomes "removed the header": the verdict
    is already carried by the ticket's status, repeating it teaches nothing.
    """
    for line in reversed(answer.splitlines()):
        stripped = line.strip().lstrip("*# ").rstrip("*")
        if stripped.upper().startswith("RESULT:"):
            rest = stripped[len("RESULT:") :].strip()
            for verdict in ("blocked", "ok"):
                if rest.lower().startswith(verdict):
                    rest = rest[len(verdict) :]
                    break
            return rest.strip(" —-:") or stripped
    return answer[-500:].strip()


def _tail(path: Path, limit: int = 500) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""
