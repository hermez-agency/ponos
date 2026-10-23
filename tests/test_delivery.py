"""`delivery.py`: the validated column — merging, publishing, closing."""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from support import (
    _board_runner,
    _closing,
    _config,
    _environment,
    _github,
    _in_progress,
    _reviewed,
    _state_home,
    case,
)

from ponos import channels, notion, projects, session, state, store, voice
from ponos import config as C
from ponos import git as git_module
from ponos import ticket as ticket_module
from ponos.web import api as web_api

# -- a merged pull request closes its ticket ---------------------------------


@case
def a_merged_pull_request_moves_its_ticket_to_done():
    client, closed = _closing(
        [
            _reviewed("p-merged", "In review", "https://github.com/x/y/pull/1"),
            _reviewed("p-open", "In review", "https://github.com/x/y/pull/2"),
            _reviewed("p-ready", "Not started", None),
        ],
        {"https://github.com/x/y/pull/1": "MERGED", "https://github.com/x/y/pull/2": "OPEN"},
        {"review": "In review", "done": "Done"},
    )
    assert closed == 1
    assert client.written == [("p-merged", {"Status": "Done"})]
    assert client.comments_written[0] == ("✅ Merged — PR #1\nhttps://github.com/x/y/pull/1")


def _checks(*buckets: str) -> list[dict]:
    return [
        {"name": f"job-{number}", "bucket": bucket, "link": f"https://ci/{number}"}
        for number, bucket in enumerate(buckets)
    ]


@case
def the_three_states_of_the_ci_are_deduced_from_the_checks():
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
def a_push_puts_the_ci_back_to_running_until_the_new_checks_are_in():
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
def the_ci_is_asked_again_often_while_it_runs_and_rarely_once_it_has_settled():
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
def a_ticket_in_review_carries_its_ci_on_the_board_and_stops_when_it_leaves(state_home):

    url = "https://github.com/x/y/pull/2"
    runner = _board_runner(
        [_reviewed("p-open", "In review", url)], {"review": "In review", "done": "Done"}
    )
    asked = []
    head, listed = git_module.pull_request_head, git_module.checks
    git_module.pull_request_head = lambda link, accounts=None: "aaa"
    git_module.checks = lambda link, accounts=None: asked.append(link) or _checks("pass", "pending")
    try:
        with _github({url: "OPEN"}):
            git_module.pull_request_head = lambda link, accounts=None: "aaa"
            runner.close_merged()
        # Written to the board, and kept for the list to read without GitHub.
        assert runner.client.written == [("p-open", {"CI": "en cours"})], runner.client.written
        cards = [{"id": "popen", "column": "review", "pull_request": url}]
        web_api._checks(cards)
        assert cards[0]["ci"]["state"] == "pending" and len(cards[0]["ci"]["checks"]) == 2
        assert cards[0]["ci"]["link"] == url + "/checks"
        # Asked again at once: not due, so GitHub is not.
        with _github({url: "OPEN"}):
            git_module.pull_request_head = lambda link, accounts=None: "aaa"
            runner.close_merged()
        assert asked == [url]
        # Out of review: no longer followed, no longer drawn.
        runner.client.written.clear()
        runner.follow_ci([])
        assert state.ci_rows() == {}
        cards = [{"id": "popen", "column": "validated", "pull_request": url}]
        web_api._checks(cards)
        assert cards[0]["ci"] is None
    finally:
        git_module.pull_request_head, git_module.checks = head, listed


@case
def a_board_told_to_answer_in_french_is_answered_in_french():
    """The whole point of the setting, checked where it is actually read.

    `runner.language` is a line of a file; what it has to change is the sentence
    written under a ticket, and nothing in between is worth checking on its own.
    """
    runner = _board_runner(
        [_reviewed("p-merged", "In review", "https://github.com/x/y/pull/1")],
        {"review": "In review", "done": "Done"},
    )
    runner.config.runner.language = "FR"
    with _github({"https://github.com/x/y/pull/1": "MERGED"}):
        assert runner.close_merged() == 1
    said = runner.client.comments_written[0]
    assert said.startswith("✅ Fusionnée — PR #1"), said
    assert "https://github.com/x/y/pull/1" in said


