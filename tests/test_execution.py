"""`execution.py`: what a finished session is worth, on the roads a full run rarely takes."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from support import _board_runner, _BoardClient, _git_answering, _reviewed, case

from ponos import execution, notion, projects, resources, session, state, stopping, store
from ponos import git as git_module
from ponos import github_token as github_token_module
from ponos import ticket as ticket_module
from ponos.question import Question
from ponos.runner import Runner

# -- doubles -------------------------------------------------------------------


def _outcome(**values: Any) -> session.Outcome:
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
    page = page or _reviewed("p-ticket", "progress", None)
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


def _runner(status: dict[str, str] | None = None) -> tuple[Runner, notion.Page, list[str]]:
    """A runner on a fake board that keeps what it says, instead of logging it."""
    page = _reviewed("p-ticket", "progress", None)
    runner = _board_runner([page], status or {"review": "review", "done": "done"})
    runner.config.runner.auto_update = False
    runner.config.runner.keep_worktree_on_failure = False
    said: list[str] = []
    runner.say = said.append  # type: ignore[method-assign, assignment]  # a double: what it says is kept
    return runner, page, said


def _client(runner: Runner) -> _BoardClient:
    """The fake board `_board_runner` gave the runner, to read what was written on it."""
    return cast(_BoardClient, runner.client)


class _Network:
    """`resources`, answering as told — and saying whether it was asked."""

    def __init__(self, reachable: bool = True, oom: str = "") -> None:
        self.reachable, self.oom, self.asked = reachable, oom, 0

    def __enter__(self) -> _Network:
        self.saved = resources.reachable, resources.oom_killed
        resources.reachable = self._reach
        resources.oom_killed = lambda seconds=900.0: self.oom
        return self

    def _reach(self, timeout: float = 3.0) -> bool:
        self.asked += 1
        return self.reachable

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        resources.reachable, resources.oom_killed = self.saved


# -- the helpers at the top of the module ----------------------------------------


@case
def a_listener_that_raises_is_dropped_and_the_other_keeps_hearing() -> None:
    heard: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []

    def refusing(event: dict[str, Any]) -> None:
        broken.append(event)
        raise RuntimeError("Notion said 500")

    listen = execution._both(heard.append, refusing)
    listen({"n": 1})
    listen({"n": 2})
    assert heard == [{"n": 1}, {"n": 2}], "the journal hears every event"
    assert broken == [{"n": 1}], "the page is dropped after its first refusal"

    alone: list[dict[str, Any]] = []
    execution._both(alone.append, None)({"n": 3})
    assert alone == [{"n": 3}], "no live block: the journal alone"


@case
def a_second_try_carries_what_the_first_one_cost() -> None:
    first = _outcome(ok=False, error="lost", cost_usd=0.25, seconds=30.0, turns=3)
    then = _outcome(summary="Le second.", cost_usd=0.5, seconds=60.0, turns=7)
    added = execution._added(first, then)
    assert (added.cost_usd, added.seconds, added.turns) == (0.75, 90.0, 10)
    assert added.ok and added.summary == "Le second.", "everything else is the second try's"
    assert first.cost_usd == 0.25, "the first outcome is left as it was"


@case
def a_report_loses_its_trailing_result_lines_whatever_their_markup() -> None:
    answer = "Le bandeau est réparé.\n\nRESULT: dans le texte reste.\n\n**RESULT:** ok — fait\n# result: ok"
    assert execution._report(answer) == "Le bandeau est réparé.\n\nRESULT: dans le texte reste."
    assert execution._report("RESULT: ok — rien d'autre") == ""
    assert execution._report("") == "" and execution._report(None) == ""  # type: ignore[arg-type]


@case
def an_answer_file_is_read_stripped_and_a_missing_one_is_empty() -> None:
    workdir = Path(tempfile.mkdtemp())
    assert execution._answer(workdir) == "", "no ANSWER.md, no answer"
    (workdir / "ANSWER.md").write_bytes(b"\n  La r\xe9ponse.  \n\n")
    assert execution._answer(workdir) == "La r�ponse.", "bad bytes do not crash the ticket"


@case
def only_a_blocked_session_that_asks_nothing_on_a_ticket_spoken_on_has_answered_anyway() -> None:
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
def a_report_of_work_done_on_a_dashboard_is_told_from_one_about_the_code() -> None:
    assert execution._done_elsewhere("Variable ajoutée sur Dokploy, service redéployé.")
    assert not execution._done_elsewhere("Redéployé, après avoir corrigé le fichier app.py.")
    assert not execution._done_elsewhere("J'ai lu le ticket et je n'ai rien trouvé.")
    assert not execution._done_elsewhere("")


@case
def the_work_of_tickets_that_ended_without_a_commit_is_told_from_their_verdict() -> None:
    """The verdicts of the sessions blocked in session.no-commit over a month."""
    settled = (
        "Rien à changer : #142 a déjà réparé dev (FrankenPHP figé en 1.12) et sa CI est verte.",
        "Aucun changement : les deux clés i18n sont déjà corrigées sur main par #63, et les "
        "tests passent (702 OK) ; le ticket peut être clos.",
        "Rien à changer : le correctif est déjà fusionné sur main par la PR #32 (squash "
        "5a8c37a), avec ses tests et son changeset.",
        "Garde fusionnée dans db.open_at (#386) et base réparée par #364 : schéma 34.",
        "Les 3 PR (#347, #351, #353) sont rebasées, corrigées, CI verte et fusionnées ; les "
        "tickets sont en done, Blocage vidé.",
        "PR #364 rebasée sur main (`_occurrences` en dernier, console allégée sous 500 kB), "
        "CI verte, fusionnée ; après `ponos update`, la vraie base s'ouvre au schéma 30.",
        "Audit complet : le site et son code sont déjà corrects, pas de PR.",
        "Already fixed on main by #12.",
    )
    for summary in settled:
        assert execution._settled(summary), summary
    for outside in (
        "8 tickets créés vers react-resource-view 1.2.2 dans Master Tickets.",
        "Sitemaps envoyés et lus par Google, indexation demandée pour 8 pages publiques.",
    ):
        assert execution._done_elsewhere(outside), outside
    for unsettled in (
        "J'ai modifié src/x.py.",
        "J'ai modifié src/x.py, le bug #12 est corrigé.",
        "Le titre de la page est corrigé.",
        "J'ai lu le ticket et je n'ai rien trouvé.",
        "",
    ):
        assert not execution._settled(unsettled), unsettled
        assert not execution._done_elsewhere(unsettled), unsettled


# -- why a session died ----------------------------------------------------------


@case
def a_session_killed_by_a_signal_says_which_and_what_the_kernel_wrote() -> None:
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
def a_stream_cut_while_the_network_was_down_is_a_death_and_otherwise_is_not() -> None:
    runner, _, _ = _runner()
    cut = _outcome(ok=False, resulted=False, error="stream ended")
    with _Network(reachable=False):
        assert runner._died(cut) == runner.voice.say("killed-network")
    with _Network(reachable=True):
        assert runner._died(cut) == "", "the network was there: the session's own ending"


@case
def a_session_that_ended_by_itself_is_never_asked_about_the_network() -> None:
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
def a_killed_session_asks_to_be_run_again_and_a_blocked_one_asks_its_own_question() -> None:
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
def a_project_is_handed_the_secrets_it_is_granted_and_told_which_could_not_be_read() -> None:
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
def only_a_code_ticket_whose_remote_has_an_owner_is_handed_a_github_token() -> None:
    runner, _, _ = _runner()

    def no_git(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("git asked about a ticket that has no repository")

    asked: list[str] = []
    saved = github_token_module.session_environment

    def environment(owner: str) -> dict[str, str]:
        asked.append(owner)
        return {"GH_TOKEN": "t"}

    github_token_module.session_environment = environment
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
def a_document_session_is_asked_for_its_report_once_and_never_twice(state_home: Path) -> None:
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
def a_code_session_with_a_verdict_a_commit_or_a_change_has_its_report(state_home: Path) -> None:
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
def a_session_is_halted_only_when_it_stopped_and_somebody_asked(state_home: Path) -> None:
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
    assert _client(runner).written == [] and _client(runner).comments_written == [], (
        "nothing on the board: the ticket is the console's"
    )
    assert said == ["    ■ p-ticket — ended on request (pause)"]


def _killed_then(
    runner: Runner, job: ticket_module.Job, during: Callable[[], object]
) -> tuple[session.Outcome, list[Path]]:
    """`job`'s session killed by a signal, and `during` done in the pause before its relaunch."""
    from ponos import journal

    started: list[Path] = []

    def relaunched(job: ticket_module.Job, text: str, log: Path, *rest: Any) -> session.Outcome:
        started.append(log)
        return _outcome()

    runner._session = relaunched  # type: ignore[method-assign, assignment]  # a double: the relaunches are kept
    paused = time.sleep
    time.sleep = lambda seconds: during()  # type: ignore[assignment]  # a double: the pause does `during`
    try:
        with _Network():
            outcome = runner._relaunch(
                job,
                "text",
                Path("/logs/x.jsonl"),
                "",
                None,
                journal.Run(None),
                _outcome(ok=False, code=-9, resulted=False),
                "signal SIGKILL",
            )
    finally:
        time.sleep = paused
    return outcome, started


