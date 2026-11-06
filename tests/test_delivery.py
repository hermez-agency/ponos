"""`delivery.py`: the validated column — merging, publishing, closing."""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from support import (
    _board_runner,
    _BoardClient,
    _closing,
    _config,
    _git_answering,
    _github,
    _in_progress,
    _reviewed,
    _state_home,
    case,
)

from ponos import channels, github_checks, notion, projects, session, state, voice
from ponos import git as git_module
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import tickets as web_tickets

# -- a merged pull request closes its ticket ---------------------------------


def _client(runner: Runner) -> _BoardClient:
    """The fake board `_board_runner` gave the runner, to read and move what it holds."""
    return cast(_BoardClient, runner.client)


@case
def a_merged_pull_request_moves_its_ticket_to_done() -> None:
    client, closed = _closing(
        [
            _reviewed("p-merged", "review", "https://github.com/x/y/pull/1"),
            _reviewed("p-open", "review", "https://github.com/x/y/pull/2"),
            _reviewed("p-ready", "Not started", None),
        ],
        {"https://github.com/x/y/pull/1": "MERGED", "https://github.com/x/y/pull/2": "OPEN"},
        {"review": "review", "done": "done"},
    )
    assert closed == 1
    assert client.written == [("p-merged", {"statut": "done"})]
    assert client.comments_written[0] == ("✅ Merged — PR #1\nhttps://github.com/x/y/pull/1")


def _checks(*buckets: str) -> list[dict[str, Any]]:
    return [
        {"name": f"job-{number}", "bucket": bucket, "link": f"https://ci/{number}"}
        for number, bucket in enumerate(buckets)
    ]


@case
def the_three_states_of_the_ci_are_deduced_from_the_checks() -> None:
    from ponos import ci

    assert ci.deduce(_checks("pass", "pass")) == "passed"
    assert ci.deduce(_checks("pass", "skipping")) == "passed"
    assert ci.deduce(_checks("pass", "pending")) == "pending"
    assert ci.deduce(_checks("fail", "pass")) == "failed"
    assert ci.deduce(_checks("cancel", "pass")) == "failed"
    # The verdict is known as soon as one is red, whatever is still running.
    assert ci.deduce(_checks("pending", "fail")) == "failed"
    # No check is no CI: never a green.
    assert ci.deduce([]) == ""
    assert ci.read({"state": "", "url": "u", "checks": []}, "u") is None


@case
def a_push_puts_the_ci_back_to_running_until_the_new_checks_are_in() -> None:
    from ponos import ci

    url = "https://github.com/x/y/pull/1"
    green = ci.settle(None, url, "aaa", _checks("pass"), 1000.0)
    assert green["state"] == "passed" and green["head"] == "aaa"
    # Same commit, same checks: nothing moves, and the date of the head stays.
    again = ci.settle(green, url, "aaa", _checks("pass"), 1400.0)
    assert again["state"] == "passed" and again["since"] == 1000.0
    # A new head whose checks are not registered yet is still running.
    pushed = ci.settle(again, url, "bbb", [], 1500.0)
    assert pushed["state"] == "pending" and pushed["since"] == 1500.0
    # A repository that never had a check says nothing, at the first reading and after.
    assert ci.settle(None, url, "aaa", [], 1000.0)["state"] == ""
    # And a pull request that answers with nothing for good is not kept pending.
    assert ci.settle(pushed, url, "bbb", [], 1500.0 + ci.APPEAR_SECONDS)["state"] == ""


@case
def the_ci_is_asked_again_often_while_it_runs_and_rarely_once_it_has_settled() -> None:
    from ponos import ci

    url = "u"
    running = {"url": url, "state": "pending", "asked": 1000.0}
    settled = {"url": url, "state": "passed", "asked": 1000.0}
    assert ci.due(None, url, 1000.0) and ci.due({**running, "url": "other"}, url, 1000.0)
    assert not ci.due(running, url, 1000.0 + ci.RUNNING_SECONDS - 1)
    assert ci.due(running, url, 1000.0 + ci.RUNNING_SECONDS)
    assert not ci.due(settled, url, 1000.0 + ci.RUNNING_SECONDS)
    assert ci.due(settled, url, 1000.0 + ci.SETTLED_SECONDS)


@case
def a_ticket_in_review_carries_its_ci_on_the_board_and_stops_when_it_leaves(
    state_home: Path,
) -> None:

    url = "https://github.com/x/y/pull/2"
    runner = _board_runner(
        [_reviewed("p-open", "review", url)], {"review": "review", "done": "done"}
    )
    asked: list[str] = []
    head, listed = git_module.pull_request_head, github_checks.checks
    git_module.pull_request_head = lambda url, accounts=None: "aaa"

    def checks(
        url: str, accounts: dict[str, str] | None = None, timeout: int = 60
    ) -> list[dict[str, Any]]:
        asked.append(url)
        return _checks("pass", "pending")

    github_checks.checks = checks
    try:
        with _github({url: "OPEN"}):
            git_module.pull_request_head = lambda url, accounts=None: "aaa"
            runner.close_merged()
        # Written to the board, and kept for the list to read without GitHub.
        assert _client(runner).written == [("p-open", {"CI": "en cours"})], _client(runner).written
        cards: list[dict[str, Any]] = [{"id": "popen", "column": "review", "pull_request": url}]
        web_tickets._checks(cards)
        assert cards[0]["ci"]["state"] == "pending" and len(cards[0]["ci"]["checks"]) == 2
        assert cards[0]["ci"]["link"] == url + "/checks"
        # Asked again at once: not due, so GitHub is not.
        with _github({url: "OPEN"}):
            git_module.pull_request_head = lambda url, accounts=None: "aaa"
            runner.close_merged()
        assert asked == [url]
        # Out of review: no longer followed, no longer drawn.
        _client(runner).written.clear()
        runner.follow_ci([])
        assert state.ci_rows() == {}
        cards = [{"id": "popen", "column": "validated", "pull_request": url}]
        web_tickets._checks(cards)
        assert cards[0]["ci"] is None
    finally:
        git_module.pull_request_head, github_checks.checks = head, listed


