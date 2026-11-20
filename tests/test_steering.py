"""`steering.py`: a message to a session that runs, handed over by its hooks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from support import _bare_api, _TalkClient, case

from ponos import progress, session, state, steering

TICKET = "d4b5bdf61a2744d3a3175cbff0541215"

# What Claude Code does with the hooks of `--settings`, as much as steering needs
# of it: after a tool call it runs the PostToolUse ones and reads their output
# into its context, and when it would stop it runs the Stop ones, and a `block`
# keeps it going. It writes what the hooks said into its stream.
FAKE = """#!{python}
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
sys.stdin.read()
hooks = json.loads(args[args.index("--settings") + 1])["hooks"]
home = Path({home!r})


def emit(event):
    print(json.dumps(event), flush=True)


def run(name):
    command = hooks[name][0]["hooks"][0]["command"]
    done = subprocess.run(command, shell=True, input="{{}}", capture_output=True, text=True)
    return json.loads(done.stdout) if done.stdout.strip() else {{}}


emit({{"type": "assistant", "message": {{"content": [
    {{"type": "tool_use", "id": "t1", "name": "Read", "input": {{"file_path": "wrong.py"}}}}]}}}})
(home / "ready").write_text("")
while not (home / "go").exists():
    time.sleep(0.02)
seen = run("PostToolUse")
emit({{"type": "assistant", "message": {{"content": [
    {{"type": "text", "text": "after the tool: " + json.dumps(seen)}}]}}}})
for turn in range(3):
    stopped = run("Stop")
    if not stopped:
        break
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "text", "text": "kept going: " + json.dumps(stopped)}}]}}}})
emit({{"type": "result", "result": "RESULT: ok — done", "session_id": "s", "num_turns": 2}})
"""


def _fake(home: Path) -> str:
    (home / "claude").write_text(FAKE.format(python=sys.executable, home=str(home)))
    (home / "claude").chmod(0o755)
    previous = os.environ["PATH"]
    os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
    return previous


@case
def a_message_sent_while_the_session_runs_reaches_the_agent_and_the_journal(
    state_home: Path,
) -> None:
    """A correction after the tool call under way, a follow-up before the session closes."""
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        previous = _fake(home)
        events: list[dict[str, Any]] = []
        sent: list[str] = []

        def talk() -> None:
            deadline = time.monotonic() + 20
            while not (home / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            sent.append(steering.route(TICKET, "non, utilise plutôt right.py", "comment 1"))
            sent.append(
                steering.route(TICKET, "puis lance les tests", "comment 2", steering.FOLLOW)
            )
            (home / "go").write_text("")

        speaker = threading.Thread(target=talk)
        speaker.start()
        try:
            outcome = session.run(
                "work",
                cwd=home,
                log=home / "run.jsonl",
                timeout_minutes=1,
                session_id="0486a9fd-44f6-4fff-9dee-9e58bc4062ba",
                steerable=True,
                on_event=events.append,
                track=lambda handle: state.track_session(
                    handle.session_id, TICKET, handle.to_json(), "job"
                ),
            )
        finally:
            speaker.join()
            os.environ["PATH"] = previous
        assert outcome.ok, outcome.error
        assert sent == [steering.STEER, steering.FOLLOW], sent
        said = [
            block["text"]
            for one in events
            if one.get("type") == "assistant"
            for block in one["message"]["content"]
            if block.get("type") == "text"
        ]
        # The correction came with the tool's result; the follow-up kept the session going.
        assert "right.py" in said[0] and "puis lance les tests" not in said[0], said
        assert "puis lance les tests" in said[1] and "block" in said[1], said
        # And both are in the journal's feed, in order, as steps.
        messages = [one for one in events if one.get("type") == "ponos"]
        assert [one["mode"] for one in messages] == [steering.STEER, steering.FOLLOW], messages
        steps = [step for one in messages for step in progress.describe(one)]
        assert [step.label for step in steps] == ["Message", "Message"], steps
        assert steps[0].detail == "non, utilise plutôt right.py"
        # Everything was read: nothing is left to write under the ticket.
        assert steering.drain("0486a9fd-44f6-4fff-9dee-9e58bc4062ba") == []


@case
def a_message_with_no_session_running_is_left_to_the_comment(state_home: Path) -> None:
    assert steering.running(TICKET) == ""
    assert steering.route(TICKET, "hello", "comment") == ""
    # A session tracked but without a queue — a reply, an older runner's — is not steered.
    state.track_session("a-session", TICKET, {"session_id": "a-session", "pid": os.getpid()}, "job")
    assert steering.running(TICKET) == ""


@case
def what_a_session_left_unread_is_drained_as_its_comment(state_home: Path) -> None:
    steering.prepare("s1")
    assert steering.send("s1", "late", steering.STEER, "the comment")
    assert not steering.send("nobody", "x")
    left = steering.drain("s1")
    assert [one["comment"] for one in left] == ["the comment"]
    assert not steering.queue("s1").exists()


@case
def the_hooks_hand_over_by_mode(state_home: Path) -> None:
    path = steering.prepare("s2")
    assert steering.hook(steering.STEER, path) == {}
    steering.send("s2", "one", steering.STEER)
    steering.send("s2", "two", steering.FOLLOW)
    steered = steering.hook(steering.STEER, path)
    assert "one" in steered["hookSpecificOutput"]["additionalContext"]
    assert "two" not in json.dumps(steered)
    followed = steering.hook(steering.FOLLOW, path)
    assert followed["decision"] == "block" and "two" in followed["reason"]
    assert steering.hook(steering.FOLLOW, path) == {}, "claimed once"
    # A correction not yet read when the agent stops is not left behind.
    steering.send("s2", "three", steering.STEER)
    assert "three" in steering.hook(steering.FOLLOW, path)["reason"]


@case
def a_steered_session_carries_its_hooks_on_the_command_line(state_home: Path) -> None:
    path = steering.prepare("s3")
    command = session._command(
        "claude",
        "s3",
        resume=False,
        permission_mode="default",
        model="",
        max_budget_usd=0,
        steered=path,
    )
    given = json.loads(command[command.index("--settings") + 1])
    assert given["attribution"] == {"commit": "", "pr": ""}
    assert set(given["hooks"]) == {"PostToolUse", "Stop"}


@case
def telling_a_running_ticket_steers_it_and_writes_no_comment(state_home: Path) -> None:
    """The console's message goes to the session; without one it is the comment it was."""
    client = _TalkClient([])
    api = _bare_api(client)
    api.tell(TICKET, "plain")
    assert [text.splitlines()[-1] for _, text, _ in client.written] == ["plain"]

    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        previous = _fake(home)

        def talk() -> None:
            deadline = time.monotonic() + 20
            while not (home / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            api.tell(TICKET, "go left")
            (home / "go").write_text("")

        speaker = threading.Thread(target=talk)
        speaker.start()
        try:
            events: list[dict[str, Any]] = []
            outcome = session.run(
                "work",
                cwd=home,
                log=home / "run.jsonl",
                timeout_minutes=1,
                session_id="1486a9fd-44f6-4fff-9dee-9e58bc4062ba",
                steerable=True,
                on_event=events.append,
                track=lambda handle: state.track_session(
                    handle.session_id, TICKET, handle.to_json(), "job"
                ),
            )
        finally:
            speaker.join()
            os.environ["PATH"] = previous
        assert outcome.ok, outcome.error
        assert len(client.written) == 1, "steered: nothing written under the ticket"
        assert any(one.get("text") == "go left" for one in events if one.get("type") == "ponos")
