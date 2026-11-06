"""What kind of work a ticket is, decided before any of it is done.

For a long time the question answered itself: a ticket whose project had a
repository came back as a pull request, and every other one as a text in its
own page. Then tickets started asking for things that are neither — enter these
DNS records at the registrar, post this on LinkedIn, deploy that — and those do
not have the same road, nor the same way of going wrong. A pull request is read
before it is merged; a post, once it is out, is out.

So a ticket has a **type**, and there are five, told apart by the road they
take rather than by what they are about:

- `code` — a repository, a branch, a pull request;
- `writing` — no repository, the answer is written into the page;
- `external` — no repository either, the work is done somewhere else: in the
  browser, in a DNS zone, in the settings of a service. It stops at the first
  doubt, and its answer is the log of what it did;
- `publication` — something public and irreversible. Prepared first, sent to
  review, and only published once somebody has moved it to *Validated*;
- `diagnostic` — no repository to change either, only one to read: a session
  investigates a symptom (« X does not work ») in the code, the logs and the
  read-only accesses its project declares, writes down the cause with its
  proof, and writes the tickets that fix it. See diagnosis.py.

The column is optional, and empty is a request: work it out. A short session on
the lightest model reads the title, the content and whether the project has a
repository, and answers in JSON — a type, a sentence saying why, how sure it is,
and the type it hesitated with. It runs in the pass's own thread, like the one
that names a nameless ticket, so it neither starts anything alongside the
sessions in flight nor holds one of their places for longer than it takes to
answer a question.

What is done with that answer is the point of the module, and it is decided
here, in code, rather than left to the model: **a doubt is never settled by
running the ticket.** A guess that is not sure enough, or that hesitated between
a harmless type and one of the two that act on the world, blocks the ticket
with the question — and the type is left empty, for you to choose, rather than
written on the page as though somebody had chosen it. When the session itself
has to choose, it is told to take the more careful of the two; see `PRUDENCE`.

One doubt is the exception, and it is settled rather than asked: **between
code and anything else, the ticket is not code.** An audit, a check, a
deployment or a setting changed in production reads like code because it is
about code, and run as code it comes back blocked for want of a commit nobody
asked for — the most frequent way a finished ticket used to end up waiting for
somebody. The other type has a deliverable that is the report itself, so it is
taken, and the comment that says which type the ticket was run as says that it
was a choice between two; see `settle`.

A type can still be wrong, and the session that runs the ticket is the first
to see it: a ticket run as a text that asks for a pull request has nothing it
can do but ask to be run again as code — and it used to ask it on every run,
since only a person changes the column. So a session that was given no
repository, on a project that has one, may end on a `KIND: code` line (see
`claimed`): the runner writes Code in the column, says so, and puts the ticket
back in ready — once a ticket, and never again, so that two sessions that
disagree cannot hand it back and forth. See `Execution._switch_to_code`.

The same answer carries a code ticket's sub-type — a bug, a feature, upkeep —
so that a ticket with neither costs one session and not two: see subtypes.py.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from . import subtypes
from .config import CONFIDENCES
from .projects import Project

KINDS = ("code", "writing", "external", "publication", "diagnostic")

# From the least guarded road to the most. Choosing “the more careful” of two
# types is choosing the one further down this line: a publication waits for a
# human before anything goes out, an external action stops at its first doubt.
# A diagnostic changes nothing anywhere — it reads, and writes tickets that are
# drafts unless its project says otherwise — so it sits beside the text.
PRUDENCE = ("writing", "diagnostic", "code", "external", "publication")

# The two that act on the world rather than on a branch or a page.
RISKY = ("external", "publication")

# None of these is worked in a repository, whatever the project holds: what
# they produce does not go into one — nor does it ever ask for a commit.
WITHOUT_REPOSITORY = ("writing", "external", "publication", "diagnostic")

# How close a word typed in an answer must be to a type's name to be read as
# it: “readction” is Rédaction, “action” alone is not. A name of four
# letters or fewer is spelled right or not at all — “mode” is not Code.
CLOSE = 0.85

# One JSON object. A session still thinking about it after two minutes is a
# session that misunderstood the question.
TIMEOUT_MINUTES = 2

PROMPT = """\
Below is a ticket that a runner is about to carry out on its own. Before it \
does, say what kind of ticket it is. Do not do the ticket, and do not open \
anything: read it and classify it.

