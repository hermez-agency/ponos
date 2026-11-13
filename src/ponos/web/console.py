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
`ponos.db` (see `chats`) with its own title, model and files, and its own run:
several can be answering at once (`Chats`, bounded by `Web.chat_max_turns`).
The server holds no conversation "open" — each browser follows the one it chose,
and every call names the conversation it is about.

A message is more than its words: what it carries — a screenshot, a PDF, a clip
— is kept in a folder of the conversation, and named in the prompt by path (see
`attachments`). And what is said aloud is turned into words before it is a
message at all: dictation is transcribed, handed back, read over, and only then
sent, like anything typed.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import disk, openrouter, progress, provider, session, speech, voice
from .. import log as log_module
from ..config import Config, state_dir
from . import agui, chats
from . import attachments as files

logger = logging.getLogger(__name__)

# The verbs the console runs, written down one by one rather than read off the
# parser. Deriving them was the convenient answer and the wrong one: every verb
# added to the CLI became something a browser could start, including the ones
# that start Claude sessions (`run`), rewrite the installation (`update`) or
# delete worktrees a session is standing in (`clean`). A command typed here is
# bounded by `COMMAND_TIMEOUT` and runs as whoever the console runs as; what is
# listed is what fits both — it reads, it reconciles, it says something, and it
# is done in seconds.
OFFERED = (
    "diagnose",
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
    "service": (
        "starts and stops the console you are typing in — do it from a terminal; "
        "`status` says how the units stand"
    ),
    "run": (
        "starts Claude sessions that outlive a command typed here — make the ticket "
        "ready and the timer runs it, or type `ponos run` in a terminal"
    ),
    "update": (
        "replaces the code this console is running — the version at the top right "
        "offers it when there is one, or type it in a terminal"
    ),
    "clean": "deletes worktrees a session may be standing in — do it from a terminal",
    "mcp": "draws and takes back the MCP server's keys — do it from a terminal",
    "vault": "keeps and removes the sessions' keys — Context → Vault, or a terminal",
}

# The Claude models the console offers, whatever else is configured: the ones
# Claude Code names by family, and that models.py knows how to read.
CLAUDE_MODELS = ("opus", "sonnet", "haiku", "fable")

# What a model may be called: a family, a full Claude id, or an OpenRouter slug.
# Nothing a shell or a flag could mistake for something else.
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*(\[[0-9a-z]+\])?$")

# A command is not a session: nothing in the CLI legitimately takes minutes.
COMMAND_TIMEOUT = 180


def web_dir() -> Path:
    return disk.private_dir(state_dir() / "web")


def attachments_dir() -> Path:
    return web_dir() / "attachments"


@dataclass
class Message:
    role: str
    text: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    # What came with it, as the page draws it: name, kind, size, and the id the
    # file is served back under for as long as the conversation keeps it.
    attachments: list[dict[str, Any]] = field(default_factory=list)
    # The page's own name for it: the id `useChat` gave the message you typed,
    # so that the conversation it is sent back in does not draw it twice.
    id: str = ""
    # What a turn of the workspace streamed, kept in the shape it was drawn in
    # (see agui.py) — and how long it took, and what it cost.
    parts: list[dict[str, Any]] = field(default_factory=list)
    seconds: float | None = None
    cost: float | None = None

    def as_dict(self) -> dict[str, Any]:
        said: dict[str, Any] = {"role": self.role, "text": self.text, "at": self.at}
        if self.attachments:
            said["attachments"] = self.attachments
        if self.id:
            said["id"] = self.id
        if self.parts:
            said["parts"] = self.parts
        if self.seconds is not None:
            said["seconds"] = self.seconds
        if self.cost is not None:
            said["cost"] = self.cost
        return said

    def as_ui(self, fallback: str) -> dict[str, Any]:
        """The message as `useChat` holds it: a `UIMessage`, with its parts.

        A message from before there were parts is its text, in one part. What
        Ponos alone knows — who said it in its own words (an answer, a problem,
        a turn you stopped), the files, the time and the cost — rides in
        `metadata.ponos`, which TanStack AI carries without reading.
        """
        ponos: dict[str, Any] = {"role": self.role, "at": self.at}
        if self.attachments:
            ponos["attachments"] = self.attachments
        if self.seconds is not None:
            ponos["seconds"] = self.seconds
        if self.cost is not None:
            ponos["cost"] = self.cost
        if self.role == "you":
            parts: list[dict[str, Any]] = (
                [{"type": "text", "content": self.text}] if self.text else []
            )
            role = "user"
        elif self.role == "error":
            # A problem is said apart from what streamed before it: the page
            # draws it as a problem, under the parts.
            parts = list(self.parts)
            ponos["error"] = self.text
            role = "assistant"
        else:
            parts = list(self.parts)
            # An answer whose words are not in its parts — the session said
            # them in its result alone, or the message is older than parts.
            if self.text and not any(part.get("type") == "text" for part in parts):
                parts.append({"type": "text", "content": self.text})
            role = "assistant"
        return {
            "id": self.id or fallback,
            "role": role,
            "parts": parts,
            "createdAt": self.at,
            "metadata": {"ponos": ponos},
        }


