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

Reading the CI is also acting on it, within limits (`Checks.rework`). A ticket
in review whose checks have settled red, or whose pull request no longer
merges, is put back in ready with a comment that says what to do — the very
gesture that was made by hand on 3 November 2026 for 17 tickets out of 18. It
is done `review.ci_retries` times at most, and a counter in `ponos.db` keeps the
score; the next red blocks the ticket and asks. What is not the code's red is
left alone (billing, a base branch that is red itself), and so is a verdict not
yet in: a rework is only sent on checks that have stopped running, so a push
cannot be answered by a second rework before its own CI has spoken.
"""

from __future__ import annotations

import time
from typing import Any

from . import git, github_checks, question, state, store
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
APPEAR_SECONDS = github_checks.CHECKS_APPEAR_SECONDS

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


def stable(checks: list[dict[str, Any]]) -> bool:
    """Has every check of that list stopped running?"""
    return not any(str(one.get("bucket") or "") in RUNNING + ("",) for one in checks)


def link(url: str) -> str:
    """Where GitHub lists the pull request's checks."""
    return f"{url.rstrip('/')}/checks"


def read(
    row: dict[str, Any] | None, url: str, retries: int = 0, limit: int = 0
) -> dict[str, Any] | None:
    """What a card shows of a stored row: nothing when there is none worth drawing.

    `retries` is how many times the CI was handed back to a session, out of
    `limit`; the card says « CI retry n/5 » once it is not zero.
    """
    if not row or not row.get("state") or row.get("url") != url:
        return None
    return {
        "state": row["state"],
        "label": LABELS[row["state"]],
        "checks": row["checks"],
        "link": link(url),
        "retries": retries,
        "limit": limit,
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
        column = self.config.board.prop("ci")
        rows = state.ci_rows()
        following: set[str] = set()
        changed = 0
        for page in pages:
            ticket = Ticket(page)
            url = str(store.read(page, self.config.board.prop("pull_request")) or "")
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
            row = settle(before, url, head, github_checks.checks(url, self.config.github), now)
            state.keep_ci(ticket.id, row)
            if not self.dry_run:
                self.rework(ticket, url, row)
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

    def rework(self, ticket: Ticket, url: str, row: dict[str, Any]) -> bool:
        """Put the ticket back in ready when its pull request is for a session to repair.

        `row` is what has just been read. Two things call for it, and only on a
        verdict that is in: checks that have all stopped and one is red, or a
        pull request GitHub says no longer merges (a green CI does not excuse
        that one). The counter goes back to zero on a green, mergeable one.

        Not for a red that is not the code's — jobs GitHub never started (the
        account's billing above all), or the same checks red on the base too,
        said once on the card — nor for a closed pull request, nor while a
        session of this run is on the ticket. Past `review.ci_retries` the
        ticket is blocked (`ci.rework-exhausted`) with the choices of a failing
        CI, and the counter starts again for whoever answers. Returns whether
        the ticket was handed back.
        """
        accounts = self.config.github
        limit = self.config.review.ci_retries
        count, said_base = state.reworks().get(ticket.id, (0, False))
        red = row["state"] == FAILED and stable(row["checks"])
        if row["state"] == PENDING or (row["state"] == FAILED and not red):
            return False
        unmergeable = git.pull_request_unmergeable(url, accounts)
        if not red and not unmergeable:
            if row["state"] == PASSED and (count or said_base):
                state.keep_rework(ticket.id, 0, False)
            return False
        if ticket.id in self._claimed:
            return False
        failing = github_checks.failing_checks(url, accounts) if red else []
        if red and not unmergeable:
            if github_checks.unstarted_checks(url, accounts):
                return False
            _, base = git.pull_request_branches(url, accounts)
            held = set(failing) & set(github_checks.failing_on(url, base, accounts))
            if failing and held == set(failing):
                if not said_base:
                    voice = self.voice
                    self.say(f"  · {ticket.title} — CI red on {base} too, no retry")
                    state.keep_rework(ticket.id, count, True)
                    self._comment(
                        ticket,
                        voice.say("ci-base-red", base=base, names=", ".join(sorted(held))),
                    )
                return False
        if git.pull_request_state(url, accounts) != "OPEN":
            return False
        said = self.voice
        try:
            if count >= limit:
                self.say(f"  ✗ {ticket.title} — CI retries spent ({count}/{limit})")
                state.keep_rework(ticket.id, 0, False)
                self._fail(
                    ticket,
                    said.say("ci-rework-exhausted", limit=limit),
                    url,
                    code="ci.rework-exhausted",
                    blocked=True,
                    question=question.Question(
                        ask=said.say("ci-rework-exhausted-question", limit=limit, url=url),
                        why=said.say("ci-rework-exhausted", limit=limit),
                        category="ci",
                    ),
                )
                return False
            why = [said.say("ci-rework-red")] if red else []
            if unmergeable:
                why.append(said.say("ci-rework-conflict"))
            self._comment(
                ticket,
                said.say(
                    "ci-rework",
                    n=count + 1,
                    limit=limit,
                    why="; ".join(why),
                    url=url,
                    names=", ".join(failing) or said.say("ci-rework-none"),
                ),
            )
            self._set(
                ticket, **{self.config.board.prop("status"): self.config.board.state("ready")}
            )
        except store.Unreachable:
            raise
        except store.StoreError as error:
            self.say(f"    ! {ticket.title} was not handed back for its CI — {error}")
            return False
        state.keep_rework(ticket.id, count + 1, False)
        self.say(f"  ↻ {ticket.title} — back in ready for its CI ({count + 1}/{limit})")
        return True
