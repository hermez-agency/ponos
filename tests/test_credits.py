"""`credits.py`: when the credits run out, and stopping short of the wall."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from support import _board_runner, _config, _git_answering, _ready, _reviewed, _state_home, case

from ponos import config as C
from ponos import credits, notion, projects, prompt, question, session, state
from ponos import git as git_module
from ponos import ticket as ticket_module
from ponos.runner import Runner

# -- when the credits run out -------------------------------------------------


@case
def an_exhausted_quota_is_told_apart_from_every_other_failure():
    """The one refusal that is not the session's fault, read off what it said.

    A false positive here would put the runner to sleep for a quarter of an
    hour on an ordinary crash, so nothing but these two sentences counts.
    """
    assert credits.reached("Claude AI usage limit reached|1758031200") == 1758031200.0
    # A timestamp in milliseconds would otherwise be the year 57000: a runner
    # asleep for good, on a message whose format changed under it.
    far = credits.reached("Claude AI usage limit reached|1758031200000")
    assert far <= time.time() + credits.LONGEST_WAIT
    # No moment named: a short wait, and the next run asks again.
    blind = credits.reached("Claude usage limit reached. Your limit will reset at 10pm.")
    assert time.time() + credits.BLIND_WAIT - 5 < blind <= time.time() + credits.BLIND_WAIT
    assert credits.reached("API Error: Credit balance is too low") > 0
    assert credits.reached("claude exited with code 1") == 0.0
    assert credits.reached("the session was killed after 30 min") == 0.0
    assert credits.reached("") == 0.0


@case
def a_wait_outlives_the_run_that_wrote_it(state_home):
    """A run is a process the timer starts: what it learned only travels on disk."""
    assert credits.held() == 0.0, "nothing waited for until something says so"
    credits.hold(time.time() + 300)
    assert credits.held() > time.time(), "the next run finds it and stands down"
    # A moment that has passed is no wait at all — and `release` is what
    # removes the note, so the run that finds the credits back can say so.
    credits.hold(time.time() - 1)
    assert credits.held() == 0.0
    assert credits.release() and not credits.release()


def _spent(seconds_away: float = 300) -> session.Outcome:
    """What `session.run` hands back when the subscription's window is spent."""
    return session.Outcome(
        ok=False,
        blocked=False,
        session_id="s-1",
        summary="",
        log=Path("/dev/null"),
        error="Claude AI usage limit reached",
        exhausted=True,
        resets_at=time.time() + seconds_away,
    )


def _out_of_credit(page: notion.Page) -> Runner:
    """A board runner whose every session dies on the quota."""
    runner = _board_runner([page], {})
    runner.config.runner.auto_update = False
    runner._run_session = lambda job, template: _spent()
    return runner


def _doc_job(page: notion.Page) -> ticket_module.Job:
    return ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )


@case
def a_ticket_the_credits_ran_out_on_waits_for_credit_rather_than_failing():
    """Nothing was wrong with it: there was nothing left to work on it with.

    Failing it would cost the ticket twice — once for the quota, and once for
    the four hours nobody is there to put it back. Blocking it would cost the
    board instead: "Blocked" is the column that means *you* are needed, and a
    column that also means "come back at six" has stopped saying anything. So
    it goes back to Ready, where it came from, and the attribute is what says
    the credit is why it is sitting there.
    """
    page = _reviewed("p-doc", "In progress", None)
    runner = _out_of_credit(page)
    runner.client.waiting = True
    result = runner._execute_document(_doc_job(page))
    assert runner.client.written[0][1]["Status"] == "Ready", "back where it came from"
    assert runner.client.written[0][1]["Waiting for credit"] is True
    # The session goes on the page with it: it is what the pass that has credit
    # again picks the ticket back up by, rather than starting it over.
    assert runner.client.written[0][1]["Session"] == "s-1"
    assert result["status"] == "waiting", "neither done, nor failed, nor blocked"
    said = runner.client.comments_written[0]
    assert said.startswith("⏸️ Waiting — out of credit, back in “Ready” until "), said
    assert "?" not in said, "a wait asks nothing of anybody"


