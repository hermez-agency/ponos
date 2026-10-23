"""Lock, claims, logs and history, under ~/.local/state/ponos.

The lock is the only thing stopping the systemd timer from picking up a ticket
already in flight: a run lasting longer than the interval is normal, two
simultaneous runs are not.

The claims are the other half of that: the column each in-flight ticket was
taken from, so that a run which dies mid-ticket is recovered as what it was
rather than as work to redo. They, the replay counts and the history live in
`ponos.db` (see `db.py`); the lock and the session logs stay files.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db, disk
from .config import state_dir


def logs_dir() -> Path:
    """Where session transcripts go — readable by this account and nobody else.

    A transcript is everything a session read and wrote: the brief, the code,
    whatever a command printed, a secret included if one was in the way.
    """
    path = state_dir() / "logs"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


class Busy(Exception):
    """Another run is already in progress."""


@contextmanager
def lock() -> Iterator[None]:
    """Hold the run lock for as long as the block lasts, or raise Busy.

    The file is never deleted, and that is the point. Unlinking it on release
    opened a window for two runs at once: a run that had opened the old file
    and was waiting to lock it would lock a file no longer on disk, while the
    next one created a fresh `run.lock` and locked that — two locks, two runs.
    One path, one inode, for good.

    And the file is opened without being emptied: `open("w")` truncated it
    before the lock was even asked for, so a run turned away as busy had just
    erased the PID of the run that turned it away. It is emptied and written
    only once the lock is ours.
    """
    state_dir().mkdir(parents=True, exist_ok=True)
    path = state_dir() / "run.lock"
    handle = open(path, "a+", encoding="utf-8", opener=disk.opener())  # noqa: SIM115
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise Busy(f"a run is already in progress (lock {path})") from error
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {datetime.now(UTC).isoformat()}\n")
    handle.flush()
    try:
        yield
    finally:
        # Emptied rather than removed: the next reader finds nobody named,
        # which is what `running` says anyway once the flock is gone.
        try:
            handle.seek(0)
            handle.truncate()
        except OSError:
            pass
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def running() -> str:
    """What the lock says about the run in progress, or "" when there is none.

    The file is not the lock: the flock on it is, and the kernel drops it with
    the process that took it. A run killed mid-way leaves `run.lock` on disk,
    holding nobody — for two hours on 7 September 2026, `status` read that
    leftover as a run in progress and sent the search the wrong way. Asking the
    flock is asking the kernel, which does not keep stale files.
    """
    try:
        handle = (state_dir() / "run.lock").open("r+")
    except OSError:
        return ""
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return handle.read().strip() or "a run in progress"
        fcntl.flock(handle, fcntl.LOCK_UN)
    return ""


def claim(ticket_id: str, status: str) -> None:
    """Remember which column a ticket was taken from.

    Claiming is done by moving a ticket to "in progress", which is what stops a
    second run from taking it — and which also erases where it came from. For a
    ticket taken from the ready column that costs nothing: `sweep` puts it back
    there, and being worked twice is what "ready" means. For one taken from the
    validated column it costs everything: re-doing the work of a ticket somebody
    had already accepted is not recovery, it is a second ticket.

    Local, and that is enough: `sweep` only ever recovers tickets this host
    claimed itself, so the note only has to survive on the machine that wrote
    it. One row, in one transaction: two publications of one pass write their
    claims side by side, and neither can lose the other's — nor can a crash
    leave half a claim. Anything unreadable is no note at all, and the old
    behaviour resumes.
    """
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO claims (ticket, status) VALUES (?, ?)", (ticket_id, status)
            )
    except db.ERRORS:
        # A note nobody could write is a note nobody reads: the ticket goes back
        # to ready on a crash, exactly as it did before this existed.
        pass


def release(ticket_id: str) -> None:
    """Forget a claim: the ticket has left "in progress" under its own steam."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM claims WHERE ticket = ?", (ticket_id,))
    except db.ERRORS:
        pass


def claims() -> dict[str, str]:
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute("SELECT ticket, status FROM claims").fetchall()
    except db.ERRORS:
        return {}
    return {str(ticket): str(status) for ticket, status in rows}


