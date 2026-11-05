"""« Plan d'abord » : a ticket that proposes how it will be done before doing it.

A big ticket misread is found out late and paid for in full: sessions of half
an hour and more, some of them ending blocked or done again. The only answer
the board had was all or nothing — run it, or cut it up by hand. So a ticket
may ask to be **planned first**, by a box ticked on it: an attribute, not a
column of the board, because nothing happens to the ticket that a status would
say — it is ready, it runs, it asks.

Ticked, its first session runs in Claude Code's plan mode — it reads, it
cannot write — and ends on its plan. The runner turns that into a yes-no
question, `session.question` like any other, so it is answered wherever a
question is: the console, Telegram, Slack, a comment. A yes runs the ticket
again the ordinary way, with the plan in its prompt and the box unticked; any
other answer is an amendment, and the next session plans again with it.

**The plan is kept in the report, and nowhere else.** The question it ends on
is read back from its comment (see question.py), and the plan with it: under a
heading of its own, last in the comment, where `question.found` never looks. A
report the runner can read back still means something after a restart, on
another machine, or on a board mirrored to Markdown files.

**A project may tick the box for its tickets** — those at or above a priority,
or of some sub-types (a Refactor, say): see `Rule`. Only on a ticket's first
run, so that the box a yes unticked is not ticked again by the next claim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from . import conversation, priority, store, subtypes, voice
from . import question as question_module

# The permission mode a planning session runs under: Claude Code's own, in
# which a session reads and proposes, and every edit is refused.
PERMISSION_MODE = "plan"

# Where a planning session writes its plan in its last message: between these
# two tags, so that the plan is not confused with the fields of a question.
_PLAN = re.compile(r"<plan>\s*(.*?)\s*</plan>", re.IGNORECASE | re.DOTALL)

# How much of a plan a comment carries. Notion takes a hundred pieces of rich
# text of two thousand characters each: a plan past this is a plan of a ticket
# to split, and the rest is in the session.
LONGEST = 12000


@dataclass
class Rule:
    """When a project ticks « Plan d'abord » on its tickets by itself.

    `priority` is the lowest score that is planned first — None for no
    threshold — and `subtypes` the sub-types that always are. Either one is
    enough; neither, and the project ticks nothing.
    """

    priority: int | None = None
    subtypes: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.priority is not None or bool(self.subtypes)

    def applies(self, score: int, subtype: str) -> bool:
        """Does a ticket of that score and that sub-type start with a plan?"""
        if self.priority is not None and score >= self.priority:
            return True
        return bool(subtype) and subtype in self.subtypes

    def as_dict(self) -> dict[str, Any]:
        held: dict[str, Any] = {}
        if self.priority is not None:
            held["priority"] = self.priority
        if self.subtypes:
            held["subtypes"] = list(self.subtypes)
        return held


def rule(value: object) -> Rule:
    """A project's rule, as kept in `ponos.db` — an empty one for anything else.

    A priority outside 0–100 and a sub-type nobody knows are dropped, not
    refused: what was kept by an older version must still read.
    """
    if not isinstance(value, dict):
        return Rule()
    threshold = value.get("priority")
    score: int | None = None
    if isinstance(threshold, int | float) and not isinstance(threshold, bool):
        score = int(threshold) if priority.LOWEST <= threshold <= priority.HIGHEST else None
    kept = value.get("subtypes")
    keys = [key for key in kept if key in subtypes.KEYS] if isinstance(kept, list) else []
    return Rule(score, list(dict.fromkeys(keys)))


def ticked(page: store.Page, column: str) -> bool:
    """Is the box ticked on this ticket? Never on a board without the column."""
    return bool(column) and store.read(page, column) is True


def written(answer: str) -> str:
    """The plan a planning session wrote in its last message, or "" without one."""
    found = _PLAN.findall(str(answer or ""))
    return found[-1].strip() if found else ""


def heading_lines() -> tuple[str, ...]:
    """The line a plan opens on in a report, in every language it was written in."""
    return voice.every("plan-heading")


def proposed(report: str) -> str:
    """The plan a report proposes, read back from under its heading — or "".

    Everything after the heading: the plan is the last thing a report says, so
    that the blank lines inside it cannot be taken for the end of it.
    """
    lines = str(report or "").splitlines()
    headings = heading_lines()
    for index, line in enumerate(lines):
        if line.strip() in headings:
            return "\n".join(lines[index + 1 :]).strip()
    return ""


@dataclass
class Pending:
    """A plan proposed on a ticket, and what was answered to it since."""

    plan: str
    answer: str = ""

    @property
    def approved(self) -> bool:
        """Did the answer say yes — “oui”, “ok”, the console's Yes button?

        A yes with more after it (« oui, mais sans la migration ») is a yes:
        what follows travels with the plan, as the answer that approved it.
        """
        lines = [line.strip() for line in self.answer.splitlines() if line.strip()]
        if not lines:
            return False
        # Typed, or relayed from a phone: the answer opens on its yes. Clicked
        # in the console, it opens on the decision, and says its yes under it.
        if question_module.decide(lines[0]) == "yes":
            return True
        return any(line in voice.every("relayed-yes") for line in lines[1:])


def pending(comments: Iterable[store.Comment], me: str = "") -> Pending | None:
    """The plan a ticket is waiting on, if its last report proposed one.

    Only the last report: a plan proposed, answered and followed by another
    report — the plan carried out, or a question of another kind — is waiting
    on nothing. The answer is the last thing a person said under it, the
    runner's own words left out.
    """
    listed = list(comments)
    reports = [index for index, comment in enumerate(listed) if voice.is_report(comment.text)]
    if not reports:
        return None
    plan = proposed(listed[reports[-1]].text)
    if not plan:
        return None
    answers = [
        conversation.said(comment.text)
        for comment in listed[reports[-1] + 1 :]
        if not conversation.ours(comment, me) and not voice.is_report(comment.text)
    ]
    return Pending(plan, answers[-1] if answers else "")


def reported(comments: Iterable[store.Comment]) -> bool:
    """Has a run already reported on this ticket — is this not its first?"""
    return any(voice.is_report(comment.text) for comment in comments)


def clipped(plan: str) -> str:
    """A plan short enough for a comment, cut at a line."""
    plan = plan.strip()
    if len(plan) <= LONGEST:
        return plan
    return plan[:LONGEST].rsplit("\n", 1)[0].rstrip() + "\n…"


# What a planning session is told, whatever the template: last in its prompt,
# where it overrides what the template expects of an ordinary session.
PROPOSE = """\
# Plan first — this session plans, it does not write