@case
def a_board_without_the_attribute_puts_the_ticket_back_and_says_nothing():
    """The property is added by `init`, and an old board has never had one.

    Until it is there, an exhausted quota does exactly what it did before the
    attribute existed: the ticket goes back to the column it was claimed from,
    with nothing on the board saying why.
    """
    page = _reviewed("p-doc", "In progress", None)
    runner = _out_of_credit(page)
    assert runner.client.waiting is False, "premise"
    runner._execute_document(_doc_job(page))
    assert runner.client.written[0][1]["Status"] == "Ready"
    assert "back in “Ready”" in runner.client.comments_written[0]
    assert runner.waiting_flag() == "", "nothing to tick, and nothing pretends there is"


def _that_failed(page: notion.Page, *, folded: bool) -> tuple[Runner, list[str], dict]:
    """A document ticket whose session stopped, run to its report."""
    runner = _board_runner([page], {})
    runner.config.runner.auto_update = False
    runner.config.runner.keep_worktree_on_failure = False

    def stopped(job, template):
        # Half an answer written, and then the session died: a failure rather
        # than a question, which is the road a trace is actually read on.
        (job.workdir / "ANSWER.md").write_text("La moitié d'une réponse.")
        return session.Outcome(
            ok=False,
            blocked=False,
            session_id="s-1",
            summary="",
            error="npm test exited 1",
            log=Path("/logs/x.jsonl"),
            seconds=90.0,
            turns=4,
        )

    runner._run_session = stopped
    filed: list[str] = []
    job = ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )
    if folded:
        job.live = type("L", (), {"detail": lambda self, text: bool(filed.append(text)) or True})()
    return runner, filed, runner._execute_document(job)


@case
def a_run_that_failed_says_what_to_do_and_folds_the_rest_into_the_page():
    """A report used to end on the session id, the log path and the directory
    to resume from — three lines of machinery pushed to a phone every time.

    They are not gone, they are folded: the block the run already wrote its
    steps into takes them, and the report spends its lines on the verdict.
    """
    runner, filed, result = _that_failed(_reviewed("p-doc", "In progress", None), folded=True)
    assert result["status"] == "failed"
    said = runner.client.comments_written[0]
    assert said.splitlines() == [
        "⚠️ Failed — The session did not make it to the end.",
        "npm test exited 1",
        "What it did is in the folded block at the bottom of the page.",
    ], said
    assert "claude --resume s-1" not in said
    assert filed == [
        "To pick the session back up: `claude --resume s-1`. Its log is `/logs/x.jsonl`."
    ]


@case
def a_ticket_whose_run_wrote_no_block_keeps_the_trace_under_its_verdict():
    """`runner.progress = false`, or a Notion that refused: the trace has
    nowhere to be folded into, so it stays where it can be read."""
    runner, filed, _ = _that_failed(_reviewed("p-none", "In progress", None), folded=False)
    said = runner.client.comments_written[0]
    assert filed == []
    assert said.endswith("Its log is `/logs/x.jsonl`.")
    assert said.startswith("⚠️ Failed — ")


def _answered_on(comments: list[str], answer: str, write: str) -> tuple[Runner, dict]:
    """A document ticket whose session said `answer` and left `write` in ANSWER.md."""

    page = _reviewed("p-doc", "In progress", None)
    runner = _board_runner([page], {"review": "In review", "done": "Done"})
    runner.client.append_markdown = lambda _page, _text: 2
    runner.config.runner.keep_worktree_on_failure = False

    def answered(job, template):
        if write:
            (job.workdir / "ANSWER.md").write_text(write)
        return session.Outcome(
            ok=False,
            blocked=True,
            session_id="s-1",
            summary=session._summary(answer),
            answer=answer,
            log=Path("/logs/x.jsonl"),
            question=question.parse(answer),
        )

    runner._run_session = answered
    job = _doc_job(page)
    job.comments = comments
    return runner, runner._execute_document(job)


