"""Ideas Ponos proposes, and what was decided about each of them.

A board only ever holds what somebody already thought of. Ideas are the other
direction: Ponos reads what a project is and what has been done in it, and
proposes what could come next — for one project, from its page, or for the
whole workspace, from the dashboard, where an idea may also be a project of its
own. Somebody keeps it or throws it away, one at a time; a kept idea becomes a
draft on the board, and the board is where it is worked on from then on.

**Ten at once, in one call, on a light model.** Ideas are cheap to propose and
dear to read: one session writing ten costs barely more than one writing a
single idea, and the choice is the person's, not the model's — so the lightest
model there is (`runner.ideas_model`) is enough. What a batch cost is written
down with it, failed ones included, since a session that answered nothing usable
was still paid for.

**Never twice.** Everything already proposed for the same scope — kept, thrown
away or still waiting — goes into the prompt, so the model knows what not to
say again, and whatever it says anyway is filtered here: a title too close to
one already known, or to a ticket of the board, is dropped before it is stored.
A model told not to repeat itself still does; a comparison of two strings does
not forget.

**An idea is ours, a ticket is the board's.** Ideas live in the local database
rather than as Notion pages, because nine out of ten are thrown away and a board
is not where a discarded thought belongs. Keeping one is the moment it crosses
over — and the ticket it became is remembered on it, so that taking the decision
back and keeping it again finds that ticket rather than writing a second one.

**Kept is not yet a ticket.** An idea is new, kept, thrown away, or turned
into a ticket: keeping one says it is worth doing, turning it into a ticket
puts it on the board — the deck's swipe to the right does both at once, the
list on a project's page one at a time. None of them deletes anything: an idea
thrown away is still there, to be taken back, and to keep the next batch from
proposing it again.

**Ponos's or ours.** Ideas are also written by hand, and reworded: each one
says who wrote it — Ponos, or the person, by the name and the picture they
had then — and who last changed it, and when.

**One category, never a tag.** Each idea is also UX/UI, feature, security or
technical — one of the four, never several: the point is to sort them, treat
them apart and put the security ones first, and an idea that is two things at
once is an idea that was not decided. Technical takes refactoring, performance
and debt, so that "feature" stays what brings something new to whoever uses
the project, rather than whatever is not something else. The model is asked to
choose; an answer that does not is left unsorted rather than guessed, and
somebody sorts it by hand.

**A score, out of a hundred, by a grid that is written down.** Ten ideas are
read one at a time; a number on each says which to read first. The model gives
it with the idea, by the grid of `RUBRIC` — impact, fit with the brief, effort
against gain, and whether it is new — and one line that says why, so the number
can be argued with. It is bounded here, and anything that is not a number is
"not scored" rather than a zero: a zero is a judgement, a missing score is the
absence of one. An idea written by hand has nobody to score it as it is written:
the light model does, with the same grid, once it is saved — and until then it
says so. Green from `GREEN`, orange from `ORANGE`, red under it: the console
reads the same two numbers from `idea-search.ts`, and a test holds them equal.

Nothing here touches the network: building the prompt, reading the answer and
remembering the decisions are testable alone. Running the session and writing
the board is `web/ideas.py`'s.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import db, goals

SCOPES = ("global", "project")
KINDS = ("ticket", "project")
STATUSES = ("proposed", "kept", "discarded", "ticket")
ORIGINS = ("ponos", "manual")
# "" is an idea nobody sorted yet: one from before categories, or one the
# model left out.
CATEGORIES = ("ux", "feature", "security", "technical")

# Where a score turns green, and orange; under ORANGE it is red. The same two
# numbers as `frontend/src/lib/idea-search.ts`.
GREEN = 70
ORANGE = 40
TONES = ("green", "orange", "red")

# Scoring ideas already there: this many to a call, on the light model, and no
# call allowed to cost more than this — what the console says before it starts
# is the number of calls times this. A call costs 0.12 to 0.14 dollars even on a
# prompt of a few thousand tokens (the CLI's own preamble weighs most of it), so
# 0.10 stopped every one of them on `error_max_budget_usd`, for nothing.
SCORE_BATCH = 20
SCORE_CEILING_USD = 0.50
# What a call is estimated to cost before it starts: the CLI's own preamble,
# plus the prompt at a price per token well above the light model's. A call
# whose estimate is over the ceiling is not started — it would be stopped by it
# after having been paid for.
SCORE_OVERHEAD_USD = 0.20
SCORE_USD_PER_TOKEN = 0.00001
# The prompt of a score carries what lets it compare, not all of it.
SCORE_BRIEF_LIMIT = 1500
SCORE_CONTEXT_LIMIT = 800
SCORE_OBJECTIVES_LIMIT = 800
SCORE_TICKETS_SHOWN = 25
SCORE_KNOWN_SHOWN = 60
SCORE_TIMEOUT_MINUTES = 3
# How long an idea waiting for its score says so: past this, the session that
# was scoring it is gone, and it is not scored.
SCORING_FOR_MINUTES = 10

# One batch. Enough to swipe through in a minute, few enough that the model
# still has something to say by the tenth.
BATCH = 10

# Ten short objects. A session still writing after three minutes is a session
# that started doing the work instead of proposing it.
TIMEOUT_MINUTES = 3

# What a card has room for: the title says it, the description says why.
TITLE_LIMIT = 90
DESCRIPTION_LINES = 3
DESCRIPTION_LIMIT = 320
# One written by hand is not a card the model filled: room for a paragraph.
WRITTEN_LIMIT = 4000

# How alike two titles may be before the second is the first said again —
# measured twice, accents and case aside. Character by character, high, since
# ideas share their openings: "Add a dark mode" and "Add dark mode" are one idea,
# "Export to CSV" and "Export to PDF" are two. And word by word, for the same
# words said in another order.
SIMILAR = 0.9
SAME_WORDS = 0.8

# What the prompt carries at most of each source — a README is read for what
# the project is, not for its installation steps.
README_LIMIT = 4000
BRIEF_LIMIT = 4000
CONTEXT_LIMIT = 2000
OBJECTIVES_LIMIT = 2000
TICKETS_SHOWN = 40
KNOWN_SHOWN = 200

# The grid a score is given by, out of 100 — for an idea proposed and for one
# written by hand alike.
RUBRIC = """\
Score each idea from 0 to 100 by this grid, and add up the four:
- impact for whoever uses the project, or for the business it serves: up to 40;
- fit with the brief and the context of the project: up to 25;
- gain against the effort it takes: up to 20;
- originality — no repeat of a ticket or an idea listed below: up to 15."""

PROMPT = """\
You are proposing ideas to somebody who will read them one at a time and keep \
or throw away each one. Do not carry any of them out, do not open anything: \
read what is below and propose.

