"""Running a Claude Code session on a ticket, and knowing what it did.

The session runs in `--print` mode with `stream-json` output: the raw stream is
written to a log as-is, which lets you follow a ticket live
(`ponos logs -f`) and read back afterwards why it failed.

`on_event` sees every event of that stream as it arrives, which is what lets
the runner write the steps into the Notion ticket while they happen.

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
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO
from urllib.parse import parse_qs, quote, urlparse

from . import credits, disk, legacy, vault
from .question import Question, caveats, parse

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

    The runner draws it at claim time so the Notion ticket can point at the work
    from the moment it starts, not only once it is finished.
    """
    return str(uuid.uuid4())


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
    on_event: Callable[[dict], None] | None = None,
    stop: threading.Event | None = None,
    max_budget_usd: float = 0.0,
) -> Outcome:
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
    )

    # What the caller adds comes last: an OpenRouter key configured for the
    # runner is meant to win over one that happens to be in this shell. See
    # openrouter.py.
    inherited = {
        **os.environ,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        **(environment or {}),
    }
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = log.with_suffix(".err")

    # Private from their first byte: a transcript is the brief, the code and
    # whatever a command printed on the way, secrets included when one was.
    with disk.open_private(log) as journal, disk.open_private(stderr_path) as errors:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            bufsize=1,
            env=inherited,
            start_new_session=True,  # its own process group, so we can kill it all
            stdin=subprocess.PIPE,
        )
        # From a thread: a prompt larger than the pipe's buffer would block
        # this write until the session reads it, while the session may be
        # waiting for us to read what it has already written.
        threading.Thread(
            target=_feed, args=(process, prompt), name="tr-prompt", daemon=True
        ).start()

        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                time.sleep(5)
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        watchdog = threading.Timer(timeout_minutes * 60, expire)
        watchdog.start()

        # Asked to stop by the caller: the console's Stop. The whole group goes,
        # and not the CLI alone — a `pytest` or a `npm install` it had started
        # would otherwise carry on with nobody to read it. Claude Code writes
        # its conversation as it goes, so what was said before the signal is
        # still there for the next `--resume`.
        interrupted = threading.Event()

        def interrupt(asked: threading.Event) -> None:
            while process.poll() is None:
                if asked.wait(0.2):
                    interrupted.set()
                    halt(process)
                    return

        if stop is not None:
            threading.Thread(target=interrupt, args=(stop,), name="tr-stop", daemon=True).start()

        try:
            final, texts = _read(process, journal, on_event)
            process.wait()
        finally:
            watchdog.cancel()
    # Written by the CLI itself, so masked once it has let go of it.
    vault.scrub(stderr_path)

    seconds = time.monotonic() - started
    return _outcome(
        final,
        texts,
        session_id=session_id,
        log=log,
        stderr_path=stderr_path,
        seconds=seconds,
        code=process.returncode,
        interrupted=interrupted.is_set(),
        timed_out=timed_out.is_set(),
        timeout_minutes=timeout_minutes,
    )


def _command(
    binary: str,
    session_id: str,
    *,
    resume: bool,
    permission_mode: str,
    model: str,
    max_budget_usd: float,
) -> list[str]:
    """The CLI's command line for one session."""
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
        "--chrome",
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
    ]
    if model:
        command += ["--model", model]
    # The CLI stops itself at the limit, between two steps, and says so in its
    # last line: a clean end, with the cost of what was done.
    if max_budget_usd > 0:
        command += ["--max-budget-usd", f"{max_budget_usd:.2f}"]
    return command


def _read(
    process: subprocess.Popen, journal: IO[str], on_event: Callable[[dict], None] | None
) -> tuple[dict, list[str]]:
    """The stream, written to the journal as it comes: its last event, and what was said."""
    final: dict = {}
    texts: list[str] = []
    for line in process.stdout:  # type: ignore[union-attr]
        # Masked before anything reads it: the transcript, the steps
        # written into the ticket, the answer — see vault.py.
        line = vault.mask(line)
        journal.write(line)
        journal.flush()
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if on_event is not None:
            try:
                on_event(event)
            except Exception as error:
                # Whoever watches the session is never allowed to stop
                # it: a reporter that throws is dropped, and the ticket
                # runs to its end unwatched.
                logger.exception("    ! live report dropped: %s", error)
                on_event = None
        if event.get("type") == "result":
            final = event
        elif event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
    return final, texts


def _outcome(
    final: dict,
    texts: list[str],
    *,
    session_id: str,
    log: Path,
    stderr_path: Path,
    seconds: float,
    code: int | None,
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
    if failed:
        tail = _tail(stderr_path)
        error = answer[-800:] or tail or f"claude exited with code {code}"
        # Read on a failure only: a session that *talks* about usage limits must
        # not put the runner to sleep. And out of both the answer and stderr,
        # because the CLI says it in whichever of the two it was writing to.
        resets_at = credits.reached(f"{answer}\n{tail}")

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
        question=parse(answer) if blocked and not over_budget else None,
        caveats=caveats(answer) if not failed and not blocked else [],
        resets_at=resets_at,
        over_budget=over_budget,
        code=code,
        resulted=bool(final),
    )


# How long a stopped session is given to end on SIGTERM before its group is killed.
GRACE_SECONDS = 5


def halt(process: subprocess.Popen) -> None:
    """End a session's whole process group: asked first, then made to.

    By the group id, which with `start_new_session` is the leader's pid and
    outlives it: a command the session started is still in it once the CLI
    itself has exited, and it is the one that has to go.
    """
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
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
TERMINALS = (
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

    Notion accepts any scheme in a URL property, and `install.sh` registers
    `ponos://` with the desktop. Clicking the Session cell of a ticket
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
# more. A link is something anybody can put in a Notion cell or a web page, and
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
    # Migration filet: a link written before the rename, still in its Notion
    # cell, says the old scheme and names the worktree where it used to be.
    old = parsed.scheme == legacy.OLD
    if parsed.scheme != SCHEME and not old:
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
    if old:
        cwd = legacy.path(cwd)
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
        candidates.insert(0, (preferred, lambda cwd, args, p=preferred: [p, "-e", *args]))
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


def _feed(process: subprocess.Popen, prompt: str) -> None:
    """Hand the prompt to the session on stdin, then close it: that is the end."""
    try:
        process.stdin.write(prompt)  # type: ignore[union-attr]
        process.stdin.close()  # type: ignore[union-attr]
    except (BrokenPipeError, OSError, ValueError):
        pass  # the session died first; what it said on the way out is the story


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
    is already carried by the Notion status, repeating it teaches nothing.
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
