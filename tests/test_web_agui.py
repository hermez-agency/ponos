"""`web/agui.py`: a turn of the workspace, said in AG-UI for the page's `useChat`."""

from __future__ import annotations

from support import case

from ponos.web import agui


def _said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _called(identifier: str, name: str, given: dict) -> dict:
    block = {"type": "tool_use", "id": identifier, "name": name, "input": given}
    return {"type": "assistant", "message": {"content": [block]}}


def _answered(identifier: str, content: object, failed: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": identifier, "content": content}
    if failed:
        block["is_error"] = True
    return {"type": "user", "message": {"content": [block]}}


@case
def a_turn_is_one_answer_made_of_its_parts_in_the_order_they_came():
    """One message for the whole turn, opened before anything is said in it.

    The session says a turn in several messages; the page draws one answer —
    the thinking, the words, each tool and what it answered, in order.
    """
    turn = agui.Turn("thread-1", "run-1")
    events = turn.started()
    thinking = {"type": "thinking", "thinking": "Where is the board?"}
    events += turn.read({"type": "assistant", "message": {"content": [thinking]}})
    events += turn.read(_said("I read the board."))
    events += turn.read(_called("toolu_1", "Bash", {"command": "ponos list"}))
    events += turn.read(_answered("toolu_1", [{"type": "text", "text": "13 tickets"}]))
    events += turn.read(_said("Done."))
    events += turn.read(_said("The board has 13 tickets."))
    events += turn.finished()

    kinds = [event["type"] for event in events]
    assert kinds[:2] == ["RUN_STARTED", "TEXT_MESSAGE_START"], kinds
    assert kinds[-2:] == ["TEXT_MESSAGE_END", "RUN_FINISHED"], kinds
    assert {event["runId"] for event in events if "runId" in event} == {"run-1"}
    assert "REASONING_MESSAGE_CONTENT" in kinds and "TOOL_CALL_RESULT" in kinds
    # Every word of the turn lands in the one message the turn opened.
    spoken = {event["messageId"] for event in events if event["type"].startswith("TEXT_MESSAGE")}
    assert spoken == {turn.message_id}, spoken
    start = next(event for event in events if event["type"] == "TOOL_CALL_START")
    assert start["parentMessageId"] == turn.message_id
    assert start["metadata"] == {"providerExecuted": True}, "ran in the session, not the page"

    assert [part["type"] for part in turn.parts] == [
        "thinking",
        "text",
        "tool-call",
        "tool-result",
        "text",
    ]
    assert turn.parts[2]["arguments"] == '{"command": "ponos list"}'
    assert turn.parts[3] == {
        "type": "tool-result",
        "toolCallId": "toolu_1",
        "content": "13 tickets",
        "state": "complete",
    }
    # Two sentences with nothing done between them are one part, a paragraph apart.
    assert turn.parts[-1]["content"] == "Done.\n\nThe board has 13 tickets."


@case
def a_failed_tool_is_said_failed_and_a_long_answer_is_kept_short():
    turn = agui.Turn("thread-1")
    turn.read(_called("toolu_1", "Bash", {"command": "false"}))
    failed = turn.read(_answered("toolu_1", "exit 1", failed=True))
    assert failed[0]["state"] == "output-error", failed
    assert turn.parts[-1]["state"] == "error" and turn.parts[-1]["error"] == "exit 1"

    turn.read(_called("toolu_2", "Read", {"file_path": "/big"}))
    turn.read(_answered("toolu_2", "x" * (agui.RESULT * 3)))
    assert len(turn.parts[-1]["content"]) == agui.RESULT

    # The answer to a call this turn never made — a sub-agent's — hangs under nothing.
    assert turn.read(_answered("toolu_elsewhere", "ok")) == []
    assert turn.read({"type": "result", "result": "Done."}) == []


@case
def a_stopped_or_failed_turn_still_closes_what_it_opened():
    turn = agui.Turn("thread-1", "run-9")
    turn.read(_called("toolu_1", "Bash", {"command": "sleep 600"}))
    stopped = turn.finished(stopped=True)
    kinds = [event["type"] for event in stopped]
    assert kinds == ["TOOL_CALL_RESULT", "TEXT_MESSAGE_END", "RUN_FINISHED"], kinds
    assert stopped[-1]["finishReason"] is None
    # The command it was in is not drawn running for ever after.
    assert turn.parts[-1]["state"] == "error" and turn.parts[-1]["content"] == agui.UNANSWERED
    assert [event["type"] for event in turn.finished()][0] == "TEXT_MESSAGE_END", "said once"
    failed = turn.failed("claude not found in PATH")
    assert failed[-1]["type"] == "RUN_ERROR" and failed[-1]["runId"] == "run-9"
    assert failed[-1]["message"] == "claude not found in PATH"


@case
def the_message_a_run_answers_is_read_whichever_way_it_is_written():
    """TanStack AI sends parts; another AG-UI client, a string or blocks."""
    tanstack = {
        "id": "msg-1",
        "role": "user",
        "parts": [{"type": "text", "content": "what is on the board?"}],
        "content": "what is on the board?",
    }
    blocks = {"role": "user", "content": [{"type": "text", "text": "and now?"}]}
    plain = {"role": "user", "content": "  plainly  "}
    assert agui.user_text(tanstack) == "what is on the board?"
    assert agui.user_text(blocks) == "and now?"
    assert agui.user_text(plain) == "plainly"
    answer = {"role": "assistant", "content": "13 tickets"}
    assert agui.last_user([tanstack, answer, blocks, answer]) is blocks
    try:
        agui.last_user([answer])
    except ValueError:
        pass
    else:
        raise AssertionError("a run with nothing from the user is refused")


@case
def an_answer_said_only_in_the_result_is_kept_as_the_last_words():
    """Claude Code repeats its last sentence in `result`: said once, never twice."""
    turn = agui.Turn("thread-1")
    turn.read(_said("Let me look."))
    turn.read(_called("toolu_1", "Read", {"file_path": "/a.py"}))
    events = turn.concluded("Done. The board has 13 tickets.")
    assert [event["type"] for event in events] == ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"]
    assert turn.parts[-1] == {"type": "text", "content": "Done. The board has 13 tickets."}
    assert turn.concluded("Done. The board has 13 tickets.") == [], "already said"
    assert turn.concluded("") == []
