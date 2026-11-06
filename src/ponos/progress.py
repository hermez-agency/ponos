"""What the session is doing, said on the board while it does it.

A run used to be a black box: the ticket went to *In progress* and nothing more
was said until the pull request arrived, half an hour later. Then the story
went into the ticket itself: one folded block per run, appended to the page,
holding every sentence the agent said. A ticket run three times ended on three
of them, nobody could tell at a glance what stood done, and the page read as a
brief could carry them into the next prompt. So the page is now the ticket's
mission and what was done, rewritten at the end of each session (ticket_page.py),
and the steps live where they are read step by step: the run journal
(journal.py, which the console's live tab reads) and the log (`ponos logs -f`).
`describe` feeds both.

What remains here is the one line of the board's `Progress` column, which a
card shows from a phone without opening anything:

- **A cadence, not a stream.** Steps are counted and the last one published at
  most once every `progress_interval_seconds` (ten by default). A session emits
  several events a second; writing each one would spend the integration's rate
  limit for a line nobody can read that fast.
- **A percentage only from a plan.** The agent cannot know how many tool calls
  it will make, so a share of steps would be a guess dressed as a figure. What
  it does know is its todo list: `TodoWrite` becomes a `Plan` step whose detail
  is the list, and the column says “3/5 — writing the tests” from it. No plan,
  no figure: the column keeps saying the last thing done, and the console draws
  a bar that does not claim a length.

Nothing here can fail a ticket. Every call to the board is caught, and one that
refuses three writes in a row switches the line off for the rest of the session.

Nor can it slow one down. The steps come from the loop that reads the session's
output, and a write to Notion can take minutes — four tries, each waiting out a
429 —, during which nothing read the pipe: it filled, and the CLI stopped on its
next write while its timeout kept running. The line is therefore written from
**a thread of its own**: feeding it only counts, and what piles up while Notion
is slow goes down in one write when it answers.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import store

logger = logging.getLogger(__name__)

# The default cadence, in seconds. Ten is short enough to feel live and long
# enough that a card is not rewritten under the reader's eyes.
CADENCE = 10.0

# How much of a tool step survives into the board's column. A command, not a file.
LINE = 200

# How much of what the agent *said* survives into a step. Generous on purpose:
# this is the part a human actually reads, in the console's live tab.
SAID = 5700

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
    "SlashCommand": ("Command", ("command",)),
}

# The plan a session keeps, and what survives of each task: a task is a sentence,
# not a paragraph, and a list that long is not a plan any more.
PLAN = "Plan"
MAX_TASKS = 40
TASK = 120

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


def plan_of(todos: Any) -> list[dict[str, str]]:
    """The tasks of a `TodoWrite` call: `content`, `active` (what is being done) and `status`.

    Also reads its own output back, which is how a `Plan` step's detail is read.
    """
    if not isinstance(todos, list):
        return []
    tasks: list[dict[str, str]] = []
    for todo in todos[:MAX_TASKS]:
        if not isinstance(todo, dict) or not str(todo.get("content") or "").strip():
            continue
        status = str(todo.get("status") or "pending")
        tasks.append(
            {
                "content": _one_line(todo["content"], TASK),
                "active": _one_line(todo.get("activeForm") or todo.get("active") or "", TASK),
                "status": status
                if status in ("pending", "in_progress", "completed")
                else "pending",
            }
        )
    return tasks


def read_plan(detail: str) -> list[dict[str, str]]:
    """The tasks a `Plan` step carries, or none when its detail is not a plan."""
    try:
        return plan_of(json.loads(detail))
    except ValueError:
        return []


def summary(tasks: list[dict[str, str]]) -> str:
    """“3/5 — writing the tests”: how far the plan is, and the task under way.

    Without the task once nothing is under way — all done, or none started.
    """
    if not tasks:
        return ""
    done = sum(1 for task in tasks if task["status"] == "completed")
    current = next((task for task in tasks if task["status"] == "in_progress"), None)
    head = f"{done}/{len(tasks)}"
    if current is None:
        return head
    return f"{head} — {_one_line(current['active'] or current['content'], LINE - len(head) - 3)}"


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
                if name == "TodoWrite":
                    # The list itself is the detail, whole: the console draws it,
                    # and `Live` reads the progress off it.
                    tasks = plan_of(payload.get("todos"))
                    if tasks:
                        steps.append(Step(PLAN, json.dumps(tasks, ensure_ascii=False)))
                    continue
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


# The titles the live report gave the toggle it used to append to a ticket's
# page: “⏳ Live”, “⏳ Live — 4 steps · 2 minutes” while it ran, “✓ 12 steps · 9
# minutes” once done, “⚠️ Trace — 3 steps · …” when the run went wrong. Bold,
# all of it.
_LIVE_TITLE = re.compile(r"⏳ .+|✓ \d+ .+|⚠️ .+ — \d+ .+", re.DOTALL)


def is_live(block: dict[str, Any]) -> bool:
    """Whether a block of a page is one of the toggles a run's live report left.

    None is written any more, but the pages written before the format in two
    parts (ticket_page.py) still hold them: a brief must not read them — old
    steps an agent can take for instructions — and putting such a page into
    its two parts takes them away. The title is the mark, bold from end to end,
    opening on the sign of a run and, once it had settled, on how many steps it
    counted. A toggle somebody wrote by hand rarely looks like that, and costs
    only itself if it does.
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


