"""What a card waiting on you offers to do about it, and what doing it says.

A blocked ticket used to offer one gesture — make it ready — and a ticket in
review three, none of which said what they were deciding on. The reason was on
the page, in the last report, and reading it meant opening the ticket and the
whole of what the agent wrote. So the console reads that report for you and
turns it into a short panel: why it stopped, what is done, and the few things
that would get it moving — each one a click.

**Everything is read off the report the runner already writes.** Nothing new is
kept anywhere, for the reason question.py gives: a report is still a report
after a restart, on another machine, or on a board mirrored to Markdown files.
A session names the kind of thing it stopped on (`CATEGORY:`), and the runner
writes that name in front of why it stops — “Missing access: …” — which is
where `blockage` finds it again, in either language. A report written before
there was such a field, or one the runner wrote on its own behalf — a conflict,
a red CI, a spending limit — has no name in front: it is read off its words by
`classify`, which is a guess, and a guess is good enough to choose which
buttons to show. The buttons never act on the guess; they act on a click.

A review report carries what the session could not check (`CAVEAT:` lines,
written “To check: …”), and those become the ready-made reasons to send it back.

Every choice ends the same way: a comment that says what was decided, under the
line that says where it came from — the same line an answer from a phone
carries — and the move. The comment is what the next session reads, as the
author's word, so the instruction typed into the panel reaches it the way an
answer always has.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from . import question as question_module
from . import voice as voice_module
from .question import CATEGORIES, Question

# What each kind of stop offers, beyond what the session itself proposed. In
# the order they are drawn; "other" — write your own instruction — always comes
# last, and is added by `unblocking`.
DEFAULTS = {
    "question": ("instruct", "abandon"),
    "access": ("done-retry", "instruct", "abandon"),
    "manual": ("done-retry", "instruct", "abandon"),
    "credits": ("retry", "model", "abandon"),
    "ci": ("retry", "instruct", "model", "abandon"),
    "conflict": ("retry", "instruct", "abandon"),
    "split": ("split", "instruct", "abandon"),
    "other": ("retry", "instruct", "model", "abandon"),
}

# The words that give a kind of stop away, on a report that does not name it.
# Folded — lowercase, no accents — and matched as the start of a word. The
# order is the order they are tried in: conflicts resolved under checks that
# still fail are the checks' to answer for.
_WORDS = (
    (
        "split",
        ("split", "decoup", "too big", "trop gros", "sub-ticket", "sous-ticket", "sous ticket"),
    ),
    (
        "credits",
        ("credit", "quota", "budget", "spending limit", "plafond", "usage limit", "rate limit"),
    ),
    (
        "ci",
        (
            "checks",
            "check ",
            "ci ",
            "ci,",
            "ci.",
            "workflow",
            "verification",
            "pipeline",
            "tests fail",
            "tests echouent",
            "build fail",
        ),
    ),
    (
        "conflict",
        (
            "conflict",
            "conflit",
            "rebase",
            "rejou",
            "replay",
            "keeps moving",
            "avance plus vite",
            "pushed to",
            "a pousse",
        ),
    ),
    (
        "access",
        (
            "access",
            "acces",
            "token",
            "jeton",
            "permission",
            "credential",
            "identifiant",
            "password",
            "mot de passe",
            "api key",
            "cle api",
            "cle d'api",
            "ssh",
            "not allowed",
            "pas autorise",
            "pas le droit",
            "forbidden",
            "unauthori",
            "401",
            "403",
            "sign in",
            "log in",
            "login",
            "connexion",
            "se connecter",
            "secret",
            "oauth",
            "2fa",
            "captcha",
        ),
    ),
    (
        "manual",
        (
            "by hand",
            "a la main",
            "manual",
            "manuel",
            "install",
            "physical",
            "physique",
            "reboot",
            "redemarr",
            "you need to",
            "you have to",
            "tu dois",
            "vous devez",
            "il faut que tu",
            "il faut que vous",
            "on your machine",
            "sur ta machine",
            "sur votre machine",
        ),
    ),
)

# The ready-made reasons to send a pull request back, read off what the session
# said it could not check.
_REWORK = (
    ("add-tests", ("test",)),
    ("screenshots", ("screenshot", "capture", "screen shot")),
    ("rebase", ("rebase", "conflict", "conflit", "behind", "en retard sur")),
)

# The words of a question that proposes to close the ticket rather than to work
# on it — a duplicate, nothing left to do. Folded, and matched as the start of a
# word, like `_WORDS`. Such a question is answered "yes, close it" in one click,
# which files the ticket as done instead of starting a session to say so.
_CLOSING = (
    "clore",
    "clos",
    "cloture",
    "fermer",
    "ferme le",
    "ferme ce",
    "close",
    "closing",
    "doublon",
    "duplicate",
    "rien a faire",
    "rien a changer",
    "nothing to do",
    "nothing to change",
    "mark it done",
    "mark it as done",
    "marquer comme termine",
    "passer en done",
    "move it to done",
)

# How many of the session's points to check become a button of their own.
CAVEATS = question_module.CAVEATS


@dataclass
class Blockage:
    """Why a blocked ticket stopped, as its last report says it."""

    category: str = "other"
    # One sentence: why it stops — the session's own words when it gave them.
    reason: str = ""
    # What is done already, from the report's first line.
    done: str = ""
    question: Question | None = None
    # What else the report said, under its question: a kept worktree, a detail.
    detail: str = ""
    # Whether the session named the category, rather than its words giving it away.
    declared: bool = False
    # Whether there is a report at all: a ticket set aside by hand has none.
    reported: bool = False


@dataclass
class Delivered:
    """What a ticket in review brought back, as its last report says it."""

    summary: str = ""
    pull_request: str = ""
    caveats: list[str] = field(default_factory=list)
    # The rest of the verdict line: where the work is, how long it took.
    facts: str = ""


@dataclass
class Solution:
    """One thing the panel offers, and what it needs before it can be done."""

    key: str
    # The column the ticket goes to.
    column: str
    # "" — a click is enough; "text" — words are required; "note" — words are
    # welcome; "model" — a model is chosen; "titles" — one sub-ticket a line.
    needs: str = ""
    # What is offered: the option's own words, or an instruction ready to edit.
    text: str = ""
    # The option it is, counted from 1, for the session's own options.
    number: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "column": self.column,
            "needs": self.needs,
            "text": self.text,
            "number": self.number,
        }


def fold(text: str) -> str:
    """Lowercase, without accents and on one line: what `classify` reads."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(bare.lower().replace("’", "'").split())