The five types are told apart by how the work is carried out, not by its \
subject:

- "code": the deliverable is a change in a code repository — a branch and a \
pull request. Documentation that lives in the repository is code too. Only a \
ticket that asks for files of the repository to change is code.
- "writing": there is no repository to change; the deliverable is a text \
written back into the ticket — an answer, a draft, a piece of research. An \
audit, a review, a check or a verification is writing, even of a codebase, \
when what it asks for is a report and not a fix — "do not code" says so.
- "external": the work is done outside, by acting on something: in a browser, \
in a DNS zone, in the settings of a third-party service, in a hosting \
dashboard, in the board itself. No repository. Deploying or redeploying, \
setting an environment variable or a setting in production, pointing a \
domain, creating tickets out of an audit: external.
- "publication": something goes out in public and cannot be taken back — a \
post on a social network, an email or a message sent to people.
- "diagnostic": something does not work and nobody knows why yet — "X is \
broken", "why does Y" — and the ticket asks to find the cause, not to fix it: \
an investigation, read only, that ends with the cause and the tickets that \
would fix it. A ticket that already says what to change is code.

When two types fit, choose the more careful one: publication before external, \
external before writing. A ticket that asks to draft a post AND to publish it \
is a publication; one that only asks for the draft is writing. Between code and \
another type, choose the other one: a ticket is code only when its deliverable \
is a commit.

{repository}

# The ticket — {title}

{body}
{comments}
# Your answer

Answer with one JSON object and nothing else — no preamble, no code fence:

{{"type": "code|writing|external|publication|diagnostic", "reason": "one sentence, in the \
language the ticket is written in", "confidence": "low|medium|high", \
"alternative": "the other type you hesitated with, or an empty string", \
"subtype": "{subtypes}, or an empty string when the type is not code", \
"subtype_confidence": "low|medium|high"}}

A code ticket also has a sub-type, which says what kind of change it is:

