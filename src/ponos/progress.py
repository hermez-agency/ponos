"""What the session is doing, written into the ticket while it does it.

A run used to be a black box: the ticket went to *In progress* and nothing more
was said until the pull request arrived, half an hour later. The transcript was
there all along — `ponos logs -f` streams it — but that means a terminal
on the machine that runs the tickets, which is not where you are when you glance
at the board from a phone.

So the story goes **into the ticket**, as it happens. The run appends one toggle
to the page and writes under it what the agent says it is doing: the page stays
as short as it was, and the gist of the work is one click away. The toggle's own
title carries the count of steps and the elapsed time, so a collapsed toggle
still shows movement.

Two things keep it from becoming noise, and they are the whole design:

- **A cadence, not a stream.** Steps are buffered and written at most once every
  `progress_interval_seconds` (ten by default). A session emits several events a
  second; writing each one would rewrite the page continuously, spend the
  integration's rate limit and produce something nobody can read.
- **What was said, never what was done.** The page used to get a bullet per
  tool call — “Bash · npx vite --port 5199”, “Read /tmp/portrait.png” — between
  the agent's sentences, and a ticket became a log nobody reads twice: those
  lines teach nothing to whoever opens it. Only the prose goes down now, whole,
  one paragraph after the other, with its markdown honoured. A failed tool call
  stays off too: the agent's next sentence says what it made of it. The calls
  are still counted in the title and still shown, one at a time, in the board's
  `Progress` column; their detail is the run journal's (journal.py, which the
  console reads) and the log's (`ponos logs -f`) — `describe` feeds both.

Nothing here can fail a ticket. Every call to Notion is caught, and a page that
refuses three writes in a row switches the whole thing off for the rest of the
session — the work carries on, unreported.

Nor can it slow one down. The steps come from the loop that reads the session's
output, and a write to Notion can take minutes — four tries, each waiting out a
429 —, during which nothing read the pipe: it filled, and the CLI stopped on its
next write while its timeout kept running. A run's report is therefore written
from **a thread of its own**: feeding it only buffers, and what piles up while
Notion is slow goes down in one write when it answers. The buffer is bounded
too: past `MAX_STEPS` paragraphs a page would not take them anyway, and the
tool calls are only counted.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import markdown, store
from . import voice as voice_module

logger = logging.getLogger(__name__)

# The default cadence, in seconds. Ten is short enough to feel live and long
# enough that a page is not rewritten under the reader's eyes.
CADENCE = 10.0

# How much of a tool step survives into the board's column. A command, not a file.
LINE = 200

# How much of what the agent *said* survives. Generous on purpose: this is the
# part a human actually reads, and the only thing that should ever shorten it is
# a turn so long that a ticket page is the wrong place for it.
SAID = 5700

# A ceiling on the paragraphs one session writes into its ticket. A long session
# can make hundreds of tool calls without one too many, since they stay off the
# page; but a turn after turn of prose without end is a log file again.
MAX_STEPS = 300

# Consecutive Notion refusals after which the reporting gives up for good.
MAX_FAILURES = 3


@dataclass
class Step:
    """One line of the story: what was done, and to what."""

    label: str
    detail: str = ""
    # Prose — what the agent said, as opposed to what it did. It is written as a
    # paragraph rather than a bullet, and it is not cut.
    said: bool = False

    @property
    def line(self) -> str:
        return f"{self.label} · {self.detail}" if self.detail else self.label


# The tools worth naming, and the input that says what they were pointed at.
# Anything else falls through to `_hint`, which is right often enough.
_TOOLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Bash": ("Bash", ("command",)),
    "Read": ("Read", ("file_path", "notebook_path")),
    "Write": ("Write", ("file_path",)),
    "Edit": ("Edit", ("file_path",)),
    "MultiEdit": ("Edit", ("file_path",)),
    "NotebookEdit": ("Edit", ("notebook_path",)),
    "Glob": ("Search", ("pattern",)),
    "Grep": ("Search", ("pattern",)),
    "Task": ("Sub-agent", ("description", "prompt")),
    "WebFetch": ("Web", ("url",)),
    "WebSearch": ("Web", ("query",)),
    "TodoWrite": ("Plan", ()),
    "SlashCommand": ("Command", ("command",)),
}

_HINTS = ("file_path", "command", "pattern", "query", "url", "description", "path", "prompt")


def _one_line(text: str, limit: int = LINE) -> str:
    """A block of text reduced to something that fits on a bullet."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _prose(text: str) -> str:
    """What the agent said, kept whole — only its blank lines are tidied.

    Its line breaks are its own: a paragraph holds them, and an agent that laid
    its answer out in three lines meant three lines.
    """
    lines = [" ".join(line.split()) for line in str(text).splitlines()]
    flat = "\n".join(line for line in lines if line)
    return flat if len(flat) <= SAID else flat[: SAID - 1].rstrip() + "…"