def _session_log(*steps: tuple[str, str]) -> Path:
    """A session's stream-json log: each step a Bash command and what it printed."""
    log = Path(tempfile.mkdtemp()) / "s.jsonl"
    lines = []
    for number, (command, printed) in enumerate(steps):
        lines.append(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"u{number}",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ]
                },
            }
        )
        lines.append(
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": f"u{number}", "content": printed}
                    ]
                },
            }
        )
    log.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return log


@case
def a_pull_request_a_writing_session_opened_is_attached_and_sent_to_review():
    """Four Whisper Desk tickets classified « Rédaction » opened their pull
    requests themselves: done, an empty Pull Request column, nothing to review,
    and two of them doing the same thing. Never again a pull request lost."""
    url = "https://github.com/SalvadorCardona/whisper-desk/pull/21"
    page = _reviewed("p-doc", "In progress", None)
    runner = _board_runner([page], {"review": "In review", "done": "Done"})
    runner.client.append_markdown = lambda _page, _text: 2
    log = _session_log(
        ("git log --oneline -3", "abc fix: something https://github.com/x/y/pull/3"),
        ("gh pr create --title 'feat: Wispr Flow' --body x", f"Creating pull request\n{url}\n"),
    )

    def answered(job, template):
        (job.workdir / "ANSWER.md").write_text("Fait : la PR est ouverte.")
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s-1",
            summary="ok",
            answer="RESULT: ok — PR ouverte",
            log=log,
        )

    runner._run_session = answered
    job = _doc_job(page)
    job.kind = "writing"
    runner._execute_document(job)
    values = runner.client.written[-1][1]
    assert values["Status"] == "In review", "in review, where a pull request waits"
    assert values["Pull Request"] == url, "the pull request is the ticket's"
    said = runner.client.comments_written[-1]
    assert url in said and "review" in said.lower(), said

    assert session.pull_requests(log) == [url], "only what `gh pr create` printed"


@case
def a_writing_session_that_opened_nothing_still_ends_in_done():
    page = _reviewed("p-doc", "In progress", None)
    runner = _board_runner([page], {"review": "In review", "done": "Done"})
    runner.client.append_markdown = lambda _page, _text: 2
    log = _session_log(("gh pr list", "https://github.com/x/y/pull/3\n"))

    def answered(job, template):
        (job.workdir / "ANSWER.md").write_text("Le texte.")
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s-1",
            summary="ok",
            answer="RESULT: ok — écrit",
            log=log,
        )

    runner._run_session = answered
    job = _doc_job(page)
    job.kind = "writing"
    runner._execute_document(job)
    values = runner.client.written[-1][1]
    assert values["Status"] == "Done" and "Pull Request" not in values


@case
def a_log_event_whose_message_is_a_sentence_does_not_crash_the_ticket():
    """Opoil and Leadz Ninja, both transferred, both « le runner lui-même a
    cassé » : Claude in Chrome refused a browser-internal tab, and the
    `permission_denied` event it logs carries its `message` as a sentence, not
    as a dict. Reading the pull requests out of the log broke on it."""
    url = "https://github.com/SalvadorCardona/opoil/pull/4"
    log = _session_log(("gh pr create --title x --body y", f"{url}\n"))
    with log.open("a") as written:
        written.write(
            json.dumps(
                {
                    "type": "system",
                    "subtype": "permission_denied",
                    "tool_name": "mcp__claude-in-chrome__get_page_text",
                    "message": "Can't interact with browser-internal or extension pages",
                }
            )
            + "\n"
        )
        written.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "id": "u9", "name": "Read", "input": "not a dict"},
                        ]
                    },
                }
            )
            + "\n"
        )
    assert session.pull_requests(log) == [url]