@case
def a_killed_session_whose_ticket_is_cancelled_in_the_pause_is_not_tried_again(
    state_home: Path,
) -> None:
    runner, page, _ = _runner({"cancelled": "cancelled"})
    job = _job(code=True, page=page)

    def cancel() -> None:
        # Moved on the board, under the page this run holds: Notion's copy, not ours.
        _client(runner)._pages = [_reviewed("p-ticket", "cancelled", None)]

    outcome, started = _killed_then(runner, job, cancel)
    assert started == [], "no session -again for a ticket somebody gave up on"
    assert outcome.killed == "signal SIGKILL" and not outcome.ok
    with _git_answering(remove_worktree=lambda repo, path: None):
        runner._code_stopped(job, outcome)
    assert [values for _, values in _client(runner).written if "statut" in values] == [], (
        "the ticket stays cancelled"
    )


@case
def a_killed_session_asked_to_stop_in_the_pause_is_not_tried_again(state_home: Path) -> None:
    runner, page, said = _runner()
    job = _job(page=page)
    outcome, started = _killed_then(runner, job, lambda: stopping.request(job.ticket.id, "abandon"))
    assert started == [], "the Stop came before the relaunch: there is none"
    assert runner._halted(job, outcome) is not None, "ended as the console's Stop ends it"
    assert stopping._file(job.ticket.id, "done").exists()
    stopping.clear(job.ticket.id)  # the console's, once it has the ticket

    runner, page, _ = _runner()
    outcome, started = _killed_then(runner, _job(page=page), lambda: None)
    assert len(started) == 1 and started[0].name == "x-again.jsonl", "nobody let go: tried again"