def classify(*texts: str) -> str:
    """The kind of stop a report's words give away, for one that does not name it.

    A question mark with nothing else to go on is a decision to make; nothing at
    all is `other`, which offers to run it again.
    """
    folded = " " + " ".join(fold(text) for text in texts if text) + " "
    for category, words in _WORDS:
        if any(re.search(r"(?<![a-z])" + re.escape(word), folded) for word in words):
            return category
    return "question" if "?" in folded else "other"


def closing(asked: Question | None) -> bool:
    """Whether a question proposes to close the ticket: a duplicate, nothing to do."""
    if not asked or asked.mode == "free":
        return False
    folded = " " + fold(" ".join([asked.ask, *asked.options])) + " "
    return any(re.search(r"(?<![a-z])" + re.escape(word), folded) for word in _CLOSING)


def _labelled(line: str) -> tuple[str, str]:
    """The category a reason line opens on, and the reason after it — or ("", line)."""
    for category in CATEGORIES:
        for named in voice_module.every(f"category-{category}"):
            if line == named:
                return category, ""
            for separator in (" : ", ": "):
                if line.startswith(named + separator):
                    return category, line[len(named) + len(separator) :].strip()
    return "", line


def _last_report(comments: Iterable[str]) -> str:
    for text in reversed(list(comments)):
        if voice_module.is_report(text):
            return voice_module.plain(str(text)).strip()
    return ""