def enter(ticket_id: str, phase: str, detail: str = "") -> None:
    """Write down what a ticket in progress is going through now, and since when.

    A ticket in progress is not always in a session: it is replayed onto its
    base, its CI is run here or waited for on GitHub, a session is sent after a
    red check. None of that writes a log, so the console, which reads the logs
    for what is happening, had nothing to say for an hour but « starting… ».
    One row a ticket, replaced at every phase — the console reads it beside the
    board, as it reads `ci`.
    """
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO phases (ticket, phase, detail, since) VALUES (?, ?, ?, ?)",
                (ticket_id, phase, detail, datetime.now(UTC).isoformat(timespec="seconds")),
            )
    except db.ERRORS:
        pass


def leave(ticket_id: str) -> None:
    """The ticket has left "in progress": no phase of it is current any more."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM phases WHERE ticket = ?", (ticket_id,))
    except db.ERRORS:
        pass


def phases() -> dict[str, tuple[str, str, str]]:
    """What `enter` last wrote, by ticket: the phase, its detail, and since when."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute("SELECT ticket, phase, detail, since FROM phases").fetchall()
    except db.ERRORS:
        return {}
    return {
        str(ticket): (str(phase), str(detail), str(since)) for ticket, phase, detail, since in rows
    }


def hold(reasons: dict[str, tuple[str, str]]) -> None:
    """Write down why each of these ready tickets was left in its column.

    The whole set, replacing the last one: it is what the pass's latest reading
    of the board decided, and a ticket it has since taken has no reason left.
    An empty set is the pass ending. Never a reason to fail one — the console
    then says what it can tell without it.
    """
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM held")
            connection.executemany(
                "INSERT INTO held (ticket, reason, detail) VALUES (?, ?, ?)",
                [(ticket, reason, detail) for ticket, (reason, detail) in reasons.items()],
            )
    except db.ERRORS:
        pass


def held() -> dict[str, tuple[str, str]]:
    """What `hold` last wrote: the ticket, and why it waits — see `Board.explain`."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute("SELECT ticket, reason, detail FROM held").fetchall()
    except db.ERRORS:
        return {}
    return {str(ticket): (str(reason), str(detail)) for ticket, reason, detail in rows}


def rebases(ticket_id: str) -> int:
    """How many times a validated ticket's branch has been replayed to be merged.

    Counted because a base branch can move faster than a replay: a repository
    that takes a merge every ten minutes would otherwise have the runner
    replaying the same pull request all afternoon. Local, like the claims — it
    is the machine doing the replaying that has to know when to stop.
    """
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT count FROM rebases WHERE ticket = ?", (ticket_id,)
            ).fetchone()
    except db.ERRORS:
        return 0
    return int(row[0]) if row else 0


def rebased(ticket_id: str) -> int:
    """One more replay for that ticket; how many that makes."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO rebases (ticket, count) VALUES (?, 1)"
                " ON CONFLICT (ticket) DO UPDATE SET count = count + 1",
                (ticket_id,),
            )
            row = connection.execute(
                "SELECT count FROM rebases WHERE ticket = ?", (ticket_id,)
            ).fetchone()
    except db.ERRORS:
        return 1  # a count nobody could keep is a limit that does not hold, not a crash
    return int(row[0])


def forget_rebases(ticket_id: str) -> None:
    """The ticket has left the validated column: its count starts again from zero."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM rebases WHERE ticket = ?", (ticket_id,))
    except db.ERRORS:
        pass


def wait_for_base(ticket_id: str, base: str, url: str, names: list[str]) -> None:
    """A validated ticket set aside because its base is red, and not it.

    Local, like the replay counts: it is the machine that set the ticket aside
    that looks again, at the top of each pass, whether the base is green.
    """
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO base_waits (ticket, base, url, names) VALUES (?, ?, ?, ?)",
                (ticket_id, base, url, "\n".join(names)),
            )
    except db.ERRORS:
        pass


def waiting_for_base(ticket_id: str) -> tuple[str, str, list[str]] | None:
    """The base, the pull request and the red checks a ticket waits on, or nothing."""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT base, url, names FROM base_waits WHERE ticket = ?", (ticket_id,)
            ).fetchone()
    except db.ERRORS:
        return None
    return (
        (str(row[0]), str(row[1]), [name for name in str(row[2]).split("\n") if name])
        if row
        else None
    )


def forget_base_wait(ticket_id: str) -> None:
    """The base is green again, or the ticket left the validated column."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM base_waits WHERE ticket = ?", (ticket_id,))
    except db.ERRORS:
        pass