class Live:
    """A ticket's live line: buffer the steps, publish the last one on the cadence.

    Held by the job that runs the session, fed one event at a time, and closed
    when the session ends. It writes one thing, the board's `Progress` column:
    the page is the ticket's mission and what was done (ticket_page.py), and
    the steps are the run journal's.
    """

    def __init__(
        self,
        backend: store.Store,
        page_id: str,
        *,
        database: str = "",
        property_name: str = "",
        interval: float = CADENCE,
        clock: Callable[[], float] = time.monotonic,
        say: Callable[[str], None] = lambda message: None,
        background: bool = False,
    ) -> None:
        self.client = backend
        self.page_id = page_id
        self.database = database
        self.property_name = property_name
        self.interval = max(1.0, float(interval))
        self.clock = clock
        self.say = say
        self.started = clock()
        self.written = 0
        self.disabled = False
        # What waits for the next write: how many steps, and the last of them
        # — the only one the board's column shows.
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
        self._plan: list[dict[str, str]] = []
        self._failures = 0

    # -- feeding ------------------------------------------------------------

    def event(self, payload: dict[str, Any]) -> None:
        """One stream-json event. Writes only if the cadence has come round."""
        for step in describe(payload):
            self.add(step)

    def add(self, step: Step) -> None:
        if self.disabled:
            return
        # Two identical lines in a row say nothing the first one did not: the
        # same call made twice would otherwise count as two steps.
        with self._lock:
            if step.line == self._latest:
                return
            self._latest = step.line
            self._waiting += 1
            if step.label == PLAN:
                self._plan = read_plan(step.detail)
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
        """Publish what has accumulated. Returns how many steps it counted."""
        self._last_flush = self.clock()
        if self.disabled:
            return 0
        with self._lock:
            count, self._waiting = self._waiting, 0
            last = self._latest
        if not count:
            return 0
        self.written += count
        self._publish(summary(self._plan) or _one_line(last))
        return count

    def close(self) -> None:
        """Last flush, then the column stops saying what is being done.

        The ticket's own report — its part « What was done », the comment, the
        status, the pull request — is what speaks now; a column still showing
        “Edit src/x.py” would be saying something that stopped being true.

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
        if self.written:
            self._publish("")

    # -- the board ----------------------------------------------------------

    def _publish(self, line: str) -> None:
        """The current step, in the board's own column — when there is one."""
        if not (self.database and self.property_name):
            return
        try:
            self.client.update(self.database, self.page_id, {self.property_name: line})
        except store.StoreError as error:
            self._failed(error)
            return
        self._failures = 0

    def _failed(self, error: store.StoreError) -> None:
        self._failures += 1
        if self._failures < MAX_FAILURES:
            return
        self.disabled = True
        self.say(f"    ! live steps switched off for this ticket: {error}")