@case
def a_question_answered_on_a_finished_ticket_goes_to_review_rather_than_blocked():
    """« C'est quoi X ? » — answered, nothing left to do, and said as a stop.

    No QUESTION written, so nothing to wait for: the ticket is read, not
    blocked again with its own answer as the reason.
    """
    with _state_home():
        runner, result = _answered_on(
            ["Salva: c'est quoi un CNAME ?"],
            "RESULT: blocked — un CNAME est un alias de nom de domaine",
            "Un CNAME est un alias.",
        )
    assert result["status"] == "done", result
    assert runner.client.written[-1][1]["Status"] == "In review", runner.client.written

    # A real question still blocks, and so does a stop with nothing written.
    with _state_home():
        _, asked = _answered_on(
            ["Salva: c'est quoi un CNAME ?"],
            "QUESTION: Je le crée chez OVH ?\nMODE: yes-no\nRESULT: blocked — où le créer ?",
            "Un CNAME est un alias.",
        )
        _, empty = _answered_on(["Salva: et alors ?"], "RESULT: blocked — je ne sais pas", "")
        _, unasked = _answered_on([], "RESULT: blocked — un CNAME est un alias", "Un alias.")
    assert asked["status"] == "blocked", asked
    assert empty["status"] == "blocked", empty
    assert unasked["status"] == "blocked", "nobody asked anything: a stop is a stop"


@case
def a_publication_the_credits_ran_out_on_goes_back_to_validated(state_home):
    """Not to ready: the decision to publish it has already been taken."""
    page = _reviewed("p-post", "Validated", None)
    runner = _out_of_credit(page)
    result = runner._publish(ticket_module.Ticket(page), projects.Project(name="", path=None))
    assert runner.client.written[0][1]["Status"] == "In progress", "claimed first"
    assert runner.client.written[-1][1]["Status"] == "Validated"
    assert result["status"] == "waiting"
    assert state.claims() == {}, "and the claim is let go of on the way out"


@case
def nothing_at_all_is_run_while_the_credits_are_out(state_home):
    """Every session this pass could start would die on the same sentence."""
    runner = _out_of_credit(_reviewed("p-ready", "Ready", None))
    said: list[str] = []
    runner.quiet, runner.say, runner.announce_idle = False, said.append, True
    credits.hold(time.time() + 300)
    assert runner.tick() == []
    assert runner.client.queried == [], "the board is not even read"
    assert runner.client.written == []
    assert any("Out of credit" in line for line in said)

    # And the wait ends by itself: the run that finds it over says so, once.
    credits.hold(time.time() - 1)
    assert runner.waiting_for_credits() == 0.0
    assert any("credits are back" in line for line in said)


@case
def a_runner_told_not_to_wait_fails_on_the_quota_as_it_always_did(state_home):
    """`wait_for_credits = false` is the old behaviour, kept for an API key."""
    page = _reviewed("p-doc", "In progress", None)
    runner = _out_of_credit(page)
    runner.config.runner.wait_for_credits = False
    credits.hold(time.time() + 300)
    assert runner.waiting_for_credits() == 0.0, "a note nobody reads"

    job = ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )
    # Reported as the session failure it looks like — here a question, the
    # way a session that writes no answer always came back.
    assert runner._execute_document(job)["status"] == "blocked"
    assert "the credits are out" not in runner.client.comments_written[0]


# -- stopping short of the wall ------------------------------------------------


@contextmanager
def _usage(payload: object):
    """Claude Code's own store, replaced by what it would have cached.

    `payload` is what goes under `cachedUsageUtilization.utilization`; `None`
    writes no store at all, which is the reading nobody can take.
    """
    directory = Path(tempfile.mkdtemp())
    if payload is not None:
        (directory / ".claude.json").write_text(
            json.dumps({"cachedUsageUtilization": {"utilization": payload}}),
            encoding="utf-8",
        )
    previous = os.environ.get("CLAUDE_CONFIG_DIR")
    os.environ["CLAUDE_CONFIG_DIR"] = str(directory)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = previous


def _windows(session_percent: float, weekly: float = 0.0, hours: float = 4) -> dict:
    """The two windows `/usage` shows, as the cache holds them."""
    moment = datetime.now().astimezone() + timedelta(hours=hours)
    return {
        "five_hour": {"utilization": session_percent, "resets_at": moment.isoformat()},
        "seven_day": {"utilization": weekly, "resets_at": moment.isoformat()},
    }


