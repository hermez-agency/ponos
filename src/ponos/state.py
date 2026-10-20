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
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

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
def lock():
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
    return (str(row[0]), str(row[1]), [name for name in str(row[2]).split("\n") if name]) if row else None


def forget_base_wait(ticket_id: str) -> None:
    """The base is green again, or the ticket left the validated column."""
    try:
        with db.transaction() as connection:
            connection.execute("DELETE FROM base_waits WHERE ticket = ?", (ticket_id,))
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
            connection.execute(
                "DELETE FROM mends WHERE ticket = ? AND head = ?", (ticket_id, head)
            )
    except db.ERRORS:
        pass


def ci_rows() -> dict[str, dict]:
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
    found: dict[str, dict] = {}
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


def keep_ci(ticket_id: str, row: dict) -> None:
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
            connection.executemany("DELETE FROM ci WHERE ticket = ?", [(one,) for one in ticket_ids])
    except db.ERRORS:
        pass


def _number(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def record(entry: dict) -> None:
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


def record_all(entries: Iterable[dict | None]) -> list[dict]:
    """Record every entry there is, and hand them back as a list.

    A `None` is skipped rather than written: it is what a publication that had
    nothing to do returns, and a history line saying nothing is noise.
    """
    kept = [entry for entry in entries if entry]
    for entry in kept:
        record(entry)
    return kept


def spent_today() -> float:
    """What the sessions have cost since local midnight, from the history.

    The history records a run when it ends, so a session still in flight is not
    in the figure yet: the daily limit is read where a session is about to
    *start*, and one that began under it is left to finish.
    """
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(UTC).isoformat(timespec="seconds")
    try:
        with db.transaction(immediate=False) as connection:
            (total,) = connection.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM history WHERE at >= ?", (since,)
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


def causes() -> dict[str, str]:
    """{ticket id without dashes: the cause it last stopped on}, from the history.

    What a card falls back on when the board has no « Blocage » column to read
    it from. Empty when the database cannot be read: a card without its badge
    is still a card.
    """
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT ticket, code FROM history WHERE code != '' ORDER BY id"
            ).fetchall()
    except db.ERRORS:
        return {}
    return {str(ticket).replace("-", ""): str(code) for ticket, code in rows}


def history(limit: int = 20) -> list[dict]:
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


def log_file(short: str) -> Path:
    """One log per session, named by the ticket's short id (see `short_id`)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return logs_dir() / f"{stamp}-{short}.jsonl"