@case
def a_ticket_in_progress_carries_the_phase_it_is_in_and_drops_it_when_it_leaves(
    state_home: Path,
) -> None:
    """A ticket waiting for its CI says so on its card, not « starting… » for an hour."""
    url = "https://github.com/x/y/pull/371"
    runner = _board_runner([], {"review": "review", "done": "done"})
    ticket = ticket_module.Ticket(_reviewed("p-wait", "ready", ""))
    settings = runner.config.notion
    runner._write(ticket, {settings.prop("status"): settings.state("running")})
    assert state.phases()["pwait"][0] == "starting", state.phases()

    with _git_answering(wait_for_checks=lambda *args, **kwargs: "passed"):
        assert runner._checked(ticket, url, Path("/work"), "main")[0] == "passed"
    cards: list[dict[str, Any]] = [
        {"id": "pwait", "column": "running"},
        {"id": "pwait", "column": "review"},
    ]
    web_tickets._phases(cards)
    assert cards[0]["phase"]["key"] == "checks" and cards[0]["phase"]["detail"] == url
    assert cards[0]["phase"]["since"], cards[0]
    # Only a card in progress is going through anything.
    assert cards[1]["phase"] is None

    runner._write(ticket, {settings.prop("status"): settings.state("review")})
    assert state.phases() == {}


@case
def a_board_told_to_answer_in_french_is_answered_in_french() -> None:
    """The whole point of the setting, checked where it is actually read.

    `runner.language` is a line of a file; what it has to change is the sentence
    written under a ticket, and nothing in between is worth checking on its own.
    """
    runner = _board_runner(
        [_reviewed("p-merged", "review", "https://github.com/x/y/pull/1")],
        {"review": "review", "done": "done"},
    )
    runner.config.runner.language = "FR"
    with _github({"https://github.com/x/y/pull/1": "MERGED"}):
        assert runner.close_merged() == 1
    said = _client(runner).comments_written[0]
    assert said.startswith("✅ Fusionnée — PR #1"), said
    assert "https://github.com/x/y/pull/1" in said


@case
def a_stuck_ticket_in_french_is_stuck_in_french_from_the_first_line_to_the_phone() -> None:
    """The comment that asked for the setting: a French question wrapped in
    three English sentences. Every line of it comes out of `voice`, and so does
    the message that reaches the phone."""
    runner = _board_runner([_reviewed("p-stuck", "progress", None)], {"blocked": "blocked"})
    runner.config.runner.language = "fr"
    runner.config.notify = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    ).notify
    said = runner.voice
    ticket = ticket_module.Ticket(_client(runner)._pages[0])
    sent: list[str] = []
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)  # type: ignore[assignment]  # a double: what reaches the phone is kept
    try:
        runner._fail(
            ticket,
            said.say("asked-something"),
            code="session.question",
            blocked=True,
            question="Audit déjà livré et validé : on le refait ?",
            note=said.say("trace-in-page"),
        )
    finally:
        channels.announce = original
    comment = _client(runner).comments_written[0]
    assert comment == "🙋 Bloqué\nAudit déjà livré et validé : on le refait ?", comment
    assert sent and sent[0].startswith("🙋 Bloqué · p-stuck"), sent
    english = voice.Voice("en")
    for key in ("verdict-blocked", "yes-or-no", "trace-in-page"):
        assert english.say(key) not in comment + sent[0], key
    # The folded block and the session's footer, said the same way.
    assert said.count(130, "step") + " · " + said.minutes(19 * 60) == "130 étapes · 19 minutes"
    assert said.minutes(20.0) == "moins d'une minute"
    assert said.trace("claude --resume abc", "/tmp/log").startswith("Pour reprendre la session")


# -- validating is the gesture the runner acts on ----------------------------


def _validating(
    pages: list[notion.Page],
    states: dict[str, str],
    status: dict[str, str],
    *,
    options: list[str] | None = None,
    refuses: str = "",
) -> tuple[_BoardClient, list[tuple[str, str]], list[str], list[dict[str, Any]]]:
    """Run `deliver` against a fake board, a fake GitHub, and no session."""

    runner = _board_runner(pages, status, options)
    merges: list[tuple[str, str]] = []
    published: list[str] = []

    def merge(url: str, method: str = "squash", accounts: Any = None) -> str:
        merges.append((url, method))
        if refuses:
            raise git_module.GitError(refuses)
        return "merged"

    # Publishing runs a Claude session, which is the one thing these tests do
    # not do: what is checked here is that a ticket with no pull request goes
    # down that road at all.
    runner._publish = lambda ticket, project: published.append(ticket.id)  # type: ignore[method-assign, misc, assignment]  # a double: no session
    with _github(states, merge=merge):
        return _client(runner), merges, published, runner.deliver()