def _messages(row: dict[str, Any]) -> list[Message]:
    """The transcript of a conversation's row, as messages."""
    return [
        Message(
            str(item.get("role", "")),
            str(item.get("text", "")),
            str(item.get("at", "")),
            [entry for entry in item.get("attachments") or [] if isinstance(entry, dict)],
            id=str(item.get("id") or ""),
            parts=[part for part in item.get("parts") or [] if isinstance(part, dict)],
            seconds=item.get("seconds"),
            cost=item.get("cost"),
        )
        for item in row.get("messages", [])
        # A turn you stopped before it said anything is still a turn: the
        # transcript says it was stopped, with nothing under it.
        if item.get("role")
        and (
            item.get("text")
            or item.get("attachments")
            or item.get("parts")
            or item.get("role") == "stopped"
        )
    ]


@dataclass
class Queued:
    """A message sent while the workspace was still answering: it waits its turn."""

    text: str
    carried: list[files.Attachment]
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    # The run and the message `useChat` named, when it is the page that sent
    # it through AG-UI: kept until the turn starts, so it starts under them.
    run_id: str = ""
    message_id: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def as_dict(self) -> dict[str, Any]:
        said: dict[str, Any] = {"id": self.id, "text": self.text, "at": self.at}
        if self.carried:
            said["attachments"] = [attachment.as_dict() for attachment in self.carried]
        return said


# What the console names a conversation: twelve hex digits, like its files.
_NAME = re.compile(r"[0-9a-f]{12}")