The ticket is ticked « Plan d'abord »: before any code is written, its author \
wants to read and approve how it will be done. You run in plan mode — you can \
read the repository, search it and run commands that change nothing; every \
edit is refused. Do not try to write, commit, or leave plan mode (no \
ExitPlanMode): the answer comes later, from a person, after this session.

Read what you need, then write your plan in your last message, between \
`<plan>` and `</plan>`, in Markdown, short enough to read on a phone:

- **Steps** — what you will do, in order;
- **Files** — the files you will create or change;
- **Risks** — what may break, and what you are unsure of;
- **Cost** — your estimate of the session that carries it out: its size \
(S, M, L), and whether it should rather be split.

{amend}After the plan, end with `RESULT: blocked — <the plan, in one sentence>`. \
Do not write the question fields yourself: the runner asks whether to go ahead. \
Only if the ticket is too unclear to plan at all, write no plan and ask your \
question instead, with the fields below.
"""

AMEND = """\
A plan was proposed already, and its author answered it — their answer is in \
the discussion above. Propose the plan again, amended as they asked. The plan \
they answered:

{plan}

"""

APPROVED = """\
# The plan you carry out

This ticket was planned first, and its author approved the plan below \
(“{answer}”). Carry it out: it is what was agreed, so follow it, and say in \
your report where you had to leave it and why.

{plan}
"""


def propose_prompt(amending: str = "") -> str:
    """What a planning session is told: the first plan, or `amending` the one answered."""
    return PROPOSE.format(amend=AMEND.format(plan=amending.strip()) if amending.strip() else "")


def approved_prompt(plan: str, answer: str) -> str:
    """What the session that carries out an approved plan is told."""
    return APPROVED.format(plan=plan.strip(), answer=" ".join(answer.split())[:200])