{scope}

Propose exactly {count} ideas, each of them new: none of them may repeat, \
reword or narrow an idea listed under "Already proposed", nor a ticket listed \
under "Tickets". Prefer ideas that are concrete, useful and small enough to be \
one piece of work.

Answer with a JSON array and nothing else — no preamble, no fence. One object \
per idea:

- "title": what to do, in one line of {title_limit} characters at most;
- "description": why it is worth doing, in {lines} short lines at most;
- "kind": {kinds};
- "category": one of "ux" (the interface and how it feels to use), "feature" \
(something new that is worth something to whoever uses it), "security" (a flaw \
or a risk), "technical" (refactoring, performance, technical debt) — exactly \
one of them;
- "where": where the work happens — the part of the project, the files, the \
service — in one sentence;
- "done": a list of two to four checks that say the work is finished;
- "out": a list of one to three things this idea does not include;
- "score": a whole number from 0 to 100, by the grid below;
- "score_reason": one line that says why it has that score.

{rubric}

{language}
{sections}"""

_GLOBAL = """\
The scope is the whole workspace: ideas of new projects worth starting, or of \
improvements that cut across the existing projects."""

_PROJECT = """\
The scope is one project, {name}: ideas for this project only."""

_KINDS_GLOBAL = (
    '"project" for a new project worth starting, "ticket" for an improvement to the existing work'
)
_KINDS_PROJECT = '"ticket", always'


@dataclass
class Idea:
    """One idea, as the local database keeps it.

    `project` is the page of the project it was proposed for — "" for the
    workspace. `ticket` is the draft it became, and `created` the project it
    created when it was the idea of one: both stay after the decision is taken
    back, so that turning it into a ticket again does not write them twice.
    `author` is the name of who wrote it by hand, "" for Ponos; `edited_by`
    the last person who changed it. `category` is one of CATEGORIES, or ""
    for an idea nobody sorted. `score` is out of 100, None for one not scored;
    its reason is `detail["score_reason"]`, and `detail["scoring"]` the moment
    a session started scoring it, while one is.
    """

    id: int
    batch: int | None
    scope: str
    project: str
    kind: str
    title: str
    description: str
    detail: dict[str, Any] = field(default_factory=dict)
    category: str = ""
    status: str = "proposed"
    ticket: str = ""
    created: str = ""
    cost_usd: float | None = None
    created_at: str = ""
    decided_at: str | None = None
    origin: str = "ponos"
    author: str = ""
    author_avatar: str = ""
    edited_by: str = ""
    edited_by_avatar: str = ""
    edited_at: str | None = None
    changed_at: str | None = None
    score: int | None = None

    def scoring(self) -> bool:
        """Whether a session is scoring it now — one that started recently enough to still be."""
        started = str(self.detail.get("scoring") or "")
        if not started or self.score is not None:
            return False
        try:
            since = datetime.now(UTC) - datetime.fromisoformat(started)
        except ValueError:
            return False
        return since.total_seconds() < SCORING_FOR_MINUTES * 60

    def shown(self) -> dict[str, Any]:
        """The idea as the console reads it."""
        return {
            "id": self.id,
            "batch": self.batch,
            "scope": self.scope,
            "project": self.project,
            "kind": self.kind,
            "category": self.category,
            "score": self.score,
            "score_reason": str(self.detail.get("score_reason") or ""),
            "score_error": ""
            if self.score is not None
            else str(self.detail.get("score_error") or ""),
            "tone": tone(self.score),
            "scoring": self.scoring(),
            "title": self.title,
            "description": self.description,
            "where": str(self.detail.get("where") or ""),
            "done": list(self.detail.get("done") or []),
            "out": list(self.detail.get("out") or []),
            "status": self.status,
            "ticket": self.ticket,
            "created": self.created,
            "cost_usd": self.cost_usd,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "changed_at": self.changed_at or self.created_at,
            "origin": self.origin,
            "author": (
                {"kind": "ponos", "name": "Ponos", "avatar": ""}
                if self.origin == "ponos"
                else {"kind": "human", "name": self.author, "avatar": self.author_avatar}
            ),
            "edited": (
                {"name": self.edited_by, "avatar": self.edited_by_avatar, "at": self.edited_at}
                if self.edited_at
                else None
            ),
        }


def scope_of(project: str) -> str:
    return "project" if project else "global"


def bare(page_id: str) -> str:
    """A page id the way ideas are filed under it: no dashes."""
    return page_id.replace("-", "").strip()


# -- the prompt ----------------------------------------------------------------


def _objectives(objectives: list[goals.Goal] | None, limit: int) -> str:
    """The active goals, one line each: name, criterion, due date.

    Material to read, not a criterion: the grid is the same with or without
    them, so scores already given stay comparable with the new ones.
    """
    lines = []
    for goal in objectives or []:
        details = [f"criterion: {goal.criterion}"] if goal.criterion else []
        details += [f"due: {goal.due}"] if goal.due else []
        lines.append(f"- {goal.name}" + (f" ({'; '.join(details)})" if details else ""))
    return "\n".join(lines)[:limit]


def prompt(
    *,
    project: str = "",
    brief: str = "",
    readme: str = "",
    tickets: list[tuple[str, str]] | None = None,
    projects: list[str] | None = None,
    context: str = "",
    objectives: list[goals.Goal] | None = None,
    known: list[str] | None = None,
    language: str = "English",
    count: int = BATCH,
) -> str:
    """What the session is asked, with everything it is given to read.

    `project` is the project's name, "" for the whole workspace. `tickets` are
    (title, column) pairs, latest first; `projects` the names of every project,
    for the workspace; `known` every title already proposed for this scope.
    A section with nothing in it is left out rather than shown empty: an empty
    heading reads as a claim that there is nothing there.
    """
    sections: list[str] = []
    if context.strip():
        sections.append(_section("Who the ideas are for", context.strip()[:CONTEXT_LIMIT]))
    if text := _objectives(objectives, OBJECTIVES_LIMIT):
        sections.append(_section("Les caps du moment", text))
    if projects:
        sections.append(_section("Projects", "\n".join(f"- {name}" for name in projects)))
    if brief.strip():
        sections.append(_section("The project's brief", brief.strip()[:BRIEF_LIMIT]))
    if readme.strip():
        sections.append(_section("The project's README", readme.strip()[:README_LIMIT]))
    if tickets:
        lines = [f"- {title} ({column})" if column else f"- {title}" for title, column in tickets]
        sections.append(_section("Tickets", "\n".join(lines[:TICKETS_SHOWN])))
    if known:
        sections.append(
            _section("Already proposed", "\n".join(f"- {title}" for title in known[:KNOWN_SHOWN]))
        )
    return PROMPT.format(
        scope=_PROJECT.format(name=project) if project else _GLOBAL,
        count=count,
        title_limit=TITLE_LIMIT,
        lines=DESCRIPTION_LINES,
        kinds=_KINDS_PROJECT if project else _KINDS_GLOBAL,
        rubric=RUBRIC,
        language=f"Write every title and description in {language}.",
        sections="".join(f"\n{section}" for section in sections),
    )


SCORE_PROMPT = """\
You are scoring ideas somebody will read one at a time, to decide which are \
worth turning into a piece of work. Do not carry any of them out, do not open \
anything: read what is below and score.