# -- a code ticket that did not get there -----------------------------------------


@case
def a_blocked_code_session_drops_its_worktree_unless_asked_to_keep_it(state_home: Path) -> None:
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
    said = _client(runner).comments_written[-1]
    assert str(kept.workdir) in said and "ticket/x" in said, said


@case
def a_code_session_killed_twice_is_blocked_on_its_cause(state_home: Path) -> None:
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    killed = _outcome(ok=False, killed="signal SIGKILL ; le réseau était injoignable")
    with _git_answering(remove_worktree=lambda repo, path: None):
        result = runner._code_stopped(job, killed)
    assert result["status"] == "blocked", "a kill is somebody's to look at, not a failure"
    said = _client(runner).comments_written[-1]
    assert "SIGKILL" in said and runner.voice.say("session-killed-question") in said, said


@case
def work_done_on_a_dashboard_with_nothing_committed_is_delivered_into_the_page(
    state_home: Path,
) -> None:
    runner, page, _ = _runner()
    bodies: list[str] = []

    def replace(page_id: str, titles: Sequence[str], markdown: str) -> int:
        bodies.append(markdown)
        return 1

    runner.client.replace_section = replace  # type: ignore[method-assign]  # a double: the part is kept
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
    assert _client(runner).written[-1][1]["statut"] == "done"
    assert runner.voice.say("done-elsewhere") in _client(runner).comments_written[-1]