class Chats:
    """Every conversation the console holds, and the places their turns share.

    A conversation is a `Chat`, and each carries its own state of execution —
    the turn in flight, the messages waiting behind it, the Stop event, the
    AG-UI stream. What belongs to none of them is here: the registry, the list
    of conversations, the model catalogue, the voice, and the limit on how many
    turns run at once (`Web.chat_max_turns`), since each is a Claude session
    that spends the subscription.

    Which conversation a browser follows is that browser's own business: the
    server holds no "open" one, and every call names the conversation it is
    about. One lock serves all of them — what it protects is bookkeeping done in
    microseconds, and a turn itself runs outside it — which is also what keeps
    "is there a place left?" and "take it" a single step.
    """

    # Past this many held in memory, the ones nobody is using go back to the
    # database they came from.
    HELD = 30

    def __init__(
        self,
        config: Config,
        publish: Callable[..., None],
        brief: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self.publish = publish
        self.brief = brief or (lambda: "")
        self.lock = threading.RLock()
        self._held: dict[str, Chat] = {}
        files.prune(attachments_dir(), self._config.web.attachment_days)

    @property
    def config(self) -> Config:
        return self._config

    @config.setter
    def config(self, fresh: Config) -> None:
        self._config = fresh

    def _make(self, identifier: str, row: dict[str, Any] | None = None) -> Chat:
        return Chat(self, identifier, row)

    # -- the registry --------------------------------------------------------

    def get(self, identifier: str, blank: bool = False) -> Chat:
        """The conversation of that name: held, else read from its row.

        With `blank`, a name nothing answers to is a conversation nobody has
        spoken in yet — a browser may hold the name of one the server forgot
        (a restart, a tidy), and it is not an error to carry on in it.
        """
        with self.lock:
            found = self._held.get(identifier)
            if found is not None:
                return found
            row = chats.load(identifier) if _NAME.fullmatch(identifier) else None
            if row is None and not (blank and _NAME.fullmatch(identifier)):
                raise LookupError("no such session")
            found = self._make(identifier, row)
            self._held[identifier] = found
            self._tidy(keep=found)
            return found

    def create(self, like: str = "") -> Chat:
        """A new conversation, on the model of `like` — starting over is not changing one's mind."""
        with self.lock:
            model = ""
            if like:
                try:
                    model = self.get(like, blank=True).model
                except LookupError:
                    model = ""
            chat = self._make(secrets.token_hex(6))
            chat.model = model
            self._held[chat.id] = chat
            self._tidy(keep=chat)
            return chat

    def latest(self) -> Chat:
        """The conversation spoken in last, or a new one: where a browser with none starts."""
        row = chats.latest()
        return self.get(str(row["id"])) if row is not None else self.create()

    def hold(self, chat: Chat) -> None:
        """Keep a conversation that is about to run where the places are counted."""
        self._held[chat.id] = chat

    def _tidy(self, keep: Chat) -> None:
        """Forget the conversations nobody is using: blank ones, and saved ones past `HELD`.

        Never the one just asked for, nor one the caller may still hold: a
        blank conversation held by a browser is recreated by name when asked for.
        """
        idle = [chat for chat in self._held.values() if chat.idle() and chat is not keep]
        for chat in idle:
            if not chat.messages or len(self._held) > self.HELD:
                del self._held[chat.id]

    @property
    def busy(self) -> bool:
        with self.lock:
            return any(chat.busy for chat in self._held.values())

    # -- the places ----------------------------------------------------------

    @property
    def limit(self) -> int:
        return max(1, self._config.web.chat_max_turns)

    def running(self) -> int:
        with self.lock:
            return sum(1 for chat in self._held.values() if chat.busy)

    def room(self) -> bool:
        """Whether one more turn may start now. The lock is held by whoever asks."""
        return self.running() < self.limit

    def advance(self) -> None:
        """Start what waits for a place, the oldest message first, as places free up."""
        with self.lock:
            waiting = sorted(
                (chat for chat in self._held.values() if chat.queue and not chat.busy),
                key=lambda chat: chat.queue[0].at,
            )
            for chat in waiting:
                if not self.room():
                    return
                chat.advance()

    # -- state ---------------------------------------------------------------

    def defaults(self) -> dict[str, Any]:
        """What holds for every conversation: what a message may carry, the voice, the places."""
        why = speech.refusal(self.config.speech)
        return {
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
            "speech": {
                "ready": not why,
                "why": why,
                "installable": self.config.speech.enabled and not speech.available(),
            },
            "running": self.running(),
            "limit": self.limit,
        }

    def sessions(self, query: str = "") -> list[dict[str, Any]]:
        """Every conversation, the latest first, with the ones answering or unread flagged."""
        found = chats.listing(query)
        with self.lock:
            for item in found:
                held = self._held.get(item["id"])
                item["busy"] = bool(held and held.busy)
                item["waiting"] = bool(held and held.queue and not held.busy and not held.held)
                item["unread"] = bool(held and held.unread)
        return found

    # -- the conversations ---------------------------------------------------

    def rename(self, identifier: str, title: str) -> dict[str, Any]:
        title = " ".join(title.split())
        if not title:
            raise ValueError("a session needs a title")
        chat = self.get(identifier)
        with self.lock:
            chat.title = title[:200]
            chat.save()
        self.publish("chat", stage="renamed", id=identifier)
        return chat.state()

    def link(self, identifier: str, project: str) -> dict[str, Any]:
        """Say which project a conversation is about — or none, with an empty name."""
        project = " ".join(project.split())[:200]
        chat = self.get(identifier)
        with self.lock:
            chat.project = project
            chat.save()
        self.publish("chat", stage="renamed", id=identifier)
        return chat.state()

    def delete(self, identifier: str) -> dict[str, Any]:
        """Forget a conversation and the files dropped in it.

        A turn still answering is stopped first, and what it would have said is
        thrown away with the rest: it never writes the row back.
        """
        with self.lock:
            chat = self.get(identifier)
            folder = chat.folder_name
            chat.discard_all()
            self._held.pop(identifier, None)
            chats.remove(identifier)
        if folder:
            files.Folder(attachments_dir(), folder).clear()
        self.publish("chat", stage="deleted", id=identifier)
        self.advance()
        return {"id": identifier}

    # -- the model -----------------------------------------------------------

    def effective_model(self, model: str = "") -> str:
        """What a turn runs on: the conversation's own, else the settings' default."""
        return model or self.config.web.chat_model.strip() or self.config.runner.model

    def models(self, current: str = "") -> dict[str, Any]:
        """What the picker offers: Claude's, and OpenRouter's when it has a key."""
        configured = bool(self.config.openrouter.key)
        listed: list[dict[str, Any]] = []
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
            "in_use": self.effective_model(current),
        }

    # -- the voice -----------------------------------------------------------

    def transcribe(self, audio: bytes, content_type: str, interface: str = "") -> dict[str, Any]:
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

    def speech_plan(self, text: str, lang: str, final: bool) -> dict[str, Any]:
        """The sentences of a reply worth saying aloud, in the language of the page."""
        spoken = self.config.runner.language.strip() or lang
        speech.warm(self.config.speech, spoken)
        return {"sentences": speech.plan(text, spoken, final), "language": voice.understood(spoken)}

    def speak(self, text: str, lang: str) -> bytes:
        """A sentence of the reply as a WAV, in the voice of the language."""
        spoken = self.config.runner.language.strip() or lang
        return speech.synthesize(self.config.speech, text, spoken)

    def attachment(self, identifier: str) -> files.Attachment:
        """A file of any conversation, by its name: they are unguessable, and found where they were kept."""
        if not _NAME.fullmatch(identifier or ""):
            raise LookupError(f"no such attachment: {identifier}")
        root = attachments_dir()
        for path in root.glob(f"*/{identifier}-*") if root.is_dir() else ():
            if path.is_file():
                return files.Attachment(identifier, path.name[len(identifier) + 1 :], path)
        raise LookupError(
            f"no such attachment: {identifier} — it was removed, or the conversation is over"
        )