{scope}

{rubric}

Answer with a JSON array and nothing else — no preamble, no fence. One object \
per idea, in any order:

- "id": the idea's number, as written under "Ideas to score";
- "score": a whole number from 0 to 100;
- "score_reason": one line that says why it has that score.

Write every reason in {language}.

# Ideas to score

{ideas}
{sections}"""


def score_prompt(
    candidates: list[Idea],
    *,
    project: str = "",
    brief: str = "",
    tickets: list[tuple[str, str]] | None = None,
    context: str = "",
    objectives: list[goals.Goal] | None = None,
    known: list[str] | None = None,
    language: str = "English",
) -> str:
    """What the light model is asked to score ideas already stored.

    The same grid as a batch is scored by, given the same things to compare
    with: the brief, the tickets and every other idea of the scope — an idea
    is not scored as original against itself, so it is left out of them.
    """
    listed = "\n\n".join(
        f"{idea.id}. {idea.title}"
        + (f"\n{idea.description.strip()}" if idea.description.strip() else "")
        for idea in candidates
    )
    own = {idea.title for idea in candidates}
    sections: list[str] = []
    if context.strip():
        sections.append(_section("Who the ideas are for", context.strip()[:SCORE_CONTEXT_LIMIT]))
    if text := _objectives(objectives, SCORE_OBJECTIVES_LIMIT):
        sections.append(_section("Les caps du moment", text))
    if brief.strip():
        sections.append(_section("The project's brief", brief.strip()[:SCORE_BRIEF_LIMIT]))
    if tickets:
        lines = [f"- {title} ({column})" if column else f"- {title}" for title, column in tickets]
        sections.append(_section("Tickets", "\n".join(lines[:SCORE_TICKETS_SHOWN])))
    others = [title for title in known or [] if title not in own]
    if others:
        sections.append(
            _section("Other ideas", "\n".join(f"- {title}" for title in others[:SCORE_KNOWN_SHOWN]))
        )
    return SCORE_PROMPT.format(
        scope=_PROJECT.format(name=project) if project else _GLOBAL,
        rubric=RUBRIC,
        language=language,
        ideas=listed,
        sections="".join(f"\n{section}" for section in sections),
    )


def score_estimate(prompt: str) -> float:
    """What scoring with this prompt may cost, in dollars: four characters to a token, rounded up."""
    return SCORE_OVERHEAD_USD + (len(prompt) / 4) * SCORE_USD_PER_TOKEN


def _section(heading: str, body: str) -> str:
    return f"# {heading}\n\n{body}\n"


# -- the answer ----------------------------------------------------------------


def parse(answer: str, scope: str) -> list[dict[str, Any]]:
    """The ideas, out of whatever the session actually said.

    The widest array that reads as one, so that a fence or a sentence around it
    costs nothing. An entry with no title is dropped; a kind that is not one of
    the two is a ticket, and in a project's scope everything is — a project
    cannot propose a new project inside itself.
    """
    raw = _array(answer or "")
    found: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = _line(entry.get("title"))[:TITLE_LIMIT].strip()
        if not title:
            continue
        kind = _line(entry.get("kind")).lower()
        if scope != "global" or kind not in KINDS:
            kind = "ticket"
        found.append(
            {
                "title": title,
                "description": _description(entry.get("description")),
                "kind": kind,
                "category": _category(entry.get("category")),
                "score": score_of(entry.get("score")),
                "detail": {
                    "where": _line(entry.get("where")),
                    "done": _list(entry.get("done")),
                    "out": _list(entry.get("out")),
                    "score_reason": _line(entry.get("score_reason"))[:DESCRIPTION_LIMIT],
                },
            }
        )
    return found


def parse_scores(answer: str, identifiers: list[int]) -> dict[int, tuple[int, str]]:
    """The scores the light model gave, by idea — those it was asked for, and valid, only."""
    asked = set(identifiers)
    scores: dict[int, tuple[int, str]] = {}
    for entry in _array(answer or ""):
        if not isinstance(entry, dict):
            continue
        try:
            identifier = int(str(entry.get("id")).strip().rstrip("."))
        except ValueError:
            continue
        score = score_of(entry.get("score"))
        if identifier in asked and score is not None:
            scores[identifier] = (score, _line(entry.get("score_reason"))[:DESCRIPTION_LIMIT])
    return scores


def score_of(value: object) -> int | None:
    """A score from 0 to 100, bounded — or None for whatever is not a number.

    `True` is not 1, and "high" is not a score: either is "not scored".
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip().removesuffix("/100").strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or value != value:
        return None
    if value in (float("inf"), float("-inf")):
        value = 100 if value > 0 else 0
    return max(0, min(100, round(value)))


