"""The two things you can type into the console: a command, or a sentence.

They are not the same gesture and they are not made to look the same.

- A line starting with `>` is a **`ponos` subcommand**. The CLI is
  already the safe, considered surface of this tool; the console does not invent
  a second one — it offers the part of it that reads and reports (`OFFERED`),
  and none of what starts sessions or rewrites the installation. It is run as a
  subprocess with no shell — there is nothing to quote wrong, and nothing to
  inject into.
- Anything else is a **message to the workspace**: one long Claude Code session,
  started in `workspace_root`, that carries on from turn to turn. It has the
  `ponos` command in its PATH and your repositories under its feet, so
  "create a ticket for X on Trader Ia and make it ready" is a thing it does
  rather than a thing it explains how to do.

The conversation survives the browser, the server and the machine: it is a real
Claude Code session, resumed by its identifier, and `claude --resume <id>` in a
terminal opens the very same one. There are many of them — each is a row of
`ponos.db` (see `chats`) with its own title, model and files, and the console
has one *open* at a time: the one it talks to, which any browser sees.

A message is more than its words: what it carries — a screenshot, a PDF, a clip
— is kept in a folder of the conversation, and named in the prompt by path (see
`attachments`). And what is said aloud is turned into words before it is a
message at all: dictation is transcribed, handed back, read over, and only then
sent, like anything typed.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .. import openrouter, progress, provider, session, voice
from ..config import Config, state_dir
from . import attachments as files
from . import chats

# The verbs the console runs, written down one by one rather than read off the
# parser. Deriving them was the convenient answer and the wrong one: every verb
# added to the CLI became something a browser could start, including the ones
# that start Claude sessions (`run`), rewrite the installation (`update`) or
# delete worktrees a session is standing in (`clean`). A command typed here is
# bounded by `COMMAND_TIMEOUT` and runs as whoever the console runs as; what is
# listed is what fits both — it reads, it reconciles, it says something, and it
# is done in seconds.
OFFERED = (
    "doctor",
    "history",
    "list",
    "logs",
    "notify",
    "projects",
    "schedules",
    "status",
    "sync",
)

# Commands the console will not run, and why — so that a refusal explains
# itself instead of reading as a typo.
REFUSED = {
    "config": "opens an editor on the server — the Settings tab is that file, in this page",
    "open": "opens a terminal on the server's desktop, which is not where you are",
    "serve": "is what you are already talking to",
    "disable": "stops the console you are typing in — do it from a terminal",
    "enable": "rewrites and starts the systemd units — do it from a terminal",
    "run": (
        "starts Claude sessions that outlive a command typed here — make the ticket "
        "ready and the timer runs it, or type `ponos run` in a terminal"
    ),
    "update": (
        "replaces the code this console is running — the version at the top right "
        "offers it when there is one, or type it in a terminal"
    ),
    "clean": "deletes worktrees a session may be standing in — do it from a terminal",
    "init": "builds a whole Notion workspace — do it from a terminal, or the first connection",
    "mcp": "draws and takes back the MCP server's keys — do it from a terminal",
}

# The Claude models the console offers, whatever else is configured: the ones
# Claude Code names by family, and that models.py knows how to read.
CLAUDE_MODELS = ("opus", "sonnet", "haiku", "fable")

# What a model may be called: a family, a full Claude id, or an OpenRouter slug.
# Nothing a shell or a flag could mistake for something else.
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*(\[[0-9a-z]+\])?$")

# A command is not a session: nothing in the CLI legitimately takes minutes.
COMMAND_TIMEOUT = 180

# How long a command is given to stop on SIGTERM before its group is killed.
GRACE_SECONDS = 5


def web_dir() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path


def attachments_dir() -> Path:
    return web_dir() / "attachments"


@dataclass
class Message:
    role: str
    text: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    # What came with it, as the page draws it: name, kind, size, and the id the
    # file is served back under for as long as the conversation keeps it.
    attachments: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        said = {"role": self.role, "text": self.text, "at": self.at}
        if self.attachments:
            said["attachments"] = self.attachments
        return said


class Chat:
    """One conversation with the whole workspace, kept across restarts."""

    def __init__(
        self,
        config: Config,
        publish: Callable[..., None],
        brief: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.publish = publish
        self.brief = brief or (lambda: "")
        self.path = web_dir() / "chat.json"
        self._lock = threading.Lock()
        self._busy = False
        # Set by Stop, read by the session of the turn in flight: one per turn,
        # so a stop that arrives late cannot reach the next one.
        self._stop: threading.Event | None = None
        self._blank()
        self._load()
        files.prune(attachments_dir(), self.config.web.attachment_days)

    def _blank(self) -> None:
        """A conversation nobody has spoken in: not written anywhere until someone does."""
        self.id = secrets.token_hex(6)
        self.title = ""
        # Empty: the default of the settings, whatever it is when the turn runs.
        self.model = ""
        self.project = ""
        self.created = chats.now()
        self.session_id = ""
        self.turns = 0
        self.messages: list[Message] = []
        # The folder this conversation's files are kept in: named when the
        # first one arrives, and emptied with the conversation.
        self.folder_name = ""

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        """Reopen the conversation spoken in last — or the single one of `chat.json`.

        The file is what the console kept before there were many. It is read
        once, into the table, and set aside: the table is the truth from then on.
        """
        row = chats.latest()
        if row is None and chats.empty():
            row = self._imported()
        if row is not None:
            self._adopt(row)

    def _imported(self) -> dict | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or not raw.get("messages"):
            return None
        row = {
            "id": secrets.token_hex(6),
            "claude": str(raw.get("session_id") or ""),
            "turns": int(raw.get("turns") or 0),
            "folder": str(raw.get("files") or ""),
            "messages": [item for item in raw.get("messages", []) if isinstance(item, dict)],
        }
        first = next((item for item in row["messages"] if item.get("role") == "you"), {})
        row["title"] = chats.titled(str(first.get("text", "")))
        stamp = next((str(item["at"]) for item in reversed(row["messages"]) if item.get("at")), "")
        row["created"] = row["updated"] = stamp or chats.now()
        chats.save(row)
        try:
            self.path.rename(self.path.with_suffix(".json.imported"))
        except OSError:
            pass
        return chats.load(row["id"])

    def _adopt(self, row: dict) -> None:
        self.id = str(row["id"])
        self.title = str(row.get("title") or "")
        self.model = str(row.get("model") or "")
        self.project = str(row.get("project") or "")
        self.created = str(row.get("created") or chats.now())
        self.session_id = str(row.get("claude") or "")
        self.turns = int(row.get("turns") or 0)
        self.folder_name = str(row.get("folder") or "")
        self.messages = [
            Message(
                str(item.get("role", "")),
                str(item.get("text", "")),
                str(item.get("at", "")),
                [entry for entry in item.get("attachments") or [] if isinstance(entry, dict)],
            )
            for item in row.get("messages", [])
            # A turn you stopped before it said anything is still a turn: the
            # transcript says it was stopped, with nothing under it.
            if item.get("role")
            and (item.get("text") or item.get("attachments") or item.get("role") == "stopped")
        ]

    def _save(self) -> None:
        if not self.messages:
            # Nothing said, nothing to keep: a new conversation opened and left
            # again is not one more row in the list.
            return
        chats.save(
            {
                "id": self.id,
                "title": self.title,
                "model": self.model,
                "project": self.project,
                "claude": self.session_id,
                "turns": self.turns,
                "folder": self.folder_name,
                "created": self.created,
                "updated": chats.now(),
                # The transcript on disk is the console's scrollback, not the
                # session's memory: Claude Code keeps that itself. A hundred turns
                # is more than anybody scrolls back through.
                "messages": [message.as_dict() for message in self.messages[-200:]],
            }
        )

    # -- state ---------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    def state(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "model_in_use": self.effective_model(),
            "project": self.project,
            "session_id": self.session_id,
            "turns": self.turns,
            "busy": self._busy,
            "stopping": bool(self._stop and self._stop.is_set()),
            "resume_command": f"claude --resume {self.session_id}" if self.session_id else "",
            "attachments": {
                "max_mb": self.config.web.attachment_max_mb,
                "accepted": sorted(files.ACCEPTED),
                "ffmpeg": bool(files.ffmpeg()),
            },
            "dictation": {
                "ready": bool(self.config.openrouter.key),
                "why": ""
                if self.config.openrouter.key
                else (
                    "Dictation is transcribed by OpenRouter: add an OpenRouter key in the settings"
                ),
                "send": self.config.web.send_after_transcription,
            },
        }

    def history(self) -> list[dict]:
        return [message.as_dict() for message in self.messages]

    def reset(self) -> dict:
        """Start a new conversation. The old one stays in the list, to be reopened."""
        with self._lock:
            if self._busy:
                raise RuntimeError("a turn is in flight — let it finish first")
            self._blank()
        self.publish("chat", stage="reset")
        return self.state()

    # -- the conversations ---------------------------------------------------

    def sessions(self, query: str = "") -> list[dict]:
        """Every conversation, the latest first, flagged for the one that is open."""
        found = chats.listing(query)
        for item in found:
            item["current"] = item["id"] == self.id
        return found

    def open(self, identifier: str) -> dict:
        """Make another conversation the one the console talks to."""
        with self._lock:
            if self._busy:
                raise RuntimeError("a turn is in flight — let it finish first")
            if identifier != self.id:
                row = chats.load(identifier)
                if row is None:
                    raise LookupError("no such session")
                self._blank()
                self._adopt(row)
        self.publish("chat", stage="opened")
        return self.state()

    def rename(self, identifier: str, title: str) -> dict:
        title = " ".join(title.split())
        if not title:
            raise ValueError("a session needs a title")
        with self._lock:
            if identifier == self.id:
                self.title = title[:200]
                self._save()
            else:
                row = chats.load(identifier)
                if row is None:
                    raise LookupError("no such session")
                chats.save({**row, "title": title[:200]})
        self.publish("chat", stage="renamed", id=identifier)
        return self.state()

    def delete(self, identifier: str) -> dict:
        """Forget a conversation and the files that were dropped in it."""
        with self._lock:
            if identifier == self.id:
                if self._busy:
                    raise RuntimeError("a turn is in flight — let it finish first")
                folder = self.folder_name
                self._blank()
            else:
                row = chats.load(identifier)
                if row is None:
                    raise LookupError("no such session")
                folder = row.get("folder", "")
            chats.remove(identifier)
        if folder:
            files.Folder(attachments_dir(), folder).clear()
        self.publish("chat", stage="deleted", id=identifier)
        return self.state()

    def link(self, identifier: str, project: str) -> dict:
        """Say which project a conversation is about — or none, with an empty name."""
        project = " ".join(project.split())[:200]
        with self._lock:
            if identifier == self.id:
                self.project = project
                self._save()
            else:
                row = chats.load(identifier)
                if row is None:
                    raise LookupError("no such session")
                chats.save({**row, "project": project})
        self.publish("chat", stage="renamed", id=identifier)
        return self.state()

    # -- the model -----------------------------------------------------------

    def effective_model(self) -> str:
        """What a turn runs on: the conversation's own, else the settings' default."""
        return self.model or self.config.web.chat_model.strip() or self.config.runner.model

    def choose(self, model: str) -> dict:
        """Run this conversation on `model` from the next turn on; empty: the default."""
        model = model.strip()
        if model and not MODEL_NAME.match(model):
            raise ValueError(f"“{model}” is not a model name")
        if provider.on_openrouter(model) and not self.config.openrouter.key:
            raise ValueError("an OpenRouter model needs the OpenRouter key: add it in the settings")
        with self._lock:
            self.model = model
            self._save()
        self.publish("chat", stage="model", model=self.effective_model())
        return self.state()

    def models(self) -> dict:
        """What the picker offers: Claude's, and OpenRouter's when it has a key."""
        configured = bool(self.config.openrouter.key)
        listed: list[dict] = []
        why = ""
        if configured:
            try:
                listed = openrouter.catalogue(self.config.openrouter)
            except openrouter.Unavailable as error:
                why = str(error)
        return {
            "claude": [{"id": name, "name": name.capitalize()} for name in CLAUDE_MODELS],
            "openrouter": {"configured": configured, "models": listed, "error": why},
            "recent": chats.recent_models(),
            "default": self.config.web.chat_model.strip() or self.config.runner.model,
            "in_use": self.effective_model(),
        }

    # -- what a message carries ----------------------------------------------

    def folder(self) -> files.Folder:
        return files.Folder(attachments_dir(), self.folder_name or "none")

    def attach(self, name: str, source, length: int) -> dict:
        """Keep one file for the message being written; say what it became."""
        files.prune(attachments_dir(), self.config.web.attachment_days)
        with self._lock:
            if not self.folder_name:
                self.folder_name = secrets.token_hex(8)
                self._save()
        limit = self.config.web.attachment_max_mb * 1024 * 1024
        return self.folder().save(name, source, length, limit).as_dict()

    def detach(self, identifier: str) -> dict:
        self.folder().remove(identifier)
        return {"removed": identifier}

    def attachment(self, identifier: str) -> files.Attachment:
        return self.folder().find(identifier)

    def transcribe(self, audio: bytes, content_type: str, interface: str = "") -> dict:
        """What was said, as text, in the language the runner speaks.

        `runner.language` when it names one; otherwise the page's own language,
        which is what the person talking is reading; otherwise Whisper's guess.
        """
        asked = self.config.runner.language.strip()
        language = (
            voice.understood(asked) if asked else voice.understood(interface) if interface else ""
        )
        text = openrouter.transcribe(self.config.openrouter, audio, content_type, language)
        return {"text": text, "language": language}

    # -- one turn ------------------------------------------------------------

    def send(self, text: str, attached: list[str] | None = None) -> dict:
        text = text.strip()
        # Every id resolved before anything moves: a message whose file is gone
        # is refused whole, rather than sent without what it was about.
        carried = [self.attachment(str(identifier)) for identifier in attached or []]
        if not text and not carried:
            raise ValueError("nothing to send")
        if not session.available():
            raise FileNotFoundError("claude not found in PATH")
        if provider.on_openrouter(self.effective_model()) and not self.config.openrouter.key:
            raise ValueError(
                f"{self.effective_model()} runs on OpenRouter, which has no key: "
                "pick a Claude model, or add the key in the settings"
            )
        said = [attachment.as_dict() for attachment in carried]
        with self._lock:
            if self._busy:
                raise RuntimeError("the workspace is still answering the previous message")
            self._busy = True
            self._stop = threading.Event()
            first = not self.session_id
            if first:
                self.session_id = session.new_id()
            self.messages.append(Message("you", text, attachments=said))
            if not self.title:
                self.title = chats.titled(text) or (said[0]["name"] if said else "")
            self._save()
        self.publish("chat", stage="sent", text=text, attachments=said, session_id=self.session_id)
        thread = threading.Thread(
            target=self._turn, args=(text, first, carried, self._stop), name="tr-chat", daemon=True
        )
        thread.start()
        return self.state()

    def stop(self) -> dict:
        """Interrupt the turn in flight; the conversation carries on after it.

        Asking twice, or after the turn has ended on its own, is not an error:
        the button is pressed by somebody who saw a turn running, and the turn
        does not wait for the click to arrive before it finishes.
        """
        with self._lock:
            asked = self._stop
            if not self._busy or asked is None or asked.is_set():
                return self.state()
            asked.set()
        self.publish("chat", stage="stopping")
        return self.state()

    def _turn(
        self,
        text: str,
        first: bool,
        carried: list[files.Attachment] | None = None,
        stop: threading.Event | None = None,
    ) -> None:
        started = time.monotonic()
        log = web_dir() / f"chat-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        # Drawn here and not in `send`: taking frames from a video is seconds of
        # ffmpeg, and the page is waiting for `send` to say the message left.
        message = "\n\n".join(part for part in (text, files.brief(carried or [])) if part)
        if self.project:
            message = f"[This conversation is about the project “{self.project}”.]\n\n{message}"
        prompt = f"{self.brief()}\n\n{message}" if first else message
        chosen = self.effective_model()
        try:
            outcome = session.run(
                prompt,
                cwd=self._cwd(),
                log=log,
                # A slug is OpenRouter's to name; Fable is Opus where it is not allowed.
                model=chosen
                if provider.on_openrouter(chosen)
                else self.config.runner.allowed(chosen),
                permission_mode=self.config.runner.permission_mode,
                timeout_minutes=self.config.web.chat_timeout_minutes,
                session_id=self.session_id,
                resume=not first,
                environment=provider.environment(self.config, chosen),
                on_event=self._on_event,
                stop=stop,
            )
        except Exception as error:  # noqa: BLE001
            with self._lock:
                self._stop = None
                self.messages.append(Message("error", str(error)))
                # Written before the turn is said to be over: whoever waits for
                # `busy` to drop (a test, a restart) finds the transcript saved.
                self._save()
                self._busy = False
            self.publish("chat", stage="failed", text=str(error))
            return

        if outcome.stopped:
            self._stopped(outcome, first, started)
            return

        answer = outcome.answer or outcome.error or "(no answer)"
        with self._lock:
            self._stop = None
            self.turns += 1
            self.messages.append(Message("workspace" if outcome.ok else "error", answer))
            self._save()
            self._busy = False
        self.publish(
            "chat",
            stage="answer",
            text=answer,
            ok=outcome.ok,
            cost_usd=round(outcome.cost_usd, 4),
            seconds=round(time.monotonic() - started, 1),
            session_id=self.session_id,
        )

    def _stopped(self, outcome: session.Outcome, first: bool, started: float) -> None:
        """A turn you ended: what it had said is kept, and so is the session.

        Unless there was none to keep — a first turn stopped before Claude Code
        wrote its first line leaves an identifier nothing answers to, and the
        next message would be a `--resume` of a stranger. It starts afresh
        instead, brief included.
        """
        with self._lock:
            self._stop = None
            if first and not session.exists(self.session_id):
                self.session_id = ""
            else:
                self.turns += 1
            self.messages.append(Message("stopped", outcome.answer))
            self._save()
            self._busy = False
        self.publish(
            "chat",
            stage="stopped",
            text=outcome.answer,
            seconds=round(time.monotonic() - started, 1),
            session_id=self.session_id,
        )

    def _on_event(self, event: dict) -> None:
        for step in progress.describe(event):
            self.publish("chat", stage="step", label=step.label, detail=step.detail, said=step.said)

    def _cwd(self) -> Path:
        root = self.config.runner.workspace_root
        if root.is_dir():
            return root
        # A workspace_root that does not exist would fail the session before it
        # said a word. Home is a poor workspace and a fine fallback.
        return Path.home()


class Commands:
    """`ponos <verb>`, run for the browser and streamed back."""

    def __init__(self, publish: Callable[..., None], allowed: tuple[str, ...]) -> None:
        self.publish = publish
        # What the CLI offers *and* the console lists: a verb the parser lost is
        # not offered, and a verb the parser gained is not offered until it is
        # written into `OFFERED`. Offering a verb in the error message and then
        # refusing it would be a small lie told to somebody already lost.
        self.allowed = tuple(verb for verb in allowed if verb in OFFERED and verb not in REFUSED)
        self.timeout = COMMAND_TIMEOUT
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def parse(self, line: str) -> list[str]:
        """The argument list a typed command means, or an explanation of why not.

        `shlex` and no shell: the words that come out of here are handed to
        `execve` as they are, so a quote in a ticket title is a quote in a ticket
        title, and there is no interpreter left for a `;` to speak to.
        """
        try:
            argv = shlex.split(line.strip())
        except ValueError as error:
            raise ValueError(f"unbalanced quotes: {error}") from error
        if not argv:
            raise ValueError("no command")
        verb = argv[0].lstrip(">").strip()
        if not verb:
            raise ValueError("no command")
        argv[0] = verb
        if verb in REFUSED:
            raise ValueError(f"{verb} {REFUSED[verb]}")
        if verb not in self.allowed:
            offered = ", ".join(sorted(self.allowed))
            raise ValueError(f"unknown command “{verb}” — try one of: {offered}")
        # `logs -f` never returns, and the live panel already is that feed.
        if verb == "logs":
            return [word for word in argv if word not in ("-f", "--follow")]
        return argv

    def start(self, line: str) -> dict:
        argv = self.parse(line)
        with self._lock:
            if self._busy:
                raise RuntimeError("a command is already running")
            self._busy = True
        self.publish("command", stage="started", argv=argv)
        threading.Thread(target=self._run, args=(argv,), name="tr-command", daemon=True).start()
        return {"argv": argv}

    def _run(self, argv: list[str]) -> None:
        command = [sys.executable, "-m", "ponos", *argv]
        source = str(Path(__file__).resolve().parents[2])
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([source, os.environ.get("PYTHONPATH", "")]).rstrip(
                os.pathsep
            ),
            "PYTHONUNBUFFERED": "1",
            # No colour: the console renders the text, and escape codes would
            # reach it as mojibake. The CLI already drops them off a tty, but
            # `logs` writes its header to stderr either way.
            "NO_COLOR": "1",
        }
        self._stream(command, environment)

    def _stream(self, command: list[str], environment: dict[str, str] | None = None) -> None:
        """Run one command, publish what it says, and bound it — all of it.

        The command runs in a process group of its own, and the timeout ends
        the *group*: killing only the process we started used to leave whatever
        it had started in turn — a Claude session, most of all — running with
        nobody left to read it or to stop it.
        """
        code = -1
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path.home()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=environment,
                start_new_session=True,  # its own group: see `_end`
            )
        except OSError as error:
            self.publish("command", stage="line", text=f"could not start: {error}")
            with self._lock:
                self._busy = False
            self.publish("command", stage="ended", code=code)
            return

        expired = threading.Event()
        watchdog = threading.Timer(self.timeout, _end, args=(process, expired))
        watchdog.daemon = True
        watchdog.start()
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                self.publish("command", stage="line", text=line.rstrip("\n"))
            code = process.wait()
        finally:
            watchdog.cancel()
            with self._lock:
                self._busy = False
        if expired.is_set():
            self.publish(
                "command", stage="line", text=f"stopped after {self.timeout}s — too long for here"
            )
        self.publish("command", stage="ended", code=code)


def _end(process: subprocess.Popen, expired: threading.Event) -> None:
    """Stop a command's whole process group: asked first, then made to.

    The group, and not the process: with `start_new_session` its id is the
    leader's pid, and it outlives the leader for as long as anything it started
    is still alive — which is exactly what has to go.
    """
    expired.set()
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
