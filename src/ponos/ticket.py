"""A ticket, and the work it becomes once a run has taken it on.

Two nouns and three readings of them, and nothing that does anything: this is
the bottom of the runner. Every module that does a piece of a run — claiming,
executing, delivering, answering — passes a `Ticket` or a `Job` to the next
one, so they have to live somewhere that none of those modules owns, or the
first one to import the second would be importing the whole run back.

`Ticket` is a page read the way a run reads it; `Job` is that ticket
once a run has decided where it will happen — which branch, which worktree,
which session, in whose voice — and is filled in as the run learns the rest.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import agents, goals, store
from .projects import Project


@dataclass
class Ticket:
    page: store.Page

    @property
    def id(self) -> str:
        return self.page.id.replace("-", "")

    @property
    def title(self) -> str:
        return self.page.title or "(untitled ticket)"

    @property
    def url(self) -> str:
        return self.page.url


@dataclass
class Job:
    ticket: Ticket
    project: Project
    branch: str
    base: str
    workdir: Path
    body: str = ""
    session_id: str = ""
    log: Path | None = None
    session_home: Path | None = None
    model: str = ""
    # Whether `model` was chosen by the runner rather than read off the ticket,
    # and whether that choice was one level up from a run that failed — see
    # models.py. Written into the run's journal, which is where the next
    # attempt reads them back.
    chosen: bool = False
    escalated: bool = False
    agent: agents.Agent = field(default_factory=agents.Agent)
    goal: goals.Goal = field(default_factory=goals.Goal)
    comments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    resumed: bool = False
    # The branch an interrupted worktree of this ticket was saved to, if one was.
    backup: str = ""
    # What the session is told when the project's setup command has run in its
    # worktree: that it has, and that it is not to install again.
    prepared: str = ""
    # Which of the four types the ticket was run as — see kinds.py — and the
    # repository it is not worked in but may read, when the type took it off
    # one. Both empty for a ticket run the way every ticket used to be.
    kind: str = ""
    reference: Path | None = None
    # What kind of change a code ticket is — see subtypes.py — "" for none.
    subtype: str = ""
    # The browser an external ticket acts in, once the run has chosen: "ponos"
    # for Ponos's own (browser.py), "" for Claude in Chrome as before.
    browser: str = ""
    # Whether `session_id` names a conversation Claude Code already has, to be
    # carried on rather than opened. Only ever true for a ticket that came back
    # ticked as waiting for credit — see `prepare`.
    resume: bool = False
    # The project's secrets, read from `[vault]` once per session and handed to
    # it as environment variables — see vault.py. Never written anywhere.
    secrets: dict[str, str] = field(default_factory=dict)
    # Which of them are the addresses of the vault's entries (`<NAME>_URL`):
    # given beside the keys, and no secret — see vault_store.addresses.
    addresses: list[str] = field(default_factory=list)
    # « Plan d'abord » — see planning.py. "propose" for a session that only
    # plans (and `plan` holds the one it amends, if any), "carry" for one that
    # carries out the plan approved in `plan`, with the `answer` that approved
    # it; "" for an ordinary session.
    planning: str = ""
    plan: str = ""
    answer: str = ""
    # What the self-review raised and what became of it, as the pull request
    # says it under the session's summary — see review.py. "" for nothing to say.
    review: str = ""
    # Whether the worktree was an earlier attempt's branch, picked up — which
    # makes its push a forced one. Kept on the job so that a session adopted
    # after a restart pushes the way the one that started it would have.
    reused: bool = False
    # The run this job writes into the local journal, once opened — see
    # journal.py — so that an adopted session goes on writing into the same one.
    run: int | None = None
    # Whether this job's session is the ticket's own — the one a restart
    # adopts and carries on (adoption.py) — and the session a runner before
    # this one started, when it is being carried on: a `session.Handle`, typed
    # loosely so that this module still depends on nothing.
    adoptable: bool = False
    adopted: object = None


def short_id(page_id: str) -> str:
    """Eight characters that actually tell two tickets apart.

    Page IDs are time-ordered: two tickets created the same day share a
    long *prefix*. Taking the first eight gave both of the first two tickets
    written for this tool the same short id — which would have had them fight
    over one scratch directory. The tail is where the entropy is.
    """
    return page_id.replace("-", "")[-8:]


def is_blank(body: str) -> bool:
    """A ticket body that says nothing, template headings included.

    A database template fills a new page with empty headings. They are not
    blank text, so they would travel into the prompt as noise and — worse —
    stop the "everything is in the title" fallback from firing on a ticket
    whose whole content is its title.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and set(stripped) != {"-"}:
            return False
    return True


def slugify(text: str, limit: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:limit].rstrip("-")) or "ticket"