def tone(score: int | None) -> str:
    """Green, orange or red by the two thresholds — "" for an idea not scored."""
    if score is None:
        return ""
    if score >= GREEN:
        return "green"
    if score >= ORANGE:
        return "orange"
    return "red"


def _category(value: object) -> str:
    """One of the four categories, or "" — never a guess at what was meant."""
    said = _line(value).lower()
    return said if said in CATEGORIES else ""


def _array(answer: str) -> list[Any]:
    start = answer.find("[")
    while start != -1:
        end = answer.rfind("]")
        while end > start:
            try:
                value = json.loads(answer[start : end + 1])
            except ValueError:
                end = answer.rfind("]", start, end)
                continue
            if isinstance(value, list):
                return value
            break
        start = answer.find("[", start + 1)
    return []


def _line(value: object) -> str:
    return " ".join(str(value or "").split()) if isinstance(value, (str, int, float)) else ""


def _list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [line for line in (_line(item) for item in value) if line][:6]


def _description(value: object) -> str:
    """At most three lines, each of them one line: a card, not a page."""
    text = str(value or "") if isinstance(value, str) else ""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    kept = "\n".join([line for line in lines if line][:DESCRIPTION_LINES])
    return kept[:DESCRIPTION_LIMIT].strip()


# -- never twice ---------------------------------------------------------------


