"""`stopping.py`: a ticket's session ended from the console, and what the console does after."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

from support import _bare_api, _bare_runner, _ColumnsClient, case

from ponos import git as git_module
from ponos import notion, session, state, stopping
from ponos import ticket as ticket_module
from ponos.config import state_dir
from ponos.projects import Project

TICKET = "1" * 32


@case
def a_request_is_read_until_it_goes_stale_and_cleared_by_the_console(state_home):
    assert stopping.requested(TICKET) == ""
    stopping.request(TICKET, "pause")
    assert stopping.requested("11111111-1111-1111-1111-111111111111") == "pause"
    old = time.time() - stopping.STALE_SECONDS - 1
    os.utime(state_dir() / "stops" / f"{TICKET}.ask", (old, old))
    assert stopping.requested(TICKET) == "", "a leftover must not stop the next session at birth"
    stopping.request(TICKET, "abandon")
    stopping.acknowledge(TICKET)
    assert stopping.wait(TICKET, 0) is True
    stopping.clear(TICKET)
    assert stopping.requested(TICKET) == "" and stopping.wait(TICKET, 0) is False


@case
def a_session_is_told_to_stop_when_its_ticket_is_asked_for_and_not_before(state_home):
    over = threading.Event()
    asked = stopping.watch(TICKET, over)
    assert stopping.held(TICKET), "the console only waits for a session that is there"
    assert not asked.wait(0.2)
    stopping.request(TICKET, "pause")
    assert asked.wait(5), "a request is seen while the session runs"
    over.set()
    deadline = time.time() + 5
    while stopping.held(TICKET) and time.time() < deadline:
        time.sleep(0.05)
    assert not stopping.held(TICKET), "the mark goes with the session"

    # A request made before the session began ends it as it starts.
    again = threading.Event()
    assert stopping.watch(TICKET, again).wait(5)
    again.set()


@case
def a_mark_left_by_a_run_that_died_is_no_session(state_home):
    path = state_dir() / "stops" / f"{TICKET}.live"
    path.parent.mkdir(parents=True)
    path.write_text("2147483646")
    assert not stopping.held(TICKET)
    path.write_text(str(os.getpid()))
    assert stopping.held(TICKET)


@case
def a_worktree_stopped_mid_work_is_saved_on_its_branch_and_a_clean_one_is_left_alone():
    with tempfile.TemporaryDirectory() as home:
        repo = Path(home) / "repo"
        repo.mkdir()
        for step in (
            ["init", "-q", "-b", "main"],
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
        ):
            assert git_module.git(step, repo).ok
        (repo / "a.txt").write_text("one")
        assert git_module.git(["add", "."], repo).ok
        assert git_module.git(["commit", "-qm", "first"], repo).ok
        path = Path(home) / "worktrees" / "site-9d2cb790"
        git_module.add_worktree(repo, path, "ticket/x-9d2cb790", "main")
        assert git_module.save(path, "saved") is False, "nothing to save"
        (path / "b.txt").write_text("half done")
        assert git_module.save(path, "saved") is True
        assert not git_module.is_dirty(path) and git_module.commits_ahead(path, "main") == 1
        # The next session of that ticket picks the worktree up as it stands.
        again = git_module.add_worktree(repo, path, "ticket/x-9d2cb790", "main")
        assert again.reused and again.why == "held" and again.carried == 1


class _Running(_ColumnsClient):
    """A board with one ticket in progress, and what was written on it."""

    def __init__(
        self, status: str = "In progress", options: tuple[str, ...] = ("Paused", "Cancelled")
    ) -> None:
        super().__init__([status])
        self.status = status
        self.extra = list(options)
        self.comments_written: list[tuple[str, str]] = []

    def options(self, database: str, prop: str) -> list[str]:
        return [*super().options(database, prop), *self.extra]

    def page(self, page_id: str, **rest) -> notion.Page:
        return notion.Page(
            id=page_id,
            url="",
            title="ticket",
            properties={"Status": {"type": "status", "status": {"name": self.status}}},
            raw={},
        )

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.comments_written.append((page_id, text))


def _console(client: _Running):
    api = _bare_api(client)
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api.watch = type("W", (), {"nudge": lambda self: None})()
    api._schema_at = time.time()
    api.reader.hold(client.page(TICKET))  # the card the console last read
    return api


def _scratch(name: str = "notes-11111111") -> Path:
    path = state_dir() / "scratch" / name
    path.mkdir(parents=True)
    (path / "ANSWER.md").write_text("draft")
    return path


@case
def a_ticket_in_progress_is_paused_with_its_work_kept_and_one_short_line(state_home):
    client = _Running()
    api = _console(client)
    path = _scratch()
    state.claim(TICKET, "Ready")
    answered = api.set_status(TICKET, "paused")
    assert answered["status"] == "Paused", answered
    assert path.exists(), "pausing keeps what was done"
    assert client.comments_written == [(TICKET, "Paused")], client.comments_written
    assert state.claims() == {}, "the sweep must not put a paused ticket back to ready"
    assert stopping.requested(TICKET) == "", "the request is the console's to clear"


@case
def a_ticket_is_abandoned_with_its_directory_removed_and_never_left_as_residue(state_home):
    client = _Running()
    api = _console(client)
    path = _scratch()
    assert api.set_status(TICKET, "cancelled")["status"] == "Cancelled"
    assert not path.exists()
    assert client.comments_written == [(TICKET, "Abandoned")]


@case
def the_console_waits_for_the_session_to_be_gone_before_it_touches_the_worktree(state_home):
    api = _console(_Running())
    path = _scratch()
    seen: list[bool] = []
    over = threading.Event()
    stopping.watch(TICKET, over)  # a session of this very process, so it counts as held

    def run() -> None:
        # The run: sees the request, ends the session, and only then says so.
        while not stopping.requested(TICKET):
            time.sleep(0.05)
        time.sleep(0.3)
        seen.append(path.exists())
        over.set()
        stopping.acknowledge(TICKET)

    thread = threading.Thread(target=run)
    thread.start()
    started = time.monotonic()
    api.set_status(TICKET, "cancelled")
    thread.join()
    assert seen == [True], "the worktree was still there while the session ended"
    assert not path.exists() and time.monotonic() - started >= 0.3


@case
def a_ticket_that_is_not_in_progress_is_only_moved_and_no_session_is_asked_to_stop(state_home):
    client = _Running("Ready")
    api = _console(client)
    assert api.set_status(TICKET, "paused")["sync"] == "pending"
    assert stopping.requested(TICKET) == "" and client.comments_written == []
    # Or a card dragged there that still shows the status it was in.
    stale = _console(_Running())
    stale.set_status(TICKET, "cancelled", "Ready")
    assert stale.runner.client.comments_written == []


@case
def a_board_without_the_option_is_never_written_into_and_does_not_offer_it(state_home):
    for options, key, word in (
        (("Cancelled",), "paused", "no “Paused” option"),
        (("Paused",), "cancelled", "no “Cancelled” option"),
    ):
        try:
            _console(_Running(options=options)).set_status(TICKET, key)
        except ValueError as error:
            assert word in str(error), error
        else:
            raise AssertionError(f"a ticket was moved into a status the board lacks: {key}")
    columns = lambda client: [item["key"] for item in _console(client).board()["columns"]]  # noqa: E731
    assert "paused" in columns(_Running())
    assert "paused" not in columns(_Running(options=("Cancelled",)))


@case
def a_session_the_console_asked_to_end_is_ended_and_left_to_the_console(state_home):
    ended: list[bool] = []

    def fake_run(prompt, **options):
        # What session.run does with its `stop`: it ends the session when it is set.
        ended.append(options["stop"].wait(5))
        return session.Outcome(
            ok=False,
            blocked=False,
            session_id="s",
            summary="",
            log=Path("/dev/null"),
            error="stopped",
            stopped=True,
            resulted=False,
        )

    runner = _bare_runner(None)
    job = ticket_module.Job(
        ticket_module.Ticket(notion.Page(id="1" * 32, url="", title="ticket")),
        Project(name="p", path=None),
        "",
        "",
        Path("/nowhere"),
    )
    original, session.run = session.run, fake_run
    try:
        # Nobody asked: a session that stops anyway is nothing this method owns.
        assert (
            runner._halted(
                job, session.Outcome(False, False, "s", "", Path("/dev/null"), stopped=True)
            )
            is None
        )
        stopping.request(TICKET, "pause")
        outcome = runner._paid(TICKET, "work")
    finally:
        session.run = original
    assert ended == [True] and outcome.stopped
    state.claim(TICKET, "Ready")
    result = runner._halted(job, outcome)
    assert result and result["status"] == "stopped" and result["reason"] == "pause", result
    assert stopping.wait(TICKET, 0), "the console is told the session is gone"
    assert state.claims() == {}
    # A session that finished before the request reached it keeps its own road.
    ok = session.Outcome(True, False, "s", "done", Path("/dev/null"))
    assert runner._halted(job, ok) is None