def blockage(comments: Iterable[str]) -> Blockage:
    """Why a blocked ticket stopped, read off the last report on its page.

    The report's first paragraph is its question — see `Reports._block`: the
    verdict and what is done, why it stops, then the question. Under a blank
    line, the notes. A report that is not a blocked one — a ticket somebody set
    aside by hand, after it came back — says nothing about why, and neither does
    a page with no report at all: both read as `other`, unreported.
    """
    report = _last_report(comments)
    if not report.startswith(voice_module.MARKS["blocked"]):
        if not report:
            return Blockage()
        # A report from before the marks, or one that did not stop on a
        # question: its first sentence is all there is to go on.
        lines = [line.strip() for line in report.split("\n\n", 1)[0].splitlines() if line.strip()]
        reason = " ".join(lines[1:2]) or lines[0].split("—", 1)[-1].strip()
        legacy = report.startswith(voice_module.SIGNATURE) and "blocked" in lines[0].lower()
        if not legacy:
            return Blockage()
        return Blockage(category=classify(reason), reason=reason, reported=True)
    first, _, rest = report.partition("\n\n")
    lines = [line.strip() for line in first.splitlines() if line.strip()]
    verdict = lines[0]
    done = verdict.split(" — ", 1)[1].strip() if " — " in verdict else ""
    asked = question_module.found(report)
    # Between the verdict and the question: why it stops, when the session said.
    told = lines[1:]
    if asked:
        told = told[: -2 if asked.mode == "choice" else -1]
    why = " ".join(told)
    category, why = _labelled(why) if why else ("", "")
    declared = bool(category)
    ask = asked.ask if asked else ""
    if not category:
        category = classify(why, ask, rest)
    if asked:
        asked.category = category
        asked.done = done
        asked.why = why
    return Blockage(
        category=category,
        reason=why or ask,
        done=done,
        question=asked,
        detail=" ".join(rest.split()),
        declared=declared,
        reported=True,
    )


def delivered(comments: Iterable[str]) -> Delivered:
    """What a ticket in review brought back, read off its last report.

    A review report is the verdict and its facts, the session's sentence, the
    pull request, then whatever else the run had to say — the session's points
    to check among them, each on its own line.
    """
    report = _last_report(comments)
    if not report:
        return Delivered()
    lines = [line.strip() for line in report.splitlines() if line.strip()]
    verdict = lines[0]
    facts = verdict.split(" — ", 1)[1].strip() if " — " in verdict else ""
    openings = voice_module.openings("caveat")
    caveats = [
        line[len(opening) :].strip()
        for line in lines[1:]
        for opening in openings
        if line.startswith(opening)
    ]
    pull_request = next(
        (line for line in lines[1:] if re.match(r"https?://\S+/pull/\d+\S*$", line)), ""
    )
    summary = next(
        (line for line in lines[1:] if line != pull_request and not line.startswith(openings)),
        "",
    )
    return Delivered(summary=summary, pull_request=pull_request, caveats=caveats, facts=facts)


def unblocking(found: Blockage, *, models: bool = True, cancel: bool = False) -> list[Solution]:
    """What a blocked ticket offers, the session's own proposals first.

    A yes-no question offers its yes, and a choice its options — except on a
    ticket too big for one, whose options are the sub-tickets it proposes and go
    into the split instead. A question that proposes to close the ticket — a
    duplicate, nothing to do — offers to do it at once, as done. Then whatever its kind of stop calls for, and last,
    always, an instruction of your own. `models` is whether the board has a Model
    column to run it again on another model with, and `cancel` whether it has a
    cancelled one to file an abandoned ticket under rather than done.
    """
    solutions: list[Solution] = []
    asked = found.question
    if asked and asked.mode == "yes-no":
        solutions.append(Solution("yes", "ready"))
    if closing(asked) and found.category != "split":
        solutions.append(Solution("close", "done"))
    if asked and asked.mode == "choice" and found.category != "split":
        solutions.extend(
            Solution("option", "ready", text=option, number=number)
            for number, option in enumerate(asked.options, 1)
        )
    if asked and asked.mode != "choice":
        solutions.append(Solution("answer", "ready", needs="text"))
    for key in DEFAULTS.get(found.category, DEFAULTS["other"]):
        if key == "model" and not models:
            continue
        if key == "split":
            proposed = asked.options if asked and found.category == "split" else []
            solutions.append(Solution("split", "done", needs="titles", text="\n".join(proposed)))
        elif key == "model":
            solutions.append(Solution("model", "ready", needs="model"))
        elif key == "abandon":
            solutions.append(Solution("abandon", "cancelled" if cancel else "done", needs="note"))
        elif key in ("instruct",):
            solutions.append(Solution(key, "ready", needs="text"))
        else:
            solutions.append(Solution(key, "ready", needs="note"))
    solutions.append(Solution("other", "ready", needs="text"))
    return solutions