def _words(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return " ".join(re.findall(r"\w+", plain))


def similar(first: str, second: str) -> bool:
    """Whether two titles are one idea said twice."""
    a, b = _words(first), _words(second)
    if not a or not b:
        return False
    if a == b or difflib.SequenceMatcher(None, a, b).ratio() >= SIMILAR:
        return True
    # Words of three letters or more: "a", "de", "un" say nothing of the idea.
    left = {word for word in a.split() if len(word) > 2}
    right = {word for word in b.split() if len(word) > 2}
    return bool(left and right) and len(left & right) / len(left | right) >= SAME_WORDS


def fresh(
    candidates: list[dict[str, Any]], known: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The candidates worth keeping, and those that were already said.

    Compared with what is known and with each other: a batch that proposes the
    same idea twice proposes it once.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen = [title for title in known if title.strip()]
    for candidate in candidates:
        if any(similar(candidate["title"], title) for title in seen):
            dropped.append(candidate)
            continue
        kept.append(candidate)
        seen.append(candidate["title"])
    return kept, dropped


# -- the draft a kept idea becomes ---------------------------------------------


def body(idea: Idea, say: Callable[..., str]) -> str:
    """The ticket a kept idea is written as: What / Where / Done when / Out of scope.

    `say` is the runner's voice, so the headings are in the board's language.
    The description opens the page, since it is the reason the idea was kept.
    """
    what = idea.description.strip() or idea.title
    return draft(
        say,
        what=what,
        where=str(idea.detail.get("where") or ""),
        done=list(idea.detail.get("done") or []),
        out=list(idea.detail.get("out") or []),
    )


def framing(idea: Idea, say: Callable[..., str]) -> str:
    """The first ticket of a project an idea created: frame it."""
    what = say("idea-frame-what")
    if idea.description.strip():
        what = f"{idea.description.strip()}\n\n{what}"
    return draft(
        say,
        what=what,
        where=say("idea-frame-where"),
        done=[say("idea-frame-done")],
        out=[say("idea-frame-out")],
    )


def draft(
    say: Callable[..., str], *, what: str, where: str, done: list[str], out: list[str]
) -> str:
    parts = [f"## {say('idea-what')}\n\n{what.strip()}"]
    if where.strip():
        parts.append(f"## {say('idea-where')}\n\n{where.strip()}")
    if done:
        parts.append(f"## {say('idea-done')}\n\n" + "\n".join(f"- [ ] {line}" for line in done))
    if out:
        parts.append(f"## {say('idea-out')}\n\n" + "\n".join(f"- {line}" for line in out))
    return "\n\n".join(parts) + "\n"


# -- the local database --------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_COLUMNS = (
    "id, batch, scope, project, kind, title, description, detail, status, ticket, created,"
    " cost_usd, created_at, decided_at, origin, author, author_avatar, edited_by,"
    " edited_by_avatar, edited_at, changed_at, category, score"
)


def _idea(row: tuple[Any, ...]) -> Idea:
    try:
        detail = json.loads(row[7] or "{}")
    except ValueError:
        detail = {}
    return Idea(
        id=row[0],
        batch=row[1],
        scope=row[2],
        project=row[3],
        kind=row[4],
        title=row[5],
        description=row[6],
        detail=detail if isinstance(detail, dict) else {},
        status=row[8],
        ticket=row[9],
        created=row[10],
        cost_usd=row[11],
        created_at=row[12],
        decided_at=row[13],
        origin=row[14],
        author=row[15],
        author_avatar=row[16],
        edited_by=row[17],
        edited_by_avatar=row[18],
        edited_at=row[19],
        changed_at=row[20],
        category=row[21],
        score=row[22],
    )


def record(
    project: str,
    model: str,
    cost_usd: float | None,
    ideas: list[dict[str, Any]],
    error: str = "",
) -> tuple[int, list[Idea]]:
    """Write one batch and its ideas, and give them back as stored.

    Each idea carries its share of what the batch cost; the batch carries the
    whole of it — and is written even with no idea in it, since it was paid.
    """
    project = bare(project)
    scope = scope_of(project)
    now = _now()
    share = cost_usd / len(ideas) if cost_usd is not None and ideas else None
    with db.transaction() as connection:
        batch = connection.execute(
            "INSERT INTO idea_batches (scope, project, model, created_at, count, cost_usd, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scope, project, model, now, len(ideas), cost_usd, error),
        ).lastrowid
        for idea in ideas:
            connection.execute(
                "INSERT INTO ideas (batch, scope, project, kind, category, score, title,"
                " description, detail, cost_usd, created_at, changed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch,
                    scope,
                    project,
                    idea["kind"],
                    _category(idea.get("category")),
                    score_of(idea.get("score")),
                    idea["title"],
                    idea.get("description", ""),
                    json.dumps(idea.get("detail") or {}, ensure_ascii=False),
                    share,
                    now,
                    now,
                ),
            )
        rows = connection.execute(
            f"SELECT {_COLUMNS} FROM ideas WHERE batch = ? ORDER BY id", (batch,)
        ).fetchall()
    return int(batch or 0), [_idea(row) for row in rows]


