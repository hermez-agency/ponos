"""`ci.py`: a ticket in review whose CI is red, or that conflicts, is handed back to a session."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from support import _board_runner, _reviewed, case

from ponos import ci, github_checks, state
from ponos import config as C
from ponos import git as git_module

URL = "https://github.com/x/y/pull/7"
STATUS = {"review": "review", "done": "done", "ready": "ready", "blocked": "blocked"}


def _checks(*buckets: str) -> list[dict[str, Any]]:
    return [
        {"name": f"job-{number}", "bucket": bucket, "link": f"https://ci/{number}"}
        for number, bucket in enumerate(buckets)
    ]


@contextlib.contextmanager
def _github_says(
    checks: list[dict[str, Any]],
    *,
    head: str = "aaa",
    unmergeable: bool = False,
    base_red: list[str] | None = None,
    unstarted: str = "",
    pull_request: str = "OPEN",
) -> Iterator[None]:
    """`gh`, replaced by what it would say about one pull request in review."""
    names = ("pull_request_head", "pull_request_unmergeable", "pull_request_state")
    saved = [getattr(git_module, name) for name in names]
    others = (
        git_module.pull_request_branches,
        github_checks.checks,
        github_checks.failing_on,
        github_checks.unstarted_checks,
    )
    git_module.pull_request_head = lambda url, accounts=None: head
    git_module.pull_request_unmergeable = lambda url, accounts=None: unmergeable
    git_module.pull_request_state = lambda url, accounts=None: pull_request
    git_module.pull_request_branches = lambda url, accounts=None: ("ticket/x", "main")
    github_checks.checks = lambda url, accounts=None, timeout=60: checks
    github_checks.failing_on = lambda url, base, accounts=None: base_red or []
    github_checks.unstarted_checks = lambda url, accounts=None: unstarted
    try:
        yield
    finally:
        for name, original in zip(names, saved, strict=True):
            setattr(git_module, name, original)
        (
            git_module.pull_request_branches,
            github_checks.checks,
            github_checks.failing_on,
            github_checks.unstarted_checks,
        ) = others


def _pass(runner: Any, checks: list[dict[str, Any]], **says: Any) -> Any:
    """One reading of the board's reviews, as the pass makes it."""
    state.drop_ci({"pticket"})  # due again: the checks are asked for, whatever was read before
    with _github_says(checks, **says):
        return runner.follow_ci([_reviewed("pticket", "review", URL)])


def _runner() -> Any:
    runner = _board_runner([_reviewed("pticket", "review", URL)], STATUS)
    runner.config.review = C.Review(ci_retries=5)
    return runner


def _statuses(runner: Any) -> list[str]:
    return [values["statut"] for _, values in runner.client.written if "statut" in values]


@case
def a_red_ci_puts_the_ticket_back_in_ready_with_the_instruction(state_home: object) -> None:
    runner = _runner()
    _pass(runner, _checks("pass", "fail"))
    assert _statuses(runner) == ["ready"], runner.client.written
    said = runner.client.comments_written[-1]
    assert "1/5" in said and "job-1" in said and URL in said
    for word in ("gh run view --log-failed", "Rebase", "pull request"):
        assert word.lower() in said.lower(), word
    assert state.reworks()["pticket"] == (1, False)


@case
def a_ci_still_running_is_not_a_verdict(state_home: object) -> None:
    runner = _runner()
    _pass(runner, _checks("pending", "fail"))
    _pass(runner, _checks("pending"))
    assert _statuses(runner) == [] and state.reworks() == {}


@case
def a_ci_red_five_times_is_retried_five_times_then_the_ticket_is_blocked(
    state_home: object,
) -> None:
    runner = _runner()
    for attempt in range(1, 6):
        _pass(runner, _checks("fail"), head=f"head-{attempt}")
        assert state.reworks()["pticket"][0] == attempt
    assert _statuses(runner) == ["ready"] * 5
    _pass(runner, _checks("fail"), head="head-6")
    assert _statuses(runner) == ["ready"] * 5 + ["blocked"], runner.client.written
    assert any(
        values.get(runner.config.board.prop("block")) == "ci.rework-exhausted"
        for _, values in runner.client.written
    ), runner.client.written
    # The counter starts again for whoever answers the question.
    assert state.reworks() == {}
    from ponos import decisions

    assert decisions.DEFAULTS["ci"] == ("retry", "instruct", "model", "abandon")


@case
def a_green_ci_resets_the_counter(state_home: object) -> None:
    runner = _runner()
    _pass(runner, _checks("fail"))
    assert state.reworks()["pticket"][0] == 1
    _pass(runner, _checks("pass"), head="bbb")
    assert state.reworks() == {}


@case
def a_red_that_is_not_the_codes_is_left_alone(state_home: object) -> None:
    runner = _runner()
    _pass(
        runner,
        _checks("fail"),
        unstarted="The job was not started because recent account payments have failed",
    )
    assert _statuses(runner) == [] and state.reworks() == {}
    # The base branch is red on the same job: waiting, and said once on the card.
    _pass(runner, _checks("pass", "fail"), base_red=["job-1"])
    _pass(runner, _checks("pass", "fail"), base_red=["job-1"])
    assert _statuses(runner) == []
    assert len(runner.client.comments_written) == 1 and "main" in runner.client.comments_written[0]
    assert state.reworks() == {"pticket": (0, True)}
    # The base is green again: the red is the pull request's own.
    _pass(runner, _checks("pass", "fail"))
    assert _statuses(runner) == ["ready"] and state.reworks() == {"pticket": (1, False)}


@case
def a_conflicting_pull_request_is_taken_back_even_with_a_green_ci(state_home: object) -> None:
    runner = _runner()
    _pass(runner, _checks("pass"), unmergeable=True)
    assert _statuses(runner) == ["ready"]
    assert state.reworks()["pticket"][0] == 1
    # A conflict does not wait on the base's CI, and a green one does not clear its count.
    _pass(runner, _checks("pass"), unmergeable=True, base_red=["job-0"], head="bbb")
    assert state.reworks()["pticket"][0] == 2


@case
def nothing_is_taken_back_that_is_closed_or_already_in_a_session(state_home: object) -> None:
    runner = _runner()
    _pass(runner, _checks("fail"), pull_request="CLOSED")
    runner._claimed.add("pticket")
    _pass(runner, _checks("fail"))
    assert _statuses(runner) == [] and state.reworks() == {}


@case
def the_limit_is_read_from_the_review_table_and_zero_never_retries(state_home: object) -> None:
    assert C.Review().ci_retries == 5
    runner = _runner()
    runner.config.review = C.Review(ci_retries=0)
    _pass(runner, _checks("fail"))
    assert _statuses(runner) == ["blocked"]


@case
def the_card_says_how_many_retries_were_spent(state_home: object) -> None:
    row = {"url": URL, "state": "failed", "checks": [], "head": "a", "since": 0, "asked": 0}
    card = ci.read(row, URL, 2, 5)
    assert card is not None and (card["retries"], card["limit"]) == (2, 5)
