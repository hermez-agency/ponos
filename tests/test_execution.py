"""`execution.py`: what a finished session is worth, on the roads a full run rarely takes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from support import _board_runner, _git_answering, _reviewed, case

from ponos import execution, notion, projects, resources, session, state, stopping, store
from ponos import git as git_module
from ponos import github_token as github_token_module
from ponos import ticket as ticket_module
from ponos.question import Question

# -- doubles -------------------------------------------------------------------


def _outcome(**values) -> session.Outcome:
    """A session's ending: a plain success unless `values` say otherwise."""
    fields = {
        "ok": True,
        "blocked": False,
        "session_id": "s-1",
        "summary": "Fait.",
        "log": Path("/logs/x.jsonl"),
    }
    return session.Outcome(**{**fields, **values})


def _job(*, code: bool = False, page: notion.Page | None = None) -> ticket_module.Job:
    """A job on a fresh scratch directory: on a repository when `code` says so."""
    page = page or _reviewed("p-ticket", "In progress", None)
    root = Path(tempfile.mkdtemp())
    project = (
        projects.Project(name="Northwind", path=root / "repository")
        if code
        else projects.Project(name="", path=None)
    )
    return ticket_module.Job(
        ticket_module.Ticket(page),
        project,
        branch="ticket/x" if code else "",
        base="main" if code else "",
        workdir=root / "work",
    )


def _runner(status: dict[str, str] | None = None):
    """A runner on a fake board that keeps what it says, instead of logging it."""
    page = _reviewed("p-ticket", "In progress", None)
    runner = _board_runner([page], status or {"review": "In review", "done": "Done"})
    runner.config.runner.auto_update = False
    runner.config.runner.keep_worktree_on_failure = False
    said: list[str] = []
    runner.say = said.append
    return runner, page, said


class _Network:
    """`resources`, answering as told — and saying whether it was asked."""

    def __init__(self, reachable: bool = True, oom: str = ""):
        self.reachable, self.oom, self.asked = reachable, oom, 0

    def __enter__(self):
        self.saved = resources.reachable, resources.oom_killed
        resources.reachable = self._reach
        resources.oom_killed = lambda seconds=900.0: self.oom
        return self

    def _reach(self, timeout: float = 3.0) -> bool:
        self.asked += 1
        return self.reachable

    def __exit__(self, *exc):
        resources.reachable, resources.oom_killed = self.saved


# -- the helpers at the top of the module ----------------------------------------


@case
def a_listener_that_raises_is_dropped_and_the_other_keeps_hearing():
    heard: list[dict] = []
    broken: list[dict] = []

    def refusing(event):
        broken.append(event)
        raise RuntimeError("Notion said 500")

    listen = execution._both(heard.append, refusing)
    listen({"n": 1})
    listen({"n": 2})
    assert heard == [{"n": 1}, {"n": 2}], "the journal hears every event"
    assert broken == [{"n": 1}], "the page is dropped after its first refusal"

    alone: list[dict] = []
    execution._both(alone.append, None)({"n": 3})
    assert alone == [{"n": 3}], "no live block: the journal alone"


@case
def a_second_try_carries_what_the_first_one_cost():
    first = _outcome(ok=False, error="lost", cost_usd=0.25, seconds=30.0, turns=3)
    then = _outcome(summary="Le second.", cost_usd=0.5, seconds=60.0, turns=7)
    added = execution._added(first, then)
    assert (added.cost_usd, added.seconds, added.turns) == (0.75, 90.0, 10)
    assert added.ok and added.summary == "Le second.", "everything else is the second try's"
    assert first.cost_usd == 0.25, "the first outcome is left as it was"


@case
def a_report_loses_its_trailing_result_lines_whatever_their_markup():
    answer = "Le bandeau est réparé.\n\nRESULT: dans le texte reste.\n\n**RESULT:** ok — fait\n# result: ok"
    assert execution._report(answer) == "Le bandeau est réparé.\n\nRESULT: dans le texte reste."
    assert execution._report("RESULT: ok — rien d'autre") == ""
    assert execution._report("") == "" and execution._report(None) == ""  # type: ignore[arg-type]