@case
def validating_a_ticket_is_what_merges_its_pull_request() -> None:
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
    )
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert client.written == [("p-validated", {"statut": "done"})]
    assert results and results[0]["status"] == "done"
    assert client.comments_written[0].startswith("✅ Merged — PR #1 · squash merge")


@case
def a_pull_request_already_merged_only_moves_its_ticket() -> None:
    """Merged by hand between two runs: nothing to merge, still done."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"statut": "done"})]
    assert client.comments_written[0].startswith("✅ Merged — PR #1 · already merged")


@case
def a_merge_github_refuses_leaves_the_ticket_blocked_and_says_why() -> None:
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        refuses="gh pr merge: Pull request is not mergeable: the merge commit cannot be cleanly created",
    )
    assert len(merges) == 1, "refused once, not retried in the same pass"
    assert client.written == [("p-validated", {"statut": "blocked", "Blocage": "merge.refused"})]
    assert "not mergeable" in client.comments_written[0]
    assert results and results[0]["status"] == "blocked"


@case
def a_pull_request_closed_rather_than_merged_is_a_question_not_a_merge() -> None:
    client, merges, _, _ = _validating(
        [_reviewed("p-validated", "validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "CLOSED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"statut": "blocked", "Blocage": "merge.pr-closed"})]


@case
def nothing_is_merged_on_an_answer_github_did_not_give() -> None:
    """`gh` missing or unauthenticated: the ticket waits for the next pass."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "validated", "https://github.com/x/y/pull/1")],
        {},
        {},
    )
    assert merges == [] and client.written == [] and results == []


@case
def a_validated_ticket_with_no_pull_request_is_published_rather_than_merged() -> None:
    """The Instagram post, the email, the announcement: work with no branch."""
    client, merges, published, _ = _validating(
        [
            _reviewed("p-post", "validated", None),
            _reviewed("p-empty", "validated", ""),
        ],
        {},
        {},
    )
    assert merges == [] and client.written == []
    assert published == ["ppost", "pempty"]  # `Ticket.id` drops the dashes