def written(
    project: str,
    title: str,
    description: str = "",
    *,
    kind: str = "ticket",
    category: str = "",
    author: str = "",
    avatar: str = "",
) -> Idea:
    """Store an idea somebody wrote by hand — no batch, nothing paid for it.

    A project's ideas are tickets, as Ponos's are; the workspace may also hold
    the idea of a project.
    """
    project = bare(project)
    scope = scope_of(project)
    title = _line(title)[:TITLE_LIMIT].strip()
    if not title:
        raise ValueError("an idea needs a title")
    if scope != "global" or kind not in KINDS:
        kind = "ticket"
    now = _now()
    with db.transaction() as connection:
        identifier = connection.execute(
            "INSERT INTO ideas (scope, project, kind, category, title, description, origin,"
            " author, author_avatar, created_at, changed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'manual', ?, ?, ?, ?)",
            (
                scope,
                project,
                kind,
                _category(category),
                title,
                _written(description),
                author,
                avatar,
                now,
                now,
            ),
        ).lastrowid
    return get(int(identifier or 0))


def edit(
    identifier: int,
    title: str,
    description: str,
    *,
    category: str | None = None,
    editor: str = "",
    avatar: str = "",
) -> Idea:
    """Reword an idea, and say who did and when. Its author stays its author.

    `category` None leaves it as it was; "" says it is not sorted after all.
    """
    title = _line(title)[:TITLE_LIMIT].strip()
    if not title:
        raise ValueError("an idea needs a title")
    before = get(identifier)
    sorted_as = before.category if category is None else _category(category)
    with db.transaction() as connection:
        connection.execute(
            "UPDATE ideas SET title = ?, description = ?, category = ?, edited_by = ?,"
            " edited_by_avatar = ?, edited_at = ? WHERE id = ?",
            (title, _written(description), sorted_as, editor, avatar, _now(), identifier),
        )
    return get(identifier)


