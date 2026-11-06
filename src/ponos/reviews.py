"""A pull request reviewed on GitHub, taken as work.

A remark on the code of a pull request used to be said at the ticket: back to
the console, « resend with an instruction », and a session that copied the
remark by hand without the line of code it was about. A reviewer who lives in
GitHub now speaks where the diff is, and the ticket in review hears it.

Two things wake a ticket, and nothing else does: a review that **requests
changes**, and a comment — a line comment, or the body of a review — that
**opens on the mention** (`@ponos`, `runner.pr_review_mention`). A comment of a
bot never does, and neither does one of the runner's own, which is told by the
hidden marker it opens on and not by its author: it writes under the account of
whoever installed it, so the login says nothing. The runner answering in a
thread therefore never wakes itself.

Waking is `ci.rework`'s gesture: the ticket goes back to ready with a comment,
and the session resumes on the branch the pull request already has (the branch
is named after the ticket, `git.ticket_branch`). What differs is the weight of
what is handed over. A ticket's discussion is read under a budget of a few
hundred characters a line, which a diff excerpt would blow; the comments are
kept in `ponos.db` with the threads they came from, and read from there into the
prompt (`brief`).

What has been read is a mark, not a log: the id of the last review and of the
last line comment seen. The first reading of a pull request only sets the marks
— comments written before the runner looked are not requests it should answer
weeks later — and a reading that wakes nothing still moves them, so that a
remark that was not a request is not re-read at every pass. GitHub numbers
comments in the order they were written, and that is all the order this needs.

The session is told to end its report with a `REPLY <id>: …` line per thread.
They are posted once the work is delivered, or once it said why there was none
(`answer`); a thread the session did not answer gets a plain line of the
runner's own, so that nobody is left without one.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Collection
from typing import Any

from . import git, state, store
from .base import Base
from .ticket import Ticket

# How often a ticket's pull request is asked about its reviews. A reviewer is
# not waiting on the second, and each reading is three requests.
INTERVAL_SECONDS = 60
PAGE = 100
PAGES = 5
# What one pass hands to a session, and how much of the diff comes with a comment.
MOST_THREADS = 20
HUNK_LINES = 6
HUNK_CHARS = 700
BODY_CHARS = 1500

_PR_URL = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")
_REPLY = re.compile(r"^\W*REPLY\s+#?([\w-]+)\s*[:：\-—]+\s*(.+?)\s*$", re.IGNORECASE)


def locate(url: str) -> tuple[str, int] | None:
    """`owner/name` and the number of a pull request address, or None."""
    found = _PR_URL.search(url)
    return (found.group(1), int(found.group(2))) if found else None


# What a comment of the runner's starts with: invisible on GitHub, and the only
# way to tell its words from those of the account it writes under — which is,
# more often than not, yours.
MARKER = "<!-- ponos -->"


def human(item: dict[str, Any]) -> bool:
    """Was this review or comment written by a person — not a bot, not the runner?"""
    user = item.get("user") or {}
    login = str(user.get("login") or "")
    if str(user.get("type") or "").lower() == "bot" or login.endswith("[bot]"):
        return False
    return MARKER not in str(item.get("body") or "")


def mentions(body: object, word: str) -> bool:
    """Does the text open on the mention — `@ponos fix this`, not `@ponos-ci` or `x @ponos`?"""
    said = str(body or "").lstrip().lower()
    word = word.strip().lower()
    if not word or not said.startswith(word):
        return False
    after = said[len(word) :][:1]
    return not (after.isalnum() or after in ("-", "_"))


def read_all(path: str, accounts: git.Accounts | None, url: str) -> list[dict[str, Any]] | None:
    """Every page of a list of the REST API — None when GitHub could not be asked."""
    if not shutil.which("gh"):
        return None
    found: list[dict[str, Any]] = []
    for page in range(1, PAGES + 1):
        result = git.run(
            ["gh", "api", f"{path}?per_page={PAGE}&page={page}"],
            timeout=60,
            token=git.token_for(url, accounts),
        )
        if not result.ok:
            return None
        try:
            listed = json.loads(result.out or "[]")
        except ValueError:
            return None
        if not isinstance(listed, list):
            return None
        found += [one for one in listed if isinstance(one, dict)]
        if len(listed) < PAGE:
            break
    return found


def fetch(
    url: str, accounts: git.Accounts | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """The reviews and the line comments of that pull request, or None."""
    where = locate(url)
    if not where:
        return None
    base = f"repos/{where[0]}/pulls/{where[1]}"
    reviews = read_all(f"{base}/reviews", accounts, url)
    comments = read_all(f"{base}/comments", accounts, url) if reviews is not None else None
    if reviews is None or comments is None:
        return None
    return reviews, comments


def _hunk(text: object) -> str:
    """The end of a diff hunk: the lines the comment is about sit last."""
    lines = str(text or "").splitlines()[-HUNK_LINES:]
    return "\n".join(lines)[-HUNK_CHARS:]


def collect(
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    review_mark: int,
    comment_mark: int,
    mention: str,
    known: Collection[str] = (),
) -> list[dict[str, Any]]:
    """The threads a ticket owes work to since the marks, oldest first.

    A thread is `{id, root, path, line, author, body, hunk, state}`: `id` is what
    the session answers by, `root` the comment a reply is posted under (0 for a
    review's own body, answered at the foot of the pull request).
    """
    wanted: dict[str, dict[str, Any]] = {}
    requested = {
        int(one["id"])
        for one in reviews
        if int(one.get("id") or 0) > review_mark
        and str(one.get("state") or "").upper() == "CHANGES_REQUESTED"
        and human(one)
    }
    for review in reviews:
        number = int(review.get("id") or 0)
        if number <= review_mark or not human(review):
            continue
        said = str(review.get("body") or "").strip()
        asked = str(review.get("state") or "").upper() == "CHANGES_REQUESTED"
        if said and (asked or mentions(said, mention)):
            wanted[f"review-{number}"] = {
                "id": f"review-{number}",
                "root": 0,
                "path": "",
                "line": 0,
                "author": str((review.get("user") or {}).get("login") or ""),
                "body": said[:BODY_CHARS],
                "hunk": "",
                "state": "changes requested" if asked else "mention",
            }
    for comment in comments:
        number = int(comment.get("id") or 0)
        if not human(comment):
            continue
        by_review = int(comment.get("pull_request_review_id") or 0) in requested
        by_mention = number > comment_mark and mentions(comment.get("body"), mention)
        if not (by_review or by_mention):
            continue
        root = int(comment.get("in_reply_to_id") or 0) or number
        wanted[str(number)] = {
            "id": str(number),
            "root": root,
            "path": str(comment.get("path") or ""),
            "line": int(comment.get("line") or comment.get("original_line") or 0),
            "author": str((comment.get("user") or {}).get("login") or ""),
            "body": str(comment.get("body") or "").strip()[:BODY_CHARS],
            "hunk": _hunk(comment.get("diff_hunk")),
            "state": "changes requested" if by_review else "mention",
        }

    def order(thread: dict[str, Any]) -> tuple[int, int]:
        text = thread["id"]
        return (1, int(text.split("-")[-1])) if text.startswith("review-") else (0, int(text))

    return [one for one in sorted(wanted.values(), key=order) if one["id"] not in known]


def describe(threads: list[dict[str, Any]]) -> str:
    """The threads as a session reads them: id, author, place, diff, then the words."""
    parts: list[str] = []
    for thread in threads[:MOST_THREADS]:
        place = f" — {thread['path']}:{thread['line']}" if thread["path"] else " — (the review)"
        block = [f"[{thread['id']}] @{thread['author']}{place}"]
        if thread["hunk"]:
            block.append("```diff\n" + thread["hunk"] + "\n```")
        block.append(thread["body"])
        parts.append("\n".join(block))
    if len(threads) > MOST_THREADS:
        parts.append(f"(and {len(threads) - MOST_THREADS} more on the pull request)")
    return "\n\n".join(parts)


def replies(answer: str) -> dict[str, str]:
    """The `REPLY <id>: …` lines of a session's report, by id."""
    found: dict[str, str] = {}
    for line in (answer or "").splitlines():
        matched = _REPLY.match(line.replace("`", ""))
        if matched:
            found[matched.group(1)] = matched.group(2)
    return found


def post(url: str, thread: dict[str, Any], text: str, accounts: git.Accounts | None) -> str:
    """Write one line in a thread of the pull request — "" when it went, else why not."""
    where = locate(url)
    if not where or not shutil.which("gh"):
        return "gh not found"
    body = f"{MARKER}\n{text}"
    token = git.token_for(url, accounts)
    if thread["root"]:
        result = git.run(
            [
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{where[0]}/pulls/{where[1]}/comments/{thread['root']}/replies",
                "-f",
                f"body={body}",
            ],
            timeout=60,
            token=token,
        )
    else:
        result = git.run(["gh", "pr", "comment", url, "--body", body], timeout=60, token=token)
    return "" if result.ok else (result.err or result.out or "gh failed")


class Reviews(Base):
    """The tickets in review, listened to for what GitHub's reviewers say."""

    def follow_reviews(self, pages: list[store.Page]) -> int:
        """Hand back the tickets of those pages whose pull request was reviewed.

        Called with the pages `close_merged` has just read, as `follow_ci` is,
        so it asks the board nothing. Returns how many tickets went back to
        ready.
        """
        runner = self.config.runner
        if self.dry_run or not runner.pr_review_comments:
            return 0
        column = self.config.notion.prop("pull_request")
        handed = 0
        for page in pages:
            ticket = Ticket(page)
            url = str(store.read(page, column) or "")
            if not url.startswith("http") or ticket.id in self._claimed:
                continue
            row = state.review_row(ticket.id)
            now = time.time()
            if row and row["url"] == url and now - row["asked"] < INTERVAL_SECONDS:
                continue
            seen = fetch(url, self.config.github)
            if seen is None:
                continue
            reviews, comments = seen
            marks = {
                "review_id": max([int(one.get("id") or 0) for one in reviews] or [0]),
                "comment_id": max([int(one.get("id") or 0) for one in comments] or [0]),
            }
            if not row or row["url"] != url:
                # The first reading only sets the marks — see the docstring.
                state.keep_review(
                    ticket.id, {"url": url, "asked": now, "pending": [], "brief": "", **marks}
                )
                continue
            kept = {**row, "asked": now}
            if marks["review_id"] > row["review_id"] or marks["comment_id"] > row["comment_id"]:
                kept.update(
                    review_id=max(row["review_id"], marks["review_id"]),
                    comment_id=max(row["comment_id"], marks["comment_id"]),
                )
            threads = collect(
                reviews,
                comments,
                row["review_id"],
                row["comment_id"],
                runner.pr_review_mention,
                {str(one["id"]) for one in row["pending"]},
            )
            if not threads:
                state.keep_review(ticket.id, kept)
                continue
            if git.pull_request_state(url, self.config.github) != "OPEN":
                state.keep_review(ticket.id, kept)
                continue
            if self._hand_back(ticket, url, row, kept, threads):
                handed += 1
        return handed

    def _hand_back(
        self,
        ticket: Ticket,
        url: str,
        before: dict[str, Any],
        kept: dict[str, Any],
        threads: list[dict[str, Any]],
    ) -> bool:
        """Put the ticket back in ready with these threads for its next session."""
        said = self.voice
        everything = [*before["pending"], *threads]
        brief = said.say("pr-review-brief", url=url, threads=describe(everything))
        who = ", ".join(sorted({f"@{one['author']}" for one in threads}))
        # The marks and the brief first: a ticket that went back to ready without
        # them would run again with nothing to say. Undone if the board refuses.
        state.keep_review(ticket.id, {**kept, "pending": everything, "brief": brief})
        try:
            self._comment(ticket, said.say("pr-review-handback", n=len(threads), who=who, url=url))
            self._set(
                ticket, **{self.config.notion.prop("status"): self.config.notion.state("ready")}
            )
        except store.Unreachable:
            state.keep_review(ticket.id, before)
            raise
        except store.StoreError as error:
            state.keep_review(ticket.id, before)
            self.say(f"    ! {ticket.title} was not handed back for its review — {error}")
            return False
        self.say(f"  ↻ {ticket.title} — back in ready, {len(threads)} review comment(s) on GitHub")
        return True

    def review_brief(self, ticket: Ticket) -> str:
        """The review comments a session of that ticket is to address, or ""."""
        row = state.review_row(ticket.id)
        return str(row["brief"]) if row and row["pending"] else ""

    def answer_reviews(self, ticket: Ticket, answer: str, *, changed: bool, why: str = "") -> int:
        """Answer in every thread the ticket owes one to, once; returns how many were posted.

        `answer` is the session's report, where its `REPLY` lines are; a thread
        without one gets the runner's own line — done when `changed`, otherwise
        `why` nothing was. Never raises: a reply that GitHub refused is said in
        the journal and is not a reason to fail work that is delivered.
        """
        row = state.review_row(ticket.id)
        if not row or not row["pending"] or self.dry_run:
            return 0
        said = self.voice
        written = replies(answer)
        posted = 0
        left: list[dict[str, Any]] = []
        for thread in row["pending"]:
            fallback = (
                said.say("pr-review-reply-done")
                if changed
                else said.say("pr-review-reply-none", why=why or "-")
            )
            text = written.get(str(thread["id"])) or fallback
            failure = post(row["url"], thread, text, self.config.github)
            if failure:
                self.say(f"    ! {ticket.title} — reply to {thread['id']} not posted: {failure}")
                left.append(thread)
            else:
                posted += 1
        state.keep_review(
            ticket.id, {**row, "pending": left, "brief": row["brief"] if left else ""}
        )
        if posted:
            self.say(f"    · {posted} reply(ies) posted on the pull request")
        return posted