def hold_billing(account: str, name: str, reason: str) -> bool:
    """An account whose GitHub Actions billing refuses its jobs. Whether it is news.

    True only for the first ticket to find it: the one that says it out loud.
    The others of the same account, in this pass or the next, find it held.
    """
    try:
        with db.transaction() as connection:
            added = connection.execute(
                "INSERT OR IGNORE INTO billing_holds (account, name, reason, since, probed) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    account,
                    name,
                    reason,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    time.time(),
                ),
            )
            return bool(added.rowcount)
    except db.ERRORS:
        return False


def billing_holds() -> list[dict[str, Any]]:
    """The accounts held by their billing, oldest first."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT account, name, reason, since, probed FROM billing_holds ORDER BY since"
            ).fetchall()
    except db.ERRORS:
        return []
    return [
        {"account": row[0], "name": row[1], "reason": row[2], "since": row[3], "probed": row[4]}
        for row in rows
    ]


def billing_hold(account: str) -> dict[str, Any] | None:
    """The hold on that account, or nothing when its CI runs."""
    return next((one for one in billing_holds() if one["account"] == account), None)


def billing_probed(account: str, moment: float) -> None:
    """The refused jobs of that account were just asked to run again."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "UPDATE billing_holds SET probed = ? WHERE account = ?", (moment, account)
            )
    except db.ERRORS:
        pass


def lift_billing(account: str) -> None:
    """The account's jobs start again: nothing of it waits any more."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM billing_holds WHERE account = ?", (account,))
    except db.ERRORS:
        pass


def wait_for_billing(ticket_id: str, account: str) -> None:
    """A validated ticket whose merge waits on its account's billing."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO billing_waits (ticket, account, at) VALUES (?, ?, ?)",
                (ticket_id, account, time.time()),
            )
    except db.ERRORS:
        pass


def waiting_for_billing(ticket_id: str) -> str:
    """The account a ticket waits on, or nothing."""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT account FROM billing_waits WHERE ticket = ?", (ticket_id,)
            ).fetchone()
    except db.ERRORS:
        return ""
    return str(row[0]) if row else ""


def forget_billing_wait(ticket_id: str) -> None:
    """Its merge no longer waits on the billing: it ran, or it landed."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM billing_waits WHERE ticket = ?", (ticket_id,))
    except db.ERRORS:
        pass


def settle_billing(validated: set[str], older_than: float) -> None:
    """Let go of the waits of tickets no longer validated, and of holds nothing waits on.

    A ticket moved out by hand waits on nothing; an account none of whose
    merges waits is no longer worth a warning. A wait younger than
    `older_than` is kept: the ticket is being moved to validated as it is read.
    """
    try:
        with db.transaction() as connection:
            for (ticket,) in connection.execute(
                "SELECT ticket FROM billing_waits WHERE at < ?", (older_than,)
            ).fetchall():
                if ticket not in validated:
                    connection.execute("DELETE FROM billing_waits WHERE ticket = ?", (ticket,))
            connection.execute(
                "DELETE FROM billing_holds WHERE account NOT IN (SELECT account FROM billing_waits)"
            )
    except db.ERRORS:
        pass


def repair_of(repository: str, base: str) -> str:
    """The ticket opened to repair that base, or nothing."""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT ticket FROM base_repairs WHERE repository = ? AND base = ?",
                (repository, base),
            ).fetchone()
    except db.ERRORS:
        return ""
    return str(row[0]) if row else ""


def is_repair(ticket_id: str) -> bool:
    """Was this ticket opened by the runner to repair a red base?"""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT 1 FROM base_repairs WHERE REPLACE(ticket, '-', '') = ?",
                (ticket_id.replace("-", ""),),
            ).fetchone()
    except db.ERRORS:
        return False
    return row is not None


def repairing(repository: str, base: str, ticket_id: str) -> None:
    """Remember the ticket that repairs that base, so that a second is never opened."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO base_repairs (repository, base, ticket) VALUES (?, ?, ?)",
                (repository, base, ticket_id),
            )
    except db.ERRORS:
        pass