def deciding(
    found: Delivered,
    said: voice_module.Voice,
    *,
    checks: str = "",
    validate: bool = True,
    cancel: bool = False,
) -> list[Solution]:
    """What a ticket in review offers: validate, send it back, or reject it.

    Sending it back comes ready-made for what is known to be missing — red
    checks, and each point the session said it could not check — with the
    instruction written out, for you to send as it is or to change. `validate`
    is whether the board has the column the runner acts on; without it, a
    validated ticket is a done one. `cancel` is whether a rejected ticket can be
    filed as cancelled — given up on — rather than as done.
    """
    solutions = [Solution("validate", "validated" if validate else "done")]
    solutions.append(Solution("rework", "ready", needs="text"))
    if checks == "failed":
        solutions.append(Solution("fix-ci", "ready", needs="text", text=said.say("told-fix-ci")))
    offered: set[str] = set()
    for number, caveat in enumerate(found.caveats[:CAVEATS], 1):
        folded = fold(caveat)
        key = next(
            (key for key, words in _REWORK if any(word in folded for word in words)), "caveat"
        )
        if key in offered:
            continue
        if key != "caveat":
            offered.add(key)
        text = (
            said.say("told-caveat", caveat=caveat)
            if key == "caveat"
            else f"{said.say(f'told-{key}')} — {caveat}"
        )
        solutions.append(Solution(key, "ready", needs="text", text=text, number=number))
    solutions.append(Solution("reject", "cancelled" if cancel else "done", needs="note"))
    return solutions


KEYS = {
    "blocked": (
        "yes",
        "close",
        "option",
        "answer",
        "instruct",
        "done-retry",
        "retry",
        "model",
        "split",
        "abandon",
        "other",
    ),
    "review": (
        "validate",
        "rework",
        "fix-ci",
        "add-tests",
        "screenshots",
        "rebase",
        "caveat",
        "reject",
    ),
}


def label(
    said: voice_module.Voice, solution: Solution, *, model: str = "", titles: Iterable[str] = ()
) -> str:
    """A choice, named the way the ticket is told it — “run it again on opus”."""
    if solution.key == "option":
        return said.say("decided-option", number=solution.number, option=solution.text)
    if solution.key == "model":
        return said.say("decided-model", model=model or "…")
    if solution.key == "split":
        named = [title.strip() for title in titles if title.strip()]
        if not named:
            return said.say("offer-split")
        return said.say("decided-split", count=len(named), titles=" · ".join(named))
    if solution.column == "cancelled":
        return said.say(f"decided-{solution.key}-cancelled")
    return said.say(f"decided-{solution.key}")


def told(
    said: voice_module.Voice,
    solution: Solution,
    text: str = "",
    *,
    model: str = "",
    titles: Iterable[str] = (),
) -> list[str]:
    """What the ticket is told about a choice, one line each.

    The decision first, in the runner's words, then what the next session is
    to read: the words typed into the panel, or — for a choice that carries
    none — the sentence that says it for you. A move to done carries a note,
    when one was written, and nothing else: nobody reads it but you.
    """
    key = solution.key
    words = str(text or "").strip()
    instruction = {
        "yes": said.say("relayed-yes"),
        "option": said.say("relayed-option", number=solution.number, option=solution.text),
        "done-retry": said.say("told-done-retry"),
        "retry": said.say("told-retry"),
        "close": said.say("told-close"),
    }.get(key, "")
    lines = [said.say("decision", choice=label(said, solution, model=model, titles=titles))]
    lines.extend(line for line in (words or instruction).splitlines() if line.strip())
    return lines


def checks_state(checks: list[dict[str, Any]]) -> str:
    """`passed`, `failed`, `pending`, or `none` — what a pull request's checks say together."""
    buckets = {str(check.get("bucket") or "") for check in checks}
    if not buckets:
        return "none"
    if buckets & {"fail", "cancel"}:
        return "failed"
    if "pending" in buckets:
        return "pending"
    return "passed"