def _written(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").strip().splitlines()]
    return "\n".join(lines)[:WRITTEN_LIMIT].strip()


def scoring(identifier: int) -> None:
    """Say an idea is being scored: the console shows "…" rather than "not scored"."""
    _detail(identifier, scoring=_now())


def scored(identifier: int, score: int | None, reason: str = "", error: str = "") -> Idea:
    """Write an idea's score and why — or, with None, that the session gave none and why not."""
    if score is None:
        _detail(identifier, scoring=None, score_error=_line(error)[:DESCRIPTION_LIMIT] or None)
        return get(identifier)
    _detail(
        identifier, scoring=None, score_error=None, score_reason=_line(reason)[:DESCRIPTION_LIMIT]
    )
    with db.transaction() as connection:
        connection.execute("UPDATE ideas SET score = ? WHERE id = ?", (score_of(score), identifier))
    return get(identifier)


def _detail(identifier: int, **changes: object) -> None:
    """Change a few keys of an idea's detail, and drop those set to None."""
    with db.transaction() as connection:
        row = connection.execute("SELECT detail FROM ideas WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            raise LookupError(f"no idea {identifier}")
        try:
            detail = json.loads(row[0] or "{}")
        except ValueError:
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        for key, value in changes.items():
            if value is None:
                detail.pop(key, None)
            else:
                detail[key] = value
        connection.execute(
            "UPDATE ideas SET detail = ? WHERE id = ?",
            (json.dumps(detail, ensure_ascii=False), identifier),
        )


# What is worth scoring: a decision on an idea thrown away or turned into a
# ticket is already taken, and a score would only be paid for.
UNSCORED_STATUSES = ("proposed", "kept")


def unscored(project: str | None = None) -> list[Idea]:
    """The ideas still waiting or kept that have no score — of one scope, or of every one."""
    marks = ", ".join("?" for _ in UNSCORED_STATUSES)
    query = f"SELECT {_COLUMNS} FROM ideas WHERE score IS NULL AND status IN ({marks})"
    values: tuple[Any, ...] = UNSCORED_STATUSES
    if project is not None:
        query += " AND project = ?"
        values = (*values, bare(project))
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(query + " ORDER BY id", values).fetchall()
    return [_idea(row) for row in rows]


def listed(project: str, statuses: tuple[str, ...] = ("proposed",)) -> list[Idea]:
    """The ideas of one scope in these statuses, oldest first — the order they came in."""
    marks = ", ".join("?" for _ in statuses)
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            f"SELECT {_COLUMNS} FROM ideas WHERE project = ? AND status IN ({marks}) ORDER BY id",
            (bare(project), *statuses),
        ).fetchall()
    return [_idea(row) for row in rows]


def forget(project: str) -> int:
    """Drop every idea proposed for a project, and the batches that found them.

    For a project that was deleted: nobody will ever read them again, and the
    batches' cost is the project's alone. The tickets ideas became are
    the board's, and stay there.
    """
    with db.transaction() as connection:
        gone = connection.execute("DELETE FROM ideas WHERE project = ?", (bare(project),)).rowcount
        connection.execute("DELETE FROM idea_batches WHERE project = ?", (bare(project),))
    return gone


def every(project: str | None) -> list[Idea]:
    """Every idea of one scope — of all of them when None — whatever became of it, the newest first."""
    if project is not None:
        ideas = listed(project, STATUSES)
        ideas.reverse()
        return ideas
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(f"SELECT {_COLUMNS} FROM ideas ORDER BY id DESC").fetchall()
    return [_idea(row) for row in rows]


def known(project: str) -> list[str]:
    """Every title ever proposed for this scope, whatever was decided about it."""
    return [idea.title for idea in listed(project, STATUSES)]


def get(identifier: int) -> Idea:
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            f"SELECT {_COLUMNS} FROM ideas WHERE id = ?", (identifier,)
        ).fetchone()
    if row is None:
        raise LookupError(f"no idea {identifier}")
    return _idea(row)


