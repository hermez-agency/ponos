"""What kind of work a ticket is, decided before any of it is done.

For a long time the question answered itself: a ticket whose project had a
repository came back as a pull request, and every other one as a text in its
own page. Then tickets started asking for things that are neither — enter these
DNS records at the registrar, post this on LinkedIn, deploy that — and those do
not have the same road, nor the same way of going wrong. A pull request is read
before it is merged; a post, once it is out, is out.

So a ticket has a **type**, and there are four, told apart by the road they
take rather than by what they are about:

- `code` — a repository, a branch, a pull request;
- `writing` — no repository, the answer is written into the page;
- `external` — no repository either, the work is done somewhere else: in the
  browser, in a DNS zone, in the settings of a service. It stops at the first
  doubt, and its answer is the log of what it did;
- `publication` — something public and irreversible. Prepared first, sent to
  review, and only published once somebody has moved it to *Validated*.

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

The same answer carries a code ticket's sub-type — a bug, a feature, upkeep —
so that a ticket with neither costs one session and not two: see subtypes.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from . import subtypes
from .config import CONFIDENCES
from .projects import Project

KINDS = ("code", "writing", "external", "publication")

# From the least guarded road to the most. Choosing “the more careful” of two
# types is choosing the one further down this line: a publication waits for a
# human before anything goes out, an external action stops at its first doubt.
PRUDENCE = ("writing", "code", "external", "publication")

# The two that act on the world rather than on a branch or a page.
RISKY = ("external", "publication")

# Neither of these three is worked in a repository, whatever the project holds:
# what they produce does not go into one — nor does it ever ask for a commit.
WITHOUT_REPOSITORY = ("writing", "external", "publication")

# One JSON object. A session still thinking about it after two minutes is a
# session that misunderstood the question.
TIMEOUT_MINUTES = 2

PROMPT = """\
Below is a ticket that a runner is about to carry out on its own. Before it \
does, say what kind of ticket it is. Do not do the ticket, and do not open \
anything: read it and classify it.

The four types are told apart by how the work is carried out, not by its \
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

{{"type": "code|writing|external|publication", "reason": "one sentence, in the \
language the ticket is written in", "confidence": "low|medium|high", \
"alternative": "the other type you hesitated with, or an empty string", \
"subtype": "{subtypes}, or an empty string when the type is not code", \
"subtype_confidence": "low|medium|high"}}

A code ticket also has a sub-type, which says what kind of change it is:

{choices}
"""


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
    the four types comes back as no type at all, which `doubt` refuses.
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


def worked_in(project: Project, kind: str) -> Project:
    """The project as this type of ticket works in it: with its repository or not.

    A text, an external action and a publication have nowhere to go in a
    repository, even on a project that has one — the project still gives the
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