def written_up(ticket_id: str) -> bool:
    """Has this ticket's session already been asked for the report it did not write?

    Once a ticket, and never again — see `Execution._write_up`. A table that
    cannot be read answers yes: a second relaunch is a session nobody budgeted,
    a missing one only a ticket blocked a little sooner.
    """
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT 1 FROM write_ups WHERE ticket = ?", (ticket_id,)
            ).fetchone()
    except db.ERRORS:
        return True
    return row is not None


def wrote_up(ticket_id: str) -> None:
    """That ticket's session has been asked for its report: it will not be again."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO write_ups (ticket, at) VALUES (?, ?)",
                (ticket_id, datetime.now(UTC).isoformat(timespec="seconds")),
            )
    except db.ERRORS:
        pass


def mended(ticket_id: str, head: str) -> bool:
    """Has a session already been sent after the red checks of the ticket's branch at `head`?

    Once a ticket and a head commit, and never again — see `Delivery._mend`.
    A table that cannot be read answers yes, for the reason `written_up` does:
    a second session nobody budgeted costs more than a ticket blocked sooner.
    """
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT 1 FROM mends WHERE ticket = ? AND head = ?", (ticket_id, head)
            ).fetchone()
    except db.ERRORS:
        return True
    return row is not None


def mending(ticket_id: str, head: str) -> None:
    """A session is sent after the red checks of that branch at `head`: not again."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO mends (ticket, head, at) VALUES (?, ?, ?)",
                (ticket_id, head, datetime.now(UTC).isoformat(timespec="seconds")),
            )
    except db.ERRORS:
        pass


def forget_mending(ticket_id: str, head: str) -> None:
    """That repair never ran (no credit left): it may be asked for again."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM mends WHERE ticket = ? AND head = ?", (ticket_id, head))
    except db.ERRORS:
        pass


def ci_rows() -> dict[str, dict[str, Any]]:
    """{ticket id without dashes: what the runner last read of its pull request's checks}.

    What a card is drawn with: read with the list, from here, so that opening
    the board never asks GitHub anything. Empty when the database cannot be
    read — a card without its badge is still a card.
    """
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT ticket, url, head, state, checks, since, asked FROM ci"
            ).fetchall()
    except db.ERRORS:
        return {}
    found: dict[str, dict[str, Any]] = {}
    for ticket, url, head, status, checks, since, asked in rows:
        try:
            listed = json.loads(checks)
        except json.JSONDecodeError:
            listed = []
        found[str(ticket).replace("-", "")] = {
            "url": str(url),
            "head": str(head),
            "state": str(status),
            "checks": listed if isinstance(listed, list) else [],
            "since": float(since),
            "asked": float(asked),
        }
    return found


def keep_ci(ticket_id: str, row: dict[str, Any]) -> None:
    """Write what was read of that ticket's checks, in place of what was there."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO ci (ticket, url, head, state, checks, since, asked) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ticket_id,
                    row["url"],
                    row["head"],
                    row["state"],
                    json.dumps(row["checks"], ensure_ascii=False),
                    row["since"],
                    row["asked"],
                ),
            )
    except db.ERRORS:
        pass


def drop_ci(ticket_ids: Iterable[str]) -> None:
    """Stop following those tickets: they have left review."""
    try:
        with db.transaction() as connection:
            connection.executemany(
                "DELETE FROM ci WHERE ticket = ?", [(one,) for one in ticket_ids]
            )
    except db.ERRORS:
        pass