@case
def files_left_uncommitted_block_the_ticket_and_keep_the_worktree(state_home: Path) -> None:
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    removed: list[Path] = []
    answer = "Service redéployé sur Dokploy."
    with _git_answering(
        is_dirty=lambda workdir: True, remove_worktree=lambda repo, path: removed.append(path)
    ):
        result = runner._nothing_committed(job, _outcome(answer=answer))
    assert result is not None and result["status"] == "blocked"
    assert removed == [], "the changes are there for somebody to commit"
    assert _client(runner).bodies == [], "nothing delivered"


@case
def a_report_that_claims_code_it_did_not_commit_is_blocked(state_home: Path) -> None:
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    removed: list[Path] = []
    answer = "J'ai corrigé le fichier src/app.py et redéployé sur Dokploy."
    with _git_answering(
        is_dirty=lambda workdir: False, remove_worktree=lambda repo, path: removed.append(path)
    ):
        result = runner._nothing_committed(job, _outcome(answer=answer, summary="Corrigé."))
    assert result is not None and result["status"] == "blocked"
    assert removed == [job.workdir], "a clean worktree holds nothing worth keeping"
    said = _client(runner).comments_written[-1]
    assert said.startswith("🙋") and "Corrigé." in said, "asked what became of the change"


# -- the branch, its push and its pull request ------------------------------------


@case
def a_refused_rebase_is_said_and_a_moved_head_counts_as_replayed(state_home: Path) -> None:
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
def a_push_github_refuses_fails_the_ticket_and_keeps_the_branch(state_home: Path) -> None:
    runner, page, _ = _runner()
    job = _job(code=True, page=page)
    refused = git_module.Result(
        1, "", "! [remote rejected] ticket/x (protected branch hook declined)"
    )
    with _git_answering(push=lambda *args, **kwargs: refused), _Network():
        result = runner._push_branch(job, _outcome(), force=False)
    assert result is not None and result["status"] == "failed"
    said = _client(runner).comments_written[-1]
    assert "protected branch hook declined" in said and "ticket/x" in said, said

    with _git_answering(push=lambda *args, **kwargs: git_module.Result(0, "", "")):
        assert runner._push_branch(job, _outcome(), force=True) is None


@case
def a_push_that_never_reached_github_is_not_a_refusal(state_home: Path) -> None:
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
    assert _client(runner).written == [] and _client(runner).comments_written == []

    with _git_answering(push=lambda *args, **kwargs: offline), _Network(reachable=True):
        result = runner._push_branch(job, _outcome(), force=False)
    assert result is not None and result["status"] == "failed", (
        "the network answers: GitHub's own refusal"
    )


@case
def a_pull_request_that_cannot_be_opened_is_said_on_the_ticket(state_home: Path) -> None:
    runner, page, said = _runner()
    job = _job(code=True, page=page)

    def refused(*args: Any, **kwargs: Any) -> str:
        raise git_module.GitError("gh: no default remote")

    with _git_answering(open_pull_request=refused):
        assert runner._open_pull_request(job, _outcome(), commits=2) == ""
    assert "gh: no default remote" in job.notes[-1]
    assert said[-1] == "    ! pull request not opened: gh: no default remote"

    titles: list[str] = []

    def opened(workdir: Path, title: str, body: str, base: str, accounts: Any = None) -> str:
        titles.append(title)
        return "https://github.com/x/y/pull/7"

    job.subtype = "chore"
    with _git_answering(open_pull_request=opened):
        assert runner._open_pull_request(job, _outcome(), commits=1).endswith("/pull/7")
    assert titles == ["chore: p-ticket"], "squashed, the title is the commit"


# -- a ticket with no repository --------------------------------------------------


@case
def a_document_session_that_wrote_no_answer_is_blocked_and_its_directory_removed(
    state_home: Path,
) -> None:
    runner, page, _ = _runner()
    job = _job(page=page)
    runner._run_session = lambda job, template: _outcome(summary="J'ai lu le ticket.")  # type: ignore[method-assign, misc, assignment]  # a double: no answer written
    result = runner._execute_document(job)
    assert result is not None and result["status"] == "blocked"
    assert not job.workdir.exists(), "nothing worth keeping"
    said = _client(runner).comments_written[-1]
    assert "ANSWER.md" in said and "J'ai lu le ticket." in said, said