@case
def a_stuck_ticket_in_french_is_stuck_in_french_from_the_first_line_to_the_phone():
    """The comment that asked for the setting: a French question wrapped in
    three English sentences. Every line of it comes out of `voice`, and so does
    the message that reaches the phone."""
    runner = _board_runner([_reviewed("p-stuck", "In progress", None)], {"blocked": "Blocked"})
    runner.config.runner.language = "fr"
    runner.config.notify = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    ).notify
    said = runner.voice
    ticket = ticket_module.Ticket(runner.client._pages[0])
    sent: list[str] = []
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
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
    comment = runner.client.comments_written[0]
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
    options=None,
    refuses: str = "",
):
    """Run `deliver` against a fake board, a fake GitHub, and no session."""

    runner = _board_runner(pages, status, options)
    merges: list[tuple[str, str]] = []
    published: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        merges.append((url, method))
        if refuses:
            raise git_module.GitError(refuses)
        return "merged"

    # Publishing runs a Claude session, which is the one thing these tests do
    # not do: what is checked here is that a ticket with no pull request goes
    # down that road at all.
    runner._publish = lambda ticket, project: published.append(ticket.id)
    with _github(states, merge=merge):
        return runner.client, merges, published, runner.deliver()


@case
def validating_a_ticket_is_what_merges_its_pull_request():
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
    )
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert client.written == [("p-validated", {"Status": "Done"})]
    assert results and results[0]["status"] == "done"
    assert client.comments_written[0].startswith("✅ Merged — PR #1 · squash merge")


@case
def a_pull_request_already_merged_only_moves_its_ticket():
    """Merged by hand between two runs: nothing to merge, still done."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"Status": "Done"})]
    assert client.comments_written[0].startswith("✅ Merged — PR #1 · already merged")


@case
def a_merge_github_refuses_leaves_the_ticket_blocked_and_says_why():
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        refuses="gh pr merge: Pull request is not mergeable: the merge commit cannot be cleanly created",
    )
    assert len(merges) == 1, "refused once, not retried in the same pass"
    assert client.written == [("p-validated", {"Status": "Blocked", "Blocage": "merge.refused"})]
    assert "not mergeable" in client.comments_written[0]
    assert results and results[0]["status"] == "blocked"


@case
def a_pull_request_closed_rather_than_merged_is_a_question_not_a_merge():
    client, merges, _, _ = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "CLOSED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"Status": "Blocked", "Blocage": "merge.pr-closed"})]


@case
def nothing_is_merged_on_an_answer_github_did_not_give():
    """`gh` missing or unauthenticated: the ticket waits for the next pass."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {},
        {},
    )
    assert merges == [] and client.written == [] and results == []


@case
def a_validated_ticket_with_no_pull_request_is_published_rather_than_merged():
    """The Instagram post, the email, the announcement: work with no branch."""
    client, merges, published, _ = _validating(
        [
            _reviewed("p-post", "Validated", None),
            _reviewed("p-empty", "Validated", ""),
        ],
        {},
        {},
    )
    assert merges == [] and client.written == []
    assert published == ["ppost", "pempty"]  # `Ticket.id` drops the dashes


@case
def a_board_without_a_validated_column_is_never_even_queried():
    """No such option on the board, no such gesture: not even a query."""
    client, merges, published, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        options=["Ready", "In progress", "In review", "Done"],
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == [], "a board with no column is not read at all"