@case
def the_most_constraining_of_the_two_windows_is_the_one_that_counts():
    """20 % of the week and 97 % of the session is 97 % spent, not 20 %."""
    with _usage(_windows(97, weekly=20)):
        used, until = credits.used()
        assert used == 97 and until > time.time()
    with _usage(_windows(3, weekly=88)):
        assert credits.used()[0] == 88

    # A window whose moment has passed rolled over after the cache was written,
    # so it is empty now whatever figure sits beside it — which is what makes a
    # stale cache safe to read rather than something to date-check.
    with _usage(_windows(99, weekly=99, hours=-2)):
        assert credits.used() == (0.0, 0.0)

    # And a reading is never invented: no store, no key, a shape that changed.
    with _usage(None):
        assert credits.used() is None
    with _usage({"five_hour": None, "seven_day": "?"}):
        assert credits.used() is None


def _reserving(pages: list[notion.Page], percent: int = 5) -> Runner:
    """A board runner with a reserve, whose sessions would all succeed."""
    runner = _board_runner(pages, {}, waiting=True)
    runner.config.runner.auto_update = False
    runner.config.runner.credit_reserve_percent = percent
    runner.config.runner.reply = False
    runner.announce_idle = False
    return runner


@case
def the_reserve_stops_the_runner_before_the_subscription_is_spent(state_home):
    """The whole point: a runner that spends the last of it is one you turn off.

    At 95 % nothing new is started — and the ticket that was ready says so on
    the board, ticked as waiting for credit, rather than sitting in a ready
    column that looks like a runner gone silent. It does not move: nothing
    happened to it, and it is still exactly as ready as it was.
    """
    started: list[str] = []
    with _usage(_windows(96)):
        runner = _reserving([_ready("p-1"), _ready("p-2")])
        runner.prepare = lambda ticket: started.append(ticket.id)
        results = runner.tick()

    assert started == [], "not one session begun"
    assert {page: values["Waiting for credit"] for page, values in runner.client.written} == {
        "p-1": True,
        "p-2": True,
    }
    assert all("Status" not in values for _, values in runner.client.written), "nothing moved"
    # The Session cell is emptied: nothing was started for these, so there is no
    # conversation to carry on — and a ticket woken by a comment must not have
    # the run before it resumed, arguing with its own verdict.
    assert all(values["Session"] == "" for _, values in runner.client.written)
    assert [result["status"] for result in results] == ["waiting", "waiting"]
    assert all("⏸️ Waiting" in said for said in runner.client.comments_written)


@case
def the_budget_limits_are_empty_unless_the_file_names_an_amount():
    assert _config("").budget == C.Budget(0.0, 0.0), "no table, no limit"
    assert _config('[budget]\ndaily_usd = ""\nper_ticket_usd = ""\n').budget == C.Budget(0.0, 0.0)
    assert _config("[budget]\ndaily_usd = 25\nper_ticket_usd = 2.5\n").budget == C.Budget(25.0, 2.5)
    assert _config('[budget]\ndaily_usd = -4\nper_ticket_usd = "n/a"\n').budget == C.Budget(
        0.0, 0.0
    )


@case
def the_daily_limit_holds_from_the_history_until_midnight_and_lifts_after(state_home):
    """Read off what the history says was spent today, and never before it is."""
    runner = _reserving([])
    assert runner.under_reserve() == 0.0, "no limit set"
    runner.config.budget.daily_usd = 5.0
    assert runner.under_reserve() == 0.0, "nothing spent yet"
    state.record({"id": "a", "status": "blocked", "cost_usd": 3.0})
    assert runner.under_reserve() == 0.0, "3 $ of 5 $"
    state.record({"id": "b", "status": "failed", "cost_usd": 2.0})
    until = runner.under_reserve()
    assert 0 < until - time.time() <= 24 * 3600, "held until the next midnight"
    assert credits.held(what="budget") == until
    runner.config.budget.daily_usd = 6.0
    assert runner.under_reserve() == 0.0, "a raised limit lifts it"
    assert not credits.held(what="budget"), "and the note goes with it"