@case
def an_answer_notion_refuses_fails_the_ticket_and_says_where_it_still_is(state_home: Path) -> None:
    runner, page, _ = _runner()
    job = _job(page=page)

    def refusing(page_id: str, titles: Sequence[str], text: str) -> None:
        raise notion.NotionError("PATCH /blocks: 502 bad gateway")

    runner.client.replace_section = refusing  # type: ignore[method-assign, assignment]  # a double: Notion refuses

    def answered(job: ticket_module.Job, template: str) -> session.Outcome:
        (job.workdir / "ANSWER.md").write_text("La réponse, entière.")
        return _outcome()

    runner._run_session = answered  # type: ignore[method-assign, assignment]  # a double: the answer is written
    result = runner._execute_document(job)
    assert result is not None and result["status"] == "failed"
    assert (job.workdir / "ANSWER.md").exists(), "the answer stays on disk"
    said = _client(runner).comments_written[-1]
    assert str(job.workdir / "ANSWER.md") in said and "502" in said, said


@case
def a_session_that_cannot_start_fails_the_document_ticket(state_home: Path) -> None:
    runner, page, _ = _runner()

    def missing(job: ticket_module.Job, template: str) -> session.Outcome:
        raise FileNotFoundError("claude: command not found")

    runner._run_session = missing  # type: ignore[method-assign, assignment]  # a double: no `claude`
    result = runner._execute_document(_job(page=page))
    assert result is not None and result["status"] == "failed"
    assert "claude: command not found" in _client(runner).comments_written[-1]


@case
def a_dry_run_starts_no_session() -> None:
    runner, page, said = _runner()
    runner.dry_run = True

    def no_session(*args: Any, **kwargs: Any) -> session.Outcome:
        raise AssertionError("a dry run starts nothing")

    runner._run_session = no_session  # type: ignore[method-assign]  # a double: never to be called
    job = _job(page=page)
    assert runner.execute(job) == {
        "ticket": "p-ticket",
        "id": job.ticket.id,
        "status": "dry-run",
    }
    runner.execute(_job(code=True, page=page))
    assert said == ["    (dry run) document", "    (dry run) ticket/x from main"]


# -- the session itself -----------------------------------------------------------


def _sessions(runner: Runner, *outcomes: session.Outcome) -> list[dict[str, Any]]:
    """`_paid`, answering with `outcomes` in turn; records how each was asked."""
    asked: list[dict[str, Any]] = []
    queue = list(outcomes)

    def paid(ticket: str, prompt_text: str, **options: Any) -> session.Outcome:
        asked.append({"prompt": prompt_text, **options})
        return queue.pop(0)

    runner._paid = paid  # type: ignore[method-assign, assignment]  # a double: the outcomes above, in turn
    runner.config.runner.progress = False
    return asked


@case
def a_resumed_session_claude_no_longer_has_starts_afresh_on_a_log_of_its_own(
    state_home: Path,
) -> None:
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
def a_session_that_forgot_its_answer_is_picked_up_once_to_write_it(state_home: Path) -> None:
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


# -- the project's setup, before the session ---------------------------------------