@case
def an_answer_file_is_read_stripped_and_a_missing_one_is_empty():
    workdir = Path(tempfile.mkdtemp())
    assert execution._answer(workdir) == "", "no ANSWER.md, no answer"
    (workdir / "ANSWER.md").write_bytes(b"\n  La r\xe9ponse.  \n\n")
    assert execution._answer(workdir) == "La r�ponse.", "bad bytes do not crash the ticket"


@case
def only_a_blocked_session_that_asks_nothing_on_a_ticket_spoken_on_has_answered_anyway():
    job = _job()
    blocked = _outcome(ok=False, blocked=True)
    assert not execution._answered_anyway(job, blocked), "nobody spoke on the ticket"
    job.comments = ["Qu'est-ce que X ?"]
    assert execution._answered_anyway(job, blocked)
    asked = _outcome(ok=False, blocked=True, question=Question(ask="Lequel ?"))
    assert not execution._answered_anyway(job, asked), "a question is waited for"
    spent = _outcome(ok=False, blocked=True, over_budget=True)
    assert not execution._answered_anyway(job, spent), "a spent budget is not an answer"
    assert not execution._answered_anyway(job, _outcome()), "a success is not a stop"


@case
def a_report_of_work_done_on_a_dashboard_is_told_from_one_about_the_code():
    assert execution._done_elsewhere("Variable ajoutée sur Dokploy, service redéployé.")
    assert not execution._done_elsewhere("Redéployé, après avoir corrigé le fichier app.py.")
    assert not execution._done_elsewhere("J'ai lu le ticket et je n'ai rien trouvé.")
    assert not execution._done_elsewhere("")


# -- why a session died ----------------------------------------------------------


@case
def a_session_killed_by_a_signal_says_which_and_what_the_kernel_wrote():
    runner, _, _ = _runner()
    killed = _outcome(ok=False, code=-9, resulted=False)
    with _Network(oom="Out of memory: Killed process 4242 (claude)"):
        why = runner._died(killed)
    assert why.startswith(runner.voice.say("killed-signal", signal=resources.signal_name(-9)))
    assert "Killed process 4242" in why, why
    with _Network():
        assert runner._died(_outcome(ok=False, code=137)) == runner.voice.say(
            "killed-signal", signal=resources.signal_name(137)
        ), "no OOM line, only the signal"


@case
def a_stream_cut_while_the_network_was_down_is_a_death_and_otherwise_is_not():
    runner, _, _ = _runner()
    cut = _outcome(ok=False, resulted=False, error="stream ended")
    with _Network(reachable=False):
        assert runner._died(cut) == runner.voice.say("killed-network")
    with _Network(reachable=True):
        assert runner._died(cut) == "", "the network was there: the session's own ending"


@case
def a_session_that_ended_by_itself_is_never_asked_about_the_network():
    runner, _, _ = _runner()
    endings = (
        _outcome(),
        _outcome(ok=False, blocked=True),
        _outcome(ok=False, stopped=True, resulted=False),
        _outcome(ok=False, timed_out=True, resulted=False),
        _outcome(ok=False, exhausted=True, resulted=False),
        _outcome(ok=False, error="claude exited with code 1"),
    )
    with _Network(reachable=False) as network:
        assert [runner._died(ending) for ending in endings] == [""] * len(endings)
    assert network.asked == 0, "no connection opened for an ordinary ending"


@case
def a_killed_session_asks_to_be_run_again_and_a_blocked_one_asks_its_own_question():
    runner, _, _ = _runner()
    killed = _outcome(ok=False, blocked=True, killed="signal SIGKILL")
    assert runner._question(killed, "détail") == runner.voice.say("session-killed-question")
    own = Question(ask="Quelle base ?")
    assert runner._question(_outcome(ok=False, blocked=True, question=own), "détail") is own
    assert runner._question(_outcome(ok=False, blocked=True), "détail") == "détail"
    assert runner._question(_outcome(ok=False, error="crash"), "détail") == "", (
        "a crash asks nothing"
    )


# -- what a session is handed ---------------------------------------------------


