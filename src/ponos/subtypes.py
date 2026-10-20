"""What kind of change a code ticket is: a bug, a feature, some upkeep.

The type says the road a ticket takes (kinds.py); a code ticket's **sub-type**
says what is done once it is on it. It was read, until now, in prefixes written
by hand at the front of a title — `[Bug]`, `[Feature]`, `[Docs]` — mixed in with
prefixes of another sort, the part of the product a ticket is about (`[UX]`,
`[Gameplay]`, `[Console]`), and spelled however the day went. A prefix is a
convention, and a convention is what a pull request title, a commit and a
CHANGELOG all need to agree on. So it became a column of the board, a select
nobody has to remember the spelling of, and one table here that says, for each
sub-type, everything the rest of the runner needs of it:

- the **option** the board writes it as, and the other spellings it is known
  by — the English word, the prefix of the old titles (`[Ops]` was a chore);
- its **colour**, on the card and in Notion — and its **icon**, which only the
  command line still prints: the console tells them apart by colour alone,
  an emoji beside a coloured dot said the same thing twice;
- the **prefix** of its commit and its pull request, the conventional commits
  one, and the **section** of the CHANGELOG it goes under — or none;
- how it moves the **level of the model** a code ticket starts at: a page of
  documentation is lighter work than a feature, a security hole heavier.

A new sub-type is a line in `SUBTYPES` and nothing else: the select, the
classifier's prompt, the card, the filter, the statistics and the settings all
read the table.

**An empty column is a request, like an empty Type**, and it is answered in two
ways, the cheap one first. A title whose prefix says it (`[Bug] …`) is classified
by that prefix alone, without asking anybody. Otherwise the short session that
tells a ticket's type tells its sub-type in the same answer — or, on a ticket
whose type somebody already wrote, a session of its own on the same light
model. A doubt is not a question here: the wrong sub-type costs a word in a
commit, not a post published, so in doubt the ticket is an `improvement`, and
its report says the runner was not sure. A value somebody wrote is never
rewritten.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

# The one taken when nothing better can be said: "make better what exists" is
# the widest of them, and the least wrong in a CHANGELOG.
DOUBT = "improvement"

# How a sub-type moves the level a code ticket starts at — see models.py.
SHIFTS = {"lower": -1, "same": 0, "higher": 1}


@dataclass(frozen=True)
class Subtype:
    key: str
    # The board's option, and the console's word — in every language, since
    # the sub-types are not translated: see `SUBTYPES`.
    option: str
    label: str
    icon: str
    # A Notion colour: the select's, and the card's.
    colour: str
    # `fix`, `feat`… — the conventional commits prefix.
    commit: str
    # The CHANGELOG section, "" for none at all.
    changelog: str
    # Where the level of the model goes from Code's: one of `SHIFTS`.
    shift: str
    # What it is recognised by, folded: the option, the label, and these —
    # the prefixes the titles were written with.
    words: tuple[str, ...] = ()
    # What the session is told of it, on top of the prefix and the section.
    rule: str = ""

    def names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(fold(name) for name in (self.key, self.option, self.label, *self.words))
        )

    def as_dict(self) -> dict[str, object]:
        """What the console is handed."""
        return {
            "key": self.key,
            "option": self.option,
            "label": self.label,
            "colour": self.colour,
            "commit": self.commit,
            "changelog": self.changelog,
        }


# The label is the developers' word, and the console shows it as it is in
# every language: « Feature », « Security », not « Fonctionnalité » nor
# « Sécurité ». It is the word of the tickets, the pull requests and the commits
# — translated, it reads wrong and matches none of them. A language added to the
# console leaves it alone; the French words it used to be are kept in `words`,
# so that a title or an answer written with them is still understood.
SUBTYPES = (
    Subtype(
        "bug", "Bug", "Bug", "🐞", "red", "fix", "Fixed", "same",
        ("fix", "bugfix", "hotfix", "bogue"),
        rule=(
            "Before you fix it, write a test that reproduces the bug and fails "
            "on the code as it is; then fix it, and the test passes. If the "
            "repository has no tests at all, say in your report how you reproduced it."
        ),
    ),
    Subtype(
        "feature", "Feature", "Feature", "✨", "green",
        "feat", "Added", "same", ("feat", "nouveaute", "fonctionnalite"),
    ),
    Subtype(
        "improvement", "Amélioration", "Improvement", "⬆️",
        "blue", "feat", "Changed", "same", ("enhancement", "evolution"),
    ),
    Subtype(
        "chore", "Chore", "Chore", "🧹", "gray", "chore",
        "", "lower", ("ops", "maintenance", "deps", "ci"),
        rule=(
            "No CHANGELOG entry, unless the CHANGELOG has a Maintenance section: "
            "then it goes there."
        ),
    ),
    Subtype(
        "refactor", "Refactor", "Refactor", "♻️", "purple",
        "refactor", "Changed", "same", ("refacto", "refactoring", "refonte"),
        rule=(
            "The behaviour does not change: the tests that pass before pass after. "
            "A CHANGELOG entry under Changed only if somebody using it can tell."
        ),
    ),
    Subtype(
        "perf", "Perf", "Perf", "⚡", "yellow", "perf",
        "Changed", "same", ("performance", "perfs", "optim", "optimisation", "optimization"),
        rule="Measure before and after, and give both figures in the report.",
    ),
    Subtype(
        "docs", "Docs", "Docs", "📝", "brown", "docs", "", "lower",
        ("doc", "documentation"),
    ),
    Subtype(
        "security", "Sécurité", "Security", "🔒", "orange", "fix",
        "Security", "higher", ("secu", "vuln", "vulnerability"),
    ),
)

KEYS = tuple(subtype.key for subtype in SUBTYPES)
BY_KEY = {subtype.key: subtype for subtype in SUBTYPES}

# A bracketed word, wherever it is in the title: “Ponos — [Feature] …” puts the
# project first and the sub-type after it.
_TAG = re.compile(r"\[\s*([^\[\]]{1,30}?)\s*\]")

# A title that already says it the conventional way.
_CONVENTIONAL = re.compile(r"^\s*[a-z]+(\([^)]*\))?!?:\s")


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


def of(value: object) -> str:
    """The sub-type a board option — or any of its spellings — means, or ""."""
    wanted = fold(str(value or ""))
    if not wanted:
        return ""
    for subtype in SUBTYPES:
        if wanted in subtype.names():
            return subtype.key
    return ""


def option(key: str) -> str:
    """How the board writes a sub-type, "" for none."""
    return BY_KEY[key].option if key in BY_KEY else ""


def from_prefix(title: str) -> str:
    """The sub-type a title's bracketed prefix says, or "" when none of them does.

    The first one that is a sub-type: `[UX] [Bug]` is a bug about the UX, and a
    title whose only prefix is a domain says nothing about the change.
    """
    for word in _TAG.findall(title or ""):
        found = of(word)
        if found:
            return found
    return ""


def titled(key: str, title: str) -> str:
    """A pull request's title: the conventional prefix, then the title without its tag.

    The tag goes, since `fix:` already says `[Bug]`; a domain tag stays. A
    title that already starts the conventional way is left as it is.
    """
    if key not in BY_KEY or _CONVENTIONAL.match(title or ""):
        return title
    kept = title
    for match in _TAG.finditer(title):
        if of(match.group(1)) == key:
            kept = (title[: match.start()] + title[match.end():]).strip()
            kept = re.sub(r"\s{2,}", " ", kept)
            break
    return f"{BY_KEY[key].commit}: {kept}"


def section(key: str) -> str:
    """What a session is told about the change it makes, or "" with no sub-type."""
    subtype = BY_KEY.get(key)
    if not subtype:
        return ""
    where = (
        f"under **{subtype.changelog}**" if subtype.changelog else "nowhere: no entry"
    )
    lines = [
        f"# Kind of change — {subtype.label}",
        "",
        f"This ticket is a {subtype.label.lower()} ({subtype.key}).",
        "",
        f"- The title of your commit starts with `{subtype.commit}: ` (conventional "
        "commits), and so will the pull request opened from it.",
        f"- If the repository keeps a CHANGELOG, the entry goes {where}.",
    ]
    if subtype.rule:
        lines.append(f"- {subtype.rule}")
    return "\n".join(lines) + "\n"


# The question the classifier is asked, after the type — see kinds.py.
CHOICES = "\n".join(
    f'- "{subtype.key}": {line}'
    for subtype, line in zip(
        SUBTYPES,
        (
            "something does not work as it should",
            "a capability that did not exist",
            "making better what exists: UX, UI, wording, ergonomics",
            "upkeep: dependencies, CI, configuration, tooling, cleaning up",
            "restructuring the code without changing what it does",
            "making it faster or lighter",
            "documentation, README, a documentation site",
            "a security hole, a secret, permissions",
        ),
        strict=True,
    )
)

PROMPT = """\
Below is a code ticket that a runner is about to carry out on its own. Before \
it does, say what kind of change it is. Do not do the ticket, and do not open \
anything: read it and classify it.