def _number(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def record(entry: dict[str, Any]) -> None:
    """One line of history: the whole entry, and beside it what one sorts and sums on."""
    entry = {"at": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO history"
            " (at, ticket, status, kind, project, seconds, cost_usd, code, entry)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(entry.get("at") or ""),
                str(entry.get("id") or ""),
                str(entry.get("status") or ""),
                str(entry.get("kind") or ""),
                str(entry.get("project") or ""),
                _number(entry.get("seconds")),
                _number(entry.get("cost_usd")),
                str(entry.get("code") or ""),
                json.dumps(entry, ensure_ascii=False),
            ),
        )


def record_all(entries: Iterable[dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Record every entry there is, and hand them back as a list.

    A `None` is skipped rather than written: it is what a publication that had
    nothing to do returns, and a history line saying nothing is noise.
    """
    kept = [entry for entry in entries if entry]
    for entry in kept:
        record(entry)
    return kept


def occurred(
    schedule: str, outcome: str, *, ticket: str = "", title: str = "", reason: str = ""
) -> None:
    """One occurrence of a schedule: `born`, `launched`, `skipped` or `failed`.

    Never a reason to fail a pass: the ticket is made whether or not this
    line is kept, and a console that cannot say where a ticket came from is
    better than a schedule that stops making them.
    """
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO occurrences (schedule, at, outcome, ticket, title, reason)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    schedule.replace("-", ""),
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    outcome,
                    ticket.replace("-", ""),
                    title,
                    reason,
                ),
            )
    except db.ERRORS:
        pass


def occurrences(schedule: str) -> list[dict[str, Any]]:
    """Every occurrence of a schedule kept, the latest first."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT at, outcome, ticket, title, reason FROM occurrences"
                " WHERE schedule = ? ORDER BY id DESC",
                (schedule.replace("-", ""),),
            ).fetchall()
    except db.ERRORS:
        return []
    return [
        {"at": at, "outcome": outcome, "ticket": ticket, "title": title, "reason": reason}
        for at, outcome, ticket, title, reason in rows
    ]


def spend(cost_usd: float, ticket: str = "") -> None:
    """What one session cost, written down the moment it ends.

    Every session the runner starts comes through here — see `Base._paid` —
    whatever becomes of its ticket after: one that names or classifies it, one
    that repairs its CI, one whose report Notion never took. The history keeps
    a line per ticket and could not say all of that; this is what the day's
    limit adds up. Nothing to write when nothing was paid: a subscription
    reports no cost.
    """
    if not cost_usd:
        return
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO spending (at, ticket, cost_usd) VALUES (?, ?, ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"), ticket, float(cost_usd)),
            )
    except db.ERRORS:
        pass


def spent_today() -> float:
    """What the sessions have cost since local midnight — see `spend`.

    A session is written down when it ends, so one still in flight is not in
    the figure yet: the daily limit is read where a session is about to
    *start*, and one that began under it is left to finish.
    """
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(UTC).isoformat(timespec="seconds")
    try:
        with db.transaction(immediate=False) as connection:
            (total,) = connection.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM spending WHERE at >= ?", (since,)
            ).fetchone()
    except db.ERRORS:
        return 0.0
    return float(total or 0.0)


def spent_by_project(since: datetime) -> list[tuple[str, int, float]]:
    """What the sessions ended since `since` cost, project by project, the dearest first.

    `(project, sessions, cost)`; a session of no project is filed under "".
    """
    stamp = since.astimezone(UTC).isoformat(timespec="seconds")
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT project, COUNT(*), COALESCE(SUM(cost_usd), 0) FROM history"
            " WHERE at >= ? GROUP BY project ORDER BY 3 DESC, 1",
            (stamp,),
        ).fetchall()
    return [(str(project or ""), int(count), float(total or 0.0)) for project, count, total in rows]