@case
def a_project_is_handed_the_secrets_it_is_granted_and_told_which_could_not_be_read():
    runner, _, said = _runner()
    job = _job(code=True)
    assert runner._secrets(job) == {}, "a project the vault does not name gets nothing"

    runner.config.vault.projects = {
        "northwind": {"NPM_TOKEN": "PONOS_TEST_NPM_SECRET", "MISSING_TOKEN": "PONOS_TEST_ABSENT"}
    }
    os.environ["PONOS_TEST_NPM_SECRET"] = "npm_execution_case_0123456789"
    os.environ.pop("PONOS_TEST_ABSENT", None)
    try:
        runner.dry_run = True
        assert runner._secrets(job) == {}, "a dry run reads nothing"
        runner.dry_run = False
        found = runner._secrets(job)
    finally:
        os.environ.pop("PONOS_TEST_NPM_SECRET", None)
    assert found == {"NPM_TOKEN": "npm_execution_case_0123456789"}, "matched however it is spelt"
    assert "    · secrets: NPM_TOKEN" in said
    assert any(line.startswith("    ! secret not read: MISSING_TOKEN") for line in said), said
    assert not any("npm_execution_case" in line for line in said), "the value is never said"


@case
def only_a_code_ticket_whose_remote_has_an_owner_is_handed_a_github_token():
    runner, _, _ = _runner()

    def no_git(*args, **kwargs):
        raise AssertionError("git asked about a ticket that has no repository")

    asked: list[str] = []
    saved = github_token_module.session_environment
    github_token_module.session_environment = lambda owner: asked.append(owner) or {"GH_TOKEN": "t"}
    try:
        with _git_answering(remote_url=no_git):
            assert runner._github(_job()) == {}
        runner.dry_run = True
        with _git_answering(remote_url=no_git):
            assert runner._github(_job(code=True)) == {}, "a dry run asks GitHub nothing"
        runner.dry_run = False
        with _git_answering(remote_url=lambda repo: ""):
            assert runner._github(_job(code=True)) == {}, "no origin, no owner, no token"
        with _git_answering(remote_url=lambda repo: "git@github.com:hermez-agency/ponos.git"):
            assert runner._github(_job(code=True)) == {"GH_TOKEN": "t"}
    finally:
        github_token_module.session_environment = saved
    assert asked == ["hermez-agency"]


# -- a session that stopped without its report -----------------------------------


@case
def a_document_session_is_asked_for_its_report_once_and_never_twice(state_home):
    runner, _, said = _runner()
    job = _job()
    job.workdir.mkdir(parents=True)
    assert not runner._report_missing(job, _outcome(ok=False, error="crash")), (
        "a crash forgot nothing"
    )
    assert runner._report_missing(job, _outcome()), "ok, and no ANSWER.md"
    (job.workdir / "ANSWER.md").write_text("La réponse.")
    assert not runner._report_missing(job, _outcome()), "the answer is there"

    (job.workdir / "ANSWER.md").unlink()
    state.wrote_up(job.ticket.id)
    assert not runner._report_missing(job, _outcome())
    assert "    · stopped without its report, and was already asked for one once" in said


@case
def a_code_session_with_a_verdict_a_commit_or_a_change_has_its_report(state_home):
    runner, _, _ = _runner()
    job = _job(code=True)
    with _git_answering(commits_ahead=lambda *args: 0, is_dirty=lambda *args: False):
        assert not runner._report_missing(job, _outcome(answer="RESULT: ok — fait"))
        assert runner._report_missing(job, _outcome(answer="J'ai fini.")), "nothing at all"
    with _git_answering(commits_ahead=lambda *args: 2, is_dirty=lambda *args: False):
        assert not runner._report_missing(job, _outcome(answer=""))
    with _git_answering(commits_ahead=lambda *args: 0, is_dirty=lambda *args: True):
        assert not runner._report_missing(job, _outcome(answer=""))


# -- a session ended from the console ---------------------------------------------


@case
def a_session_is_halted_only_when_it_stopped_and_somebody_asked(state_home):
    runner, page, said = _runner()
    job = _job(page=page)
    assert runner._halted(job, _outcome(ok=False, stopped=True)) is None, "nobody asked"
    stopping.request(job.ticket.id, "pause")
    assert runner._halted(job, _outcome(ok=False, error="crash")) is None, "it died on its own"

    result = runner._halted(job, _outcome(ok=False, stopped=True))
    assert result == {
        "ticket": "p-ticket",
        "id": job.ticket.id,
        "status": "stopped",
        "reason": "pause",
    }
    assert stopping._file(job.ticket.id, "done").exists(), "the console is told it is gone"
    assert runner.client.written == [] and runner.client.comments_written == [], (
        "nothing on the board: the ticket is the console's"
    )
    assert said == ["    ■ p-ticket — ended on request (pause)"]


