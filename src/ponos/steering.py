"""Talking to a session while it runs: a correction, or a message for after.

A comment on a ticket whose session is going used to be read by the next pass,
or answered without the work changing. To say « no, not that file » one had to
wait for the end of the session, or stop it and start again. Claude Code's
`--print` mode reads its prompt once, on standard input, and the tether closes
it (tether.py): a message cannot be written to the session. What the CLI does
run, between two of its steps, are **hooks** — commands it starts and whose
standard output it reads. So the message is not sent to the session, it is
left where a hook finds it:

- the runner (or the console, or a channel) appends it to the session's queue,
  a file under the state directory — `send`;
- `PostToolUse` runs `python -m ponos.steering steer <queue>` after every tool
  call, and what it prints is added to the agent's context: the **correction**,
  given at the end of the turn under way, nothing stopped;
- `Stop` runs the same with `follow`, when the agent thinks it is done: it
  claims what is left, and by answering `block` it keeps the session going on
  that message, before the session closes — the **follow-up**.

A file rather than a pipe or a socket because the session outlives the runner
that started it (adoption.py): whoever runs next, and the console whichever
process it is, find the same queue. Everything a hook claims moves to a
`.sent` file, which `follow` in session.py reads as it reads the log, and turns
into a step of the ticket's journal — in its place in the thread of what the
agent did, rather than in the comments.

The hook half is **the standard library only** and takes the queue's path on
its command line: it runs in the CLI's environment, long after the session
started, and must not need Ponos's configuration. A hook that fails costs a
message its delivery, not the session its life: `drain` hands what a session
left unclaimed back as a comment, which is where it always went.
"""

from __future__ import annotations

import fcntl
import json
import shlex
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# A correction: handed over after the tool call under way. A follow-up: kept
# for when the agent has finished what it was doing. The hook of a follow-up
# takes both — a correction not yet read is not left behind the end.
STEER = "steer"
FOLLOW = "follow"
MODES = (STEER, FOLLOW)

# What the CLI is given to wait for a hook: far more than reading a file takes.
HOOK_TIMEOUT_SECONDS = 10


def directory() -> Path:
    from .config import state_dir

    return state_dir() / "steering"


def queue(session_id: str) -> Path:
    return directory() / f"{session_id}.queue"


def _sent(path: Path) -> Path:
    return path.with_suffix(".sent")


def prepare(session_id: str) -> Path:
    """Open a session's queue, empty: its presence is what says hooks listen to it."""
    path = queue(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    _sent(path).write_text("", encoding="utf-8")
    return path


def hooks(path: Path) -> dict[str, Any]:
    """The `hooks` of the session's settings: the two moments a message can be handed over."""
    command = f"{shlex.quote(sys.executable)} -m ponos.steering"
    source = shlex.quote(str(Path(__file__).resolve().parents[1]))

    def entry(mode: str) -> list[dict[str, Any]]:
        return [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"PYTHONPATH={source} {command} {mode} {shlex.quote(str(path))}",
                        "timeout": HOOK_TIMEOUT_SECONDS,
                    }
                ]
            }
        ]

    return {"PostToolUse": entry(STEER), "Stop": entry(FOLLOW)}


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """One writer at a time, the console's and the hook's alike."""
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and str(value.get("text") or "").strip():
            found.append(value)
    return found


def send(session_id: str, text: str, mode: str = STEER, comment: str = "") -> bool:
    """Leave a message for a session's hooks. False when no queue listens.

    `comment` is what the message becomes on the ticket's page if no hook ever
    takes it — see `drain`.
    """
    path = queue(session_id)
    if not path.exists() or not text.strip():
        return False
    entry = {
        "text": text.strip(),
        "mode": mode if mode in MODES else STEER,
        "comment": comment,
        "at": time.time(),
    }
    try:
        with _locked(path), path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