def causes(ticket: str = "") -> dict[str, str]:
    """{ticket id without dashes: the cause it last stopped on}, from the history.

    What a card falls back on when the board has no « Blocage » column to read
    it from. Empty when the database cannot be read: a card without its badge
    is still a card. One ticket's only when `ticket` is given, asked of the
    index on the lines that carry a code rather than read off the whole
    history — under either form of its id, as a line may have kept the dashes.
    """
    query = "SELECT ticket, code FROM history WHERE code != ''"
    values: tuple[str, ...] = ()
    if ticket:
        key = ticket.replace("-", "")
        query += " AND ticket IN (?, ?)"
        values = (key, f"{key[:8]}-{key[8:12]}-{key[12:16]}-{key[16:20]}-{key[20:]}")
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(query + " ORDER BY id", values).fetchall()
    except db.ERRORS:
        return {}
    return {str(ticket).replace("-", ""): str(code) for ticket, code in rows}


def totals() -> tuple[int, float]:
    """`(handled, spend)`: every outcome the history holds, and what they cost.

    Asked of the columns, never of the lines: the header reads it after every
    turn of the chat, and decoding the whole history for a count and a sum
    cost tens of milliseconds a time — and capped both at the lines decoded.
    """
    with db.transaction(immediate=False) as connection:
        (handled, spend) = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM history"
        ).fetchone()
    return int(handled), float(spend)


def history(limit: int = 20) -> list[dict[str, Any]]:
    """The last `limit` entries, oldest first."""
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT entry FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    entries = []
    for (raw,) in reversed(rows):
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return entries


def outcomes() -> list[dict[str, Any]]:
    """Every line of history, oldest first, cut down to what the statistics count.

    Read off the columns rather than decoded line by line: the statistics
    want the whole history at every call, and `json.loads` on each of
    thousands of lines is most of what reading it costs. The two keys with no
    column of their own are asked of the line only where they can matter — a
    merge on a line that ended done, a reason on a stop that has no code — and
    only of a line that parses: a broken one still counts by its columns.
    """
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT ticket, at, status, kind, cost_usd, seconds, code,"
            " CASE WHEN status = 'done' AND json_valid(entry)"
            " THEN json_extract(entry, '$.merged') END,"
            " CASE WHEN code = '' AND status IN ('blocked', 'failed') AND json_valid(entry)"
            " THEN json_extract(entry, '$.reason') END"
            " FROM history ORDER BY id"
        ).fetchall()
    keys = ("id", "at", "status", "kind", "cost_usd", "seconds", "code", "merged", "reason")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def prune_logs(days: int) -> int:
    """Drop session logs older than `days`. Zero keeps everything.

    A session log is a few hundred kilobytes and one is written per ticket; at
    a ten-second cadence that adds up quietly. The Notion comment keeps the
    summary either way, and the transcript lives in ~/.claude/projects.
    """
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for path in logs_dir().glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def prune_records(days: int) -> int:
    """Drop what `ponos.db` keeps row by row past `days`, as `prune_logs` does
    the files. Zero keeps everything. Returns how many rows went.

    The steps of a run copy its log line by line, so they go when the log
    would: the run itself stays — its outcome, its cost and its cause are what
    the history and the statistics count. The sync journal, the MCP calls and
    the transitions that are over are a trail, read for the last few entries;
    a transition still to run, or running, is work and is kept whatever its age.
    """
    if days <= 0:
        return 0
    cutoff = datetime.fromtimestamp(time.time() - days * 86400, UTC).isoformat(timespec="seconds")
    with db.transaction() as connection:
        removed = sum(
            connection.execute(statement, (cutoff,)).rowcount
            for statement in (
                "DELETE FROM steps WHERE run IN"
                " (SELECT id FROM runs WHERE COALESCE(ended_at, started_at) < ?)",
                "DELETE FROM sync_journal WHERE at < ?",
                "DELETE FROM mcp_calls WHERE at < ?",
                "DELETE FROM transitions WHERE state NOT IN ('pending', 'running')"
                " AND COALESCE(NULLIF(ended_at, ''), seen_at) < ?",
            )
        )
    db.compact()
    return removed


def log_file(short: str) -> Path:
    """One log per session, named by the ticket's short id (see `short_id`)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return logs_dir() / f"{stamp}-{short}.jsonl"
