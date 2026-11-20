"""`forks.py`: a ticket started again from one step of an earlier run."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from support import case

from ponos import db, forks, journal, prompt, session
from ponos.web import api as web_api

TICKET = "f" * 32


def _said(uuid: str, text: str, parent: str | None = None) -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "parent_tool_use_id": parent,
        "message": {"content": [{"type": "text", "text": text}]},
    }


def _call(uuid: str, call: str, command: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "message": {
            "content": [
                {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}}
            ]
        },
    }


def _result(uuid: str, call: str, error: bool = False) -> dict[str, Any]:
    return {
        "type": "user",
        "uuid": uuid,
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": call, "content": "no", "is_error": error}
            ]
        },
    }


@contextmanager
def _transcript(session_id: str, *uuids: str) -> Iterator[None]:
    """A ~/.claude/projects of the case's own, holding one session with these messages."""
    original = session.PROJECTS
    with tempfile.TemporaryDirectory() as tmp:
        session.PROJECTS = Path(tmp)
        folder = session.PROJECTS / "-work-app"
        folder.mkdir()
        (folder / f"{session_id}.jsonl").write_text(
            "".join(f'{{"type":"assistant","uuid":"{uuid}"}}\n' for uuid in uuids)
        )
        try:
            yield
        finally:
            session.PROJECTS = original


def _anchors(run: int) -> list[str]:
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT anchor FROM steps WHERE run = ? ORDER BY position", (run,)
        ).fetchall()
    return [str(row[0]) for row in rows]


@case
def a_step_is_anchored_on_its_message_and_a_call_on_its_result(state_home: Path) -> None:
    try:
        run = journal.Run.start(ticket=TICKET, session="s-1")
        assert run.id is not None
        run.event(_said("u-1", "I look first."))
        run.event(_call("u-2", "call-a", "ls"))
        run.event(_result("u-3", "call-a"))
        run.event(_said("u-4", "A subagent's word.", parent="call-x"))
        run.event(_call("u-5", "call-b", "false"))
        run.event(_result("u-6", "call-b", error=True))
        assert _anchors(run.id) == ["u-1", "u-3", "", "u-6", "u-6"]
        steps = journal.steps(run.id)["steps"]
        assert [step["forkable"] for step in steps] == [True, True, False, True, True]
    finally:
        db.close()


@case
def a_branch_is_refused_where_no_session_can_start_and_kept_until_taken(state_home: Path) -> None:
    try:
        run = journal.Run.start(ticket=TICKET, session="s-1")
        assert run.id is not None
        run.event(_said("u-1", "One."))
        run.event(_said("u-2", "A subagent's.", parent="call-x"))

        def refused(position: int) -> str:
            try:
                forks.ask(run.id or 0, position)
            except forks.Refused as error:
                return str(error)
            raise AssertionError("asked")

        assert "still going" in refused(1)
        run.end("failed", "crashed")
        assert "cannot start from this step" in refused(2)
        assert "no longer on this machine" in refused(1), "no transcript, nothing to cut"
        try:
            forks.ask(999, 1)
        except LookupError:
            pass
        else:
            raise AssertionError("an unknown run is not found")
        assert forks.pending(TICKET) is None

        with _transcript("s-1", "u-1"):
            asked = forks.ask(run.id, 1, "  This time, by the API.  ")
        assert asked == forks.Fork(TICKET, run.id, 1, "s-1", "u-1", "This time, by the API.")
        assert forks.pending(TICKET) == asked
        with _transcript("s-1", "u-1"):
            forks.ask(run.id, 1)
        assert forks.pending(TICKET) == forks.Fork(TICKET, run.id, 1, "s-1", "u-1", ""), (
            "asked twice, the second replaces the first"
        )
        forks.forget(TICKET)
        assert forks.pending(TICKET) is None
    finally:
        db.close()


@case
def a_branched_session_is_a_copy_of_the_other_cut_at_its_message() -> None:
    command = session._command(
        "claude",
        "s-new",
        resume=False,
        permission_mode="default",
        model="",
        max_budget_usd=0,
        fork=("s-old", "u-12"),
    )
    at = command.index("--resume")
    assert command[at : at + 7] == [
        "--resume",
        "s-old",
        "--fork-session",
        "--session-id",
        "s-new",
        "--resume-session-at",
        "u-12",
    ]
    assert command.count("--session-id") == 1


@case
def a_branched_session_is_told_the_message_and_that_the_files_were_not_taken_back() -> None:
    said = prompt.fork("Use the API.", "Write in French.")
    assert "What they ask you to do this time:\n\nUse the API." in said
    assert "The files were not taken back" in said and "git status" in said
    assert said.rstrip().endswith("Write in French.")
    assert "They added nothing" in prompt.fork("")


class _Console(web_api.Api):
    """The console's API with a board of one ticket, in the column `status`."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.moved: list[tuple[str, str]] = []

    @property
    def config(self) -> Any:
        # The one name read: the column of a ticket in progress.
        return SimpleNamespace(
            board=SimpleNamespace(state=lambda key: {"running": "In progress"}.get(key, key))
        )

    def _status_of(self, page_id: str) -> str:
        return self.status

    def set_status(self, page_id: str, key: str, seen: str | None = None) -> dict[str, Any]:
        self.moved.append((page_id, key))
        return {"id": page_id, "status": "Ready", "sync": "pending"}


@case
def the_console_starts_a_ticket_again_from_a_step_and_puts_it_back_in_ready(
    state_home: Path,
) -> None:
    try:
        run = journal.Run.start(ticket=TICKET, session="s-1")
        assert run.id is not None
        run.event(_said("u-1", "One."))
        run.end("blocked", "a question")

        running = _Console("In progress")
        try:
            running.fork(run.id, 1)
        except forks.Refused as error:
            assert "in progress" in str(error)
        else:
            raise AssertionError("a ticket in progress is stopped first")
        assert running.moved == [] and forks.pending(TICKET) is None

        console = _Console("Blocked")
        with _transcript("s-1", "u-1"):
            answered = console.fork(run.id, 1, "Otherwise.")
        assert answered == {"ticket": TICKET, "run": run.id, "position": 1, "status": "Ready"}
        assert console.moved == [(TICKET, "ready")]
        assert forks.pending(TICKET) is not None
        assert console.runs(TICKET)["runs"][0]["parent"] is None
    finally:
        db.close()