{choices}

# The ticket — {title}

{body}

# Your answer

Answer with one JSON object and nothing else — no preamble, no code fence:

{{"subtype": "{keys}", "reason": "one sentence, in the language the ticket is \
written in", "confidence": "low|medium|high"}}
"""


def prompt(title: str, body: str) -> str:
    return PROMPT.format(
        choices=CHOICES,
        title=title.strip() or "(untitled)",
        body=body.strip() or "(no description: everything is in the title)",
        keys="|".join(KEYS),
    )


@dataclass
class Guess:
    subtype: str = ""
    reason: str = ""
    confidence: str = ""


def parse(answer: str) -> Guess:
    """The sub-type out of what the session said — the last object, as in kinds.py."""
    for found in reversed(re.findall(r"\{[^{}]*\}", answer or "")):
        try:
            raw = json.loads(found)
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue
        confidence = str(raw.get("subtype_confidence") or raw.get("confidence") or "").strip().lower()
        return Guess(
            subtype=of(raw.get("subtype")),
            reason=" ".join(str(raw.get("subtype_reason") or raw.get("reason") or "").split()),
            confidence=confidence if confidence in ("low", "medium", "high") else "low",
        )
    return Guess()


def settle(guess: Guess, least: str = "medium") -> tuple[str, bool]:
    """The sub-type to write, and whether it was a doubt settled as `DOUBT`."""
    levels = ("low", "medium", "high")
    floor = levels.index(least) if least in levels else 1
    if guess.subtype and levels.index(guess.confidence or "low") >= floor:
        return guess.subtype, False
    return DOUBT, True


def shift(key: str, shifts: dict[str, str] | None = None) -> int:
    """How many levels a sub-type moves a code ticket's start: -1, 0 or 1."""
    subtype = BY_KEY.get(key)
    if not subtype:
        return 0
    said = (shifts or {}).get(key, subtype.shift)
    return SHIFTS.get(said, SHIFTS[subtype.shift])
