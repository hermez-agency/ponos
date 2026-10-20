"""The question a blocked ticket asks, and what an answer to it means.

A blocked report used to be the session's last sentence, posted as it came,
with the same footer under every one of them — *yes, no, or a sentence*. It
read as a paragraph on a phone, and it never said what the question *was*: on
the day a pull request was ready and only the merge was forbidden, nobody could
tell whether “yes” meant *merge it* or *I will*. So the session no longer writes
the comment. It hands over the parts — what is done, why it stops, the question,
and **which kind of answer it wants** — and the runner lays them out, one line
each, the same way every time:

- **yes-no**, when one word is enough to carry on, and the question is put so
  that “yes” means *go ahead*;
- **choice**, two to four concrete roads, numbered, so that “2” is an answer;
- **free**, when no option makes sense, and the question says what to give.

The other half is reading the answer back, and that is why the kind is worth
asking for: “2”, « la 2 », “ok” or a sentence all arrive as a comment, and a
comment is read by the next session minutes later, with no idea what “2”
referred to. `read` ties it to the option it names, and the run carries the
question along with it — see `Reports.discussion`.

The question is not kept anywhere but in the comment itself. A report the
runner can read back is a report that still means something after a restart, on
another machine, or on a board mirrored to Markdown files — so `found` reads the
layout `Voice.question` writes, and nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import voice

MODES = ("yes-no", "choice", "free")

# What kind of thing a ticket stopped on, as the session names it. Said on the
# comment, in front of why it stops, and what the console offers to do about it
# depends on it — see decisions.py. `other` is what nothing else fits.
CATEGORIES = ("question", "access", "manual", "credits", "ci", "conflict", "split", "other")

# The blocks that mean "run this yourself, then say done": the session prepares
# the commands and asks nothing. See `prompt.PERMISSIONS`.
CODES = ("access.sudo", "access.credentials")

# Two roads is a choice, five is a menu: past four, the session is asking you to
# do its thinking.
FEWEST = 2
MOST = 4

# The fields a blocked session writes before its RESULT line. Uppercase like the
# RESULT line itself, because a model reads them as the same kind of thing.
_FIELD = re.compile(r"^(DONE|WHY|CATEGORY|QUESTION|MODE|OPTION|CODE|COMMAND)\s*:\s*(.*)$", re.IGNORECASE)

# What a session that ends ok hands over for whoever reviews it: one line per
# thing it could not check. Read like the fields above, from the end.
_CAVEAT = re.compile(r"^CAVEAT\s*:\s*(.*)$", re.IGNORECASE)
CAVEATS = 4

# How the options sit on their line: “1. Tu fusionnes · 2. Tu m'autorises”.
_OPTION = re.compile(r"(\d)\.\s+(.+?)(?=\s+·\s+\d\.\s|$)")

# The words that name a number, for « la deuxième » as much as for “2”.
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "premier": 1, "première": 1, "premiere": 1, "deuxième": 2, "deuxieme": 2,
    "seconde": 2, "troisième": 3, "troisieme": 3, "quatrième": 4,
    "quatrieme": 4, "un": 1, "deux": 2, "trois": 3, "quatre": 4,
    "one": 1, "two": 2, "three": 3, "four": 4,
}
# What may stand in front of the number: « la 2 », “option 2”, “#2”, « n°2 ».
_BEFORE = r"(?:(?:la|le|l'|option|choix|choice|number|numéro|numero|n°|#)\s*)?"

# Yes and no, in both languages and in the shapes people actually type them.
_YES = {
    "y", "yes", "yep", "yeah", "ok", "okay", "go", "sure", "do it", "ship it",
    "oui", "ouais", "vas-y", "vas y", "allez", "d'accord", "daccord", "ça marche",
    "ca marche", "👍", "✅", "👌",
}
_NO = {
    "n", "no", "nope", "nah", "stop", "cancel", "drop it",
    "non", "nan", "laisse", "laisse tomber", "annule", "👎", "❌", "🚫",
}


@dataclass
class Question:
    """What a blocked session asks, in the parts the runner lays out."""

    ask: str
    mode: str = "free"
    options: list[str] = field(default_factory=list)
    done: str = ""
    why: str = ""
    # One of CATEGORIES, or "" when the session did not say — the console then
    # reads it off the words, as it does on a report older than the field.
    category: str = ""
    # An action a session cannot take itself — `access.sudo`, `access.credentials`
    # — and the commands it prepared for somebody else to run. Never a yes-no:
    # nobody can say yes to a session that has no password.
    code: str = ""
    commands: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # A choice of one is a yes-no that does not know it, and a choice
        # without options is a free question: read as what they are, rather
        # than drawn as a list nobody can pick from.
        self.mode = self.mode if self.mode in MODES else "free"
        self.options = [option for option in self.options if option.strip()][:MOST]
        if self.mode == "choice" and len(self.options) < FEWEST:
            self.mode = "free"
        if self.mode != "choice":
            self.options = []
        self.category = self.category if self.category in CATEGORIES else ""
        if self.code in CODES:
            self.mode = "free"
            self.options = []
        else:
            self.code = ""
            self.commands = []


@dataclass
class Reading:
    """An answer, as the option it names — or as what it says, when it names none."""

    kind: str  # "yes", "no", "option" or "free"
    text: str
    option: int = 0
    label: str = ""


def decide(text: str) -> str:
    """"yes", "no", or "" for anything that is not one of those two.

    Only the *first* word is read, and only when it stands alone or opens the
    sentence: "yes, and rename the column while you are there" is a yes with an
    instruction attached, while "no idea what you mean" is not a no. The rest of
    the message travels either way — the verdict never replaces what was said.
    """
    stripped = " ".join(text.strip().lower().split())
    if not stripped:
        return ""
    if any(_opens(stripped, word) for word in _YES):
        return "yes"
    if any(_opens(stripped, word) for word in _NO):
        return "no"
    return ""


def _opens(sentence: str, word: str) -> bool:
    return sentence == word or sentence.startswith(f"{word} ") or sentence.startswith(f"{word},")


def parse(answer: str) -> Question | None:
    """The question a session wrote before its RESULT line, if it wrote one.

    Read from the end, because the fields belong to the verdict and a session
    may well have quoted them earlier, explaining itself. Nothing without a
    QUESTION: a prompt file of your own, older than this, still blocks the way
    it always did, and the runner falls back on the RESULT line.
    """
    found: dict[str, str] = {}
    options: list[str] = []
    commands: list[str] = []
    for line in reversed(str(answer or "").splitlines()):
        stripped = line.strip().strip("*_`").lstrip("-#> ").strip("*_` ")
        matched = _FIELD.match(stripped)
        if not matched:
            continue
        name = matched.group(1).upper()
        value = " ".join(matched.group(2).strip("*_` ").split())
        if name == "OPTION":
            options.insert(0, re.sub(r"^\d[.)]\s*", "", value))
        elif name == "COMMAND":
            commands.insert(0, value)
        else:
            found.setdefault(name, value)
    if not found.get("QUESTION"):
        return None
    mode = found.get("MODE", "").lower().replace("/", "-").replace(" ", "-").replace("_", "-")
    mode = {"yes-or-no": "yes-no", "yesno": "yes-no", "choices": "choice"}.get(mode, mode)
    return Question(
        ask=found["QUESTION"],
        mode=mode or ("choice" if options else "free"),
        options=options,
        done="" if found.get("DONE", "").lower() in ("nothing", "rien", "-") else found.get("DONE", ""),
        why=found.get("WHY", ""),
        category=found.get("CATEGORY", "").lower().strip(" .`"),
        code=found.get("CODE", "").lower(),
        commands=commands,
    )


def caveats(answer: str) -> list[str]:
    """What a session that ended ok says it could not check, oldest first.

    Only the lines just above the RESULT line, like the fields of a question:
    a session explaining itself may well quote one earlier on. At most four —
    past that, it is a report, and the report is in the page.
    """
    lines = [line.strip().strip("*_`").lstrip("-#> ").strip("*_` ") for line in str(answer or "").splitlines()]
    lines = [line for line in lines if line]
    if lines and lines[-1].upper().startswith("RESULT"):
        lines.pop()
    said: list[str] = []
    for line in reversed(lines):
        matched = _CAVEAT.match(line)
        if not matched:
            break
        value = " ".join(matched.group(1).strip("*_` ").split())
        if value:
            said.insert(0, value)
    return said[-CAVEATS:]


def found(report: str) -> Question | None:
    """The question a blocked report asked, read back from its own layout.

    Only the first paragraph: what comes after a blank line is a note — a kept
    worktree, a trace — and never the question. Yes-no and choice are told by
    their last line; a free question is the last line of a report that has more
    than its verdict. A report written before the questions had a kind reads as
    none, and is carried the way it always was.
    """
    text = str(report or "").strip()
    if not text.startswith(voice.MARKS["blocked"]):
        return None
    lines = [line.strip() for line in text.split("\n\n", 1)[0].splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    last = lines[-1]
    if last.startswith("1. ") and len(lines) >= 3:
        options = [match.group(2).strip() for match in _OPTION.finditer(last)]
        return Question(ask=lines[-2], mode="choice", options=options)
    for spelled in voice.openings("yes-or-no"):
        tail = f" → {spelled}"
        if last.endswith(tail):
            return Question(ask=last[: -len(tail)].strip(), mode="yes-no")
    return Question(ask=last, mode="free")


def waiting(comments: Iterable[str]) -> Question | None:
    """The question a page is waiting on: its last report's, if that one asked.

    Only the last report: a ticket that asked, was answered and has reported
    since is waiting on nothing, and yesterday's list must not turn today's “2”
    into one of its options.
    """
    for text in reversed(list(comments)):
        if voice.is_report(text):
            return found(text)
    return None


def read(text: str, question: Question | None = None) -> Reading:
    """What an answer means, against the question it answers.

    A number is read only on a choice, and only one that is on the list: “3” to
    a yes-no question is a sentence somebody meant, not an option nobody
    offered. An option's own words, typed back, are that option. Yes and no are
    read on any question — on a choice they choose nothing, and travel as they
    are. Everything else is a free answer, and is never replaced by a reading:
    the reading is said *with* it.
    """
    said = " ".join(str(text or "").split())
    lowered = said.lower().rstrip(" .!")
    if question and question.mode == "choice":
        for index, option in enumerate(question.options, start=1):
            if lowered == option.lower().rstrip(" .!"):
                return Reading("option", said, index, option)
        number = _number(lowered)
        if 1 <= number <= len(question.options):
            return Reading("option", said, number, question.options[number - 1])
    verdict = decide(said)
    return Reading(verdict or "free", said)


def _number(lowered: str) -> int:
    """The option a reply opens on — “2”, « la 2 », “#2”, « la deuxième » — or 0."""
    matched = re.match(rf"^{_BEFORE}(\d)(?:\b|$)", lowered)
    if matched:
        return int(matched.group(1))
    matched = re.match(rf"^{_BEFORE}(\w+)", lowered)
    if matched and matched.group(1) in _ORDINALS:
        rest = lowered[matched.end() :].strip()
        # « un » alone is a number; « un détail » is a sentence.
        if matched.group(1) in ("un", "one", "deux", "two", "trois", "three", "quatre", "four"):
            return _ORDINALS[matched.group(1)] if not rest or rest[0] in ",.;:—-" else 0
        return _ORDINALS[matched.group(1)]
    return 0


def context(question: Question) -> str:
    """The question, as the next session is told it was asked.

    In English, like the rest of a prompt: this is the runner telling a model
    what happened, not a sentence anybody reads on a ticket.
    """
    if question.mode == "choice":
        listed = "; ".join(f"{index}. {option}" for index, option in enumerate(question.options, 1))
        return f"{question.ask} (options: {listed})"
    if question.mode == "yes-no":
        return f"{question.ask} (yes or no)"
    return question.ask


def meant(reading: Reading) -> str:
    """What an answer was read as, for the next session — or nothing to add."""
    if reading.kind == "option":
        return f"option {reading.option}, “{reading.label}”"
    if reading.kind in ("yes", "no"):
        return reading.kind
    return ""