def _hint(payload: dict[str, Any]) -> str:
    for key in _HINTS:
        value = payload.get(key)
        if value:
            return _one_line(value)
    return ""


def describe(event: dict[str, Any]) -> list[Step]:
    """The steps a stream-json event is worth, in reading order.

    Assistant events carry both what the agent said and what it decided to do;
    both belong on the board. Tool *results* do not — they are the payload, and
    the payload is what the log is for — except when they failed, which is
    exactly the moment somebody watching would want to know.
    """
    kind = event.get("type")
    steps: list[Step] = []
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text":
                spoken = _prose(block.get("text", ""))
                if spoken:
                    steps.append(Step(spoken, said=True))
            elif block.get("type") == "tool_use":
                name = str(block.get("name", "tool"))
                payload = block.get("input") or {}
                label, keys = _TOOLS.get(name, (name.split("__")[-1], ()))
                detail = ""
                for key in keys:
                    if payload.get(key):
                        detail = _one_line(payload[key])
                        break
                steps.append(Step(label, detail or _hint(payload)))
    elif kind == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                steps.append(Step("Error", _one_line(content or "")))
    return steps


# The titles `Live` gives its toggle, and has given it: “⏳ Live”, “⏳ Live — 4
# steps · 2 minutes” while it runs, “✓ 12 steps · 9 minutes” once done, “⚠️ Trace
# — 3 steps · …” when the run went wrong. Bold, all of it, as `_open` writes it.
_LIVE_TITLE = re.compile(r"⏳ .+|✓ \d+ .+|⚠️ .+ — \d+ .+", re.DOTALL)


def is_live(block: dict[str, Any]) -> bool:
    """Whether a block of a page is one of the toggles this module wrote.

    A ticket keeps the story of every run, and a page read as a brief must not:
    a ticket sent back to *Ready* would hand its next session the journal of
    the previous ones — tokens paid for nothing, and old steps an agent can
    take for instructions. No marker of our own is needed to tell them apart,
    and an older page has none anyway: the title is the mark, bold from end to
    end, opening on the sign of a run — and, once it has settled, on how many
    steps it counted. A
    toggle somebody wrote by hand rarely looks like that, and costs only itself
    if it does.
    """
    if block.get("type") != "toggle":
        return False
    parts = (block.get("toggle") or {}).get("rich_text") or []
    if not parts or not all((part.get("annotations") or {}).get("bold") for part in parts):
        return False
    title = "".join(
        part.get("plain_text") or (part.get("text") or {}).get("content", "") for part in parts
    )
    return bool(_LIVE_TITLE.fullmatch(title.strip()))


def _paragraph(step: Step) -> dict[str, Any]:
    """A sentence the agent wrote, as a sentence — whole, and in its own words.

    Notion caps one piece of rich text at two thousand characters, not the block
    that holds them, so a long turn is a handful of pieces and not a cut.
    """
    parts: list[dict[str, Any]] = []
    for start in range(0, len(step.label), markdown.MAX_CONTENT):
        parts += markdown.inline(step.label[start : start + markdown.MAX_CONTENT])
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": parts}}


