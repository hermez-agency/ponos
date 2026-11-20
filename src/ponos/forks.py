"""« Relancer depuis ici »: a ticket's next session, started from one step of an earlier one.

A ticket that went wrong at its twelfth step of thirty had two ways back: pick
the session up where it stopped (and argue with the eighteen steps it should
never have taken), or run the whole ticket again (and pay for the eleven it got
right). Branching is the third: a new session that knows the conversation up
to the step chosen, and nothing after it, then reads a message — « this time,
do it this way » — and carries on from there.

**Claude Code does the cutting, not us.** `--resume <session> --fork-session
--resume-session-at <message uuid>` writes a new conversation holding the old
one up to that message, under the identifier `--session-id` gives it, and
leaves the old file as it was: the run that went wrong stays readable in the
journal, step by step, beside the one that branched off it. Rewriting a
truncated copy of the transcript ourselves would have worked too, and would
have broken on the first change to a format that is the CLI's, not ours. The
uuid is the step's `anchor` (journal.py): a tool call is cut after its result,
so the new session does not run it again blind.

**The worktree is not put back.** Nothing records the files as they were at
each step, and a commit per step would fill every pull request with them. So
the new session meets the ticket's branch as it is now — what the old session
committed after the step included — and is told so (`prompt.fork`), as the
console says it before anybody confirms: the conversation is rewound, the code
is not.

A branch asked for waits here, in `ponos.db`, until the ticket's next session
starts — the console moves the ticket to ready, and the claim that takes it
reads this row (`Preparation._job`). One per ticket: asked twice, the second
replaces the first. Taken by the run that starts the session, and forgotten
then; a ticket moved elsewhere meanwhile keeps it for its next run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from . import db, journal, session

# What the message given with a branch is cut to: a few lines of direction,
# not a second ticket.
MESSAGE = 4000


class Refused(ValueError):
    """A step a new session cannot start from — said in words the console shows."""


@dataclass(frozen=True)
class Fork:
    ticket: str
    run: int
    position: int
    session: str
    anchor: str
    message: str = ""


def _key(ticket: str) -> str:
    return ticket.replace("-", "")


def holds(session_id: str, anchor: str) -> bool:
    """Does Claude Code still have this session, with this message in it?

    The transcript is read, not trusted: a session pruned by the CLI, filed on
    another machine, or a run whose steps came from a session started over
    (`Run.again`) has no such message to be cut at.
    """
    needle = f'"uuid":"{anchor}"'
    try:
        for path in session.PROJECTS.glob(f"*/{session_id}.jsonl"):
            with path.open(encoding="utf-8", errors="replace") as handle:
                if any(needle in line for line in handle):
                    return True
    except OSError:
        return False
    return False


def ask(run_id: int, position: int, message: str = "") -> Fork:
    """Write down that the ticket of this run starts again from this step of it.

    Refused — `LookupError` for a run that does not exist, `Refused` for one
    that cannot be branched from here — before anything is written.
    """
    found = journal.run(run_id)
    if found is None:
        raise LookupError(f"no such run: {run_id}")
    if not found.get("ended_at"):
        raise Refused(
            "this session is still going: stop it before starting again from one of its steps"
        )
    anchor = journal.anchor(run_id, position)
    if not anchor:
        raise Refused("a new session cannot start from this step")
    session_id = str(found.get("session") or "")
    if not session_id or not holds(session_id, anchor):
        raise Refused(
            "this session is no longer on this machine: it cannot be started again from one of its steps"
        )
    fork = Fork(
        ticket=_key(str(found["ticket"])),
        run=run_id,
        position=position,
        session=session_id,
        anchor=anchor,
        message=message.strip()[:MESSAGE],
    )
    with db.transaction() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO forks (ticket, run, position, session, anchor, message, at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                fork.ticket,
                fork.run,
                fork.position,
                fork.session,
                fork.anchor,
                fork.message,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
    return fork


def pending(ticket: str) -> Fork | None:
    """The branch this ticket's next session starts from, if one was asked for.

    None when the database cannot be read: the ticket then runs as it would
    have, from the start — never a reason to fail it.
    """
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT ticket, run, position, session, anchor, message FROM forks"
                " WHERE ticket = ?",
                (_key(ticket),),
            ).fetchone()
    except db.ERRORS:
        return None
    if row is None:
        return None
    return Fork(str(row[0]), int(row[1]), int(row[2]), str(row[3]), str(row[4]), str(row[5]))


def forget(ticket: str) -> None:
    """The branch asked for this ticket, taken — or no longer wanted."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM forks WHERE ticket = ?", (_key(ticket),))
    except db.ERRORS:
        pass