def decide(identifier: int, status: str, *, ticket: str = "", created: str = "") -> Idea:
    """Write what was decided about an idea, and the board pages it became."""
    if status not in STATUSES:
        raise ValueError(f"an idea is {', '.join(STATUSES)} — not {status}")
    with db.transaction() as connection:
        connection.execute(
            "UPDATE ideas SET status = ?, decided_at = ?, changed_at = ?,"
            " ticket = CASE WHEN ? != '' THEN ? ELSE ticket END,"
            " created = CASE WHEN ? != '' THEN ? ELSE created END"
            " WHERE id = ?",
            (
                status,
                None if status == "proposed" else _now(),
                _now(),
                ticket,
                ticket,
                created,
                created,
                identifier,
            ),
        )
    return get(identifier)


def last_decided(project: str | None = None) -> Idea | None:
    """The idea decided most recently — in one scope, or in any when None."""
    query = f"SELECT {_COLUMNS} FROM ideas WHERE status != 'proposed' AND decided_at IS NOT NULL"
    values: tuple[Any, ...] = ()
    if project is not None:
        query += " AND project = ?"
        values = (bare(project),)
    query += " ORDER BY decided_at DESC, id DESC LIMIT 1"
    with db.transaction(immediate=False) as connection:
        row = connection.execute(query, values).fetchone()
    return _idea(row) if row else None


def spent(project: str | None = None) -> tuple[int, float]:
    """How many batches were asked for, and what they cost together."""
    query = "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM idea_batches"
    values: tuple[Any, ...] = ()
    if project is not None:
        query += " WHERE project = ?"
        values = (bare(project),)
    with db.transaction(immediate=False) as connection:
        count, total = connection.execute(query, values).fetchone()
    return int(count), float(total)
