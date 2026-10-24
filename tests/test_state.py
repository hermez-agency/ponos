"""`state.py`: the lock, the claims, and the timer that keeps the runner alive."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from support import ROOT, _state_home, case

from ponos import config as C
from ponos import db, state, systemd, update

# -- staying alive -----------------------------------------------------------


@case
def a_lock_left_by_a_dead_run_is_not_a_run(state_home):
    """`run.lock` on disk is what a killed run leaves behind; the flock is not.

    For two hours on 7 September 2026, `status` read the leftover file as a run
    in progress, and the search for the silence went the wrong way.
    """
    state_home.mkdir(parents=True)
    (state_home / "run.lock").write_text("4242 2026-09-07T11:57:17+00:00\n")
    assert state.running() == "", "a file nobody holds is not a run"
    with state.lock():
        assert state.running().startswith(str(os.getpid())), "a held lock is one"
    assert state.running() == ""


@case
def a_run_turned_away_leaves_the_lock_and_its_holder_alone(state_home):
    """The lock file is one inode for good, and its PID survives a refusal.

    Unlinking it on release let a run waiting on the old inode and a run that
    created a new one both hold "the" lock. And `open("w")` emptied the file
    before asking for the lock — so a run turned away as busy had erased the
    name of the run that turned it away.
    """
    path = state_home / "run.lock"
    with state.lock():
        inode = path.stat().st_ino
        try:
            with state.lock():
                raise AssertionError("two runs held the lock at once")
        except state.Busy:
            pass
        assert path.read_text().startswith(f"{os.getpid()} "), "the holder is still named"
        assert state.running().startswith(str(os.getpid()))
    assert path.exists(), "the lock file is never removed"
    assert path.stat().st_ino == inode, "and never replaced"
    assert path.read_text() == "", "nobody is named once the lock is let go of"
    assert path.stat().st_mode & 0o777 == 0o600
    with state.lock():
        assert path.stat().st_ino == inode
        assert path.read_text().count("\n") == 1, "one holder, written once"


@case
def a_copy_of_a_secret_is_private_before_it_holds_anything():
    """The console's token, and the copies a save makes of the configuration.

    Written with the umask and tightened with `chmod` afterwards, each was
    readable by the group for the moment in between — the configuration holds
    the Notion token, the bot tokens and the console's password.
    """
    from ponos import disk
    from ponos.web import server as web_server

    created: list[tuple[str, int]] = []
    original = disk.os.open

    def spying(path, flags, mode=0o777, *rest, **kept):
        if flags & os.O_CREAT:
            created.append((str(path), mode))
        return original(path, flags, mode, *rest, **kept)

    previous = os.umask(0o022)
    disk.os.open = spying
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
        disk.os.open = original
        os.umask(previous)
    names = {Path(name).name: mode for name, mode in created}
    assert names.get("token") == 0o600, names
    assert names.get("config.toml.bak") == 0o600, names
    assert any(
        name.startswith(".config.toml.saving") and mode == 0o600 for name, mode in names.items()
    ), names


@case
def a_claim_is_written_whole_or_not_at_all(state_home):
    """A crash halfway through a write must leave the claims as they were.

    A lost claim reads as "no claim", and a validated ticket without its claim
    comes back from a crash as work to redo. And two publications of one pass
    claim side by side: neither may lose the other's.
    """
    try:
        state.claim("a" * 32, "Validated")
        try:
            with db.transaction() as connection:
                connection.execute("DELETE FROM claims")
                connection.execute("INSERT INTO claims VALUES (?, ?)", ("b" * 32, "Ready"))
                raise OSError("disk full")
        except OSError:
            pass
        assert state.claims() == {"a" * 32: "Validated"}, "the old claims are intact"
        workers = [
            threading.Thread(target=state.claim, args=(f"{n:032d}", "Ready")) for n in range(8)
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
def what_a_session_said_is_kept_for_this_account_only(state_home):
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
def the_totals_count_every_line_of_the_history(state_home):
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
def a_timer_with_no_next_run_is_stalled_rather_than_enabled():
    """What the incident's timer answered, and what a healthy one answers."""
    starved = systemd.describe(
        "enabled",
        "SubState=elapsed\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=infinity\n",
        "NEXT LEFT LAST PASSED UNIT ACTIVATES\n- - Mon 2026-09-07 13:57:17 CEST 2h ago ponos.timer ponos.service\n",
    )
    assert starved.stalled and starved.label == "stalled"
    assert starved.row.startswith("- -"), "the list-timers line travels with the verdict"

    armed = systemd.describe(
        "enabled", "SubState=waiting\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=18h 48min\n"
    )
    assert armed.armed and not armed.stalled and armed.label == "enabled"

    busy = systemd.describe(
        "enabled", "SubState=running\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=\n"
    )
    assert busy.running and not busy.stalled, "no next run while the service runs is a run"

    off = systemd.describe(
        "disabled", "SubState=dead\nNextElapseUSecRealtime=\nNextElapseUSecMonotonic=\n"
    )
    assert not off.stalled and off.label == "disabled", "only an enabled timer can lie"
    assert systemd.describe("", "").label == "", "and what is not installed says so as it did"


@case
def the_timer_counts_from_its_own_start():
    """OnBootSec serves once; OnUnitActiveSec needs a service that ran. A timer
    restarted after a failed run had neither, and never fired again."""
    previous = os.environ.get("HOME")
    os.environ["HOME"] = tempfile.mkdtemp()
    try:
        units = update.write_units(600, ROOT)
    finally:
        os.environ["HOME"] = previous
    timer = (units / "ponos.timer").read_text()
    for directive in ("OnActiveSec=600s", "OnBootSec=600s", "OnUnitActiveSec=600s"):
        assert directive in timer, directive
    assert "@" not in timer, "a placeholder left in the unit"