# -- a code ticket that did not get there -----------------------------------------


@case
def a_blocked_code_session_drops_its_worktree_unless_asked_to_keep_it(state_home):
    removed: list[Path] = []
    blocked = _outcome(ok=False, blocked=True, summary="Quelle base viser ?")
    with _git_answering(remove_worktree=lambda repo, path: removed.append(path)):
        runner, page, _ = _runner()
        job = _job(code=True, page=page)
        result = runner._code_stopped(job, blocked)
        assert result["status"] == "blocked"
        assert removed == [job.workdir]

        runner, page, _ = _runner()
        runner.config.runner.keep_worktree_on_failure = True
        kept = _job(code=True, page=page)
        runner._code_stopped(kept, blocked)
    assert removed == [job.workdir], "the second one is kept"
    said = runner.client.comments_written[-1]
    assert str(kept.workdir) in said and "ticket/x" in said, said


@case
def a_code_session_killed_twice_is_blocked_on_its_cause(state_home):
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    killed = _outcome(ok=False, killed="signal SIGKILL ; le réseau était injoignable")
    with _git_answering(remove_worktree=lambda repo, path: None):
        result = runner._code_stopped(job, killed)
    assert result["status"] == "blocked", "a kill is somebody's to look at, not a failure"
    said = runner.client.comments_written[-1]
    assert "SIGKILL" in said and runner.voice.say("session-killed-question") in said, said


@case
def work_done_on_a_dashboard_with_nothing_committed_is_delivered_into_the_page(state_home):
    runner, page, _ = _runner()
    bodies: list[str] = []
    runner.client.append_markdown = lambda page_id, text: bodies.append(text) or 1
    job = _job(code=True, page=page)
    removed: list[Path] = []
    answer = "Variable ajoutée sur Dokploy, service redéployé.\n\nRESULT: ok — redéployé"
    with _git_answering(
        is_dirty=lambda workdir: False, remove_worktree=lambda repo, path: removed.append(path)
    ):
        result = runner._nothing_committed(job, _outcome(answer=answer))
    assert result is not None and result["status"] == "done"
    assert removed == [job.workdir]
    assert "Variable ajoutée sur Dokploy" in bodies[0] and "RESULT" not in bodies[0], bodies
    assert runner.client.written[-1][1]["Status"] == "Done"
    assert runner.voice.say("done-elsewhere") in runner.client.comments_written[-1]


@case
def files_left_uncommitted_block_the_ticket_and_keep_the_worktree(state_home):
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    removed: list[Path] = []
    answer = "Service redéployé sur Dokploy."
    with _git_answering(
        is_dirty=lambda workdir: True, remove_worktree=lambda repo, path: removed.append(path)
    ):
        result = runner._nothing_committed(job, _outcome(answer=answer))
    assert result["status"] == "blocked"
    assert removed == [], "the changes are there for somebody to commit"
    assert runner.client.bodies == [], "nothing delivered"


@case
def a_report_that_claims_code_it_did_not_commit_is_blocked(state_home):
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    removed: list[Path] = []
    answer = "J'ai corrigé le fichier src/app.py et redéployé sur Dokploy."
    with _git_answering(
        is_dirty=lambda workdir: False, remove_worktree=lambda repo, path: removed.append(path)
    ):
        result = runner._nothing_committed(job, _outcome(answer=answer, summary="Corrigé."))
    assert result["status"] == "blocked"
    assert removed == [job.workdir], "a clean worktree holds nothing worth keeping"
    said = runner.client.comments_written[-1]
    assert said.startswith("🙋") and "Corrigé." in said, "asked what became of the change"


# -- the branch, its push and its pull request ------------------------------------


