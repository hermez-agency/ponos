"""`db.py`: the local database."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from support import ROOT, case

from ponos import config as C
from ponos import conversation, credits, db, images, state, sync
from ponos.web import statistics as web_statistics

# -- the local database ------------------------------------------------------


@case
def a_new_database_is_brought_to_the_current_schema(state_home):
    try:
        location, found, disorder = db.check()
        assert location == state_home / "ponos.db"
        assert found == len(db.MIGRATIONS) >= 1
        assert disorder == ""
        connection = db.connect()
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"runs", "steps"} <= tables, tables
        assert location.stat().st_mode & 0o777 == 0o600
        with db.transaction() as writing:
            run = writing.execute(
                "INSERT INTO runs (ticket, started_at) VALUES ('abc', '2026-10-02T10:00:00+00:00')"
            ).lastrowid
            writing.execute(
                "INSERT INTO steps (run, position, at, kind) VALUES (?, 1, '2026-10-02T10:00:01+00:00', 'text')",
                (run,),
            )
        with db.transaction(immediate=False) as reading:
            assert reading.execute("SELECT status FROM runs").fetchone()[0] is None, (
                "running: no status yet"
            )
        assert db.connect() is connection, "one connection per process"
    finally:
        db.close()


@case
def a_database_one_migration_behind_is_brought_up_to_date():
    """Faked with one more migration than the code has."""
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    db.open_at(location).close()

    def notes(connection):
        connection.execute("CREATE TABLE notes (text TEXT)")

    upgraded = db.open_at(location, (*db.MIGRATIONS, notes))
    try:
        assert db.version(upgraded) == len(db.MIGRATIONS) + 1
        upgraded.execute("INSERT INTO notes VALUES ('kept')")
    finally:
        upgraded.close()
    again = db.open_at(location, (*db.MIGRATIONS, notes))
    try:
        assert again.execute("SELECT text FROM notes").fetchall() == [("kept",)], (
            "applied once, not twice"
        )
    finally:
        again.close()


@case
def a_migration_that_fails_leaves_the_file_as_it_was():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    db.open_at(location).close()

    def broken(connection):
        connection.execute("CREATE TABLE half (x)")
        raise RuntimeError("halfway")

    try:
        db.open_at(location, (*db.MIGRATIONS, broken))
    except RuntimeError:
        pass
    else:
        raise AssertionError("the failure must reach the caller")
    connection = db.open_at(location)
    try:
        assert db.version(connection) == len(db.MIGRATIONS)
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'half'").fetchall()
    finally:
        connection.close()


@case
def two_processes_opening_a_new_database_together_both_get_it():
    """The timer and the console start at once: one migrates, the other finds it done."""
    home = tempfile.mkdtemp()
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from ponos import db;"
        "conn = db.connect();"
        "[conn.execute(\"INSERT INTO runs (ticket, started_at) VALUES ('t', 'now')\") for _ in range(50)];"
        "print(db.version(conn))"
    )
    environment = {**os.environ, "XDG_STATE_HOME": home}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(ROOT / "src")],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    for process in processes:
        out, err = process.communicate(timeout=60)
        assert process.returncode == 0, err
        assert out.strip() == str(len(db.MIGRATIONS)), out
    connection = db.open_at(Path(home) / "ponos" / "ponos.db")
    try:
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 200
    finally:
        connection.close()


def _json_installation(state_home: Path) -> dict:
    """The state directory of an installation from before the database, filled in.

    What each file holds is handed back, to be found again once it is a table.
    """
    state_home.mkdir(parents=True, exist_ok=True)
    history = [
        {
            "at": "2026-09-28T09:00:00+00:00",
            "ticket": "Fix the footer",
            "id": "a" * 32,
            "status": "done",
            "project": "app",
            "seconds": 312.4,
            "cost_usd": 1.25,
            "pull_request": "https://github.com/o/r/pull/7",
            "merged": "https://github.com/o/r/pull/7",
        },
        {
            "at": "2026-09-29T14:30:00+00:00",
            "ticket": "Write the guide",
            "id": "b" * 32,
            "status": "done",
            "kind": "document",
            "project": "docs",
            "cost_usd": 0.5,
        },
        {
            "at": "2026-09-30T08:00:00+00:00",
            "ticket": "Flaky",
            "id": "c" * 32,
            "status": "failed",
            "reason": "tests red",
        },
    ]
    (state_home / "history.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in history[:2])
        + "half a line of jso\n"
        + json.dumps(history[2])
        + "\n"
    )
    claims = {"a" * 32: "Validated", "d" * 32: "Ready"}
    (state_home / "claims.json").write_text(json.dumps(claims))
    (state_home / "rebases.json").write_text(json.dumps({"a" * 32: 2}))
    (state_home / "conversations.json").write_text(
        json.dumps(
            {
                "pages": {
                    "e" * 32: "2026-09-30T10:00:00+00:00",
                    "f" * 32: "2026-09-29T10:00:00+00:00",
                },
                "threads": {
                    "d1": {"session": "s-1", "answered": "c-42", "at": "2026-09-30T10:00:00+00:00"}
                },
                "cursor": 3,
                "at": 1790000000.5,
            }
        )
    )
    later = time.time() + 3600
    (state_home / "credits.json").write_text(json.dumps({"until": later, "since": time.time()}))
    (state_home / "reserve.json").write_text(
        json.dumps({"until": later + 60, "since": time.time()})
    )
    (state_home / "sync.json").write_text(
        json.dumps(
            {
                "p1": ["2026-09-30T10:00:00.000Z", "2026-09-30T10:00:01+00:00", "f1ngerpr1nt"],
                "p2": ["2026-09-29T10:00:00.000Z", "2026-09-29T10:00:01+00:00"],
            }
        )
    )
    journal = [
        {
            "at": "2026-09-30T10:00:00+00:00",
            "what": "conflict",
            "collection": "tickets",
            "page": "p1",
            "title": "Le ticket",
            "detail": "both moved",
        },
        {
            "at": "2026-09-30T10:05:00+00:00",
            "what": "seen",
            "collection": "tickets",
            "page": "p2",
            "title": "L'autre",
            "detail": "",
        },
    ]
    (state_home / "sync.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in journal))
    (state_home / "images").mkdir()
    pictures = {f"{'e' * 32}:cover": {"agreed": "emoji:🐾", "kind": "emoji", "url": ""}}
    (state_home / "images" / "index.json").write_text(json.dumps(pictures, ensure_ascii=False))
    return {
        "history": history,
        "claims": claims,
        "journal": journal,
        "pictures": pictures,
        "files": sorted(path.relative_to(state_home) for path in state_home.rglob("*.json*")),
    }


@case
def an_installation_of_json_files_starts_on_the_database_with_everything_it_had(state_home):
    """Same statistics, same conversations, same claims — and the files set aside, not deleted.

    Four processes open it at once, as the timer and the console do after an
    update: the files are read in once, not four times.
    """
    try:
        had = _json_installation(state_home)
        originals = {name: (state_home / name).read_bytes() for name in had["files"]}
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from ponos import db; print(db.version(db.connect()))"
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(ROOT / "src")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(4)
        ]
        for process in processes:
            out, err = process.communicate(timeout=60)
            assert process.returncode == 0, err
            assert out.strip() == str(len(db.MIGRATIONS)), out

        # Migration 17 gives every stop its cause, read back from its sentence.
        coded = [
            {**entry, "code": "unknown"} if entry.get("status") == "failed" else entry
            for entry in had["history"]
        ]
        assert state.history(1_000_000) == coded, "every whole line, in order, once"
        assert state.history(1) == coded[-1:]
        first, last = date(2026, 9, 1), date(2026, 9, 30)
        assert web_statistics.figures([], state.history(1_000_000), first, last) == (
            web_statistics.figures([], had["history"], first, last)
        ), "the same statistics"
        assert web_statistics.figures([], state.outcomes(), first, last) == (
            web_statistics.figures([], had["history"], first, last)
        ), "the same statistics, read off the columns"
        with db.transaction(immediate=False) as connection:
            spent = connection.execute(
                "SELECT project, sum(cost_usd) FROM history GROUP BY project ORDER BY project"
            ).fetchall()
        assert spent == [("", None), ("app", 1.25), ("docs", 0.5)], spent

        assert state.claims() == had["claims"], "the same claims"
        assert state.rebases("a" * 32) == 2 and state.rebased("a" * 32) == 3

        ledger = conversation.Ledger.load()
        assert ledger.known_pages() == ["e" * 32, "f" * 32], "the same conversations"
        assert ledger.session_of("d1") == "s-1" and ledger.answered("d1") == "c-42"
        assert ledger.cursor == 3 and ledger.at == 1790000000.5

        assert credits.held() > time.time() and credits.held(what="reserve") > credits.held()

        stamps = sync.Stamps()
        assert stamps.seen("p1") and stamps.printed("p1") == "f1ngerpr1nt"
        assert stamps.notion("p2") == "2026-09-29T10:00:00.000Z" and stamps.printed("p2") == ""
        assert sync.journal() == had["journal"]

        pictures = images.Cache(state_home / "images")
        assert pictures.entry("e" * 32, "cover") == had["pictures"][f"{'e' * 32}:cover"]

        for name, content in originals.items():
            assert not (state_home / name).exists(), f"{name} is no longer where it was read"
            kept = state_home / name.with_name(name.name + ".imported")
            assert kept.read_bytes() == content, f"{name} is set aside whole, never deleted"
    finally:
        db.close()


@case
def a_new_installation_has_nothing_to_import_and_nothing_to_set_aside(state_home):
    try:
        assert state.history() == [] and state.claims() == {} and sync.journal() == []
        assert conversation.Ledger.load().known_pages() == [] and credits.held() == 0.0
        assert sorted(path.name for path in state_home.iterdir() if ".imported" in path.name) == []
    finally:
        db.close()


@case
def a_database_newer_than_the_code_is_refused_untouched():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    newer = len(db.MIGRATIONS) + 3
    raw = sqlite3.connect(location)
    raw.execute(f"PRAGMA user_version = {newer}")
    raw.close()
    try:
        db.open_at(location)
    except db.TooNew as error:
        message = str(error)
        assert f"version {newer}" in message and f"up to {len(db.MIGRATIONS)}" in message, message
        assert "ponos update" in message
    else:
        raise AssertionError("a newer file must be refused")
    raw = sqlite3.connect(location)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == newer
        assert not raw.execute("SELECT 1 FROM sqlite_master").fetchall(), "nothing created"
    finally:
        raw.close()


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _migrated_by_a_branch(location):
    """A file migrated by a branch whose last two migrations were in the other
    order — `_write_ups` before `_stops_have_a_cause`, as on 12/10/2026. Those
    that main has after them since, the branch did not have yet."""
    names = [db.name(migration) for migration in db.MIGRATIONS]
    first, second = names.index("stops_have_a_cause"), names.index("write_ups")
    assert second == first + 1, "the two this test swaps"
    branch = (*db.MIGRATIONS[:first], db.MIGRATIONS[second])
    db.open_at(location, branch).close()


@case
def a_database_migrated_by_a_branch_in_another_order_is_finished_by_main():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    _migrated_by_a_branch(location)
    connection = db.open_at(location)
    try:
        assert db.version(connection) == len(db.MIGRATIONS)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"write_ups", "mends", "history", "runs", "migrations"} <= tables, tables
        assert "code" in _columns(connection, "history") and "code" in _columns(connection, "runs")
        done = db.applied(connection)
        assert sorted(done) == sorted(db.name(migration) for migration in db.MIGRATIONS), done
        first = done.index("write_ups")
        assert done[first : first + 2] == ["write_ups", "stops_have_a_cause"], (
            "the one applied under another rank is not again"
        )
    finally:
        connection.close()
    again = db.open_at(location)
    try:
        assert db.version(again) == len(db.MIGRATIONS), "nothing left, nothing replayed"
    finally:
        again.close()


@case
def a_database_from_before_the_names_is_given_them_by_its_version():
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    old = db.open_at(location, db.MIGRATIONS[:5])
    old.execute("DROP TABLE migrations")
    old.close()
    connection = db.open_at(location)
    try:
        names = [db.name(migration) for migration in db.MIGRATIONS]
        assert db.applied(connection) == names
        rows = connection.execute("SELECT name, at FROM migrations ORDER BY rowid").fetchall()
        assert all(at == "" for _, at in rows[:5]), "filled in: nobody wrote the moment down"
        assert all(at for _, at in rows[5:]), "applied now, and said when"
        assert db.disorder(connection) == ""
    finally:
        connection.close()


@case
def a_database_that_went_through_a_migration_this_code_does_not_know_is_refused_untouched():
    location = Path(tempfile.mkdtemp()) / "ponos.db"

    def notes(connection):
        connection.execute("CREATE TABLE notes (text TEXT)")

    # Another branch's: in the middle of the list, at the rank main has one more.
    db.open_at(location, (*db.MIGRATIONS[:-1], notes)).close()
    raw = sqlite3.connect(location)
    before = raw.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
    raw.close()
    try:
        db.open_at(location)
    except db.TooNew as error:
        assert "notes" in str(error) and "ponos update" in str(error), str(error)
    else:
        raise AssertionError("a migration nobody here knows must stop the file being written")
    raw = sqlite3.connect(location)
    try:
        assert raw.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall() == before
        assert raw.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    finally:
        raw.close()


@case
def a_checkout_does_not_write_the_real_state_unless_told_to(state_home):
    if C.checkout() is None:
        return  # a copy without its .git: an installation, which this is not about
    assert C.checkout() == ROOT
    previous = os.environ.pop("XDG_STATE_HOME", None)
    try:
        try:
            C.refuse_real_state()
        except C.RealStateRefused as error:
            assert "XDG_STATE_HOME" in str(error), str(error)
        else:
            raise AssertionError("a checkout without XDG_STATE_HOME must be refused")
        try:
            db.connect()
        except db.DatabaseError as error:
            assert "XDG_STATE_HOME" in str(error), str(error)
        else:
            raise AssertionError("nor open the real database")
    finally:
        if previous is not None:
            os.environ["XDG_STATE_HOME"] = previous
    home = Path(tempfile.mkdtemp())
    environment = {key: value for key, value in os.environ.items() if key != "XDG_STATE_HOME"}
    environment.update(HOME=str(home), PYTHONPATH=str(ROOT / "src"))
    done = subprocess.run(
        [sys.executable, "-m", "ponos", "history"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 2 and "XDG_STATE_HOME=$(mktemp -d)" in done.stderr, done.stderr
    assert not (home / ".local" / "state").exists(), "nothing written"
    C.refuse_real_state()