def claim(path: Path, modes: tuple[str, ...] = MODES) -> list[dict[str, Any]]:
    """Take the messages of these modes out of the queue, oldest first.

    They are written to the `.sent` file in the same breath, so that a message
    is in the queue or in the record, never in both and never in neither.
    """
    try:
        with _locked(path):
            waiting = _read(path)
            taken = [one for one in waiting if one.get("mode") in modes]
            if not taken:
                return []
            kept = [one for one in waiting if one not in taken]
            path.write_text(
                "".join(json.dumps(one, ensure_ascii=False) + "\n" for one in kept),
                encoding="utf-8",
            )
            with _sent(path).open("a", encoding="utf-8") as record:
                for one in taken:
                    record.write(json.dumps(one, ensure_ascii=False) + "\n")
            return taken
    except OSError:
        return []


def delivered(session_id: str, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """The messages the hooks have handed over since `offset`, and the new offset."""
    path = _sent(queue(session_id))
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], offset
    whole, _, _ = chunk.rpartition(b"\n")
    if not whole:
        return [], offset
    found = []
    for line in whole.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found, offset + len(whole) + 1


def size(session_id: str) -> int:
    try:
        return _sent(queue(session_id)).stat().st_size
    except OSError:
        return 0


def drain(session_id: str) -> list[dict[str, Any]]:
    """What a session ended without reading, and the files that held it gone."""
    path = queue(session_id)
    left = _read(path)
    for stale in (path, _sent(path), path.with_suffix(".lock")):
        stale.unlink(missing_ok=True)
    return left


def running(ticket: str) -> str:
    """The session of this ticket's work that a hook is listening to, or "".

    Only a session the runner started with hooks has a queue; one adopted from
    a runner before this feature, a reply or a classification has none, and the
    comment goes the way it always went.
    """
    from . import session, state

    key = ticket.replace("-", "")
    for row in state.sessions():
        if row["ticket"] != key or not row["job"] or not queue(row["session"]).exists():
            continue
        try:
            if session.Handle.from_json(row["handle"]).alive():
                return str(row["session"])
        except (KeyError, TypeError, ValueError):
            continue
    return ""


def route(ticket: str, text: str, comment: str, mode: str = STEER) -> str:
    """Hand a message to the ticket's running session: its mode, or "" when none runs.

    Empty is the answer that changes nothing: the caller writes the comment as
    it always did.
    """
    found = running(ticket)
    if found and send(found, text, mode, comment):
        return mode if mode in MODES else STEER
    return ""


def event(message: dict[str, Any]) -> dict[str, Any]:
    """A delivered message as an event of the session's stream, for whoever follows it."""
    return {
        "type": "ponos",
        "subtype": "message",
        "mode": message.get("mode", STEER),
        "text": str(message.get("text") or ""),
    }


# -- what the agent reads ------------------------------------------------------


def words(messages: list[dict[str, Any]], mode: str) -> str:
    """The messages as the agent is told them."""
    said = "\n\n".join(f"> {' '.join(str(one['text']).split())}" for one in messages)
    if mode == STEER:
        return (
            "The person who gave you this ticket has just sent you a correction while you work. "
            "Take it into account from now on, without starting over what is already right:\n\n"
            f"{said}"
        )
    return (
        "The person who gave you this ticket sent you a message while you worked. "
        "Do what it asks before you finish, then close the session as you would have, with "
        "your report and your final RESULT line:\n\n"
        f"{said}"
    )


def hook(mode: str, path: Path) -> dict[str, Any]:
    """What the CLI is answered, for one of its hooks: nothing when no message waits."""
    taken = claim(path, (STEER,) if mode == STEER else MODES)
    if not taken:
        return {}
    if mode == STEER:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": words(taken, STEER),
            }
        }
    return {"decision": "block", "reason": words(taken, FOLLOW)}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in MODES:
        return 0
    try:
        sys.stdin.read()
        answer = hook(argv[0], Path(argv[1]))
    except Exception:  # noqa: BLE001 — a hook that fails must never fail the session
        return 0
    if answer:
        sys.stdout.write(json.dumps(answer, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