@case
def a_refused_rebase_is_said_and_a_moved_head_counts_as_replayed(state_home):
    runner, page, said = _runner()
    runner.config.runner.fetch = False
    heads = iter(["aaa", "aaa"])
    with _git_answering(
        has_ref=lambda repo, ref: True,
        head=lambda workdir: next(heads),
        rebase=lambda workdir, onto, settle=None: "CONFLICT (content): Merge conflict in app.py",
    ):
        job = _job(code=True, page=page)
        assert runner._replay_branch(job) is False
    assert "CONFLICT" in job.notes[-1] and "origin/main" in job.notes[-1], job.notes
    assert said[-1].startswith("    ! not replayed onto origin/main")

    heads = iter(["aaa", "bbb"])
    with _git_answering(
        has_ref=lambda repo, ref: False,
        head=lambda workdir: next(heads),
        rebase=lambda workdir, onto, settle=None: "",
    ):
        moved = _job(code=True, page=page)
        assert runner._replay_branch(moved) is True
    assert moved.notes == [runner.voice.say("rebased-onto", base="main")], (
        "no origin: the local base"
    )


@case
def a_push_github_refuses_fails_the_ticket_and_keeps_the_branch(state_home):
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    refused = git_module.Result(
        1, "", "! [remote rejected] ticket/x (protected branch hook declined)"
    )
    with _git_answering(push=lambda *args, **kwargs: refused), _Network():
        result = runner._push_branch(job, _outcome(), force=False)
    assert result is not None and result["status"] == "failed"
    said = runner.client.comments_written[-1]
    assert "protected branch hook declined" in said and "ticket/x" in said, said

    with _git_answering(push=lambda *args, **kwargs: git_module.Result(0, "", "")):
        assert runner._push_branch(job, _outcome(), force=True) is None


@case
def a_push_that_never_reached_github_is_not_a_refusal(state_home):
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    offline = git_module.Result(
        128,
        "",
        "fatal: unable to access 'https://github.com/x/y/': Could not resolve host: github.com",
    )
    assert resources.network_error(offline.err), "premise: this reads as the network away"
    with _git_answering(push=lambda *args, **kwargs: offline), _Network(reachable=False):
        try:
            runner._push_branch(job, _outcome(), force=False)
        except store.Unreachable as error:
            assert "git push" in str(error)
        else:
            raise AssertionError("an unreachable GitHub fails no ticket")
    assert runner.client.written == [] and runner.client.comments_written == []

    with _git_answering(push=lambda *args, **kwargs: offline), _Network(reachable=True):
        result = runner._push_branch(job, _outcome(), force=False)
    assert result["status"] == "failed", "the network answers: GitHub's own refusal"


@case
def a_pull_request_that_cannot_be_opened_is_said_on_the_ticket(state_home):
    runner, page, said = _runner()
    job = _job(code=True, page=page)

    def refused(*args, **kwargs):
        raise git_module.GitError("gh: no default remote")

    with _git_answering(open_pull_request=refused):
        assert runner._open_pull_request(job, _outcome(), commits=2) == ""
    assert "gh: no default remote" in job.notes[-1]
    assert said[-1] == "    ! pull request not opened: gh: no default remote"

    titles: list[str] = []

    def opened(workdir, title, body, base, accounts=None):
        titles.append(title)
        return "https://github.com/x/y/pull/7"

    job.subtype = "chore"
    with _git_answering(open_pull_request=opened):
        assert runner._open_pull_request(job, _outcome(), commits=1).endswith("/pull/7")
    assert titles == ["chore: p-ticket"], "squashed, the title is the commit"


# -- a ticket with no repository --------------------------------------------------


@case
def a_document_session_that_wrote_no_answer_is_blocked_and_its_directory_removed(state_home):
    runner, page, _ = _runner()
    job = _job(page=page)
    runner._run_session = lambda job, template: _outcome(summary="J'ai lu le ticket.")
    result = runner._execute_document(job)
    assert result["status"] == "blocked"
    assert not job.workdir.exists(), "nothing worth keeping"
    said = runner.client.comments_written[-1]
    assert "ANSWER.md" in said and "J'ai lu le ticket." in said, said


