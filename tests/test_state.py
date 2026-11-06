"""`state.py`: the scheduler's place, the claims, the sessions, and the daemon's unit."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any

from support import ROOT, _state_home, case

from ponos import config as C
from ponos import db, log, state, systemd, update

# -- staying alive -----------------------------------------------------------


@case
def a_scheduler_lock_left_by_a_dead_daemon_is_not_a_scheduler(state_home: Path) -> None:
    """`scheduler.lock` on disk is what a killed daemon leaves behind; the flock is not.

    For two hours on 7 September 2026, `status` read such a leftover file as a
    run in progress, and the search for the silence went the wrong way.
    """
    state_home.mkdir(parents=True)
    (state_home / state.SCHEDULER).write_text("4242 2026-09-07T11:57:17+00:00\n")
    assert state.scheduler() == {}, "a file nobody holds is no scheduler"
    with state.scheduling():
        assert state.scheduler()["pid"] == os.getpid(), "a held lock is one"
    assert state.scheduler() == {}


@case
def a_second_scheduler_turned_away_leaves_the_lock_and_its_holder_alone(state_home: Path) -> None:
    """The lock file is one inode for good, and its PID survives a refusal.

    Unlinking it on release let a holder waiting on the old inode and one that
    created a new one both hold "the" lock. And `open("w")` emptied the file
    before asking for the lock — so a process turned away as busy had erased
    the name of the one that turned it away.
    """
    path = state_home / state.SCHEDULER
    with state.scheduling():
        inode = path.stat().st_ino
        try:
            with state.scheduling():
                raise AssertionError("two schedulers held the lock at once")
        except state.Busy:
            pass
        assert path.read_text().startswith(f"{os.getpid()} "), "the holder is still named"
        assert state.scheduler()["pid"] == os.getpid()
        with state.installing():
            pass  # another lock: an install does not wait for the daemon
    assert path.exists(), "the lock file is never removed"
    assert path.stat().st_ino == inode, "and never replaced"
    assert path.read_text() == "", "nobody is named once the lock is let go of"
    assert path.stat().st_mode & 0o777 == 0o600
    with state.scheduling():
        assert path.stat().st_ino == inode
        assert path.read_text().count("\n") == 1, "one holder, written once"


@case
def a_session_written_down_is_read_back_and_counted_as_in_flight(state_home: Path) -> None:
    """What a restart adopts: one row a session, with the job of its ticket."""
    state.track_session("s-1", "abc-def", {"pid": 12, "log": "/x"}, '{"ticket": "abcdef"}')
    state.track_session("s-2", "", {"pid": 13}, "")
    found = {row["session"]: row for row in state.sessions()}
    assert found["s-1"]["ticket"] == "abcdef" and found["s-1"]["handle"]["pid"] == 12
    assert found["s-2"]["job"] == ""
    assert "abcdef" in state.going(), "a ticket whose session is written down is in flight"
    state.untrack_session("s-1")
    assert [row["session"] for row in state.sessions()] == ["s-2"]
    state.keep_places({"width": 2, "busy": [], "queue": []})
    assert state.places()["width"] == 2 and state.places()["at"]


@case
def a_copy_of_a_secret_is_private_before_it_holds_anything() -> None:
    """The console's token, and the copies a save makes of the configuration.

    Written with the umask and tightened with `chmod` afterwards, each was
    readable by the group for the moment in between — the configuration holds
    the Notion token, the bot tokens and the console's password.
    """
    from ponos.web import server as web_server

    created: list[tuple[str, int]] = []
    original = os.open

    def spying(path: Any, flags: int, mode: int = 0o777, *rest: Any, **kept: Any) -> int:
        if flags & os.O_CREAT:
            created.append((str(path), mode))
        return original(path, flags, mode, *rest, **kept)

    previous = os.umask(0o022)
    os.open = spying
    try:
        with _state_home():
            path = Path(tempfile.mkdtemp()) / "config.toml"
            path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n')
            path.chmod(0o600)
            C.edit(path, [("runner", "model", "opus")])
            secret = web_server.token(C.load(path))
            kept = web_server.token_path()
            assert kept.read_text().strip() == secret
            assert kept.stat().st_mode & 0o777 == 0o600
            backup = path.parent / "config.toml.bak"
            assert backup.stat().st_mode & 0o777 == 0o600
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        os.open = original
        os.umask(previous)
    names = {Path(name).name: mode for name, mode in created}
    assert names.get("token") == 0o600, names
    assert names.get("config.toml.bak") == 0o600, names
    assert any(
        name.startswith(".config.toml.saving") and mode == 0o600 for name, mode in names.items()
    ), names


@case
def a_claim_is_written_whole_or_not_at_all(state_home: Path) -> None:
    """A crash halfway through a write must leave the claims as they were.

    A lost claim reads as "no claim", and a validated ticket without its claim
    comes back from a crash as work to redo. And two publications of one pass
    claim side by side: neither may lose the other's.
    """
    try:
        state.claim("a" * 32, "validated")
        try:
            with db.transaction() as connection:
                connection.execute("DELETE FROM claims")
                connection.execute("INSERT INTO claims VALUES (?, ?)", ("b" * 32, "ready"))
                raise OSError("disk full")
        except OSError:
            pass
        assert state.claims() == {"a" * 32: "validated"}, "the old claims are intact"
        workers = [
            threading.Thread(target=state.claim, args=(f"{n:032d}", "ready")) for n in range(8)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert len(state.claims()) == 9, state.claims()
        state.release("a" * 32)
        assert "a" * 32 not in state.claims()
        assert db.path().stat().st_mode & 0o777 == 0o600
    finally:
        db.close()


@case
def what_a_session_said_is_kept_for_this_account_only(state_home: Path) -> None:
    """Transcripts and the history carry briefs, code and whatever was printed."""
    previous = os.umask(0o022)
    try:
        state.record({"ticket": "t", "status": "done"})
        logs = state.logs_dir()
    finally:
        os.umask(previous)
    assert db.path().stat().st_mode & 0o777 == 0o600
    assert logs.stat().st_mode & 0o777 == 0o700


@case
def the_totals_count_every_line_of_the_history(state_home: Path) -> None:
    """The header's figures were summed over the last 10 000 lines, decoded one by one.

    One more and the oldest fell out of both: the count stuck at 10 000, and
    its cost left the spend without a word.
    """
    with db.transaction() as connection:
        connection.executemany(
            "INSERT INTO history (ticket, status, cost_usd, entry) VALUES (?, 'done', ?, '{}')",
            [(f"t{number}", 0.5 if number == 0 else None) for number in range(10_001)],
        )
    assert state.totals() == (10_001, 0.5), "the oldest line counted, and its cost too"


@case
def a_session_paid_while_the_database_is_locked_is_logged_and_counted_all_the_same(
    state_home: Path,
) -> None:
    """`spend` swallowed every database error in silence.

    The audit of 2 November 2026 found 277 $ of sessions missing from
    `spending` on 23 and 24 October, which a failed write would have hidden
    just as well. One now leaves its trace in ponos.log, and its line beside
    the database: counted by the limit as it is, and written down by the next
    pass that can.
    """
    target = log.setup(state_home / "logs" / "ponos.log")
    assert target is not None
    state.spend(1.0, "before")
    db.connect().execute("PRAGMA busy_timeout = 50")
    holder = sqlite3.connect(db.path(), isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        state.spend(5.87, "1695")
        assert state.spent_today() == 6.87, "still owed, and counted all the same"
    finally:
        holder.rollback()
        holder.close()
        db.connect().execute(f"PRAGMA busy_timeout = {db.BUSY_TIMEOUT_MS}")
    written = target.read_text(encoding="utf-8")
    assert "ERROR ponos.state:" in written and "5.87" in written, written
    assert "database is locked" in written and "Traceback" in written, written

    assert state.spent_today() == 6.87, "written down by the next pass"
    with db.transaction(immediate=False) as connection:
        rows = connection.execute("SELECT ticket, cost_usd FROM spending ORDER BY id").fetchall()
    assert rows == [("before", 1.0), ("1695", 5.87)], rows
    state.spend(0.13, "after")
    assert round(state.spent_today(), 2) == 7.0, "once, and only once"


@case
def the_statistics_read_the_history_off_its_columns(state_home: Path) -> None:
    """What `outcomes` gives the statistics is what they read of the whole lines."""
    entries: list[dict[str, Any]] = [
        {"id": "a-1", "status": "done", "merged": "https://x/pull/1", "cost_usd": 1.5},
        {"id": "b-2", "status": "blocked", "reason": "credit balance is too low", "seconds": 30},
        {"id": "c-3", "status": "failed", "code": "unknown", "reason": "kept off its column"},
        {"id": "d-4", "status": "done", "kind": "document", "at": "2026-10-01T10:00:00+00:00"},
        {"id": "e-5", "status": "review"},
    ]
    for entry in entries:
        state.record(entry)
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO history (at, ticket, status, entry) VALUES ('', 'f-6', 'done', 'broken')"
        )
    keys = ("id", "at", "status", "kind", "cost_usd", "seconds", "code", "merged", "reason")
    whole = state.history(1_000_000)
    read = state.outcomes()
    assert read[0]["merged"] == "https://x/pull/1" and read[1]["reason"]
    for line, entry in zip(read, whole, strict=False):
        assert set(line) == set(keys), line
        for key in keys:
            if key == "reason" and entry.get("code"):
                continue  # a stop with its cause has no need of its sentence
            assert (line[key] or "") == (entry.get(key) or ""), (key, line, entry)
    assert read[2]["reason"] is None and read[-1] == {
        **dict.fromkeys(keys),
        "id": "f-6",
        "at": "",
        "status": "done",
        "kind": "",
        "code": "",
    }, "a broken line counts by its columns"


@case
def the_daemon_unit_says_whether_it_runs_and_not_only_whether_it_is_enabled() -> None:
    """`is-enabled` stays true for a unit that failed: `ActiveState` is what tells."""
    running = systemd.describe("enabled", "ActiveState=active\nSubState=running\nNRestarts=2\n")
    assert running.running and running.label == "running" and running.restarts == 2
    failed = systemd.describe("enabled", "ActiveState=failed\nSubState=failed\n")
    assert not failed.running and failed.label == "failed"
    off = systemd.describe("disabled", "ActiveState=inactive\n")
    assert off.label == "disabled", "a unit switched off says so first"


@case
def the_timer_of_the_passes_is_no_longer_written_and_an_installed_one_is_taken_down() -> None:
    """The units an update writes are the daemon's; the timer it replaced goes, by itself."""
    previous = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    try:
        units = update.write_units(600, ROOT)
        assert not (units / "ponos.timer").exists()
        service = (units / "ponos.service").read_text()
        for directive in ("Type=simple", "Restart=always", "KillMode=process"):
            assert directive in service, directive
        assert " daemon" in service, "the unit runs the daemon"
        (units / "ponos.timer").write_text("[Timer]\n")
        calls: list[tuple[str, ...]] = []
        import shutil

        original, which = systemd._systemctl, shutil.which

        def recorded(*arguments: str) -> str:
            calls.append(arguments)
            return ""

        systemd._systemctl = recorded
        shutil.which = lambda *_, **__: "/bin/true"  # type: ignore[assignment]
        try:
            assert systemd.migrate(units)
            assert not systemd.migrate(units), "once"
        finally:
            systemd._systemctl, shutil.which = original, which
        assert not (units / "ponos.timer").exists()
        assert ("disable", "--now", "ponos.timer") in calls and ("enable", "ponos.service") in calls
    finally:
        if previous is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = previous


@case
def the_runner_unit_runs_its_sessions_behind_the_desktop() -> None:
    """Five sessions at nice 0, as equals of the browser they drive, and the
    desktop stopped answering: the unit `ponos service on` writes sets them back."""
    previous = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    try:
        units = update.write_units(600, ROOT)
    finally:
        if previous is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = previous
    service = (units / "ponos.service").read_text().splitlines()
    for directive in ("Nice=10", "CPUWeight=20", "IOSchedulingClass=idle", "MemoryHigh=60%"):
        assert directive in service, directive
    assert all("@" not in line for line in service if not line.startswith("#")), service