@case
def a_reserve_of_ten_percent_stops_ten_percent_earlier():
    """The number is the setting's whole job, so it is the number that is read."""
    with _state_home(), _usage(_windows(92)):
        assert _reserving([], percent=5).under_reserve() == 0.0, "92 % is under 95 %"
        assert _reserving([], percent=10).under_reserve() > 0.0, "and over 90 %"

    # The wait ends when the constraining window does, not at some invented hour.
    with _state_home(), _usage(_windows(96, hours=3)):
        until = _reserving([], percent=5).under_reserve()
        assert 2.9 * 3600 < until - time.time() <= 3 * 3600


@case
def a_reserve_nobody_can_measure_changes_nothing_at_all(state_home):
    """A cache that is not there, or a shape that changed under us.

    Refusing to run on it would be the worse failure by some distance: the
    runner would stop working because it could not find a JSON key. So it says
    so once and behaves exactly as it did before the setting existed.
    """
    started: list[str] = []
    with _usage(None):
        runner = _reserving([_ready("p-1")])
        said: list[str] = []
        runner.quiet, runner.say = False, said.append
        runner.prepare = lambda ticket: started.append(ticket.id)
        runner.tick()

    assert started == ["p1"], "the ticket ran, as it always did"
    warnings = [line for line in said if "could not be read" in line]
    assert len(warnings) == 1, f"said once per run, not once per look: {warnings}"