@case
def an_answer_notion_refuses_fails_the_ticket_and_says_where_it_still_is(state_home):
    runner, page, _ = _runner()
    job = _job(page=page)

    def refusing(page_id, text):
        raise notion.NotionError("PATCH /blocks: 502 bad gateway")

    runner.client.append_markdown = refusing

    def answered(job, template):
        (job.workdir / "ANSWER.md").write_text("La réponse, entière.")
        return _outcome()

    runner._run_session = answered
    result = runner._execute_document(job)
    assert result["status"] == "failed"
    assert (job.workdir / "ANSWER.md").exists(), "the answer stays on disk"
    said = runner.client.comments_written[-1]
    assert str(job.workdir / "ANSWER.md") in said and "502" in said, said


@case
def a_session_that_cannot_start_fails_the_document_ticket(state_home):
    runner, page, _ = _runner()

    def missing(job, template):
        raise FileNotFoundError("claude: command not found")

    runner._run_session = missing
    result = runner._execute_document(_job(page=page))
    assert result["status"] == "failed"
    assert "claude: command not found" in runner.client.comments_written[-1]


@case
def a_dry_run_starts_no_session():
    runner, page, said = _runner()
    runner.dry_run = True

    def no_session(*args, **kwargs):
        raise AssertionError("a dry run starts nothing")

    runner._run_session = no_session
    job = _job(page=page)
    assert runner.execute(job) == {
        "ticket": "p-ticket",
        "id": job.ticket.id,
        "status": "dry-run",
    }
    runner.execute(_job(code=True, page=page))
    assert said == ["    (dry run) document", "    (dry run) ticket/x from main"]


# -- the session itself -----------------------------------------------------------


def _sessions(runner, *outcomes: session.Outcome) -> list[dict]:
    """`_paid`, answering with `outcomes` in turn; records how each was asked."""
    asked: list[dict] = []
    queue = list(outcomes)

    def paid(ticket, prompt_text, **options):
        asked.append({"prompt": prompt_text, **options})
        return queue.pop(0)

    runner._paid = paid
    runner.config.runner.progress = False
    return asked


@case
def a_resumed_session_claude_no_longer_has_starts_afresh_on_a_log_of_its_own(state_home):
    runner, page, said = _runner()
    job = _job(page=page)
    job.workdir.mkdir(parents=True)
    (job.workdir / "ANSWER.md").write_text("La réponse.")
    job.session_id, job.resume = "s-old", True
    job.log = job.workdir.parent / "run.jsonl"
    lost = _outcome(ok=False, error="No conversation found with session ID: s-old", cost_usd=0.1)
    fresh = _outcome(cost_usd=0.4, seconds=50.0)
    asked = _sessions(runner, lost, fresh)
    with _Network():
        outcome = runner._run_session(job, "{title}")
    assert [call["resume"] for call in asked] == [True, False], "the second one is new"
    assert asked[1]["session_id"] != "s-old" and asked[1]["session_id"] == job.session_id
    assert asked[1]["log"].name == "run-again.jsonl", "the first transcript is not truncated"
    assert outcome.ok and outcome.cost_usd == 0.5, "both halves were paid for"
    assert "    ↻ that session could not be picked up — starting a new one" in said


@case
def a_session_that_forgot_its_answer_is_picked_up_once_to_write_it(state_home):
    runner, page, _ = _runner()
    job = _job(page=page)
    job.workdir.mkdir(parents=True)
    job.log = job.workdir.parent / "run.jsonl"
    forgot = _outcome(session_id="s-9", cost_usd=0.3, turns=5)
    wrote = _outcome(session_id="s-9", summary="Écrit.", cost_usd=0.05, turns=1)
    asked = _sessions(runner, forgot, wrote)
    outcome = runner._run_session(job, "{title}")
    assert len(asked) == 2 and asked[1]["resume"] and asked[1]["session_id"] == "s-9"
    assert asked[1]["log"].name == "run-report.jsonl"
    assert (outcome.summary, outcome.cost_usd, outcome.turns) == ("Écrit.", 0.35, 6)
    assert state.written_up(job.ticket.id), "and never again for this ticket"

    # Lost on the way: the first half is what the ticket is judged on.
    runner, page, _ = _runner()
    again = _job(page=page)
    again.workdir.mkdir(parents=True)
    again.log = again.workdir.parent / "run.jsonl"
    _sessions(runner, forgot, _outcome(ok=False, error="No conversation found"))
    assert runner._run_session(again, "{title}") is forgot