class Chat:
    """One conversation with the whole workspace, kept across restarts.

    It holds its own run: whether a turn is in flight, what waits behind it,
    the event that stops it, the AG-UI of it. Another conversation's turn is
    none of its business, except for the places they share (see `Chats`).
    """

    def __init__(self, chats_: Chats, identifier: str, row: dict[str, Any] | None = None) -> None:
        self.chats = chats_
        self._lock = chats_.lock
        self._busy = False
        # Set by Stop, read by the session of the turn in flight: one per turn,
        # so a stop that arrives late cannot reach the next one.
        self._stop: threading.Event | None = None
        # What was said while a turn ran, in the order it was said. Kept in
        # memory and not in the row: a turn does not survive a restart, and a
        # queue for a turn that is gone would be sent by nobody.
        self.queue: list[Queued] = []
        # A turn that ended before its time (Stop, or an error) leaves the queue
        # alone until somebody chooses between sending it and throwing it away.
        self.held = False
        # The turn in flight, as AG-UI says it (see agui.py): what a page that
        # opens mid-turn is drawn, and what the events of the session go through.
        self.turn: agui.Turn | None = None
        # An answer nobody has read yet: set when a turn ends, cleared by `read`.
        # In memory — it is a hint for the list, not part of the conversation.
        self.unread = False
        # Deleted while it ran: nothing it says afterwards is written anywhere.
        self.discarded = False
        # Whoever follows the turns in AG-UI on a stream of their own, besides
        # the pages that read them on `/api/events` — see `listen`.
        self._listeners: set[queue.Queue[dict[str, Any]]] = set()
        self.id = identifier
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
        if row is not None:
            self._adopt(row)

    @property
    def config(self) -> Config:
        return self.chats.config

    def publish(self, kind: str, **said: Any) -> None:
        """An event of the stream, said to be about this conversation."""
        if kind == "chat":
            said["id"] = self.id
        self.chats.publish(kind, **said)

    def brief(self) -> str:
        return self.chats.brief()

    def idle(self) -> bool:
        """Nothing runs in it and nothing waits: it can be forgotten and read again.

        Not a blank one that already has a model chosen or files dropped in it:
        nothing on disk would bring those back.
        """
        unsaved = not self.messages and bool(self.model or self.folder_name)
        return not self._busy and not self.queue and not self._listeners and not unsaved

    # -- persistence ---------------------------------------------------------

    def _adopt(self, row: dict[str, Any]) -> None:
        self.title = str(row.get("title") or "")
        self.model = str(row.get("model") or "")
        self.project = str(row.get("project") or "")
        self.created = str(row.get("created") or chats.now())
        self.session_id = str(row.get("claude") or "")
        self.turns = int(row.get("turns") or 0)
        self.folder_name = str(row.get("folder") or "")
        self.messages = _messages(row)

    def save(self) -> None:
        if not self.messages or self.discarded:
            # Nothing said, nothing to keep: a new conversation opened and left
            # again is not one more row in the list. And a deleted one stays so.
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

    def state(self) -> dict[str, Any]:
        return {
            **self.chats.defaults(),
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "model_in_use": self.effective_model(),
            "project": self.project,
            "session_id": self.session_id,
            "turns": self.turns,
            "busy": self._busy,
            "stopping": bool(self._stop and self._stop.is_set()),
            "queue": [queued.as_dict() for queued in self.queue],
            "held": self.held,
            # Something waits and nothing runs, and it was not a Stop that held
            # it: every place is taken by another conversation.
            "limited": bool(self.queue) and not self._busy and not self.held,
            "unread": self.unread,
            "resume_command": f"claude --resume {self.session_id}" if self.session_id else "",
        }

    def history(self) -> list[dict[str, Any]]:
        return [message.as_dict() for message in self.messages]

    def read(self) -> dict[str, Any]:
        """The answer has been seen, by somebody following this conversation."""
        if self.unread:
            self.unread = False
            self.publish("chat", stage="read")
        return self.state()

    # -- in AG-UI ------------------------------------------------------------

    def ui(self) -> list[dict[str, Any]]:
        """The conversation as `useChat` holds it — the turn in flight included."""
        said = [message.as_ui(f"{self.id}-{index}") for index, message in enumerate(self.messages)]
        turn = self.turn
        if turn is not None:
            said.append(
                {
                    "id": turn.message_id,
                    "role": "assistant",
                    "parts": list(turn.parts),
                    "metadata": {"ponos": {"role": "workspace"}},
                }
            )
        return said

    def thread(self) -> dict[str, Any]:
        """What `useChat` hydrates the conversation from: Ponos's own storage.

        Its turn in flight included, read from memory — which is how a page
        that comes back to a conversation catches up. Never a run to rejoin:
        the events of the turn come on the stream every page already has open.
        """
        return {"messages": self.ui(), "activeRun": None, "interrupts": None}

    def listen(self) -> queue.Queue[dict[str, Any]]:
        """A channel for every AG-UI event of the turns from now on."""
        channel: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._listeners.add(channel)
        return channel

    def unlisten(self, channel: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._listeners.discard(channel)

    def _emit(self, events: list[dict[str, Any]]) -> None:
        """AG-UI events, to every page (`/api/events`) and every listener."""
        listeners = list(self._listeners)
        for event in events:
            self.chats.publish("agui", event=event, thread=self.id)
            for channel in listeners:
                try:
                    channel.put_nowait(event)
                except queue.Full:
                    # A client that stopped reading went away: its stream ends
                    # without the turn waiting for it.
                    pass

    def _snapshot(self) -> None:
        self._emit([agui.snapshot(self.ui())])

    # -- the model -----------------------------------------------------------

    def effective_model(self) -> str:
        return self.chats.effective_model(self.model)

    def choose(self, model: str) -> dict[str, Any]:
        """Run this conversation on `model` from the next turn on; empty: the default."""
        model = model.strip()
        if model and not MODEL_NAME.match(model):
            raise ValueError(f"“{model}” is not a model name")
        if provider.on_openrouter(model) and not self.config.openrouter.key:
            raise ValueError("an OpenRouter model needs the OpenRouter key: add it in the settings")
        with self._lock:
            self.model = model
            self.save()
        self.publish("chat", stage="model", model=self.effective_model())
        return self.state()

    # -- what a message carries ----------------------------------------------

    def folder(self) -> files.Folder:
        return files.Folder(attachments_dir(), self.folder_name or "none")

    def attach(self, name: str, source: files.Source, length: int) -> dict[str, Any]:
        """Keep one file for the message being written; say what it became."""
        files.prune(attachments_dir(), self.config.web.attachment_days)
        with self._lock:
            if not self.folder_name:
                self.folder_name = secrets.token_hex(8)
                self.save()
        limit = self.config.web.attachment_max_mb * 1024 * 1024
        return self.folder().save(name, source, length, limit).as_dict()

    def detach(self, identifier: str) -> dict[str, Any]:
        self.folder().remove(identifier)
        return {"removed": identifier}

    def attachment(self, identifier: str) -> files.Attachment:
        return self.folder().find(identifier)

    # -- one turn ------------------------------------------------------------

    def send(
        self,
        text: str,
        attached: list[str] | None = None,
        run_id: str = "",
        message_id: str = "",
    ) -> dict[str, Any]:
        """Say something to the workspace — now, or behind the turn in flight.

        `run_id` and `message_id` are the names `useChat` gave the run and the
        message, when they came through AG-UI (see `run`): the turn is said
        under them, so the page that sent it recognises its own.

        It waits, in this conversation's queue, behind the turn in flight, and
        also when every place is taken by other conversations' turns.
        """
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
        with self._lock:
            self.chats.hold(self)
            if self._busy or self.queue or not self.chats.room():
                # Behind the turn in flight, and behind whatever already waits.
                self.queue.append(Queued(text, carried, run_id=run_id, message_id=message_id))
                queued = True
            else:
                self._begin(text, carried, run_id, message_id)
                queued = False
        if queued:
            self._announce_queue()
        return self.state()

    def run(self, given: dict[str, Any]) -> dict[str, Any]:
        """A run asked for in AG-UI (`RunAgentInput`): its last user message, said.

        The conversation is the server's, not the page's: of the messages the
        run carries, only the last one the user wrote is new, and the rest is
        what this conversation already holds. A run for another conversation
        than the one the door names is refused rather than said in the wrong place.
        """
        thread = str(given.get("threadId") or "")
        if thread and thread != self.id:
            raise RuntimeError("this run is for another conversation — reload the page")
        message = agui.last_user(list(given.get("messages") or []))
        forwarded = given.get("forwardedProps")
        attached = forwarded.get("attachments") if isinstance(forwarded, dict) else None
        return self.send(
            agui.user_text(message),
            [str(item) for item in attached or []],
            run_id=str(given.get("runId") or ""),
            message_id=str(message.get("id") or ""),
        )

    def _begin(
        self,
        text: str,
        carried: list[files.Attachment],
        run_id: str = "",
        message_id: str = "",
    ) -> None:
        """Start a turn on `text`. The lock is held, and nothing is running."""
        self._busy = True
        self.unread = False
        self._stop = threading.Event()
        first = not self.session_id
        if first:
            self.session_id = session.new_id()
        said = [attachment.as_dict() for attachment in carried]
        self.messages.append(
            Message("you", text, attachments=said, id=message_id or agui.new_id("you"))
        )
        if not self.title:
            self.title = chats.titled(text) or (said[0]["name"] if said else "")
        self.save()
        self.publish("chat", stage="sent", text=text, attachments=said, session_id=self.session_id)
        # The conversation first, with the message that starts the turn in it:
        # every page has it before the first word of the answer arrives.
        self._snapshot()
        turn = agui.Turn(self.id, run_id)
        self.turn = turn
        self._emit(turn.started())
        thread = threading.Thread(
            target=self._turn,
            args=(text, first, carried, self._stop, turn),
            name="tr-chat",
            daemon=True,
        )
        thread.start()

    # -- the queue -----------------------------------------------------------

    def _announce_queue(self) -> None:
        self.publish(
            "chat",
            stage="queue",
            queue=[queued.as_dict() for queued in self.queue],
            held=self.held,
            limited=bool(self.queue) and not self._busy and not self.held,
        )

    def advance(self) -> None:
        """Start the next waiting message, once the turn before it is over and a place is free."""
        with self._lock:
            if self._busy or self.held or not self.queue or self.discarded:
                return
            if not self.chats.room():
                return
            waiting = self.queue.pop(0)
            # Taken off the list before it is said in the transcript: the page
            # must not show it twice, waiting and sent.
            self._announce_queue()
            self._begin(waiting.text, waiting.carried, waiting.run_id, waiting.message_id)

    def _waiting(self, identifier: str) -> Queued:
        found = next((queued for queued in self.queue if queued.id == identifier), None)
        if found is None:
            # Already sent, or already taken back — from another tab, say.
            raise LookupError("no such waiting message")
        return found

    def unqueue(self, identifier: str) -> dict[str, Any]:
        """Take a waiting message back: it is never sent."""
        with self._lock:
            self.queue.remove(self._waiting(identifier))
            if not self.queue:
                self.held = False
        self._announce_queue()
        return self.state()

    def amend(self, identifier: str, text: str) -> dict[str, Any]:
        """Change the words of a message that has not been sent yet."""
        text = text.strip()
        with self._lock:
            waiting = self._waiting(identifier)
            if not text and not waiting.carried:
                raise ValueError("nothing to send")
            waiting.text = text
        self._announce_queue()
        return self.state()

    def release(self) -> dict[str, Any]:
        """Send what waits, after a turn that ended before its time."""
        with self._lock:
            self.held = False
        self.chats.advance()
        self._announce_queue()
        return self.state()

    def discard(self) -> dict[str, Any]:
        """Throw away everything that waits."""
        with self._lock:
            self.queue = []
            self.held = False
        self._announce_queue()
        return self.state()

    def discard_all(self) -> None:
        """The conversation is being deleted: stop its turn, drop its queue, write nothing more."""
        with self._lock:
            self.discarded = True
            self.queue = []
            self.held = False
            if self._stop is not None:
                self._stop.set()

    def stop(self) -> dict[str, Any]:
        """Interrupt the turn in flight; the conversation carries on after it.

        Asking twice, or after the turn has ended on its own, is not an error:
        the button is pressed by somebody who saw a turn running, and the turn
        does not wait for the click to arrive before it finishes. It stops this
        conversation's turn and no other.
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
        turn: agui.Turn | None = None,
    ) -> None:
        started = time.monotonic()
        turn = turn or agui.Turn(self.id)
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
                on_event=lambda event: self._on_event(event, turn),
                stop=stop,
                attribution=self.config.claude.attribution,
            )
        except Exception as error:
            logger.exception("console: the turn failed", extra=log_module.FILE_ONLY)
            with self._lock:
                self._stop = None
                self.messages.append(
                    Message("error", str(error), id=turn.message_id, parts=turn.parts)
                )
                # Written before the turn is said to be over: whoever waits for
                # `busy` to drop (a test, a restart) finds the transcript saved.
                self.save()
                self.turn = None
                self._busy = False
                self.unread = True
                self.held = bool(self.queue)
            self._emit(turn.failed(str(error)))
            self._snapshot()
            self.publish("chat", stage="failed", text=str(error))
            if self.held:
                self._announce_queue()
            # The place it held is free: another conversation may be waiting for it.
            self.chats.advance()
            return

        if outcome.stopped:
            self._stopped(outcome, first, started, turn)
            return

        answer = outcome.answer or outcome.error or "(no answer)"
        seconds = round(time.monotonic() - started, 1)
        last = turn.concluded(outcome.answer) if outcome.ok else []
        with self._lock:
            self._stop = None
            self.turns += 1
            self.messages.append(
                Message(
                    "workspace" if outcome.ok else "error",
                    answer,
                    id=turn.message_id,
                    parts=turn.parts,
                    seconds=seconds,
                    cost=round(outcome.cost_usd, 4),
                )
            )
            self.save()
            self.turn = None
            self._busy = False
            self.unread = True
        self._emit([*last, *turn.finished()])
        self._snapshot()
        self.publish(
            "chat",
            stage="answer",
            text=answer,
            ok=outcome.ok,
            cost_usd=round(outcome.cost_usd, 4),
            seconds=seconds,
            session_id=self.session_id,
        )
        # Its own queue first, then whatever waits for a place in other conversations.
        self.chats.advance()

    def _stopped(
        self, outcome: session.Outcome, first: bool, started: float, turn: agui.Turn
    ) -> None:
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
            seconds = round(time.monotonic() - started, 1)
            self.messages.append(
                Message(
                    "stopped",
                    outcome.answer,
                    id=turn.message_id,
                    parts=turn.parts,
                    seconds=seconds,
                )
            )
            self.save()
            self.turn = None
            self._busy = False
            self.unread = True
            self.held = bool(self.queue)
        self._emit(turn.finished(stopped=True))
        self._snapshot()
        self.publish(
            "chat",
            stage="stopped",
            text=outcome.answer,
            seconds=seconds,
            session_id=self.session_id,
        )
        if self.held:
            self._announce_queue()
        self.chats.advance()

    def _on_event(self, event: dict[str, Any], turn: agui.Turn | None = None) -> None:
        if turn is not None:
            self._emit(turn.read(event))
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

    def start(self, line: str) -> dict[str, Any]:
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


def _end(process: subprocess.Popen[str], expired: threading.Event) -> None:
    """Stop a command's whole process group, as `session.halt` stops a session's.

    One sequence for both, so that what changes in how a group is ended
    changes for a command typed here too.
    """
    expired.set()
    session.halt(process)