{choices}
"""


# The line a session that was not given a repository ends on when the ticket
# asks for one. Uppercase like the RESULT line, since a model reads them alike.
_CLAIM = re.compile(r"^KIND\s*:\s*(.*)$", re.IGNORECASE)


@dataclass
class Guess:
    """What the classifying session answered, read into four fields."""

    kind: str = ""
    reason: str = ""
    confidence: str = ""
    alternative: str = ""
    # The type it was not run as, when `settle` chose between code and another.
    settled: str = ""


def prompt(
    title: str,
    body: str,
    *,
    project: str,
    repository: bool,
    comments: list[str] | None = None,
) -> str:
    if not project:
        where = "The ticket belongs to no project, so there is no repository to change."
    elif repository:
        where = f"The ticket belongs to the {project} project, which has a code repository."
    else:
        where = (
            f"The ticket belongs to the {project} project, which has no code "
            "repository: it cannot be a code ticket."
        )
    said = ""
    if comments:
        # What was said since — a blocked ticket is answered in a comment, and
        # “it's a publication” is exactly the sort of thing it is answered with.
        said = (
            "\n# What was said on the ticket, oldest first\n\n"
            + "\n".join(f"- {line}" for line in comments)
            + "\n"
        )
    return PROMPT.format(
        repository=where,
        title=title.strip() or "(untitled)",
        body=body.strip() or "(no description: everything is in the title)",
        comments=said,
        subtypes="|".join(subtypes.KEYS),
        choices=subtypes.CHOICES,
    )


def parse(answer: str) -> Guess:
    """The guess, out of whatever the session actually said.

    The last object that reads as one rather than the whole answer: a session
    that ignores “and nothing else” wraps its JSON in a sentence or a fence far
    more often than it gets the JSON itself wrong. Anything that is not one of
    the five types comes back as no type at all, which `doubt` refuses.
    """
    for found in reversed(re.findall(r"\{[^{}]*\}", answer or "")):
        try:
            raw = json.loads(found)
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue
        kind = _word(raw.get("type"))
        alternative = _word(raw.get("alternative"))
        confidence = _word(raw.get("confidence"))
        return Guess(
            kind=kind if kind in KINDS else "",
            reason=" ".join(str(raw.get("reason") or "").split()),
            confidence=confidence if confidence in CONFIDENCES else "low",
            alternative=alternative if alternative in KINDS and alternative != kind else "",
        )
    return Guess()


def claimed(answer: str) -> str:
    """The type a session's answer says the ticket really is — "code", or "".

    Read from the end, like the fields of a question: a session explaining
    itself may well quote the line earlier on. Only code, the one type a
    session cannot do the work of from where it is: a text run as an external
    action can still be written, and the other way round.
    """
    for line in reversed(str(answer or "").splitlines()):
        matched = _CLAIM.match(line.strip().strip("*_`").lstrip("-#> ").strip("*_` "))
        if matched:
            return "code" if _word(matched.group(1).strip("*_`. ")) == "code" else ""
    return ""


def doubt(guess: Guess, least: str = "medium") -> str:
    """Why this guess must not be acted on, or "" when it may.

    `unknown` — no type came out of it at all. `unsure` — it said so itself,
    under the confidence the configuration asks for. `hesitant` — it hesitated
    between two types and one of them acts on the world: a ticket run as a
    text that was a publication is a post nobody read before it went out, and
    one run as a publication that was a text is a question nobody needed to be
    asked. Only the first of those costs anything, but the runner cannot tell
    which of the two it is looking at — which is the definition of a doubt.
    """
    if guess.kind not in KINDS:
        return "unknown"
    if guess.settled:
        return ""
    floor = least if least in CONFIDENCES else "medium"
    if CONFIDENCES.index(guess.confidence) < CONFIDENCES.index(floor):
        return "unsure"
    if guess.alternative and (guess.kind in RISKY or guess.alternative in RISKY):
        return "hesitant"
    return ""


def settle(guess: Guess) -> Guess:
    """The guess, with a doubt between code and another type settled for the other.

    Not a question, and not the more careful type either: the type that does
    not ask for a commit — see the module's docstring. Whatever the confidence,
    since “not sure, perhaps code” is the same doubt said less firmly. A guess
    that is not between code and one of the others comes back as it was.
    """
    between = {guess.kind, guess.alternative}
    if "code" not in between:
        return guess
    other = next(
        (kind for kind in (guess.kind, guess.alternative) if kind in WITHOUT_REPOSITORY), ""
    )
    if not other:
        return guess
    return replace(guess, kind=other, alternative="", settled="code")


def prudent(*kinds: str) -> str:
    """The more careful of these types — see `PRUDENCE`."""
    known = [kind for kind in kinds if kind in PRUDENCE]
    return max(known, key=PRUDENCE.index) if known else ""


def named(answer: str, names: Mapping[str, Sequence[str]]) -> str:
    """The one type an answer names, by any of its spellings — "" for none or two.

    The question of a type is answered on the page, from a phone more often
    than not: “action externe”, « la 2 » read as its option, or “readction”
    typed in a hurry. Each spelling is looked for among as many words of the
    answer as it has, a typo apart; an answer that names two types — “rédaction
    ou action externe ?” — has not chosen, and names none.
    """
    words = _folded(answer).split()
    found = {
        kind
        for kind, spellings in names.items()
        for spelling in spellings
        if _among(_folded(spelling).split(), words)
    }
    return found.pop() if len(found) == 1 else ""


def _among(name: list[str], words: list[str]) -> bool:
    if not name:
        return False
    wanted = " ".join(name)
    for start in range(len(words) - len(name) + 1):
        typed = " ".join(words[start : start + len(name)])
        if typed == wanted or (
            len(wanted) > 4 and SequenceMatcher(None, typed, wanted).ratio() >= CLOSE
        ):
            return True
    return False


def _folded(text: str) -> str:
    """Lower case, without accents or punctuation: what `named` compares."""
    bare = unicodedata.normalize("NFKD", str(text or ""))
    bare = "".join(char for char in bare if not unicodedata.combining(char)).lower()
    return re.sub(r"[^\w]+", " ", bare)


def worked_in(project: Project, kind: str) -> Project:
    """The project as this type of ticket works in it: with its repository or not.

    A text, an external action, a publication and a diagnostic have nowhere to
    go in a repository, even on a project that has one — the project still gives the
    ticket its name and its brief, but the work happens in a scratch directory
    and comes back into the page. A code ticket on a project without a
    repository has nothing to commit to either, and takes the road it always
    took.
    """
    if kind in WITHOUT_REPOSITORY and project.is_code:
        return replace(project, path=None)
    return project


def _word(value: object) -> str:
    return str(value or "").strip().lower()