@case
def the_reserve_is_read_again_at_every_free_place_not_once_a_pass(state_home):
    """A pass lasts as long as its longest session, and the sessions in flight
    are what fills the window: a pass that started under the line can cross it
    halfway through. What is running is left to finish — killing a session to
    save credit would spend what it has already cost.
    """
    finished = threading.Event()
    with _usage(_windows(10)) as _:
        runner = _reserving([_ready("p-1"), _ready("p-2")])
        runner.config.runner.max_concurrent = 1
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            # The session itself is what spends the window, so the reading
            # changes underneath the pass rather than before it.
            store = Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".claude.json"
            store.write_text(
                json.dumps({"cachedUsageUtilization": {"utilization": _windows(98)}}),
                encoding="utf-8",
            )
            finished.set()
            return {"id": job.ticket.page.id, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert finished.is_set()
    assert [result["status"] for result in results] == ["done", "waiting"]
    assert results[1]["id"] == "p2", "the one it did not start says so on the board"


@case
def a_ticket_that_raises_fails_alone_and_the_pass_goes_on(state_home):
    """An exception out of one ticket used to come back out of `future.result()`
    and end the pass: the other sessions ran on unreported, and the ticket that
    raised sat in progress until a later sweep put it back — to raise again."""
    with _usage(_windows(10)):
        runner = _reserving([_ready("p-1"), _ready("p-2")])
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            if job.ticket.id == "p1":
                raise subprocess.TimeoutExpired(["git", "push"], 300)
            return {"ticket": job.ticket.title, "id": job.ticket.id, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=False)
        history = state.history()

    by_id = {result["id"]: result for result in results}
    assert by_id["p2"]["status"] == "done", "the other ticket ran to its end"
    assert by_id["p1"]["status"] == "failed", results
    assert any("TimeoutExpired" in text for text in runner.client.comments_written), (
        runner.client.comments_written
    )
    assert [page for page, values in runner.client.written if values.get("Status") == "Failed"] == [
        "p-1"
    ], runner.client.written
    assert {entry["id"] for entry in history} == {"p1", "p2"}, "both are in the history"


@case
def a_git_command_that_hangs_is_a_failure_git_callers_already_read():
    """`subprocess.TimeoutExpired` was caught nowhere: a fetch on a remote that
    stopped answering raised through every caller up to the pass itself."""

    result = git_module.run(
        [sys.executable, "-c", "import time; print('begun', flush=True); time.sleep(30)"], timeout=1
    )
    assert not result.ok and result.code == git_module.TIMED_OUT, result
    assert "timed out after 1s" in result.err, result.err


@case
def an_account_gh_did_not_know_is_asked_again_once_it_might():
    """A token found is kept; a refusal is kept for a minute and no more — the
    console lives for weeks, and a `gh auth login` typed after one failed lookup
    has to be heard without a restart."""

    answers = [git_module.Result(1, "", "not logged in"), git_module.Result(0, "gho-new", "")]
    asked: list[list[str]] = []

    def run(args, *rest, **kept):
        asked.append(args)
        return answers.pop(0)

    held = dict(git_module._TOKENS)
    git_module._TOKENS.clear()
    original_which = shutil.which
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        with _git_answering(run=run):
            assert git_module.account_token("someone") == ""
            assert git_module.account_token("someone") == "", "within the minute: not asked again"
            assert len(asked) == 1
            git_module._TOKENS["someone"] = ("", time.monotonic() - 1)  # the minute is over
            assert git_module.account_token("someone") == "gho-new"
            assert git_module.account_token("someone") == "gho-new"
            assert len(asked) == 2, "a token found is kept"
    finally:
        git_module.shutil.which = original_which
        git_module._TOKENS.clear()
        git_module._TOKENS.update(held)


@case
def a_ticket_waiting_for_credit_goes_before_one_that_never_started(state_home):
    """It is the one already half done: a branch with commits on it and a
    session that can be picked back up. Starting a fresh ticket first is how a
    board spends the returning credit on beginning things rather than on
    finishing them."""
    session_id = "11111111-2222-3333-4444-555555555555"
    # Still ready — it never went anywhere. The tick is the only difference.
    parked = _ticked(_ready("p-parked"))
    parked.properties["Session"] = {"type": "url", "url": f"ponos://session/{session_id}"}
    with _usage(_windows(10)):
        runner = _reserving([_ready("p-fresh"), parked])
        queued = runner.queue()[0]
        assert [ticket.id for ticket in queued] == ["pparked", "pfresh"]

        # And it is picked up rather than started over: the session on the page
        # is the one the job carries, whatever shape the column wrote it in.
        job = runner.prepare(queued[0])
        assert job.resume and job.session_id == session_id
        assert not runner.prepare(queued[1]).resume, "a fresh ticket opens a fresh session"
        # Claiming it unticks it: the wait is over the moment something starts,
        # and a tick left behind would resume a session that is running.
        claim = next(
            values for _, values in runner.client.written if "Waiting for credit" in values
        )
        assert claim["Waiting for credit"] is False


@case
def nothing_waiting_for_credit_is_ticked_twice_while_the_credit_is_still_short(state_home):
    """Re-ticking a ticket already ticked would be a Notion write per pass for
    as long as the window lasts — four hours at a ten-second cadence."""
    with _usage(_windows(99)):
        runner = _reserving([_ticked(_ready("p-parked"))])
        assert runner.tick() == [], "nothing is written on the way past"
        assert runner.client.written == []


@case
def what_the_reserve_says_out_loud_is_said_once_and_once_on_the_way_back():
    """A run is a process the timer starts, so "already said" has to be on disk.

    Four hours at a ten-second cadence is fourteen hundred passes; a phone that
    rings on each of them is a phone that stops being read.
    """
    with _state_home(), _usage(_windows(97)):
        runner, told = _reserving([]), []
        runner._announce = lambda title, body: told.append(title)
        for _ in range(3):
            assert runner.under_reserve() > 0.0
        assert len(told) == 1, told

    with _state_home(), _usage(_windows(97)):
        runner, told = _reserving([]), []
        runner._announce = lambda title, body: told.append(title)
        assert runner.under_reserve() > 0.0
        # The window rolls over, and the run that finds it says so — once.
        (Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".claude.json").write_text(
            json.dumps({"cachedUsageUtilization": {"utilization": _windows(4)}}),
            encoding="utf-8",
        )
        for _ in range(3):
            assert runner.under_reserve() == 0.0
        assert len(told) == 2, told


@case
def a_runner_with_no_window_to_reserve_a_slice_of_ignores_the_setting(state_home):
    """`wait_for_credits = false` says this runner is not on a metered
    subscription — an API key, or sessions routed through OpenRouter. There is
    no window there, so there is no share of one to hold back."""
    with _usage(_windows(99)):
        runner = _reserving([])
        runner.config.runner.wait_for_credits = False
        assert runner.under_reserve() == 0.0


@case
def a_session_picked_back_up_is_told_what_changed_and_not_the_whole_ticket():
    """It has the ticket, the brief and the context already; resending them
    would cost on every resumption what they cost once. What it cannot know is
    that hours passed and that its own half-done work is still on disk."""
    sent: list[tuple[str, bool]] = []
    page = _ticked(_reviewed("p-doc", "Ready", None))
    runner = _board_runner([page], {}, waiting=True)
    runner._live = lambda job: None
    runner.config.runner.attach_sessions = False

    def fake_run(text, **rest):
        sent.append((text, rest["resume"]))
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id=rest["session_id"],
            summary="fait",
            log=Path("/dev/null"),
        )

    original, session.run = session.run, fake_run
    try:
        job = _doc_job(page)
        job.session_id, job.resume = "s-carried", True
        runner._run_session(job, prompt.DOCUMENT)
    finally:
        session.run = original

    text, resumed = sent[0]
    assert resumed, "`claude --resume`, not a new conversation"
    assert "carry on from where you stopped" in text
    assert page.title not in text, "the frame is not sent a second time"


