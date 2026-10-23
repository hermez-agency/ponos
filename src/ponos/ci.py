"""The state of a pull request's checks, kept beside the ticket that waits on it.

A ticket in review is a question asked of you, and whether the CI passes is the
first thing you look at before answering. It was one click away, on GitHub; here
it is on the card. Asked of GitHub by the runner, a pass at a time, and written
down in `ponos.db` — the board reads it with the list, so opening it asks GitHub
nothing, whatever the number of cards in review.

Three states, and a fourth that is not one: `pending`, `passed`, `failed`, and
nothing for a pull request without a single check. Nothing is not a green: a
repository with no CI has said nothing, and a badge saying « passed » on it
would be a promise nobody made. A red check wins over a running one — the
verdict is already known, and waiting for the rest of the jobs to finish before
saying it only delays the one thing worth knowing.

Followed while the ticket is in review and no longer: the day it is validated,
merged or done, the row goes, and so does the reading of it.

One red is not the code's at all: jobs GitHub refused to start because the
account's Actions billing failed (`billing`). It is read off the annotation
GitHub leaves on such a job, and it is a fact about an account, not about a
pull request — every repository of it says the same sentence, and saying it
ticket by ticket, in GitHub's English, was six tickets going round in circles
on one unpaid invoice.
"""

from __future__ import annotations

import time
from typing import Any

from . import git, state, store
from .base import Base
from .ticket import Ticket

PENDING, PASSED, FAILED = "pending", "passed", "failed"

# What the board's « CI » select says, in the words the ticket asked for.
LABELS = {PENDING: "en cours", PASSED: "réussi", FAILED: "erreur"}

# `gh pr checks` sorts every check into a bucket. A check that was cancelled or
# that timed out is a check that did not pass, so it is read as red.
RED = ("fail", "cancel")
RUNNING = ("pending",)

# How long before a pull request is asked again: often while something runs,
# rarely once it has settled — then it is only to catch a push.
RUNNING_SECONDS = 30
SETTLED_SECONDS = 300

# After a push, GitHub registers the new checks a few seconds late; until then
# the commit has none, and reading that as a repository without CI would erase
# the very state a push is meant to set back to running.
APPEAR_SECONDS = git.CHECKS_APPEAR_SECONDS

# What GitHub writes on a job it never started for the account's billing: a
# payment that failed, or a spending limit reached. Lower case, as `billing`
# compares them.
BILLING = ("recent account payments have failed", "spending limit needs to be increased")


def deduce(checks: list[dict[str, Any]]) -> str:
    """`pending`, `passed`, `failed` — or nothing when the pull request has no check."""
    buckets = [str(one.get("bucket") or "") for one in checks]
    if not buckets:
        return ""
    if any(bucket in RED for bucket in buckets):
        return FAILED
    if any(bucket in RUNNING or not bucket for bucket in buckets):
        return PENDING
    return PASSED


def billing(reason: str) -> bool:
    """Is that annotation GitHub refusing a job for the account's billing?"""
    said = reason.lower()
    return any(fragment in said for fragment in BILLING)


def link(url: str) -> str:
    """Where GitHub lists the pull request's checks."""
    return f"{url.rstrip('/')}/checks"


def read(row: dict[str, Any] | None, url: str) -> dict[str, Any] | None:
    """What a card shows of a stored row: nothing when there is none worth drawing."""
    if not row or not row.get("state") or row.get("url") != url:
        return None
    return {
        "state": row["state"],
        "label": LABELS[row["state"]],
        "checks": row["checks"],
        "link": link(url),
    }


def settle(
    row: dict[str, Any] | None, url: str, head: str, checks: list[dict[str, Any]], now: float
) -> dict[str, Any]:
    """The row after reading `checks` of the commit `head`.

    A head that is not the one last read is a push: the state goes back to
    running at once and stays there while the new commit has no check yet.
    """
    known = row if row and row.get("url") == url else None
    pushed = bool(known and known["head"] and known["head"] != head)
    since = now if pushed or not known else known["since"]
    state_now = deduce(checks)
    if not checks and known and known["state"] and (pushed or now - since < APPEAR_SECONDS):
        state_now = PENDING
    return {
        "url": url,
        "head": head,
        "state": state_now,
        "checks": [
            {key: str(one.get(key) or "") for key in ("name", "bucket", "link")} for one in checks
        ],
        "since": since,
        "asked": now,
    }


def due(row: dict[str, Any] | None, url: str, now: float) -> bool:
    """Is it time to ask GitHub again about that pull request?"""
    if not row or row.get("url") != url:
        return True
    wait = RUNNING_SECONDS if row["state"] in ("", PENDING) else SETTLED_SECONDS
    return bool(now - row["asked"] >= wait)


class Checks(Base):
    """The pull requests in review, followed for their CI."""

    def follow_ci(self, pages: list[store.Page]) -> int:
        """Read the checks of the pull requests of those tickets, which are in review.

        Called with the pages `close_merged` has just read, so it asks the board
        nothing of its own. Returns how many cards changed state.
        """
        column = self.config.notion.prop("ci")
        rows = state.ci_rows()
        following: set[str] = set()
        changed = 0
        for page in pages:
            ticket = Ticket(page)
            url = str(store.read(page, self.config.notion.prop("pull_request")) or "")
            if not url.startswith("http"):
                continue
            following.add(ticket.id)
            now = time.time()
            before = rows.get(ticket.id)
            if not due(before, url, now):
                continue
            head = git.pull_request_head(url, self.config.github)
            if not head:
                continue
            row = settle(before, url, head, git.checks(url, self.config.github), now)
            state.keep_ci(ticket.id, row)
            label = LABELS.get(row["state"], "")
            if row["state"] != (before or {}).get("state", ""):
                changed += 1
            if self.dry_run or str(store.read(page, column) or "") == label:
                continue
            try:
                self.client.update(self.database, page.id, {column: label})
            except store.StoreError as error:
                self.say(f"    ! the CI of {ticket.title} was not written — {error}")
        state.drop_ci(set(rows) - following)
        return changed
