"""`journal.py`: the run journal."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import tempfile
from pathlib import Path

from support import case

from ponos import db, journal, models, notion, state
from ponos import ticket as ticket_module
from ponos.__main__ import main as cli_main
from ponos.runner import Runner
from ponos.web import api as web_api

# -- the run journal ---------------------------------------------------------


def _said_event(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _tool_event(name: str, payload: dict) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": payload}]},
    }


@case
def a_file_at_schema_version_one_gets_the_tool_and_cost_columns_and_keeps_its_steps():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    old = db.open_at(location, db.MIGRATIONS[:1])
    old.execute("INSERT INTO runs (ticket, started_at) VALUES ('t', 'now')")
    old.execute(
        "INSERT INTO steps (run, position, at, kind, text) VALUES (1, 1, 'now', 'said', 'kept')"
    )
    old.close()
    upgraded = db.open_at(location)
    try:
        assert db.version(upgraded) == len(db.MIGRATIONS) >= 2
        assert upgraded.execute("SELECT kind, text, tool, cost_usd FROM steps").fetchall() == [
            ("said", "kept", "", None)
        ]
    finally:
        upgraded.close()


@case
def a_model_is_said_as_provider_slash_model_wherever_it_is_shown():

    said = {
        "opus": "claude/opus",
        "Sonnet": "claude/sonnet",
        "haiku": "claude/haiku",
        "opus[1m]": "claude/opus",
        "claude-opus-4-1-20250805": "claude/opus",
        "claude-sonnet-4-5-20250929": "claude/sonnet",
        "claude-3-5-haiku-20241022": "claude/haiku",
        "claude-fable-5-1": "claude/fable",
        "deepseek-reasoner": "deepseek/r1",
        "deepseek-r1": "deepseek/r1",
        "DeepSeek-R1-0528": "deepseek/r1",
        "deepseek-chat": "deepseek/v3",
        "openrouter/auto": "openrouter/auto",
        "deepseek/deepseek-r1": "deepseek/deepseek-r1",
        "anthropic/claude-opus-4": "anthropic/claude-opus-4",
        "gpt-9": "gpt-9",
        "": "",
        "  ": "",
    }
    for given, expected in said.items():
        assert models.label(given) == expected, (given, models.label(given))


@case
def the_model_of_a_ticket_is_the_sessions_word_then_the_column_then_the_defaults():

    settings = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json"
    before = os.environ.pop("ANTHROPIC_MODEL", None)
    try:
        settings.unlink(missing_ok=True)
        # Nothing says: honest, not invented.
        assert models.describe("") == {"label": "", "full": "", "default": True}
        # Claude Code's own setting, when it has one.
        settings.write_text('{"model": "opus"}', encoding="utf-8")
        assert models.describe("") == {"label": "claude/opus", "full": "opus", "default": True}
        # The runner's configuration comes first.
        assert models.describe("", configured="sonnet")["label"] == "claude/sonnet"
        # The session's own word beats the rest, and the default stays said.
        found = models.describe("", "claude-haiku-4-5-20251001", "sonnet")
        assert found == {
            "label": "claude/haiku",
            "full": "claude-haiku-4-5-20251001",
            "default": True,
        }
        # A column chosen is not a default.
        assert models.describe("haiku", configured="opus") == {
            "label": "claude/haiku",
            "full": "haiku",
            "default": False,
        }
        # A settings file that is not JSON is nobody knowing.
        settings.write_text("not json", encoding="utf-8")
        assert models.claude_default() == ""
    finally:
        settings.unlink(missing_ok=True)
        if before is not None:
            os.environ["ANTHROPIC_MODEL"] = before


@case
def a_run_keeps_the_model_its_session_announced(state_home):
    try:
        run = journal.Run.start(ticket="d" * 32, model="opus")
        run.event({"type": "system", "subtype": "init", "model": "claude-opus-4-1-20250805"})
        (found,) = journal.runs("d" * 32)
        assert (found["model"], found["reported"]) == ("opus", "claude-opus-4-1-20250805")
    finally:
        db.close()


@case
def a_run_is_written_step_by_step_and_closed_on_what_the_ticket_came_to(state_home):
    try:
        ticket = "3ed45168-0af4-8134-a677-f7f1e9024ae5"
        run = journal.Run.start(
            ticket=ticket, title="Journal", project="Ponos", session="s1", log="/x/a.jsonl"
        )
        assert run.open
        run.event({"type": "system", "subtype": "init"})
        run.event(_said_event("I read the brief."))
        run.event(_tool_event("Bash", {"command": "python3 tests/run.py"}))
        run.event(
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "is_error": True, "content": "exit 1"}]
                },
            }
        )
        run.event({"type": "result", "total_cost_usd": 0.25})
        run.again("s2", "/x/a-again.jsonl")
        run.event(_tool_event("Read", {"file_path": "/repo/a.py"}))
        run.event({"type": "result", "total_cost_usd": 0.5})

        (found,) = journal.runs("e9024ae5")
        assert found["ticket"] == ticket.replace("-", "")
        assert found["status"] is None and found["ended_at"] is None, "still going"
        assert found["session"] == "s2" and found["log"] == "a-again.jsonl"
        assert found["cost_usd"] == 0.75 and found["steps"] == 4
        assert journal.runs(f"https://app.notion.com/p/Journal-{ticket.replace('-', '')}") == [
            found
        ]

        run.end("done", "https://github.com/o/r/pull/1")
        run.end("failed", "too late: a run is closed once")
        (closed,) = journal.runs(ticket)
        assert closed["status"] == "done" and closed["reason"] == "https://github.com/o/r/pull/1"
        assert closed["ended_at"]

        steps = journal.steps(closed["id"])["steps"]
        assert [(step["kind"], step["label"], step["detail"], step["said"]) for step in steps] == [
            ("said", "I read the brief.", "", True),
            ("tool", "Bash", "python3 tests/run.py", False),
            ("error", "Error", "exit 1", False),
            ("tool", "Read", "/repo/a.py", False),
        ], steps
        assert [step["position"] for step in steps] == [1, 2, 3, 4]
        assert "cost_usd" not in steps[0] and steps[3]["cost_usd"] == 0.25, "the cost known then"
    finally:
        db.close()


@case
def a_run_is_read_a_page_at_a_time_from_its_end(state_home):
    try:
        run = journal.Run.start(ticket="a" * 32)
        for index in range(1, 451):
            run.event(_tool_event("Read", {"file_path": f"/f{index}"}))
        last = journal.steps(run.id)
        assert last["count"] == 450 and last["more"]
        assert [step["position"] for step in last["steps"]] == list(range(251, 451))
        before = journal.steps(run.id, before=251)
        assert [step["position"] for step in before["steps"]] == list(range(51, 251)) and before[
            "more"
        ]
        first = journal.steps(run.id, before=51)
        assert [step["position"] for step in first["steps"]] == list(range(1, 51)) and not first[
            "more"
        ]
        after = journal.steps(run.id, after=440)
        assert [step["position"] for step in after["steps"]] == list(range(441, 451))
        assert journal.steps(run.id, after=450)["steps"] == []
    finally:
        db.close()


@case
def a_journal_that_cannot_be_written_never_stops_a_ticket(state_home):
    state_home.mkdir(parents=True, exist_ok=True)
    (state_home / "ponos.db").write_bytes(b"this is not a database" * 100)
    said: list[str] = []
    try:
        run = journal.Run.start(ticket="a" * 32, say=said.append)
        assert not run.open
        run.event(_said_event("nothing to write it into"))
        run.end("done")
        assert len(said) == 1 and "run journal off" in said[0], said
    finally:
        db.close()


@case
def every_road_out_of_a_ticket_closes_its_run(state_home):
    from ponos.execution import _both

    try:
        runner = Runner.__new__(Runner)
        runner._journals = {}
        ticket = ticket_module.Ticket(notion.Page(id="b" * 32, url="", title="t"))
        runner._journals[ticket.id] = journal.Run.start(ticket=ticket.id)
        result = {
            "ticket": "t",
            "id": ticket.id,
            "status": "blocked",
            "reason": "which header?",
        }
        assert runner._guarded(ticket, lambda: result) is result
        (closed,) = journal.runs(ticket.id)
        assert (closed["status"], closed["reason"]) == ("blocked", "which header?")
        assert not runner._journals, "closed once, and forgotten"
        # A ticket's work that ran no session has no run to close.
        assert runner._guarded(ticket, lambda: None) is None
    finally:
        db.close()

    heard: list[dict] = []

    def broken(event: dict) -> None:
        raise RuntimeError("Notion is down")

    listen = _both(heard.append, broken)
    with contextlib.redirect_stdout(io.StringIO()):
        listen({"n": 1})
        listen({"n": 2})
    assert heard == [{"n": 1}, {"n": 2}], "the page failing does not cost the journal its steps"


@case
def the_console_reads_a_tickets_runs_and_their_steps_from_the_journal(state_home):
    try:
        api = web_api.Api.__new__(web_api.Api)
        older = journal.Run.start(ticket="c" * 32, title="first")
        older.event(_said_event("one"))
        older.end("failed", "crashed")
        newer = journal.Run.start(ticket="c" * 32, title="second")
        newer.event(_tool_event("Bash", {"command": "ls"}))
        runs = api.runs("c" * 32)["runs"]
        assert [run["title"] for run in runs] == ["second", "first"]
        page = api.run_steps(newer.id)
        assert page["ended"] is False and page["count"] == 1
        assert page["steps"][0]["label"] == "Bash" and page["steps"][0]["detail"] == "ls"
        assert api.run_steps(older.id)["ended"] is True
        try:
            api.run_steps(999)
        except LookupError:
            pass
        else:
            raise AssertionError("an unknown run is a 404")
    finally:
        db.close()


@case
def ponos_logs_lists_a_tickets_runs_from_the_journal(state_home):
    try:
        run = journal.Run.start(
            ticket="d" * 32, title="A ticket", log=state.logs_dir() / "x-dddddddd.jsonl"
        )
        run.event(_said_event("hello"))
        run.event({"type": "result", "total_cost_usd": 1.5})
        run.end("blocked", "which header?")
        (state.logs_dir() / "x-dddddddd.jsonl").write_text("", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert cli_main(["logs", "dddddddd", "--runs"]) == 0
        text = out.getvalue()
        assert "blocked" in text and "A ticket" in text and "1 steps" in text and "$1.50" in text, (
            text
        )
        assert "which header?" in text and "x-dddddddd.jsonl" in text, text
    finally:
        db.close()


@case
def ponos_logs_service_prints_the_end_of_the_runners_own_journal(state_home):
    """`ponos logs --service` reads ponos.log — which the command itself opened."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli_main(["logs", "--service"]) == 0
        logging.getLogger("ponos.test").warning("the board is slow today")
        assert cli_main(["logs", "--service"]) == 0
    text = out.getvalue()
    assert "WARNING ponos.test: the board is slow today" in text, text
