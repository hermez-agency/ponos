"""A turn of the workspace, said in AG-UI: the protocol the console's chat reads.

The panel of the conversation is TanStack AI's `useChat`, and `useChat` reads
AG-UI events — `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`… The
session behind a turn is Claude Code, which writes stream-json. This module is
the translation, and nothing else: no thread, no socket, no state of the
console. It is fed one event of the session at a time and answers the AG-UI
events it is worth, so it can be tested with a list of dictionaries.

Three choices, each against the obvious one:

- **One assistant message per turn, opened when the turn starts.** Claude Code
  says a turn in several assistant messages — a sentence, a tool call, its
  result, another sentence. AG-UI could open one message for each, and the
  panel would draw five Ponos speaking in a row. What a person reads is one
  answer, made of parts in the order they came; the message is opened before
  the first event, so that a turn that starts with a tool call has somewhere to
  put it.
- **Every tool call is said to have run already** (`providerExecuted`). They
  ran in the session, on the server, before the event reached us. Without the
  mark, a call the session left without a result — a turn you stopped —
  would be taken by the page for a tool of its own to run.
- **The parts are kept, not only the events.** What streamed is what the
  conversation shows once reopened: the turn leaves `parts` on the message it
  saves, in the shape `useChat` draws (`UIMessage`), so the history is drawn
  by the same components as the live turn. A tool's result is kept shortened:
  it is a file read, a command's output, and the session keeps it whole.

The conversation as a whole is said with `MESSAGES_SNAPSHOT` (see `snapshot`):
when a turn starts, so every page that watches has the message that started it
— typed here, in another tab, or waiting in the queue — and when it ends, with
what was saved, which is what any page that missed an event comes back to.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

# How much of a tool's result the conversation keeps, and shows.
RESULT = 4000

# What a call the turn ended on before it answered is said to have answered.
UNANSWERED = "Stopped before it answered."


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _now() -> int:
    return int(time.time() * 1000)


def _event(kind: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, "timestamp": _now(), **fields}


def _shortened(text: str) -> str:
    return text if len(text) <= RESULT else text[: RESULT - 1].rstrip() + "…"


def _result_text(content: Any) -> str:
    """What a tool answered, as text: Claude Code gives a string, or blocks."""
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict)
        ).strip()
    return str(content or "")


class Turn:
    """One turn: the AG-UI events it streams, and the parts it leaves behind."""

    def __init__(self, thread_id: str, run_id: str = "", message_id: str = "") -> None:
        self.thread_id = thread_id
        self.run_id = run_id or new_id("run")
        self.message_id = message_id or new_id("ponos")
        self.parts: list[dict[str, Any]] = []
        # Whether a tool was called since the last words: the next words are a
        # new part, under the call, and not the end of the sentence above it.
        self._called = True

    def started(self) -> list[dict[str, Any]]:
        return [
            _event("RUN_STARTED", threadId=self.thread_id, runId=self.run_id),
            _event("TEXT_MESSAGE_START", messageId=self.message_id, role="assistant"),
        ]

    def read(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """The AG-UI events one stream-json event of the session is worth."""
        kind = event.get("type")
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if not isinstance(blocks, list):
            return []
        said: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if kind == "assistant" and block.get("type") == "text":
                said += self._text(str(block.get("text") or ""))
            elif kind == "assistant" and block.get("type") == "thinking":
                said += self._thinking(str(block.get("thinking") or ""))
            elif kind == "assistant" and block.get("type") == "tool_use":
                said += self._call(block)
            elif kind == "user" and block.get("type") == "tool_result":
                said += self._result(block)
        return said

    def concluded(self, answer: str) -> list[dict[str, Any]]:
        """The session's last word, when its stream never said it as words.

        Claude Code ends on a `result` that repeats its last sentence; a turn
        whose answer is only there — a session cut short, a model that wrote
        its answer nowhere else — would be saved without it.
        """
        answer = answer.strip()
        texts = [part["content"] for part in self.parts if part["type"] == "text"]
        if not answer or (texts and texts[-1].strip().endswith(answer)):
            return []
        return self._text(answer)

    def finished(self, stopped: bool = False) -> list[dict[str, Any]]:
        return [
            *self._unanswered(),
            _event("TEXT_MESSAGE_END", messageId=self.message_id),
            _event(
                "RUN_FINISHED",
                threadId=self.thread_id,
                runId=self.run_id,
                finishReason="stop" if not stopped else None,
            ),
        ]

    def failed(self, message: str) -> list[dict[str, Any]]:
        return [
            *self._unanswered(),
            _event("TEXT_MESSAGE_END", messageId=self.message_id),
            _event("RUN_ERROR", runId=self.run_id, message=message, error={"message": message}),
        ]

    def _unanswered(self) -> list[dict[str, Any]]:
        """A call the turn ended on before it answered: said to have failed.

        Left open, it would be drawn running for as long as the conversation is
        kept — a turn you stopped in the middle of a command.
        """
        answered = {part.get("toolCallId") for part in self.parts if part["type"] == "tool-result"}
        said: list[dict[str, Any]] = []
        for part in list(self.parts):
            if part["type"] == "tool-call" and part["id"] not in answered:
                said += self._result(
                    {"tool_use_id": part["id"], "content": UNANSWERED, "is_error": True}
                )
        return said

    # -- one block at a time -------------------------------------------------

    def _text(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        said: list[dict[str, Any]] = []
        last = self.parts[-1] if self.parts else None
        if self._called or last is None or last.get("type") != "text":
            # A new segment of the same message: AG-UI reopens it, and the
            # words land in a part of their own, under what came before.
            said.append(_event("TEXT_MESSAGE_START", messageId=self.message_id, role="assistant"))
            self.parts.append({"type": "text", "content": text})
            delta = text
        else:
            # Two sentences in a row, with nothing done between them: one part,
            # a paragraph apart.
            delta = f"\n\n{text}"
            last["content"] += delta
        self._called = False
        said.append(_event("TEXT_MESSAGE_CONTENT", messageId=self.message_id, delta=delta))
        return said

    def _thinking(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        step = new_id("thinking")
        self.parts.append({"type": "thinking", "content": text})
        self._called = True
        return [
            _event("REASONING_START", messageId=step),
            _event("REASONING_MESSAGE_START", messageId=step, role="reasoning"),
            _event("REASONING_MESSAGE_CONTENT", messageId=step, delta=text),
            _event("REASONING_MESSAGE_END", messageId=step),
            _event("REASONING_END", messageId=step),
        ]

    def _call(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        identifier = str(block.get("id") or new_id("call"))
        name = str(block.get("name") or "tool")
        given = block.get("input") if isinstance(block.get("input"), dict) else {}
        arguments = json.dumps(given, ensure_ascii=False)
        self.parts.append(
            {
                "type": "tool-call",
                "id": identifier,
                "name": name,
                "arguments": arguments,
                "input": given,
                "state": "input-complete",
                "metadata": {"providerExecuted": True},
            }
        )
        self._called = True
        return [
            _event(
                "TOOL_CALL_START",
                toolCallId=identifier,
                toolCallName=name,
                parentMessageId=self.message_id,
                metadata={"providerExecuted": True},
            ),
            _event("TOOL_CALL_ARGS", toolCallId=identifier, delta=arguments),
            _event("TOOL_CALL_END", toolCallId=identifier),
        ]

    def _result(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        identifier = str(block.get("tool_use_id") or "")
        if not any(
            part.get("type") == "tool-call" and part.get("id") == identifier for part in self.parts
        ):
            # The answer to a call of a sub-agent, or of a turn before this one:
            # nothing on the page to hang it under.
            return []
        content = _shortened(_result_text(block.get("content")))
        failed = bool(block.get("is_error"))
        part: dict[str, Any] = {
            "type": "tool-result",
            "toolCallId": identifier,
            "content": content,
            "state": "error" if failed else "complete",
        }
        if failed:
            part["error"] = content
        self.parts.append(part)
        self._called = True
        result = _event(
            "TOOL_CALL_RESULT",
            messageId=new_id("result"),
            toolCallId=identifier,
            content=content,
            role="tool",
        )
        if failed:
            result["state"] = "output-error"
        return [result]


def snapshot(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The whole conversation, as `useChat` holds it: what a page starts again from."""
    return _event("MESSAGES_SNAPSHOT", messages=messages)


def user_text(message: dict[str, Any]) -> str:
    """What a message of a `RunAgentInput` says, whichever way it says it.

    TanStack AI sends its `UIMessage` with `parts`, and the AG-UI mirror of it
    with `content`; another client sends `content` alone, a string or blocks.
    """
    parts = message.get("parts")
    if isinstance(parts, list):
        return "\n".join(
            str(part.get("content", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    content = message.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    return str(content or "").strip()


def last_user(messages: list[Any]) -> dict[str, Any]:
    """The message a run is asked to answer: the last one the user wrote."""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return message
    raise ValueError("a run needs a message from the user")