class Live:
    """A ticket's live report: buffer the steps, write them on the cadence.

    Held by the job that runs the session, fed one event at a time, and closed
    when the session ends. Everything it writes is additive — the toggle it
    creates is its own, so a ticket run three times keeps the three stories.
    """

    def __init__(
        self,
        backend: store.Store,
        page_id: str,
        *,
        database: str = "",
        property_name: str = "",
        interval: float = CADENCE,
        heading: str = "",
        words: voice_module.Voice | None = None,
        clock: Callable[[], float] = time.monotonic,
        say: Callable[[str], None] = lambda message: None,
        background: bool = False,
    ) -> None:
        self.client = backend
        self.page_id = page_id
        self.database = database
        self.property_name = property_name
        self.interval = max(1.0, float(interval))
        # The block's title is read on the ticket, next to a report written in
        # the configured language: “⏳ Live — 16 step(s)” under a French verdict
        # was the runner speaking two languages in the same glance.
        self.words = words or voice_module.Voice()
        self.heading = heading or self.words.say("live")
        self.clock = clock
        self.say = say
        self.started = clock()
        self.written = 0
        self.disabled = False
        # What waits for the next write: the paragraphs, how many steps in all,
        # and the last of them — the only one the board's column shows.
        self._pending: list[Step] = []
        self._waiting = 0
        self._latest = ""
        self._lock = threading.Lock()
        self._last_flush = self.started
        # Off the session's path when `background`: the writer is started on
        # the first write that comes due, and `close` waits for it.
        self.background = background
        self._due = threading.Event()
        self._writer: threading.Thread | None = None
        self._closing = False
        self._toggle = ""
        self._paragraphs = 0
        self._failures = 0
        self._capped = False

    # -- feeding ------------------------------------------------------------

    def event(self, payload: dict[str, Any]) -> None:
        """One stream-json event. Writes only if the cadence has come round."""
        for step in describe(payload):
            self.add(step)

    def add(self, step: Step) -> None:
        if self.disabled:
            return
        # Two identical lines in a row say nothing the first one did not: an
        # agent saying the same sentence twice would otherwise write it twice,
        # and the same call made twice would count as two steps.
        with self._lock:
            if step.line == self._latest:
                return
            self._latest = step.line
            self._waiting += 1
            if step.said and len(self._pending) < MAX_STEPS:
                self._pending.append(step)
        if self.clock() - self._last_flush < self.interval:
            return
        if self.background:
            self._wake()
        else:
            self.flush()

    def _wake(self) -> None:
        """Hand the write to the writer, starting it the first time."""
        if self._closing:
            return
        if self._writer is None:
            self._writer = threading.Thread(target=self._write, name="live-report", daemon=True)
            self._writer.start()
        self._due.set()

    def _write(self) -> None:
        while True:
            self._due.wait()
            self._due.clear()
            if self._closing:
                return
            try:
                self.flush()
            except Exception as error:
                # The same fate as a reporter that throws on the session's own
                # thread: dropped, and the ticket runs to its end unwatched.
                logger.exception("    ! live report dropped: %s", error)
                self.disabled = True
                return

    # -- writing ------------------------------------------------------------

    def flush(self) -> int:
        """Write what has accumulated. Returns how many steps were written."""
        self._last_flush = self.clock()
        if self.disabled:
            return 0
        with self._lock:
            pending, self._pending = self._pending, []
            count, self._waiting = self._waiting, 0
            last = self._latest
        if not count:
            return 0
        said = pending[: max(0, MAX_STEPS - self._paragraphs)]

        if not self._open():
            return 0
        if said:
            try:
                self.client.append_blocks(self._toggle, [_paragraph(step) for step in said])
            except store.StoreError as error:
                self._failed(error)
                return 0
        self._failures = 0
        self.written += count
        self._paragraphs += len(said)
        self._retitle(f"⏳ {self.heading} — {self._tally()}")
        self._publish(_one_line(last))
        if self._paragraphs >= MAX_STEPS:
            self._cap()
        return count

    def close(self, note: str = "", *, ok: bool = True) -> None:
        """Last flush, then the toggle stops saying it is live.

        A run that ended badly renames it rather than ticking it: the block is
        no longer the story of a session, it is the trace of one, and it is
        where the report sends whoever wants the rest — see `detail`.

        The session is over by now: waiting here for a write still under way
        holds up the report, never the work.
        """
        if self._writer is not None:
            self._closing = True
            self._due.set()
            self._writer.join()
        if self.disabled:
            return
        self.flush()
        if not self._toggle:
            return
        tail = f" · {_one_line(note, 120)}" if note else ""
        if ok:
            self._retitle(f"✓ {self._tally()}{tail}")
        else:
            self._retitle(f"⚠️ {self.words.say('live-trace')} — {self._tally()}{tail}")
        # The ticket's own report — the comment, the status, the pull request —
        # is what speaks now; a column still showing “Edit src/x.py” would be
        # saying something that stopped being true.
        self._publish("")

    def detail(self, text: str) -> bool:
        """One last paragraph inside the block, and whether it got there.

        What a comment used to end on — the command that resumes the session,
        the log, the worktree that was kept — said once, folded, and only when
        a run went wrong. The answer matters to the caller: a block that was
        never opened, or a page that refused three writes, is not somewhere a
        trace can be left, and the report then carries it itself.
        """
        if self.disabled or not self._toggle or not str(text or "").strip():
            return False
        try:
            self.client.append_blocks(self._toggle, [_paragraph(Step(_prose(text)))])
        except store.StoreError as error:
            self._failed(error)
            return False
        return True

    # -- the page -----------------------------------------------------------

    def _open(self) -> bool:
        """Create the toggle, on the first step and not before.

        Lazily, so a session that ends before it did anything leaves no empty
        “Live” block behind on the ticket.
        """
        if self._toggle:
            return True
        try:
            created = self.client.append_blocks(
                self.page_id,
                [
                    {
                        "object": "block",
                        "type": "toggle",
                        "toggle": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": f"⏳ {self.heading}"},
                                    "annotations": {"bold": True},
                                }
                            ]
                        },
                    }
                ],
            )
        except store.StoreError as error:
            self._failed(error)
            return False
        if not created:
            self.disabled = True
            return False
        self._toggle = created[0]
        return True

    def _retitle(self, title: str) -> None:
        if not self._toggle:
            return
        try:
            self.client.update_block(
                self._toggle,
                {
                    "toggle": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": title[:LINE]},
                                "annotations": {"bold": True},
                            }
                        ]
                    }
                },
            )
        except store.StoreError as error:
            self._failed(error)

    def _publish(self, line: str) -> None:
        """The current step, in the board's own column — when there is one."""
        if not (self.database and self.property_name):
            return
        try:
            self.client.update(self.database, self.page_id, {self.property_name: line})
        except store.StoreError as error:
            self._failed(error)

    def _cap(self) -> None:
        """Enough. The paragraphs stop; the count and the title go on.

        A ticket page is not a log file, and a session that talks for hours
        would turn it into one. What stops here is the *page* — the run carries
        on, its title keeps counting, and `close` still says how it ended.
        """
        if self._capped:
            return
        self._capped = True
        if not self._toggle:
            return
        try:
            self.client.append_blocks(
                self._toggle,
                [_paragraph(Step("… " + self.words.say("too-many-steps", count=MAX_STEPS)))],
            )
        except store.StoreError:
            pass

    def _tally(self) -> str:
        elapsed = self.clock() - self.started
        return f"{self.words.count(self.written, 'step')} · {self.words.minutes(elapsed)}"

    def _failed(self, error: store.StoreError) -> None:
        self._failures += 1
        if self._failures < MAX_FAILURES:
            return
        self.disabled = True
        self.say(f"    ! live steps switched off for this ticket: {error}")