@case
def a_board_without_a_validated_column_is_never_even_queried() -> None:
    """No such option on the board, no such gesture: not even a query."""
    client, merges, published, results = _validating(
        [_reviewed("p-validated", "validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        options=["ready", "progress", "review", "done"],
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == [], "a board with no column is not read at all"


@case
def a_validated_ticket_on_a_repository_with_no_pull_request_asks_rather_than_publishes() -> None:
    """Nothing to merge, and nothing on the page to publish: a question."""
    runner = _board_runner([_reviewed("p-code", "validated", None)], {})
    runner.resolver = None  # type: ignore[assignment]  # never asked: the project is said below
    runner._project_of = lambda ticket: projects.Project(name="Site", path=Path("/repo"))  # type: ignore[method-assign]  # a double: the ticket's project
    results = runner.deliver()
    assert _client(runner).written == [("p-code", {"statut": "blocked", "Blocage": "merge.no-pr"})]
    assert (
        _client(runner)
        .comments_written[0]
        .startswith("🙋 Stuck\nThis ticket was validated but carries no pull request.")
    )
    assert results and results[0]["status"] == "blocked"


@case
def a_dry_run_says_what_it_would_merge_and_merges_nothing() -> None:
    runner = _board_runner(
        [
            _reviewed("p-pr", "validated", "https://github.com/x/y/pull/1"),
            _reviewed("p-post", "validated", None),
        ],
        {},
    )
    runner.dry_run = True
    said: list[str] = []
    runner.quiet = False
    runner.say = said.append  # type: ignore[method-assign, assignment]  # a double: what it says is kept
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        results = runner.deliver()
    assert _client(runner).written == [], "a dry run writes nothing"
    assert [done["status"] for done in results] == ["dry-run", "dry-run"]
    assert any("would merge https://github.com/x/y/pull/1" in line for line in said)
    assert any("would publish what it holds" in line for line in said)


def _never_merged(url: str, method: str = "squash") -> str:
    raise AssertionError("a dry run never merges anything")


def _dated(page: notion.Page, when: str) -> notion.Page:
    """The same ticket, with a date on it."""
    page.properties["Scheduled"] = {"type": "date", "date": {"start": when}}
    return page


def _in(**delta: float) -> str:
    """A Notion date this far from now, as the board would store it."""

    return (datetime.now().astimezone() + timedelta(**delta)).isoformat(timespec="minutes")


@case
def a_validated_publication_waits_for_its_date() -> None:
    """The post is written and accepted; the hour it goes out is still the one
    the ticket names."""
    runner = _board_runner([_dated(_reviewed("ppost", "validated", None), _in(days=2))], {})
    runner._publish = lambda ticket, project: (_ for _ in ()).throw(  # type: ignore[method-assign, misc, assignment]  # a double: never to be called
        AssertionError("published before its date")
    )
    assert runner.deliver() == []
    assert _client(runner).written == [], "nothing is claimed, nothing moves"
    held = runner._deferred
    assert [ticket.id for ticket, _ in held] == ["ppost"]
    assert "ppost" in runner._claimed, "its comments go into the publication, not an answer"


@case
def a_validated_pull_request_waits_for_its_date_too() -> None:
    """One column, one rule: a merge is held back like a publication."""
    runner = _board_runner(
        [_dated(_reviewed("ppr", "validated", "https://github.com/x/y/pull/1"), _in(hours=3))],
        {},
    )
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        assert runner.deliver() == []
    assert _client(runner).written == []
    assert [ticket.id for ticket, _ in runner._deferred] == ["ppr"]
    assert "ppr" not in runner._claimed, "a ticket with a pull request stays talkable-to"


@case
def a_validated_ticket_whose_date_has_passed_is_carried_out_at_once() -> None:
    """The date says "not before", never "not until somebody looks again"."""
    runner = _board_runner(
        [_dated(_reviewed("ppr", "validated", "https://github.com/x/y/pull/1"), _in(hours=-1))],
        {},
    )
    merges: list[tuple[str, str]] = []
    with _github(
        {"https://github.com/x/y/pull/1": "OPEN"},
        merge=lambda url, method="squash", accounts=None: merges.append((url, method)) or "merged",  # type: ignore[func-returns-value]  # appended, then merged
    ):
        results = runner.deliver()
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert results and results[0]["status"] == "done"
    assert runner._deferred == []


@case
def a_validated_date_that_cannot_be_read_never_holds_a_publication_back() -> None:
    """The same rule as the queue: an unreadable date freezes nothing."""
    runner = _board_runner([_dated(_reviewed("ppost", "validated", None), "bientôt")], {})
    published: list[str] = []
    runner._publish = lambda ticket, project: published.append(ticket.id)  # type: ignore[method-assign, misc, assignment]  # a double: no session
    runner._project_of = lambda ticket: projects.Project(name="Blog", path=None)  # type: ignore[method-assign]  # a double: the ticket's project
    runner.deliver()
    assert published == ["ppost"] and runner._deferred == []


@case
def what_the_validated_column_is_holding_back_is_listed() -> None:
    """`ponos list` shows the whole calendar, both columns of it."""
    runner = _board_runner(
        [
            _dated(_reviewed("plater", "validated", None), _in(days=3)),
            _dated(_reviewed("psoon", "validated", None), _in(hours=2)),
            _reviewed("pnow", "validated", None),
            _dated(_reviewed("pelsewhere", "ready", None), _in(hours=1)),
        ],
        {},
    )
    assert [ticket.id for ticket, _ in runner.scheduled()] == ["psoon", "plater"]


@case
def a_publication_a_crash_interrupted_comes_back_as_a_question(state_home: Path) -> None:
    """Put back in ready it would be redone; the post may already be out."""
    claimed = notion.Page(
        id="ppost",  # `Ticket.id` drops the dashes, and a claim is filed under it
        url="",
        title="Le post",
        properties={
            "statut": {"type": "status", "status": {"name": "progress"}},
            "Agent": {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    state.claim("ppost", "validated")
    recovered = runner.sweep()
    assert state.claims() == {}, "the note is dropped once it has been read"
    assert recovered == 1
    assert _client(runner).written == [
        ("ppost", {"statut": "blocked", "Blocage": "worktree.interrupted"})
    ]
    said = _client(runner).comments_written[0]
    assert said.startswith("🙋 Stuck\nIts publication was interrupted")
    assert "“validated”" in said and "An answer here" not in said


@case
def a_ticket_claimed_from_ready_is_still_put_back_in_the_queue(state_home: Path) -> None:
    claimed = notion.Page(
        id="p-work",
        url="",
        title="Le header",
        properties={
            "statut": {"type": "status", "status": {"name": "progress"}},
            "Agent": {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    assert runner.sweep() == 1
    assert _client(runner).written == [("p-work", {"statut": "ready"})]
    assert "picking it up again" in _client(runner).comments_written[0]


@case
def a_ticket_put_back_after_a_crash_leaves_its_last_step_behind(state_home: Path) -> None:
    """Only `Live.close` empties the card's line, and a killed run never got there.

    Left as it was, a ticket back in ready would go on showing « Bash · npm
    test » as though a session still ran it.
    """
    lost = _in_progress("p-lost", None)
    lost.properties["Progress"] = {
        "type": "rich_text",
        "rich_text": [{"plain_text": "Bash · npm test"}],
    }
    runner = _board_runner([lost, _in_progress("p-quiet", None)], {})
    assert runner.sweep() == 2
    assert _client(runner).written == [
        ("p-lost", {"Progress": "", "statut": "ready"}),
        ("p-quiet", {"statut": "ready"}),
    ]


@case
def a_publication_interrupted_by_a_crash_leaves_its_last_step_behind_too(state_home: Path) -> None:
    interrupted = _in_progress("ppost", None)
    interrupted.properties["Progress"] = {
        "type": "rich_text",
        "rich_text": [{"plain_text": "Bash · gh pr merge"}],
    }
    runner = _board_runner([interrupted], {})
    state.claim("ppost", "validated")
    assert runner.sweep() == 1
    assert _client(runner).written == [
        ("ppost", {"Progress": "", "statut": "blocked", "Blocage": "worktree.interrupted"})
    ]


@case
def a_board_without_a_runner_column_still_gets_its_abandoned_tickets_back(state_home: Path) -> None:
    """The 1st of October: fourteen tickets in progress, nobody behind them.

    The claims were never signed — the board had no such column — and the
    sweep only put back what this host had signed.
    """
    runner = _board_runner([_in_progress("p-lost", None), _in_progress("p-other", None)], {})
    assert runner.sweep() == 2
    assert _client(runner).written == [
        ("p-lost", {"statut": "ready"}),
        ("p-other", {"statut": "ready"}),
    ]


@case
def the_machines_free_memory_is_read_from_meminfo_and_a_guard_under_the_threshold_says_so() -> None:
    from ponos import resources

    with tempfile.TemporaryDirectory() as directory:
        meminfo = Path(directory) / "meminfo"
        meminfo.write_text("MemTotal: 16000000 kB\nMemFree: 100 kB\nMemAvailable: 1048576 kB\n")
        assert resources.available_mb(str(meminfo)) == 1024
        assert resources.available_mb(str(Path(directory) / "nothing")) is None
        meminfo.write_text("MemTotal: 16000000 kB\n")
        assert resources.available_mb(str(meminfo)) is None, (
            "a machine that cannot say is not short"
        )

    original = resources.available_mb
    try:
        resources.available_mb = lambda path="": 1024
        assert resources.short_of_memory(2048) == 1024
        assert resources.short_of_memory(1024) is None and resources.short_of_memory(0) is None
    finally:
        resources.available_mb = original


@case
def a_death_by_signal_is_told_from_a_failure_and_named() -> None:
    from ponos import resources

    def ended(code: int, **fields: Any) -> session.Outcome:
        return session.Outcome(
            ok=False, blocked=False, session_id="s", summary="", log=Path("x"), code=code, **fields
        )

    assert (
        session.signalled(ended(-9))
        and session.signalled(ended(137))
        and session.signalled(ended(143))
    )
    assert not session.signalled(ended(1)), "an ordinary failure is the session's own"
    assert not session.signalled(ended(-9, timed_out=True)), "the watchdog's kill is not a mystery"
    assert not session.signalled(ended(-15, stopped=True)), "nor is the console's Stop"
    assert resources.signal_name(-9).startswith("SIGKILL") and resources.signal_name(
        137
    ).startswith("SIGKILL")
    assert resources.signal_name(143).startswith("SIGTERM") and resources.signal_name(1) == ""
    assert resources.network_error(
        "fatal: unable to access 'x': Could not resolve host: github.com"
    )
    assert not resources.network_error("remote: Permission denied")


@case
def a_relaunched_session_adds_up_what_both_tries_cost(state_home: Path) -> None:
    """The killed try was paid for too: its price is not overwritten by the second's."""
    from types import SimpleNamespace

    from ponos import journal, resources

    runner = _board_runner([], {})
    runner.config.runner.relaunch_delay_seconds = 0
    runner.say = lambda message: None  # type: ignore[method-assign]  # a double: silent
    runner._died = lambda outcome: ""  # type: ignore[method-assign]  # a double: no cause found
    killed = session.Outcome(
        ok=False,
        blocked=False,
        session_id="s",
        summary="",
        log=Path("x"),
        cost_usd=1.5,
        turns=10,
        seconds=600.0,
        code=-9,
        resulted=False,
    )
    again = session.Outcome(
        ok=True,
        blocked=False,
        session_id="s",
        summary="",
        log=Path("y"),
        cost_usd=0.5,
        turns=3,
        seconds=60.0,
    )
    runner._session = lambda *arguments: again  # type: ignore[method-assign]  # a double: the second try
    job = SimpleNamespace(
        session_id="s",
        resume=False,
        ticket=ticket_module.Ticket(_reviewed("p-ticket", "progress", None)),
    )
    original = resources.reachable, session.exists
    try:
        resources.reachable = lambda timeout=3.0: True
        session.exists = lambda session_id: True
        outcome = runner._relaunch(
            job,  # type: ignore[arg-type]  # the three fields `_relaunch` reads of a job
            "text",
            Path("x.log"),
            "",
            None,
            journal.Run(None),
            killed,
            "SIGKILL",
        )
    finally:
        resources.reachable, session.exists = original
    assert outcome.ok and outcome.log == Path("y"), "the second try is what the ticket is judged on"
    assert (outcome.cost_usd, outcome.turns, outcome.seconds) == (2.0, 13, 660.0), outcome


@case
def a_runner_short_of_memory_starts_nothing_and_says_so_once() -> None:
    runner = _board_runner([], {})
    runner.config.runner.min_free_memory_mb = 2048
    runner._memory_warned = False
    said: list[str] = []
    runner.say = said.append  # type: ignore[method-assign, assignment]  # a double: what it says is kept
    from ponos import resources

    original = resources.available_mb
    try:
        resources.available_mb = lambda path="": 512
        assert not runner.room_for_a_session() and not runner.room_for_a_session()
        assert len(said) == 1 and "512" in said[0], said
        resources.available_mb = lambda path="": 4096
        assert runner.room_for_a_session()
        runner.config.runner.min_free_memory_mb = 0
        resources.available_mb = lambda path="": 1
        assert runner.room_for_a_session(), "zero switches the guard off"
    finally:
        resources.available_mb = original


@case
def a_ticket_this_run_holds_is_never_put_back(state_home: Path) -> None:
    runner = _board_runner(
        [_in_progress("p-held", None), _in_progress("p-signed", "ponos@laptop")], {}
    )
    _client(runner).columns = {"Agent": "rich_text"}
    runner._claimed = {"pheld", "psigned"}  # `Ticket.id`, dashes dropped
    assert runner.sweep() == 0
    assert _client(runner).written == []


@case
def with_a_runner_column_only_this_hosts_tickets_come_back(state_home: Path) -> None:
    """Unchanged where the board can say who took a ticket."""
    runner = _board_runner(
        [
            _in_progress("p-mine", "ponos@laptop"),
            _in_progress("p-theirs", "ponos@desktop"),
            _in_progress("p-unsigned", None),
        ],
        {},
    )
    _client(runner).columns = {"Agent": "rich_text"}
    assert runner.sweep() == 1
    assert _client(runner).written == [("p-mine", {"statut": "ready"})]


@case
def a_publication_interrupted_on_a_board_without_a_runner_column_still_asks(
    state_home: Path,
) -> None:
    runner = _board_runner([_in_progress("ppost", None)], {})
    state.claim("ppost", "validated")
    assert runner.sweep() == 1
    assert _client(runner).written == [
        ("ppost", {"statut": "blocked", "Blocage": "worktree.interrupted"})
    ]


class _SchemaOnly(notion.Client):
    """A Notion client whose database has these columns, and whose PATCHes stay here."""

    def __init__(
        self, columns: dict[str, str], dropped: Callable[[str, str], None] | None = None
    ) -> None:
        super().__init__("secret", dropped=dropped)
        self._columns = columns
        self.patched: list[dict[str, Any]] = []

    def schema(self, database_id: str) -> dict[str, str]:
        return dict(self._columns)

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        self.patched.append(body or {})
        return {}


@case
def a_write_to_a_column_the_board_lacks_is_said_once_a_run() -> None:
    runner = _board_runner([], {})
    runner.quiet = False
    runner._unwritten = set()
    client = _SchemaOnly({"statut": "status"}, dropped=runner._dropped)
    runner.client = client
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for page in ("p1", "p2", "p3"):
            client.update("db", page, {"statut": "progress", "Agent": "ponos@laptop"})
            client.update("db", page, {"Progress": "reading the code"})
    said = out.getvalue().splitlines()
    assert len(said) == 2, said
    assert "“Agent” is not a column of the board" in said[0]
    assert "a second one on this board would put back" in said[0], "with what it costs"
    assert "“Progress”" in said[1] and "while it runs" in said[1]
    assert all(
        body == {"properties": {"statut": {"status": {"name": "progress"}}}}
        for body in client.patched[::2]
    ), "the status still goes through"
    runner._unwritten = set()  # what `tick` does: the next run says it again
    with contextlib.redirect_stdout(out):
        client.update("db", "p4", {"Agent": "ponos@laptop"})
    assert out.getvalue().count("“Agent”") == 2


@case
def publishing_hands_the_page_as_it_stands_to_a_session_and_then_closes_it() -> None:
    """The whole road for a ticket with no branch: claim, publish, done."""
    runner = _board_runner([_reviewed("p-post", "validated", None)], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None  # type: ignore[assignment]  # a ticket with no project never reaches it

    asked: list[str] = []

    def fake_run(prompt_text: str, **kwargs: Any) -> session.Outcome:
        asked.append(prompt_text)
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id=kwargs.get("session_id", "s-1"),
            summary="publié sur le compte Instagram",
            log=Path("/tmp/none.jsonl"),
            seconds=90.0,
            turns=4,
        )

    original = session.run
    session.run = fake_run  # type: ignore[assignment]  # a double: it reads the keywords it is given
    try:
        with _state_home():
            results = runner.deliver()
    finally:
        session.run = original

    # Claimed first, exactly as a run claims a ticket, and only then closed:
    # a second machine watching the board must not post the same thing twice.
    assert [values["statut"] for _, values in _client(runner).written] == [
        "progress",
        "done",
    ]
    assert results and results[0]["kind"] == "delivery"

    prompt_text = asked[0]
    assert "Le post d'annonce" in prompt_text, "the page as it stands is what goes out"
    assert "publishing, not producing" in prompt_text
    assert "publié sur le compte Instagram" in _client(runner).comments_written[0]


@case
def a_publication_whose_session_does_not_start_fails_and_lets_its_claim_go(
    state_home: Path,
) -> None:
    """No `claude` to start: the ticket fails on that, and is not left claimed.

    Nothing went out, so the note that would turn a crash into a question — the
    post may be out already — is let go: the next run has nothing to ask about.
    """
    runner = _board_runner([_reviewed("p-post", "validated", None)], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None  # type: ignore[assignment]  # never asked: the project is said below

    def fake_run(prompt_text: str, **kwargs: Any) -> session.Outcome:
        raise FileNotFoundError("[Errno 2] No such file or directory: 'claude'")

    original = session.run
    session.run = fake_run  # type: ignore[assignment]  # a double: it reads the keywords it is given
    try:
        results = runner.deliver()
    finally:
        session.run = original

    assert results and results[0]["status"] == "failed", results
    assert results[0]["code"] == "session.not-started", results
    assert [values["statut"] for _, values in _client(runner).written] == [
        "progress",
        "blocked",
    ]
    assert _client(runner).written[-1][1]["Blocage"] == "session.not-started"
    said = _client(runner).comments_written[-1]
    assert "Failed — The Claude session would not start" in said, said
    assert "No such file or directory" in said, said
    assert state.claims() == {}, "a publication that never started is not a question"


@case
def a_publication_whose_closing_write_found_notion_down_is_not_put_back_to_ready(
    state_home: Path,
) -> None:
    """The post is out; only "done" could not be written. Ready would post it twice."""
    page = _reviewed("ppost", "validated", None)
    runner = _board_runner([page], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None  # type: ignore[assignment]  # never asked: the project is said below
    written = runner.client.update

    def update(database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if values.get("statut") == "done":
            raise notion.Offline("PATCH /pages: connection refused")
        written(database_id, page_id, values)

    runner.client.update = update  # type: ignore[method-assign]  # a double: the closing write fails
    original = session.run
    session.run = lambda prompt_text, **kwargs: session.Outcome(
        ok=True,
        blocked=False,
        session_id=kwargs.get("session_id", "s-1"),
        summary="publié",
        log=Path("/tmp/none.jsonl"),
        seconds=9.0,
        turns=1,
    )
    try:
        runner.deliver()
    finally:
        session.run = original
    assert state.claims() == {"ppost": "validated"}, "the note outlives the unwritten close"

    # The next run: the ticket is where the claim left it, in progress.
    page.properties["statut"] = {"type": "status", "status": {"name": "progress"}}
    page.raw = {"last_edited_time": "2020-01-01T00:00:00.000+00:00"}
    runner._claimed = set()
    _client(runner).written.clear()
    assert runner.sweep() == 1
    assert _client(runner).written == [
        ("ppost", {"statut": "blocked", "Blocage": "worktree.interrupted"})
    ]


# -- a red job is never merged -----------------------------------------------


@contextlib.contextmanager
def _checks_of(listed: list[dict[str, Any]]) -> Iterator[list[list[str]]]:
    """`gh` present, its checks as listed, and every merge it is asked for noted."""
    asked: list[list[str]] = []
    which, checks, run = shutil.which, github_checks.checks, git_module.run
    shutil.which = lambda name: "/usr/bin/gh"  # type: ignore[assignment]  # a double: `gh` is there
    github_checks.checks = lambda url, accounts=None, timeout=60: listed

    def merged(command: list[str], **kwargs: Any) -> git_module.Result:
        asked.append(command)
        return git_module.Result(0, "merged", "")

    git_module.run = merged  # type: ignore[assignment]  # a double: every merge is noted
    try:
        yield asked
    finally:
        shutil.which, github_checks.checks, git_module.run = which, checks, run


@case
def a_pull_request_with_a_red_job_is_never_merged() -> None:
    url = "https://github.com/x/y/pull/1"
    listed = [{"name": "frontend", "bucket": "fail"}, {"name": "core", "bucket": "pass"}]
    with _checks_of(listed) as asked:
        try:
            github_checks.merge_pull_request(url)
        except github_checks.ChecksNotGreen as error:
            assert (error.state, error.names) == ("failed", ["frontend"])
        else:
            raise AssertionError("merged with a red job")
    assert asked == [], "gh pr merge was never run"


@case
def a_pull_request_with_a_job_still_running_is_not_merged_yet() -> None:
    listed = [{"name": "core", "bucket": "pass"}, {"name": "image", "bucket": "pending"}]
    with _checks_of(listed) as asked:
        try:
            github_checks.merge_pull_request("https://github.com/x/y/pull/1")
        except github_checks.ChecksNotGreen as error:
            assert (error.state, error.names) == ("pending", ["image"])
        else:
            raise AssertionError("merged with a job running")
    assert asked == []


@case
def a_pull_request_whose_jobs_are_green_or_skipped_is_merged() -> None:
    listed = [{"name": "core", "bucket": "pass"}, {"name": "docs", "bucket": "skipping"}]
    with _checks_of(listed) as asked:
        github_checks.merge_pull_request("https://github.com/x/y/pull/1")
    assert len(asked) == 1 and asked[0][:3] == ["gh", "pr", "merge"]


@case
def a_validated_pull_request_with_a_red_job_blocks_its_ticket_as_checks_failed() -> None:
    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([_reviewed("ppr", "validated", url)], {})

    def merge(url: str, method: str = "squash", accounts: Any = None) -> str:
        raise github_checks.ChecksNotGreen("failed", ["frontend"])

    with _github({url: "OPEN"}, merge=merge):
        results = runner.deliver()
    assert results and results[0]["status"] == "blocked"
    assert _client(runner).written == [
        ("ppr", {"statut": "blocked", "Blocage": "merge.checks-failed"})
    ]


@case
def a_pull_request_validated_while_its_ci_is_red_is_blocked_without_its_review_line() -> None:
    """Refused in review, validated all the same: the card says what its column does.

    The forced merge left "not merged" on the card; validated with the CI
    still red, the ticket goes to blocked as checks failed — and the line
    written for review is emptied rather than left to contradict it.
    """
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("ppr", "validated", url)
    page.properties["Progress"] = {
        "type": "rich_text",
        "rich_text": [{"plain_text": "Not merged: CI: red."}],
    }
    runner = _board_runner([page], {})

    def merge(url: str, method: str = "squash", accounts: Any = None) -> str:
        raise github_checks.ChecksNotGreen("failed", ["frontend"])

    with _github({url: "OPEN"}, merge=merge):
        results = runner.deliver()
    assert [result["status"] for result in results] == ["blocked"]
    assert _client(runner).written == [
        ("ppr", {"Progress": ""}),
        ("ppr", {"statut": "blocked", "Blocage": "merge.checks-failed"}),
    ]


@case
def a_validated_pull_request_whose_ci_still_runs_stays_validated_with_its_line() -> None:
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("ppr", "validated", url)
    page.properties["Progress"] = {
        "type": "rich_text",
        "rich_text": [{"plain_text": "Merge postponed to the next pass, left validated"}],
    }
    runner = _board_runner([page], {})

    def merge(url: str, method: str = "squash", accounts: Any = None) -> str:
        raise github_checks.ChecksNotGreen("pending", ["frontend"])

    with _github({url: "OPEN"}, merge=merge):
        assert runner.deliver() == []
    assert _client(runner).written == []


# What GitHub answered for a pull request of an account whose Actions billing
# failed: every job red at once, and the annotation it left on each of them.
_BILLING_ROLLUP = [
    {
        "__typename": "CheckRun",
        "name": name,
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "detailsUrl": f"https://github.com/Acme/REPOSITORY/actions/runs/91/job/{job}",
    }
    for name, job in (("Tests", 301), ("Lint", 302))
]
_BILLING_ANNOTATION = (
    "The job was not started because recent account payments have failed or your "
    "spending limit needs to be increased. Please check the 'Billing & plans' section "
    "in your settings"
)


@case
def a_ci_github_refuses_for_the_accounts_billing_waits_validated_and_is_said_once(
    state_home: Path,
) -> None:
    """The audit's six tickets: one unpaid invoice, said ticket by ticket in GitHub's English.

    Two validated pull requests of one account, every job refused by its
    billing: neither is blocked nor handed to a session — both wait in
    validated with `ci.billing` on their card, the account is announced once
    and warned about once in the health, and a second pass asks GitHub nothing
    more. Paid, the refused jobs are run again and the two merge.
    """
    import json

    from ponos import health

    first = "https://github.com/Acme/site/pull/1"
    second = "https://github.com/Acme/shop/pull/2"
    runner = _board_runner(
        [_reviewed("p-site", "validated", first), _reviewed("p-shop", "validated", second)], {}
    )
    told: list[tuple[str, str]] = []
    runner._announce = lambda title, body: told.append((title, body))  # type: ignore[method-assign]  # a double: what is announced is kept
    # Paying is not enough: a job GitHub refused stays red until it is run again.
    paid: list[bool] = [False]
    asked: list[list[str]] = []
    merged: list[str] = []
    green: set[str] = set()

    def run(args: list[str], *rest: Any, **kept: Any) -> git_module.Result:
        asked.append(args)
        if args[:3] == ["gh", "pr", "checks"]:
            return git_module.Result(1, "", "unknown flag: --json")
        if args[:3] == ["gh", "pr", "view"] and "statusCheckRollup" in args:
            repository = args[3].split("/")[4]
            rollup = json.loads(json.dumps(_BILLING_ROLLUP).replace("REPOSITORY", repository))
            for one in rollup:
                one["conclusion"] = "SUCCESS" if repository in green else "FAILURE"
            return git_module.Result(0, json.dumps({"statusCheckRollup": rollup}), "")
        if args[:2] == ["gh", "api"]:
            return git_module.Result(0, _BILLING_ANNOTATION, "")
        if args[:3] == ["gh", "run", "rerun"]:
            if paid[0]:
                green.add(args[-1].split("/")[-1])
            return git_module.Result(0, "", "")
        return git_module.Result(1, "", "")

    def merge(url: str, method: str = "squash", accounts: Any = None) -> str:
        if url.split("/")[4] not in green:
            raise github_checks.ChecksNotGreen("failed", ["Tests", "Lint"])
        merged.append(url)
        return "merged"

    which = shutil.which
    shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"  # type: ignore[assignment]  # a double: every tool is there
    try:
        with (
            # The recorded answers go through the real reading, not around it.
            _github(
                {first: "OPEN", second: "OPEN"},
                merge=merge,
                unstarted=github_checks.unstarted_checks,
            ),
            _git_answering(
                run=run,
                token_for=lambda reference, accounts=None: "",
                RERUN_SETTLE_SECONDS=0,  # type: ignore[arg-type]  # a constant, set the same way
            ),
        ):
            assert runner.deliver() == [], "nothing blocked, nothing failed"
            assert told == [
                (
                    "GitHub Actions is blocked by the billing of the Acme account",
                    runner.voice.say("billing-held-detail"),
                )
            ], told
            assert _client(runner).written == [
                ("p-site", {"Blocage": "ci.billing"}),
                ("p-shop", {"Blocage": "ci.billing"}),
            ], _client(runner).written
            assert [
                "billing of the Acme account" in text for text in _client(runner).comments_written
            ] == [True, True], _client(runner).comments_written
            assert not [one for one in asked if one[:3] == ["gh", "run", "rerun"]], asked

            warned = health._github_billing()
            assert [(one.code, one.state, one.params) for one in warned] == [
                ("github.billing", health.WARN, {"account": "Acme"})
            ], warned
            assert "recent account payments have failed" in warned[0].evidence

            asked.clear()
            assert runner.deliver() == []
            assert not [one for one in asked if one[:2] == ["gh", "api"]], (
                "a held account is not asked again before its hour"
            )

            # Its hour come and the invoice still unpaid: run again, refused again.
            state.billing_probed("acme", 0.0)
            assert runner.deliver() == []
            assert [one for one in asked if one[:3] == ["gh", "run", "rerun"]], asked
            assert len(told) == 1, told

            asked.clear()
            paid[0] = True
            state.billing_probed("acme", 0.0)
            results = runner.deliver()
    finally:
        shutil.which = which

    assert [one["status"] for one in results] == ["done", "done"], results
    assert merged == [first, second], merged
    reran = [one for one in asked if one[:3] == ["gh", "run", "rerun"]]
    assert [one[-1] for one in reran] == ["github.com/Acme/site", "github.com/Acme/shop"], reran
    assert state.billing_holds() == [] and health._github_billing() == []
    assert len(told) == 1, "said once for the account, and not again once it is paid"
