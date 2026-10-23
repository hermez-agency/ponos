"""Which model a ticket runs on when nobody said.

A ticket with no Model used to run on `runner.model`, which in practice is the
heaviest model there is — for “remove that paragraph” as much as for “audit the
whole repository”. The light ones would have done the first in a minute, for a
fraction of the credit.

So an empty Model is a request, like an empty Type: work it out. Not by asking
a model, though, and that is the decision this module stands on. A choice that
costs a session is a choice that has to earn back what it spends before it
saves anything, and its reason is whatever the session felt like writing. A few
rules read off the ticket cost nothing, give the same answer twice, and say
exactly why — which is the part that gets a wrong choice corrected rather than
put up with:

- **the type** gives the starting point, one level per type, set in the
  configuration (`auto_model_code`…): a text starts lighter than a change to a
  repository;
- **the sub-type** of a code ticket moves that start (`auto_model_subtype_docs`…):
  documentation and upkeep one level lower, a security fix one level higher —
  within the four levels, and Fable still only when it is allowed;
- **the size** moves it: a short request stays where it is, one of ordinary
  size is at least standard, a long one — or one with many steps — goes up one;
  and a request that only asks to remove, rename or reword something, said in
  its title and not drowned in a long body, drops to the lightest level;
- **the words** that announce heavy work — an audit, a migration, a refactor,
  a hard bug — take it to the heavy level, and to the heaviest when the request
  is long as well;
- **the priority**: a ticket scored 75 or more never runs on the lightest
  model, since a second attempt is exactly what it cannot afford.

Four levels, and each says which model it is in the configuration — the names
are the configuration's, not this module's, so a runner routed through
OpenRouter names its slugs there and nothing here changes.

**A run that failed goes up one level, once.** A ticket chosen for and failed —
a session that crashed, timed out, went round in circles — is run on the next
level up when it comes back, and the comment says so. Once: a ticket that
failed on the level above too is not a ticket a bigger model will save, and it
stays where it went rather than climbing to the top of the price list. What a
run was chosen and how it ended is read from the local journal (journal.py), so
this works the same on any board.

A Model somebody wrote is never second-guessed, and neither is an agent's: this
only ever fills the gap that `runner.model` used to fill. With one exception,
which is the price list again: **Fable is only run when `runner.use_fable` says
so.** One Fable session cost more than a day of Opus ones, and it arrived
unasked — through the heaviest level, through an escalation, through a Model
left on an old ticket. Off, every one of those runs on Opus instead, whoever
wrote it; see `allowed`.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import priority as priority_module

# From the lightest to the heaviest. A level is what a ticket asks for; which
# model answers it is the configuration's to say.
LEVELS = ("light", "standard", "heavy", "heaviest")

# The two types that act on the world. Asking little of them is not asking
# little: a browser driven by the lightest model is a browser that clicks the
# wrong button, so they never drop below where their type puts them.
RISKY = ("external", "publication")

# What heavy work announces itself with, as the beginning of a word, accents
# and capitals read away. French and English, since tickets come in both.
HEAVY = (
    "audit",
    "architectur",
    "migrat",
    "migrer",
    "refonte",
    "refactor",
    "debog",
    "debug",
    "multi-depot",
    "multi-repo",
    "securite",
    "security",
    "vulnerab",
    "performance",
    "rewrite",
    "reecri",
    "redesign",
    "investig",
    "diagnost",
)

# And what a small change does: remove, rename, reword — a label, a text, a typo.
LIGHT = (
    "retir",
    "supprim",
    "enlev",
    "renomm",
    "rename",
    "remov",
    "delet",
    "typo",
    "coquille",
    "libelle",
    "label",
    "wording",
    "faute",
    "orthograph",
    "traduction",
    "translat",
    "text",
    "couleur",
    "colou",
    "color",
    "icon",
)

# Where short ends and long begins: a few lines, and more than a page. Measured
# on real tickets, which are written with care: “remove that paragraph” came to
# 190 words and six list items once its context and its criteria were in it, a
# card redesign to 460 words and nineteen items — still one pull request.
SHORT_WORDS, SHORT_STEPS = 120, 5
LONG_WORDS, LONG_STEPS = 600, 25

# A small change says so in its title — “Remove the paragraph…” — whatever its
# body explains around it, as long as the body stays about that long.
SMALL_WORDS, SMALL_STEPS = 250, 10

# What a Fable that is not allowed runs on instead: the heaviest of the others.
INSTEAD_OF_FABLE = "opus"

_STEP = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|\[[ xX]?\])\s+\S", re.MULTILINE)


@dataclass(frozen=True)
class Grid:
    """Which model answers each level, and where each type starts."""

    models: dict[str, str] = field(default_factory=dict)
    starts: dict[str, str] = field(default_factory=dict)
    # How many levels each sub-type of a code ticket moves its start: -1, 0, 1.
    shifts: dict[str, int] = field(default_factory=dict)

    def model(self, level: str) -> str:
        """The model of a level — or of the nearest one that names one.

        Downwards first: a level left empty is a level somebody would rather
        not pay for, and the one under it is the closest to what they meant.
        """
        index = LEVELS.index(level)
        for other in (*LEVELS[index::-1], *LEVELS[index + 1 :]):
            if self.models.get(other):
                return self.models[other]
        return ""

    def start(self, kind: str) -> int:
        level = self.starts.get(kind, "standard")
        return LEVELS.index(level) if level in LEVELS else 1

    def level_of(self, model: str) -> int | None:
        """The level a model answers, the highest when it answers several."""
        found = [index for index, level in enumerate(LEVELS) if self.model(level) == model]
        return max(found) if model and found else None


@dataclass(frozen=True)
class Earlier:
    """The last run of the same ticket whose model was chosen here."""

    model: str
    status: str = ""
    escalated: bool = False


@dataclass(frozen=True)
class Choice:
    """A model, the level it answers, and the signals that led to it.

    `signals` are keys and values for voice.py to turn into the one-line
    reason: the decision is taken here, the sentence is said there.
    """

    model: str
    level: str
    signals: tuple[tuple[str, dict[str, Any]], ...] = ()
    escalated: bool = False


def is_fable(model: str) -> bool:
    """Is this Fable — `fable`, `claude-fable-5-1`, an OpenRouter slug of it?"""
    return "fable" in model.lower()


def allowed(model: str, fable: bool) -> str:
    """The model a session is given: this one, unless it is a Fable not allowed."""
    return INSTEAD_OF_FABLE if not fable and is_fable(model) else model


# The families Claude Code names, whichever way the model is spelled: `opus`,
# `claude-opus-4-1-20250805`, `claude-3-5-haiku-20241022`, `opus[1m]`.
FAMILIES = ("opus", "sonnet", "haiku", "fable")


def label(model: str) -> str:
    """A model as the console says it, `provider/model`: claude/opus, deepseek/r1.

    One function for every place a model is shown, so that the board, a ticket's
    page and the list of its runs never spell the same model three ways. The
    version stays out — it is in `describe`'s full identifier, for a tooltip —
    and a spelling nobody here knows is kept as it was written: an honest
    `gpt-9` beats a provider guessed. An OpenRouter slug already has the
    `vendor/model` shape and is left alone.
    """
    text = re.sub(r"\[[^\]]*\]$", "", model.strip())
    lowered = text.lower()
    if not lowered:
        return ""
    if "/" in lowered:
        return text
    for family in FAMILIES:
        if re.search(rf"(?<![a-z]){family}(?![a-z])", lowered):
            return f"claude/{family}"
    if lowered.startswith("deepseek"):
        name = lowered.removeprefix("deepseek").lstrip("-_ ")
        if name == "reasoner" or re.match(r"r1(?![a-z0-9])", name):
            return "deepseek/r1"
        if name == "chat" or re.match(r"v3(?![a-z0-9])", name):
            return "deepseek/v3"
        return f"deepseek/{name}" if name else text
    return text


def claude_default() -> str:
    """The model Claude Code runs on when nothing is passed, if it can be told.

    `ANTHROPIC_MODEL`, then the `model` of its settings. Empty when neither
    says: the CLI then picks by plan, and which one it picked is only known once
    a session announces it. Read, never written, and never a reason to fail.
    """
    named = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if named:
        return named
    directory = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    settings = (
        Path(directory).expanduser() if directory else Path.home() / ".claude"
    ) / "settings.json"
    try:
        value = json.loads(settings.read_text(encoding="utf-8")).get("model")
    except (OSError, ValueError, AttributeError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def describe(ticket: str, announced: str = "", configured: str = "") -> dict[str, Any]:
    """The model a ticket runs on, for its page: what it is and how sure we are.

    In order of trust: the model its last session announced about itself (the
    `init` line of the stream — what actually ran), the one the ticket names,
    the runner's, Claude Code's own. `default` is true when nobody chose it for
    this ticket; `label` is empty only when nothing can be said before a first
    session has run. `full` is the identifier as it was given, for a tooltip.
    """
    full = announced.strip() or ticket.strip() or configured.strip() or claude_default()
    return {"label": label(full), "full": full, "default": not ticket.strip()}


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return plain.lower()


def _found(stems: tuple[str, ...], text: str) -> list[str]:
    """Which of these stems begin a word of the text, in the order listed."""
    return [stem for stem in stems if re.search(rf"(?<![a-z]){re.escape(stem)}", text)]


def _word(text: str, stem: str) -> str:
    """The word a stem was found as, accents and all, for the reason to quote it."""
    word: str
    for word in re.findall(r"[\w-]+", text.lower()):
        if _fold(word).startswith(stem):
            return word
    return stem


def choose(
    title: str,
    body: str,
    *,
    kind: str,
    code: bool,
    priority: int | None = None,
    grid: Grid,
    earlier: Earlier | None = None,
    escalate: bool = True,
    subtype: str = "",
) -> Choice:
    """The model this ticket runs on — see the module's docstring for the rules.

    `kind` is the ticket's type, empty for a board without one: it then starts
    where its project puts it, a repository's level or a text's. `subtype` is a
    code ticket's, and is read on a code ticket only.
    """
    if earlier and earlier.model and (earlier.escalated or earlier.status == "waiting"):
        # Already climbed once: it stays there. Stopped by the quota: the
        # session is carried on, and it carries on with the model it began on.
        key = "model-kept" if earlier.escalated else "model-resumed"
        index = grid.level_of(earlier.model)
        kept = LEVELS[index] if index is not None else "standard"
        return Choice(earlier.model, kept, ((key, {"model": earlier.model}),), earlier.escalated)

    text = _fold(f"{title}\n{body}")
    words = len(text.split())
    steps = len(_STEP.findall(body or ""))
    heavy = _found(HEAVY, text)
    # The title first: it is where the request says what it is, while the body
    # mentions a text or a label about any change at all.
    titled = _found(LIGHT, _fold(title))
    light = titled or _found(LIGHT, text)
    started = kind or ("code" if code else "writing")
    level = grid.start(started)
    signals: list[tuple[str, dict[str, Any]]] = [("model-type", {"kind": started})]
    moved = grid.shifts.get(subtype, 0) if started == "code" else 0
    if moved:
        level = min(max(level + moved, 0), len(LEVELS) - 1)
        signals.append(
            ("model-subtype-" + ("lower" if moved < 0 else "higher"), {"subtype": subtype})
        )

    short = words <= SHORT_WORDS and steps <= SHORT_STEPS
    long = words >= LONG_WORDS or steps >= LONG_STEPS
    small = bool((short and light) or (titled and words <= SMALL_WORDS and steps <= SMALL_STEPS))
    if heavy:
        quoted = ", ".join(_word(f"{title} {body}", stem) for stem in heavy[:3])
        level = max(level, 2)
        if long and len(heavy) >= 2:
            level = 3
        signals.append(("model-heavy", {"words": quoted}))
        if long:
            signals.append(("model-long", {"count": words, "steps": steps}))
    elif long:
        level = min(max(level, 1) + 1, 3)
        signals.append(("model-long", {"count": words, "steps": steps}))
    elif small and started not in RISKY and level <= 1:
        level = 0
        quoted = ", ".join(_word(f"{title} {body}", stem) for stem in light[:2])
        signals.append(("model-small", {"words": quoted}))
    elif short:
        signals.append(("model-short", {}))
    else:
        level = max(level, 1)
        signals.append(("model-ordinary", {}))

    if priority is not None and priority >= priority_module.URGENT and level == 0:
        level = 1
        signals.append(("model-urgent", {"priority": priority}))

    escalated = False
    if escalate and earlier and earlier.model and earlier.status == "failed":
        before = grid.level_of(earlier.model)
        # Only when that is a step up from where the rules put it: a ticket the
        # rules already send higher has nothing to climb.
        if before is not None and level <= before < len(LEVELS) - 1:
            level = before + 1
            escalated = grid.model(LEVELS[level]) != earlier.model
            if escalated:
                signals.append(("model-escalated", {"model": earlier.model}))

    return Choice(grid.model(LEVELS[level]), LEVELS[level], tuple(signals), escalated)
