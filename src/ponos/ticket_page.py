"""A ticket's page, in two parts: the mission somebody wrote, and what was done.

Every session used to append a folded block to the end of the page — the steps,
then the report — and a ticket run three times ended on three of them: nobody
could tell at a glance what stood done, and the brief read before a session
could carry the earlier ones back into its prompt. So a page now has a shape,
the same for every ticket, and it is decided here rather than in Notion's
rendering of it, so that whatever holds the ticket next keeps it as it is:

- **Mission** — written by a person, or by the agent that created the ticket.
  The runner never rewrites it, and it is the only part of the page a session
  is given, with the answers in the comments.
- **What was done** — the runner's, written at the end of every session and
  *replaced* each time, never stacked: the result in one sentence, the pull
  request, the report, what is left to check. Under it, one line per session
  — date, duration, cost, result, a link to the session in the console — read
  from the run journal of ponos.db, which is where the step-by-step detail
  stays.

The second part is found by its heading, in either language the runner speaks,
and runs to the end of the page: the runner writes it last and appends nothing
after it. A page without it is all mission — which is what a ticket written
before this format, or by hand without the template, reads as. The questions
of a blocked ticket stay in the comments: that is where they are answered.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import question as question_module
from . import voice as voice_module

# How the two parts and the history are headed, in every language the runner
# writes. Reading accepts all of them: a board keeps what was written the day
# before `runner.language` changed.
MISSION = voice_module.every("page-mission")
DONE = voice_module.every("page-done")
HISTORY = voice_module.every("page-history")

# A heading line of Markdown: one to three hashes, as `markdown.plain` writes
# Notion's three levels of heading.
_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")

# The mark of each ending a run can come to, at the head of its history line.
_MARKS = {
    "done": "✅",
    "blocked": "🙋",
    "failed": "⚠️",
    "waiting": "⏸️",
    "interrupted": "⏸️",
    "requeued": "↩️",
    "stopped": "⏹️",
}


def _folded(title: str) -> str:
    """A heading's words, as two spellings of the same heading compare.

    “### 2. Ce qui a été fait :” and “## Ce qui a été fait” are one heading:
    the level, a number in front and a colon behind are how somebody wrote it,
    not what it says.
    """
    said = re.sub(r"^\s*\d+[.)]\s*", "", title.strip().strip("*_ "))
    return " ".join(said.rstrip(" :").split()).casefold()


def is_heading(line: str, titles: Iterable[str]) -> bool:
    """Whether a line of Markdown is a heading saying one of these titles."""
    found = _HEADING.match(line.strip())
    return found is not None and _folded(found.group(2)) in {_folded(title) for title in titles}


@dataclass
class Parts:
    """A page read as its two parts. `done` is everything under its heading."""

    mission: str = ""
    done: str = ""

    @property
    def report(self) -> str:
        """The last session's report: the second part, without its history."""
        return _cut(self.done, HISTORY)[0]

    @property
    def history(self) -> list[str]:
        """The history's lines, oldest first, without their bullets."""
        lines = _cut(self.done, HISTORY)[1].splitlines()
        return [line.strip().removeprefix("- ").strip() for line in lines if line.strip()]


def _cut(text: str, titles: Sequence[str]) -> tuple[str, str]:
    """`text` before the first heading saying one of `titles`, and after it."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if is_heading(line, titles):
            return "\n".join(lines[:index]).strip(), "\n".join(lines[index + 1 :]).strip()
    return text.strip(), ""


def split(text: str) -> Parts:
    """A page's text, as its mission and what was done.

    The mission's own heading is dropped when it opens the page: it is the
    format's, not the person's. Anything else above the second part — a page
    written before the format had one — is the mission whole.
    """
    mission, done = _cut(text, DONE)
    lines = mission.splitlines()
    if lines and is_heading(lines[0], MISSION):
        mission = "\n".join(lines[1:]).strip()
    return Parts(mission, done)


def mission(text: str) -> str:
    """What a session is told of its ticket's page: the mission, and nothing else."""
    return split(text).mission


def template(words: voice_module.Voice, mission: str = "") -> str:
    """The page of a new ticket: both headings, the mission under the first.

    The second part says what will come there rather than stay empty: a
    heading with nothing under it reads as something that went missing.
    """
    return (
        f"## {words.say('page-mission')}\n\n{mission.strip()}\n\n"
        f"## {words.say('page-done')}\n\n*{words.say('page-done-empty')}*"
    ).replace("\n\n\n\n", "\n\n")


def section(words: voice_module.Voice, report: str, history: Sequence[str]) -> str:
    """The second part as the runner writes it: its heading, the report, the history."""
    lines = [f"## {words.say('page-done')}", report.strip() or f"*{words.say('page-done-empty')}*"]
    if history:
        lines.append(f"### {words.say('page-history')}")
        lines.append("\n".join(f"- {line}" for line in history))
    return "\n\n".join(lines)


def report(
    words: voice_module.Voice,
    *,
    status: str,
    summary: str = "",
    pull_request: str = "",
    answer: str = "",
    caveats: Sequence[str] = (),
) -> str:
    """What one session did, in the fixed order somebody reads it.

    The result in one sentence first, then the pull request, then the session's
    own report — what changed, what is to be decided, what was checked and what
    was not, what remains, as the prompt asks it to say them — and last the
    lines it could not check. The fields a blocked session writes for its
    question are not repeated here: the question is in the comments, where it
    is answered.
    """
    mark = _MARKS.get(status, "•")
    result = summary.strip() or words.say(
        f"page-status-{status}" if status in _MARKS else "page-status-other"
    )
    lines = [words.say("page-result", text=f"{mark} {words.brief(result, 300)}")]
    if pull_request:
        lines.append(words.say("page-pull-request", url=pull_request))
    told = question_module.prose(answer)
    if told:
        lines.append(told)
    if status == "blocked":
        lines.append(f"*{words.say('page-question-in-comments')}*")
    if caveats:
        lines.append(
            f"**{words.say('page-to-check')}**\n\n" + "\n".join(f"- {line}" for line in caveats)
        )
    return "\n\n".join(lines)


def history_line(words: voice_module.Voice, run: dict[str, Any], console: str = "") -> str:
    """One session of the run journal, as a line of the history.

    Date, duration, cost, result, and the way to its steps: the console's live
    tab of the ticket when the console has an address, nothing otherwise.
    """
    started = _moment(run.get("started_at"))
    ended = _moment(run.get("ended_at"))
    status = str(run.get("status") or "")
    parts: list[str] = []
    if started:
        parts.append(started.astimezone().strftime("%Y-%m-%d %H:%M"))
    if started and ended:
        parts.append(words.minutes((ended - started).total_seconds()))
    cost = run.get("cost_usd")
    if isinstance(cost, (int, float)) and cost > 0:
        parts.append(words.money(float(cost)))
    said = words.brief(run.get("reason") or "", 120)
    parts.append(f"{_MARKS.get(status, '•')} {said}".strip() if said else _MARKS.get(status, "•"))
    if console and run.get("ticket"):
        address = f"{console.rstrip('/')}/?view=console/tickets/read/{run['ticket']}&tab=live"
        parts.append(f"[{words.say('page-session')}]({address})")
    return " · ".join(parts)


def _moment(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