def _prepared(
    runner: Runner, job: ticket_module.Job
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """`_prepare_worktree` with `_fail` recorded rather than written: what it was told."""
    failed: list[dict[str, Any]] = []

    def fail(
        ticket: ticket_module.Ticket, reason: str, detail: str = "", **rest: Any
    ) -> dict[str, Any]:
        failed.append({"reason": reason, "detail": detail, **rest})
        return {"failed": True}

    runner._fail = fail  # type: ignore[method-assign]  # a double: what it was told is kept
    job.workdir.mkdir(parents=True, exist_ok=True)
    job.log = job.workdir.parent / "run.jsonl"
    return runner._prepare_worktree(job), failed


@case
def a_project_setup_runs_in_the_worktree_before_the_session_and_the_session_is_told(
    state_home: Path,
) -> None:
    from ponos import project_settings

    runner, _, said = _runner()
    job = _job(code=True)
    job.project.notion_id = "proj-1"
    project_settings.set_setup("proj-1", "Northwind", "echo prepared > node_modules.txt")
    done, failed = _prepared(runner, job)
    assert done is None and not failed
    assert (job.workdir / "node_modules.txt").read_text() == "prepared\n", "run in the worktree"
    assert "Do not run the installation again" in job.prepared
    assert "echo prepared" in job.prepared
    assert (job.workdir.parent / "run.setup.log").is_file(), "its output is in a log of its own"
    assert any("setup (project)" in line for line in said), said


@case
def a_project_without_a_setup_starts_its_session_as_before(state_home: Path) -> None:
    runner, _, _ = _runner()
    job = _job(code=True)
    job.project.notion_id = "proj-1"
    done, failed = _prepared(runner, job)
    assert done is None and not failed and job.prepared == ""
    assert not (job.workdir.parent / "run.setup.log").exists()


@case
def the_repository_setup_script_runs_when_the_project_has_no_command_and_loses_to_it(
    state_home: Path,
) -> None:
    from ponos import project_settings

    runner, _, _ = _runner()
    job = _job(code=True)
    job.project.notion_id = "proj-1"
    job.workdir.mkdir(parents=True)
    (job.workdir / ".ponos").mkdir()
    (job.workdir / ".ponos" / "setup.sh").write_text("echo from-script > ran.txt\n")
    done, failed = _prepared(runner, job)
    assert done is None and not failed
    assert (job.workdir / "ran.txt").read_text() == "from-script\n"

    (job.workdir / "ran.txt").unlink()
    project_settings.set_setup("proj-1", "Northwind", "echo from-project > ran.txt")
    _prepared(runner, job)
    assert (job.workdir / "ran.txt").read_text() == "from-project\n", "the project's word first"


@case
def a_setup_that_fails_blocks_the_ticket_with_the_end_of_its_output_and_no_session(
    state_home: Path,
) -> None:
    from ponos import project_settings

    runner, _, _ = _runner()
    runner.config.runner.keep_worktree_on_failure = True
    job = _job(code=True)
    job.project.notion_id = "proj-1"
    project_settings.set_setup(
        "proj-1", "Northwind", "echo installing; echo 'ERR! no lockfile'; exit 3"
    )
    done, failed = _prepared(runner, job)
    assert done == {"failed": True}
    assert len(failed) == 1
    stop = failed[0]
    assert stop["code"] == "worktree.setup-failed" and stop["blocked"] is True
    assert "exit 3" in stop["detail"] and "ERR! no lockfile" in stop["detail"]
    assert job.prepared == "", "the session is not told it was prepared"
    assert stop["question"], "a blocked ticket asks what to do"


@case
def a_setup_secret_is_given_to_the_command_and_masked_in_what_the_ticket_shows(
    state_home: Path,
) -> None:
    from ponos import project_settings

    runner, _, _ = _runner()
    runner.config.runner.keep_worktree_on_failure = True
    job = _job(code=True)
    job.project.notion_id = "proj-1"
    runner.config.vault.projects = {"northwind": {"NPM_TOKEN": "PONOS_TEST_SETUP_SECRET"}}
    os.environ["PONOS_TEST_SETUP_SECRET"] = "npm_setup_case_0123456789"
    project_settings.set_setup("proj-1", "Northwind", 'echo "token=$NPM_TOKEN"; exit 1')
    try:
        done, failed = _prepared(runner, job)
    finally:
        os.environ.pop("PONOS_TEST_SETUP_SECRET", None)
    assert done and "npm_setup_case_0123456789" not in failed[0]["detail"], failed[0]["detail"]


@case
def a_setup_that_outlasts_its_time_is_killed_and_said_so(state_home: Path) -> None:
    from ponos import worktree_setup

    root = Path(tempfile.mkdtemp())
    saved = subprocess.Popen.wait

    def impatient(self: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        if timeout:
            raise subprocess.TimeoutExpired("sleep", timeout)
        return saved(self)

    subprocess.Popen.wait = impatient  # type: ignore[method-assign, assignment]  # a double: a wait that times out
    try:
        ran = worktree_setup.run(
            worktree_setup.plan("sleep 30", root), root, root / "s.log", timeout_minutes=1
        )
    finally:
        subprocess.Popen.wait = saved  # type: ignore[method-assign]  # the double taken off
    assert not ran.ok and ran.timed_out
    assert "stopped after 1 minutes" in (root / "s.log").read_text()
