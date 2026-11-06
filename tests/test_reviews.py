"""Which review comments of a pull request are work: the marks, the mention, the bots."""

from __future__ import annotations

from typing import Any

from support import case

from ponos import reviews
from ponos.github_issues import MARKER


def _comment(number: int, body: str, login: str = "salva", kind: str = "User", **more: Any) -> Any:
    return {
        "id": number,
        "body": body,
        "path": "a.py",
        "line": 4,
        "diff_hunk": "\n".join(f"line {n}" for n in range(10)),
        "user": {"login": login, "type": kind},
        **more,
    }


@case
def the_mention_opens_a_comment_and_nothing_else_does() -> None:
    assert reviews.mentions("@ponos fix this", "@ponos")
    assert reviews.mentions("  @Ponos, fix this", "@ponos")
    assert reviews.mentions("@ponos", "@ponos")
    assert not reviews.mentions("@ponos-ci look", "@ponos")
    assert not reviews.mentions("ask @ponos", "@ponos")
    assert not reviews.mentions("@ponos", "")


@case
def bots_and_the_runners_own_words_are_not_people() -> None:
    assert reviews.human(_comment(1, "ok"))
    assert not reviews.human(_comment(1, "ok", "copilot[bot]"))
    assert not reviews.human(_comment(1, "ok", "x", "Bot"))
    assert not reviews.human(_comment(1, f"{MARKER}\n@ponos done"))


@case
def a_review_requesting_changes_brings_its_line_comments_and_the_mention_wakes_alone() -> None:
    asked = {"id": 5, "state": "CHANGES_REQUESTED", "body": "", "user": {"login": "r"}}
    comments = [
        _comment(10, "rename", pull_request_review_id=5),
        _comment(11, "nice"),
        _comment(12, "@ponos use a constant"),
        _comment(13, "@ponos hidden", "dep[bot]", "Bot"),
        _comment(14, "old", pull_request_review_id=5, in_reply_to_id=10),
    ]
    found = reviews.collect([asked], comments, 0, 0, "@ponos")
    assert [one["id"] for one in found] == ["10", "12", "14"], found
    assert found[2]["root"] == 10 and found[0]["root"] == 10

    # Past the marks, nothing is read twice.
    assert reviews.collect([asked], comments, 5, 14, "@ponos") == []
    # A thread already waiting is not handed over again.
    assert [one["id"] for one in reviews.collect([asked], comments, 0, 0, "@ponos", {"10"})] == [
        "12",
        "14",
    ]


@case
def a_plain_review_is_not_a_request_but_its_body_can_mention() -> None:
    plain = {"id": 6, "state": "COMMENTED", "body": "looks good", "user": {"login": "r"}}
    asking = {"id": 7, "state": "COMMENTED", "body": "@ponos add tests", "user": {"login": "r"}}
    found = reviews.collect([plain, asking], [], 0, 0, "@ponos")
    assert [one["id"] for one in found] == ["review-7"] and found[0]["root"] == 0


@case
def the_session_replies_are_read_by_id_and_the_description_keeps_the_end_of_the_diff() -> None:
    said = "Done.\nREPLY 10: renamed\n`REPLY review-7: nothing to do`\nRESULT: ok — x"
    assert reviews.replies(said) == {"10": "renamed", "review-7": "nothing to do"}
    thread = reviews.collect([], [_comment(12, "@ponos go")], 0, 0, "@ponos")
    text = reviews.describe(thread)
    assert text.startswith("[12] @salva — a.py:4") and "line 9" in text and "line 2" not in text


@case
def an_address_is_split_into_repository_and_number() -> None:
    assert reviews.locate("https://github.com/o/r/pull/12") == ("o/r", 12)
    assert reviews.locate("https://example.com/x") is None