@case
def a_session_that_cannot_be_picked_back_up_starts_a_fresh_one():
    """Pruned, filed on another machine, or a worktree it will not resume from.

    The ticket and its branch are still here, so the run goes on from
    everything except the thread of the interrupted session.
    """
    drawn: list[str] = []
    page = _ticked(_reviewed("p-doc", "Ready", None))
    runner = _board_runner([page], {}, waiting=True)
    runner._live = lambda job: None
    runner.config.runner.attach_sessions = False

    def fake_run(text, **rest):
        drawn.append(rest["session_id"])
        gone = rest["resume"]
        return session.Outcome(
            ok=not gone,
            blocked=False,
            session_id=rest["session_id"],
            summary="fait",
            error="No conversation found" if gone else "",
            log=Path("/dev/null"),
        )

    original, session.run = session.run, fake_run
    try:
        job = _doc_job(page)
        job.session_id, job.resume = "s-gone", True
        outcome = runner._run_session(job, prompt.DOCUMENT)
    finally:
        session.run = original

    assert drawn[0] == "s-gone" and drawn[1] != "s-gone", drawn
    assert outcome.ok and not job.resume


@case
def a_spent_window_mid_pass_says_so_on_the_tickets_it_did_not_start(state_home):
    """The other half of the reserve, and the older of the two roads: a session
    died on the quota while the pass was running. What it had queued behind it
    is not silently left in the ready column with nothing to explain it — it is
    ticked exactly as the ticket that died was, and comes back with it."""
    started: list[str] = []
    with _usage(_windows(10)):
        runner = _reserving([_ready("p-1"), _ready("p-2"), _ready("p-3")])
        runner.config.runner.max_concurrent = 1
        runner.prepare = lambda ticket: ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

        def execute(job):
            started.append(job.ticket.page.id)
            credits.hold(time.time() + 300)  # what a spent session leaves behind
            return {"id": job.ticket.page.id, "status": "waiting"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert started == ["p-1"], "the ticket in flight finished, and nothing else began"
    assert [result["status"] for result in results] == ["waiting", "waiting", "waiting"]
    assert {page for page, _ in runner.client.written} == {"p-2", "p-3"}
    assert all(values["Waiting for credit"] is True for _, values in runner.client.written)


@case
def a_reserve_is_read_off_the_file_between_none_and_half():
    """Both ends clamped rather than refused: 150 meant "keep plenty", not
    "never run again", and a negative reserve is a typo for none at all."""
    assert _config("[runner]\ncredit_reserve_percent = 10\n").runner.credit_reserve_percent == 10
    assert _config("[runner]\ncredit_reserve_percent = 150\n").runner.credit_reserve_percent == 50
    assert _config("[runner]\ncredit_reserve_percent = -3\n").runner.credit_reserve_percent == 0
    assert _config("[runner]\n").runner.credit_reserve_percent == 5


# -- a merged pull request closes its ticket ---------------------------------


def _ticked(page: notion.Page) -> notion.Page:
    """The same page, ticked as waiting for credit — where a pass left it."""
    page.properties["Waiting for credit"] = {"type": "checkbox", "checkbox": True}
    return page