@case
def a_file_that_names_its_columns_without_validated_asked_for_no_gesture():
    """Most often a file written before the column existed. It stays as it was."""
    settings = C.Notion(status={"review": "In review", "done": "Done"})
    assert settings.state("validated") == settings.state("review") == "In review"

    # But renaming some other column says nothing about this one: a file that
    # only translates "Ready" has not asked for the gesture to go away.
    settings = C.Notion(status={"ready": "À faire"})
    assert settings.state("validated") == "Validated"
    assert settings.state("ready") == "À faire"

    client, merges, published, results = _validating(
        [_reviewed("p-review", "In review", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {"review": "In review", "done": "Done"},
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == []

    # And a file that names nothing at all gets the whole board, gesture included.
    assert C.Notion().state("validated") == "Validated"


@case
def a_validated_ticket_on_a_repository_with_no_pull_request_asks_rather_than_publishes():
    """Nothing to merge, and nothing on the page to publish: a question."""
    runner = _board_runner([_reviewed("p-code", "Validated", None)], {})
    runner.resolver = None
    runner._project_of = lambda ticket: projects.Project(name="Site", path=Path("/repo"))
    results = runner.deliver()
    assert runner.client.written == [("p-code", {"Status": "Blocked", "Blocage": "merge.no-pr"})]
    assert runner.client.comments_written[0].startswith(
        "🙋 Stuck\nThis ticket was validated but carries no pull request."
    )
    assert results and results[0]["status"] == "blocked"


@case
def a_dry_run_says_what_it_would_merge_and_merges_nothing():
    runner = _board_runner(
        [
            _reviewed("p-pr", "Validated", "https://github.com/x/y/pull/1"),
            _reviewed("p-post", "Validated", None),
        ],
        {},
    )
    runner.dry_run = True
    said: list[str] = []
    runner.quiet = False
    runner.say = said.append
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        results = runner.deliver()
    assert runner.client.written == [], "a dry run writes nothing"
    assert [done["status"] for done in results] == ["dry-run", "dry-run"]
    assert any("would merge https://github.com/x/y/pull/1" in line for line in said)
    assert any("would publish what it holds" in line for line in said)


def _never_merged(url: str, method: str = "squash") -> str:
    raise AssertionError("a dry run never merges anything")


def _dated(page: notion.Page, when: str) -> notion.Page:
    """The same ticket, with a date on it."""
    page.properties["Scheduled"] = {"type": "date", "date": {"start": when}}
    return page


def _in(**delta) -> str:
    """A Notion date this far from now, as the board would store it."""

    return (datetime.now().astimezone() + timedelta(**delta)).isoformat(timespec="minutes")


@case
def a_validated_publication_waits_for_its_date():
    """The post is written and accepted; the hour it goes out is still the one
    the ticket names."""
    runner = _board_runner([_dated(_reviewed("ppost", "Validated", None), _in(days=2))], {})
    runner._publish = lambda ticket, project: (_ for _ in ()).throw(
        AssertionError("published before its date")
    )
    assert runner.deliver() == []
    assert runner.client.written == [], "nothing is claimed, nothing moves"
    held = runner._deferred
    assert [ticket.id for ticket, _ in held] == ["ppost"]
    assert "ppost" in runner._claimed, "its comments go into the publication, not an answer"


@case
def a_validated_pull_request_waits_for_its_date_too():
    """One column, one rule: a merge is held back like a publication."""
    runner = _board_runner(
        [_dated(_reviewed("ppr", "Validated", "https://github.com/x/y/pull/1"), _in(hours=3))],
        {},
    )
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        assert runner.deliver() == []
    assert runner.client.written == []
    assert [ticket.id for ticket, _ in runner._deferred] == ["ppr"]
    assert "ppr" not in runner._claimed, "a ticket with a pull request stays talkable-to"


@case
def a_validated_ticket_whose_date_has_passed_is_carried_out_at_once():
    """The date says "not before", never "not until somebody looks again"."""
    runner = _board_runner(
        [_dated(_reviewed("ppr", "Validated", "https://github.com/x/y/pull/1"), _in(hours=-1))],
        {},
    )
    merges: list[tuple[str, str]] = []
    with _github(
        {"https://github.com/x/y/pull/1": "OPEN"},
        merge=lambda url, method="squash", accounts=None: merges.append((url, method)) or "merged",
    ):
        results = runner.deliver()
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert results and results[0]["status"] == "done"
    assert runner._deferred == []


@case
def a_validated_date_that_cannot_be_read_never_holds_a_publication_back():
    """The same rule as the queue: an unreadable date freezes nothing."""
    runner = _board_runner([_dated(_reviewed("ppost", "Validated", None), "bientôt")], {})
    published: list[str] = []
    runner._publish = lambda ticket, project: published.append(ticket.id)
    runner._project_of = lambda ticket: projects.Project(name="Blog", path=None)
    runner.deliver()
    assert published == ["ppost"] and runner._deferred == []


@case
def what_the_validated_column_is_holding_back_is_listed():
    """`ponos list` shows the whole calendar, both columns of it."""
    runner = _board_runner(
        [
            _dated(_reviewed("plater", "Validated", None), _in(days=3)),
            _dated(_reviewed("psoon", "Validated", None), _in(hours=2)),
            _reviewed("pnow", "Validated", None),
            _dated(_reviewed("pelsewhere", "Ready", None), _in(hours=1)),
        ],
        {},
    )
    assert [ticket.id for ticket, _ in runner.scheduled()] == ["psoon", "plater"]


@case
def a_publication_a_crash_interrupted_comes_back_as_a_question(state_home):
    """Put back in ready it would be redone; the post may already be out."""
    claimed = notion.Page(
        id="ppost",  # `Ticket.id` drops the dashes, and a claim is filed under it
        url="",
        title="Le post",
        properties={
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Runner": {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    state.claim("ppost", "Validated")
    recovered = runner.sweep()
    assert state.claims() == {}, "the note is dropped once it has been read"
    assert recovered == 1
    assert runner.client.written == [
        ("ppost", {"Status": "Blocked", "Blocage": "worktree.interrupted"})
    ]
    said = runner.client.comments_written[0]
    assert said.startswith("🙋 Stuck\nIts publication was interrupted")
    assert "“Validated”" in said and "An answer here" not in said


@case
def a_ticket_claimed_from_ready_is_still_put_back_in_the_queue(state_home):
    claimed = notion.Page(
        id="p-work",
        url="",
        title="Le header",
        properties={
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Runner": {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    assert runner.sweep() == 1
    assert runner.client.written == [("p-work", {"Status": "Ready"})]
    assert "picking it up again" in runner.client.comments_written[0]


@case
def a_board_without_a_runner_column_still_gets_its_abandoned_tickets_back(state_home):
    """The 1st of October: fourteen tickets in progress, nobody behind them.

    The claims were never signed — the board had no such column — and the
    sweep only put back what this host had signed.
    """
    runner = _board_runner([_in_progress("p-lost", None), _in_progress("p-other", None)], {})
    assert runner.sweep() == 2
    assert runner.client.written == [
        ("p-lost", {"Status": "Ready"}),
        ("p-other", {"Status": "Ready"}),
    ]


@case
def the_machines_free_memory_is_read_from_meminfo_and_a_guard_under_the_threshold_says_so():
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
def a_death_by_signal_is_told_from_a_failure_and_named():
    from ponos import resources

    def ended(code: int, **fields) -> session.Outcome:
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
def a_runner_short_of_memory_starts_nothing_and_says_so_once():
    runner = _board_runner([], {})
    runner.config.runner.min_free_memory_mb = 2048
    runner._memory_warned = False
    said: list[str] = []
    runner.say = said.append
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
def a_ticket_this_run_holds_is_never_put_back(state_home):
    runner = _board_runner(
        [_in_progress("p-held", None), _in_progress("p-signed", "ponos@laptop")], {}
    )
    runner.client.columns = {"Runner": "rich_text"}
    runner._claimed = {"pheld", "psigned"}  # `Ticket.id`, dashes dropped
    assert runner.sweep() == 0
    assert runner.client.written == []


@case
def with_a_runner_column_only_this_hosts_tickets_come_back(state_home):
    """Unchanged where the board can say who took a ticket."""
    runner = _board_runner(
        [
            _in_progress("p-mine", "ponos@laptop"),
            _in_progress("p-theirs", "ponos@desktop"),
            _in_progress("p-unsigned", None),
        ],
        {},
    )
    runner.client.columns = {"Runner": "rich_text"}
    assert runner.sweep() == 1
    assert runner.client.written == [("p-mine", {"Status": "Ready"})]


@case
def a_publication_interrupted_on_a_board_without_a_runner_column_still_asks(state_home):
    runner = _board_runner([_in_progress("ppost", None)], {})
    state.claim("ppost", "Validated")
    assert runner.sweep() == 1
    assert runner.client.written == [
        ("ppost", {"Status": "Blocked", "Blocage": "worktree.interrupted"})
    ]


class _SchemaOnly(notion.Client):
    """A Notion client whose database has these columns, and whose PATCHes stay here."""

    def __init__(self, columns: dict[str, str], dropped=None):
        super().__init__("secret", dropped=dropped)
        self._columns = columns
        self.patched: list[dict] = []

    def schema(self, database_id: str) -> dict[str, str]:
        return dict(self._columns)

    def _request(self, method, path, body=None, **kwargs):
        self.patched.append(body or {})
        return {}


@case
def a_write_to_a_column_the_board_lacks_is_said_once_a_run():
    runner = _board_runner([], {})
    runner.quiet = False
    runner._unwritten = set()
    runner.client = _SchemaOnly({"Status": "status"}, dropped=runner._dropped)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for page in ("p1", "p2", "p3"):
            runner.client.update("db", page, {"Status": "In progress", "Runner": "ponos@laptop"})
            runner.client.update("db", page, {"Progress": "reading the code"})
    said = out.getvalue().splitlines()
    assert len(said) == 2, said
    assert "“Runner” is not a column of the board" in said[0]
    assert "a second one on this board would put back" in said[0], "with what it costs"
    assert "“Progress”" in said[1] and "while it runs" in said[1]
    assert all(
        body == {"properties": {"Status": {"status": {"name": "In progress"}}}}
        for body in runner.client.patched[::2]
    ), "the status still goes through"
    runner._unwritten = set()  # what `tick` does: the next run says it again
    with contextlib.redirect_stdout(out):
        runner.client.update("db", "p4", {"Runner": "ponos@laptop"})
    assert out.getvalue().count("“Runner”") == 2


@case
def doctor_names_every_column_the_board_lacks_and_counts_it():
    from ponos.__main__ import _doctor_columns

    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    complete = {
        settings.prop(key): kinds_accepted[0] for key, (kinds_accepted, _) in store.COLUMNS.items()
    }
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(complete, settings) == 0
    assert "missing" not in out.getvalue()

    lacking = {name: kind for name, kind in complete.items() if name not in ("Runner", "Progress")}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(lacking, settings) == 2
    said = re.sub(r"\x1b\[[0-9;]*m", "", out.getvalue())
    assert "✗ “Runner” missing — which machine took a ticket is not written" in said, said
    assert "✗ “Progress” missing — nothing says what a session is doing" in said, said
    assert "ponos init adds the missing ones" in said

    retyped = {**complete, "Cost": "rich_text"}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(retyped, settings) == 1
    assert "“Cost” is a rich_text, expected number" in out.getvalue()

    # The configuration of the 1st of October: `agent = "Agent"`, on a board
    # that has no column by that name — nor by the Runner one.
    renamed = C.Notion(properties={**C._DEFAULT_PROPERTIES, "agent": "Agent"})
    board = {name: kind for name, kind in complete.items() if name not in ("Agent", "Runner")}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert _doctor_columns(board, renamed) == 2  # the role column is “Agent” too
    assert "“Agent” missing — which machine took a ticket" in out.getvalue()


def _doctor_said(function, *args):
    """What a `doctor` section returns, and what it printed, colours taken out."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        returned = function(*args)
    return returned, re.sub(r"\x1b\[[0-9;]*m", "", out.getvalue())


class _DoctorBoard:
    """The few calls the board's sections of `doctor` make, answered from memory."""

    def __init__(self, offered: list[str], *, refusal: str = "", unread: str = "") -> None:
        self.offered = offered
        self.refusal = refusal
        self.unread = unread
        self.tickets = [type("Page", (), {"id": "p1"})()]

    def my_name(self) -> str:
        if self.refusal:
            raise store.StoreError(self.refusal)
        return "Ponos"

    def schema(self, database_id: str) -> dict[str, str]:
        if self.refusal:
            raise store.StoreError(self.refusal)
        return {"Status": "status"}

    def options(self, database_id: str, name: str) -> list[str]:
        return self.offered

    def query(self, database_id: str) -> list:
        return self.tickets

    def comments(self, page_id: str) -> list:
        if self.unread:
            raise store.StoreError(self.unread)
        return []


@case
def doctor_stops_with_2_on_a_configuration_it_cannot_read():
    from ponos import __main__ as cli

    with _environment(PONOS_CONFIG=str(Path(tempfile.mkdtemp()) / "config.toml")):
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 2
    assert "configuration not found" in said
    assert "Tools" not in said, "nothing after it is asked"


@case
def doctor_reads_a_markdown_board_to_the_end_and_finds_nothing_wrong_with_a_new_one():
    from ponos import __main__ as cli

    directory = Path(tempfile.mkdtemp())
    config = _config(f'[storage]\nmode = "markdown"\npath = "{directory}/board"\n')
    original = cli._doctor_model
    cli._doctor_model = lambda configuration: (
        0
    )  # claude and the timer are this machine's, not the board's
    try:
        code, said = _doctor_said(cli._doctor_board, config)
    finally:
        cli._doctor_model = original
    assert code == 0, said
    for section in (
        "Storage",
        "Tickets database",
        "Statuses",
        "Types",
        "Schedules database",
        "Comments",
    ):
        assert f"{section}\n" in said, section
    assert "Notion workspace" not in said, "a markdown board has no page to look for"
    assert "not created yet" in said and "Notion is never asked anything" in said
    assert "no ticket yet — nothing to read a discussion on" in said
    assert said.rstrip().endswith("Everything is in place.")


@case
def doctor_stops_on_a_board_it_cannot_reach_and_says_why():
    from ponos import __main__ as cli

    config = _config("")
    refused = _DoctorBoard([], refusal="401 unauthorized")
    original = cli.store.open
    cli.store.open = lambda configuration: refused
    try:
        client, said = _doctor_said(cli._doctor_storage, config)
    finally:
        cli.store.open = original
    assert client is None and "token refused: 401 unauthorized" in said

    schema, said = _doctor_said(cli._doctor_tickets_database, config, refused, "abc")
    assert schema is None
    assert "unreachable: 401 unauthorized" in said and "shared with the integration" in said
    schema, said = _doctor_said(cli._doctor_tickets_database, config, _DoctorBoard([]), "abc")
    assert schema == {"Status": "status"} and "readable — 1 property(ies)" in said


@case
def doctor_counts_a_missing_status_but_not_a_missing_validated_or_cancelled():
    from ponos import __main__ as cli

    config = _config("")
    every = [
        "Ready",
        "In progress",
        "In review",
        "Validated",
        "Done",
        "Failed",
        "Blocked",
        "Cancelled",
    ]
    assert _doctor_said(cli._doctor_statuses, config, _DoctorBoard(every), "db")[0] == 0

    problems, said = _doctor_said(
        cli._doctor_statuses, config, _DoctorBoard([s for s in every if s != "Validated"]), "db"
    )
    assert problems == 0 and "no column to validate from" in said
    problems, said = _doctor_said(
        cli._doctor_statuses, config, _DoctorBoard([s for s in every if s != "Cancelled"]), "db"
    )
    assert problems == 0 and "no column to give a ticket up in" in said

    problems, said = _doctor_said(
        cli._doctor_statuses, config, _DoctorBoard([s for s in every if s != "Ready"]), "db"
    )
    assert problems == 1 and "ready     → “Ready” is not offered by the database" in said

    drafted = _config('[notion.status]\ndraft = "Ready"\n')
    problems, said = _doctor_said(cli._doctor_statuses, drafted, _DoctorBoard(every), "db")
    assert problems == 1 and "draft     → “Ready” is also a status the runner moves" in said

    problems, said = _doctor_said(cli._doctor_statuses, config, _DoctorBoard([]), "db")
    assert problems == 0 and "offers no options" in said


@case
def doctor_counts_comments_it_is_refused_but_not_one_it_could_not_read_once():
    from ponos import __main__ as cli

    config = _config("")
    problems, said = _doctor_said(
        cli._doctor_comments, config, _DoctorBoard([], unread="403 restricted"), "db"
    )
    assert problems == 1 and "Read comments" in said
    problems, said = _doctor_said(
        cli._doctor_comments, config, _DoctorBoard([], unread="502 bad gateway"), "db"
    )
    assert problems == 0 and "comments could not be read: 502 bad gateway" in said
    problems, said = _doctor_said(cli._doctor_comments, config, _DoctorBoard([]), "db")
    assert problems == 0 and "comments readable" in said


@case
def doctor_says_what_leaves_the_machine_unread_and_what_cannot_be_merged():
    from ponos import __main__ as cli

    _, said = _doctor_said(
        cli._doctor_validation, _config("[runner]\nforce_validated_code = true\npush = false\n")
    )
    assert "force validated: code" in said
    assert "no pull request is opened to merge" in said
    _, said = _doctor_said(cli._doctor_validation, _config("[runner]\nrebase = false\n"))
    assert "runner.rebase is off" in said and "force validated" not in said


@case
def doctor_says_half_a_sign_in_and_a_connector_address_claude_ai_cannot_add():
    from ponos import __main__ as cli

    _, said = _doctor_said(
        cli._doctor_console, _config('[web]\nemail = "me@example.com"\nurl = "http://box.lan"\n')
    )
    assert "opened with its token" in said and "half a sign-in" in said
    assert (
        "web.url is http://box.lan: claude.ai only adds a connector at an https:// address" in said
    )


@case
def doctor_says_when_memory_is_short_and_when_it_cannot_tell():
    from ponos import __main__ as cli

    config = _config("[runner]\nmin_free_memory_mb = 2048\n")
    original = cli.resources.available_mb
    try:
        cli.resources.available_mb = lambda: 100
        assert (
            "100 MB available, under runner.min_free_memory_mb (2048 MB)"
            in _doctor_said(cli._doctor_memory, config)[1]
        )
        cli.resources.available_mb = lambda: 4096
        assert (
            "4096 MB available (a session starts above 2048 MB)"
            in _doctor_said(cli._doctor_memory, config)[1]
        )
        cli.resources.available_mb = lambda: None
        assert "the memory guard cannot tell" in _doctor_said(cli._doctor_memory, config)[1]
    finally:
        cli.resources.available_mb = original


@case
def publishing_hands_the_page_as_it_stands_to_a_session_and_then_closes_it():
    """The whole road for a ticket with no branch: claim, publish, done."""
    runner = _board_runner([_reviewed("p-post", "Validated", None)], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None  # a ticket with no project never reaches it

    asked: list[str] = []

    def fake_run(prompt_text, **kwargs):
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
    session.run = fake_run
    try:
        with _state_home():
            results = runner.deliver()
    finally:
        session.run = original

    # Claimed first, exactly as a run claims a ticket, and only then closed:
    # a second machine watching the board must not post the same thing twice.
    assert [values["Status"] for _, values in runner.client.written] == [
        "In progress",
        "Done",
    ]
    assert results and results[0]["kind"] == "delivery"

    prompt_text = asked[0]
    assert "Le post d'annonce" in prompt_text, "the page as it stands is what goes out"
    assert "publishing, not producing" in prompt_text
    assert "publié sur le compte Instagram" in runner.client.comments_written[0]


@case
def a_publication_whose_closing_write_found_notion_down_is_not_put_back_to_ready(state_home):
    """The post is out; only "done" could not be written. Ready would post it twice."""
    page = _reviewed("ppost", "Validated", None)
    runner = _board_runner([page], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None
    written = runner.client.update

    def update(database_id, page_id, values):
        if values.get("Status") == "Done":
            raise notion.Offline("PATCH /pages: connection refused")
        written(database_id, page_id, values)

    runner.client.update = update
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
    assert state.claims() == {"ppost": "Validated"}, "the note outlives the unwritten close"

    # The next run: the ticket is where the claim left it, in progress.
    page.properties["Status"] = {"type": "status", "status": {"name": "In progress"}}
    page.raw = {"last_edited_time": "2020-01-01T00:00:00.000+00:00"}
    runner._claimed = set()
    runner.client.written.clear()
    assert runner.sweep() == 1
    assert runner.client.written == [
        ("ppost", {"Status": "Blocked", "Blocage": "worktree.interrupted"})
    ]


# -- a red job is never merged -----------------------------------------------


@contextlib.contextmanager
def _checks_of(listed: list[dict]):
    """`gh` present, its checks as listed, and every merge it is asked for noted."""
    asked: list[list[str]] = []
    which, checks, run = git_module.shutil.which, git_module.checks, git_module.run
    git_module.shutil.which = lambda name: "/usr/bin/gh"
    git_module.checks = lambda url, accounts=None, timeout=60: listed

    def merged(command, **kwargs):
        asked.append(command)
        return git_module.Result(0, "merged", "")

    git_module.run = merged
    try:
        yield asked
    finally:
        git_module.shutil.which, git_module.checks, git_module.run = which, checks, run


@case
def a_pull_request_with_a_red_job_is_never_merged():
    url = "https://github.com/x/y/pull/1"
    listed = [{"name": "frontend", "bucket": "fail"}, {"name": "core", "bucket": "pass"}]
    with _checks_of(listed) as asked:
        try:
            git_module.merge_pull_request(url)
        except git_module.ChecksNotGreen as error:
            assert (error.state, error.names) == ("failed", ["frontend"])
        else:
            raise AssertionError("merged with a red job")
    assert asked == [], "gh pr merge was never run"


@case
def a_pull_request_with_a_job_still_running_is_not_merged_yet():
    listed = [{"name": "core", "bucket": "pass"}, {"name": "image", "bucket": "pending"}]
    with _checks_of(listed) as asked:
        try:
            git_module.merge_pull_request("https://github.com/x/y/pull/1")
        except git_module.ChecksNotGreen as error:
            assert (error.state, error.names) == ("pending", ["image"])
        else:
            raise AssertionError("merged with a job running")
    assert asked == []


@case
def a_pull_request_whose_jobs_are_green_or_skipped_is_merged():
    listed = [{"name": "core", "bucket": "pass"}, {"name": "docs", "bucket": "skipping"}]
    with _checks_of(listed) as asked:
        git_module.merge_pull_request("https://github.com/x/y/pull/1")
    assert len(asked) == 1 and asked[0][:3] == ["gh", "pr", "merge"]


@case
def a_validated_pull_request_with_a_red_job_blocks_its_ticket_as_checks_failed():
    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([_reviewed("ppr", "Validated", url)], {})

    def merge(url, method="squash", accounts=None):
        raise git_module.ChecksNotGreen("failed", ["frontend"])

    with _github({url: "OPEN"}, merge=merge):
        results = runner.deliver()
    assert results and results[0]["status"] == "blocked"
    assert runner.client.written == [
        ("ppr", {"Status": "Blocked", "Blocage": "merge.checks-failed"})
    ]
