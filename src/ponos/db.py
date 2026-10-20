"""The runner's local memory, in one SQLite file: ~/.local/state/ponos/ponos.db.

It does not replace the board. Tickets stay in Notion or in Markdown, because
that is where you read and edit them; this is what the runner keeps *about*
its own work, and wants to ask questions of rather than read back whole — the
dozen JSON files beside it, each with its own atomic write and no version
number, could only ever be reread from the first line. `sqlite3` ships with
Python, so the core still needs nothing but `python3` and `git`.

**One connection per process, and WAL.** The timer's run and the console are
two processes writing the same file at the same time. Write-ahead logging lets
one write while the other reads, and `busy_timeout` makes a second writer wait
its turn instead of failing on `database is locked`. Inside a process, the
console answers from several threads: they share the one connection, and
`transaction()` takes them in turn.

**Migrations, numbered by `PRAGMA user_version`.** The schema's version lives
in the file's own header, so it cannot drift from the tables it describes.
`MIGRATIONS` is an ordered tuple, and the version is how many of them have
been applied: a migration is only ever appended, never edited once released —
an installation that already ran it will not run it again. Each one runs in
its own `BEGIN IMMEDIATE` with the version bumped inside it, so a migration
that raises leaves the file as it was, and two processes starting together do
not both apply it: the second waits on the write lock, reads the version again
once it has it, and finds nothing left to do.

**Migrations known by their name, not only by their number.** Counting
assumed one list for everybody, and a branch has its own until it is rebased:
the file migrated by a branch where `_write_ups` was the 18th was then asked by
main, where it is the 19th, to apply the 19th once more — and every run's
journal stopped on "table write_ups already exists" for an evening. So the file
keeps, in `migrations`, the name of each one it went through (a function's name
without its underscore) and when, and `migrate` applies those whose name is not
there, wherever they sit in the list; one applied under another rank is not
applied again. A file from before the table has it filled in from its version,
by rank, as the only thing it can be read from — `at` empty, since nobody wrote
the moment down. `user_version` is still kept, as the number of names, for the
runner from before them. `doctor` says when the names are not in the code's
order: the schema is whole, but was once written by another branch's code.

**A file newer than the code is refused, not read.** A downgrade — a rollback
of the install, two machines sharing a state directory — would otherwise have
an old runner writing into tables it does not know the shape of. It says which
version it found and which it knows — or which migration it has never heard
of, the mark of a newer version or of another branch — and touches nothing.

Migration 1 holds what the next tickets need first: a run, and the steps of a
run. A run is one session on one ticket — a ticket run three times is three
rows, which is the point: `history.jsonl` keeps one line per outcome and has
no place for the attempts in between. The ticket is referred to by its board
id and copied by title, because the board is not ours to join against and a
renamed or deleted ticket must not take its runs with it. Times are ISO 8601
in UTC, as text, the way every other file here writes them; `status` stays
NULL while a run is still going, so a run killed mid-way is findable for what
it is. A step is one line of what the session did, in order — `position`
rather than the clock, because two steps can share a second.

Migration 2 is what filling them taught: a step is `said`, `tool` or `error`,
and a tool step is two things — the tool, and what it was pointed at — which
one `text` column could only hold glued together. So `tool` has its own, and
`cost_usd` says what the run had cost when the step was taken, as far as it
was known then: Claude Code reports a price at the end of a session, so it is
NULL until one has ended — the first half of a session picked up again.
See journal.py for who writes them, and who reads them.

Migrations 3 to 9 retire the JSON files that sat beside this one — the history,
the claims, the replay counts, the conversations, the credit waits, the
Markdown mirror's stamps and journal, the index of project pictures — one file
per migration. Each creates its table, reads the file in, and once that is
committed renames it `<name>.imported`: never deleted, the same rule as
`legacy.py`, and never read again. A file that is not there is an installation
that never wrote it, and the table starts empty. Session logs stay files: they
are read whole, by a person, and are pruned by age.

Migration 10 has a run say which model it ran on, whether that model was
chosen by the runner rather than written by somebody, and whether it was one
level up from a run that failed — what models.py reads to climb once, and only
once.

Migration 12 holds the ideas Ponos proposes and what was decided about them —
see ideas.py. A batch is a row of its own because a batch is what a session
costs: ten ideas come out of one call, and the price is the batch's before it
is anybody's share. An idea outlives the decision taken on it — kept or thrown
away, it stays, since it is what the next batch is told never to propose again.

Migration 13 is the MCP server's — see web/oauth.py and web/mcp.py: the clients
that registered, the codes and tokens they were given, and every write one of
them asked for. A token is kept as its SHA-256 and never as itself, so a copy of
this file opens nothing; a code, an access token, a refresh token and a token
drawn for Claude Code are one table told apart by `kind`, because they are
checked, expired and revoked the same way.

Migration 14 tells who wrote an idea and what happened to it since. An idea is
Ponos's or a person's (`origin`, and the person's name and picture, copied as
they were then, since nothing here can look a person up later); a person may
reword one, and the last of them is kept with the moment. Being kept and
becoming a ticket part ways: `kept` is a decision, `ticket` is a page on the
board — every idea kept before this migration had become one, so it is moved
there. `changed_at` is when the status last changed, whichever way: unlike
`decided_at`, it is not cleared when an idea is proposed again.

Migration 15 is why a ready ticket is still where it is: the pass writes it
down each time it reads the column and leaves a ticket there — still running,
every place taken — and the console reads it to say so on the card. Nothing
about it outlives the pass that wrote it, so the table is rewritten whole, and
emptied when the pass ends; it is a table and not a file because the console
reads it while the run writes it.

Migration 16 holds what a project decides for itself, against the settings of
`config.toml` — see project_settings.py. One row a project, keyed by its page
id without dashes, and its settings as one JSON object: the first of them is
its own automatic validation, and the next ones are keys of the same object
rather than a migration each. Here rather than on the board because nobody
should have to add a column to their Notion database for a switch of Ponos's;
the project's name is copied beside it, as `runs` copies a ticket's title, so
that the global settings can say which projects decide for themselves without
reading the board.

Migration 17 gives a stop its cause: a `code` column on the history and on
the runs, from the catalogue of blocks.py. A blocked or failed line written
before it had only its sentence, in whichever language and wording the runner
had that day; the migration reads the cause back from it (`blocks.classify`),
and writes the code into the line's own JSON too, since that is what the
statistics read. A sentence that matches nothing is `unknown` — counted, and
said to be unclassified, rather than guessed.

Migration 19 is the tickets whose session was picked up once more, only to
write the report it stopped without — see `Execution._write_up`. Once a ticket,
ever: a session that does not write it when asked is not asked again, on this
run or on the next one, and the table is what remembers that across a restart.

Migration 21 sorts an idea into one category — UX/UI, feature, security or
technical, see ideas.py. A column with one value rather than a table of tags,
because an idea is one of them and nothing else. Those written before it are
left unsorted (""), not guessed at: nothing read then said which they were.

Migration 24 gives an idea its score, out of 100 — see ideas.py. A column of
its own rather than a key of `detail`, because the list is sorted and filtered
on it; NULL is "not scored", which is what every idea from before it is, and
stays until somebody asks for it to be scored. The line that says why is
read, never sorted on, so it goes into `detail` with the rest of what an idea
says.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .config import RealStateRefused, refuse_real_state, state_dir

# How long a writer waits for the other process to finish before it gives up.
# A run's write is a row or two; the console's, the same. Five seconds is many
# times either, and still short enough to be an answer.
BUSY_TIMEOUT_MS = 5000


class DatabaseError(Exception):
    """The local database cannot be opened, or cannot be brought up to date."""


class TooNew(DatabaseError):
    """The file was written by a newer Ponos than the one running."""


def path() -> Path:
    return state_dir() / "ponos.db"


def _runs_and_steps(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE runs (
            id          INTEGER PRIMARY KEY,
            ticket      TEXT NOT NULL,
            title       TEXT NOT NULL DEFAULT '',
            kind        TEXT NOT NULL DEFAULT '',
            project     TEXT NOT NULL DEFAULT '',
            agent       TEXT NOT NULL DEFAULT '',
            session     TEXT NOT NULL DEFAULT '',
            log         TEXT NOT NULL DEFAULT '',
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            status      TEXT,
            reason      TEXT NOT NULL DEFAULT '',
            cost_usd    REAL
        )
        """
    )
    connection.execute("CREATE INDEX runs_by_ticket ON runs (ticket, started_at)")
    connection.execute("CREATE INDEX runs_by_start ON runs (started_at)")
    connection.execute(
        """
        CREATE TABLE steps (
            id        INTEGER PRIMARY KEY,
            run       INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            position  INTEGER NOT NULL,
            at        TEXT NOT NULL,
            kind      TEXT NOT NULL,
            text      TEXT NOT NULL DEFAULT '',
            UNIQUE (run, position)
        )
        """
    )


# -- the JSON files that came before ------------------------------------------
#
# Migrations 3 to 9 each take one of the files the runner kept beside this one,
# make it a table, and read it in once. They read the file themselves rather
# than through the module that now uses the table: a migration is frozen once
# released, and the module is not.


def _beside(connection: sqlite3.Connection, name: str) -> Path | None:
    """A file next to the database, or None for a database that is not a file."""
    row = connection.execute("PRAGMA database_list").fetchone()
    return Path(row[2]).parent / name if row and row[2] else None


def _read_json(location: Path | None) -> object:
    """What a JSON file holds, or None when it is missing or unreadable — as the
    module that wrote it read it."""
    if location is None:
        return None
    try:
        return json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_lines(location: Path | None) -> list[dict]:
    """Every whole line of a JSONL file, a broken one skipped as it always was."""
    if location is None:
        return []
    try:
        lines = location.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            found.append(entry)
    return found


def _set_aside(*files: Path | None) -> AfterCommit:
    """Rename what was imported to `<name>.imported`, once the import is committed.

    Never deleted — the same rule as `legacy.py`: what a user had stays on disk
    until they remove it. And only after the commit: a rename before it would
    lose the file to a migration that then rolled back. A crash between the two
    leaves the file where it was, read by nobody.
    """

    def rename() -> None:
        for location in files:
            if location is None or not location.exists():
                continue
            try:
                location.rename(location.with_name(location.name + ".imported"))
            except OSError:
                pass  # another process got there first, or the directory is read-only

    return rename


def _number(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _history(connection: sqlite3.Connection) -> AfterCommit:
    """history.jsonl — one row per outcome, the whole line kept in `entry`.

    The line is kept whole because its keys vary with what happened (a pull
    request, a merge, a reason); what one sorts and sums on — when, which
    ticket, how it ended, which project, how long, how much — is copied into
    columns of its own.
    """
    connection.execute(
        """
        CREATE TABLE history (
            id        INTEGER PRIMARY KEY,
            at        TEXT NOT NULL DEFAULT '',
            ticket    TEXT NOT NULL DEFAULT '',
            status    TEXT NOT NULL DEFAULT '',
            kind      TEXT NOT NULL DEFAULT '',
            project   TEXT NOT NULL DEFAULT '',
            seconds   REAL,
            cost_usd  REAL,
            entry     TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX history_by_at ON history (at)")
    source = _beside(connection, "history.jsonl")
    for entry in _read_lines(source):
        connection.execute(
            "INSERT INTO history (at, ticket, status, kind, project, seconds, cost_usd, entry)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(entry.get("at") or ""),
                str(entry.get("id") or ""),
                str(entry.get("status") or ""),
                str(entry.get("kind") or ""),
                str(entry.get("project") or ""),
                _number(entry.get("seconds")),
                _number(entry.get("cost_usd")),
                json.dumps(entry, ensure_ascii=False),
            ),
        )
    return _set_aside(source)


def _claims(connection: sqlite3.Connection) -> AfterCommit:
    """claims.json — the column each ticket in flight was taken from."""
    connection.execute("CREATE TABLE claims (ticket TEXT PRIMARY KEY, status TEXT NOT NULL)")
    source = _beside(connection, "claims.json")
    held = _read_json(source)
    if isinstance(held, dict):
        connection.executemany(
            "INSERT OR REPLACE INTO claims (ticket, status) VALUES (?, ?)",
            [(str(ticket), str(status)) for ticket, status in held.items()],
        )
    return _set_aside(source)


def _rebases(connection: sqlite3.Connection) -> AfterCommit:
    """rebases.json — how many times a validated ticket has been replayed."""
    connection.execute("CREATE TABLE rebases (ticket TEXT PRIMARY KEY, count INTEGER NOT NULL)")
    source = _beside(connection, "rebases.json")
    held = _read_json(source)
    if isinstance(held, dict):
        connection.executemany(
            "INSERT OR REPLACE INTO rebases (ticket, count) VALUES (?, ?)",
            [(str(ticket), int(count)) for ticket, count in held.items() if str(count).isdigit()],
        )
    return _set_aside(source)


def _conversations(connection: sqlite3.Connection) -> AfterCommit:
    """conversations.json — the pages spoken on, the threads, and where the scan is.

    `conversation_scan` has one row, always the same: the cursor of the
    rotation and the moment of the last scan.
    """
    connection.execute(
        "CREATE TABLE conversation_pages (page TEXT PRIMARY KEY, at TEXT NOT NULL DEFAULT '')"
    )
    connection.execute(
        """
        CREATE TABLE conversation_threads (
            discussion  TEXT PRIMARY KEY,
            session     TEXT NOT NULL DEFAULT '',
            answered    TEXT NOT NULL DEFAULT '',
            at          TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE conversation_scan (
            id      INTEGER PRIMARY KEY CHECK (id = 1),
            cursor  INTEGER NOT NULL DEFAULT 0,
            at      REAL NOT NULL DEFAULT 0
        )
        """
    )
    source = _beside(connection, "conversations.json")
    raw = _read_json(source)
    if isinstance(raw, dict):
        pages = raw.get("pages") if isinstance(raw.get("pages"), dict) else {}
        connection.executemany(
            "INSERT OR REPLACE INTO conversation_pages (page, at) VALUES (?, ?)",
            [(str(page), str(at)) for page, at in pages.items()],
        )
        threads = raw.get("threads") if isinstance(raw.get("threads"), dict) else {}
        connection.executemany(
            "INSERT OR REPLACE INTO conversation_threads (discussion, session, answered, at)"
            " VALUES (?, ?, ?, ?)",
            [
                (
                    str(discussion),
                    str(thread.get("session") or ""),
                    str(thread.get("answered") or ""),
                    str(thread.get("at") or ""),
                )
                for discussion, thread in threads.items()
                if isinstance(thread, dict)
            ],
        )
        cursor = _number(raw.get("cursor")) or 0
        at = _number(raw.get("at")) or 0.0
        connection.execute(
            "INSERT INTO conversation_scan (id, cursor, at) VALUES (1, ?, ?)", (int(cursor), at)
        )
    return _set_aside(source)


def _waits(connection: sqlite3.Connection) -> AfterCommit:
    """credits.json and reserve.json — the two waits, one row each while it lasts."""
    connection.execute(
        """
        CREATE TABLE waits (
            what   TEXT PRIMARY KEY,
            until  REAL NOT NULL,
            since  REAL NOT NULL DEFAULT 0
        )
        """
    )
    sources = {
        "spent": _beside(connection, "credits.json"),
        "reserve": _beside(connection, "reserve.json"),
    }
    for what, source in sources.items():
        note = _read_json(source)
        if not isinstance(note, dict) or not _number(note.get("until")):
            continue
        connection.execute(
            "INSERT INTO waits (what, until, since) VALUES (?, ?, ?)",
            (what, _number(note.get("until")), _number(note.get("since")) or 0.0),
        )
    return _set_aside(*sources.values())


def _sync(connection: sqlite3.Connection) -> AfterCommit:
    """sync.json and sync.jsonl — what the two boards last agreed on, and the journal."""
    connection.execute(
        """
        CREATE TABLE sync_stamps (
            page      TEXT PRIMARY KEY,
            notion    TEXT NOT NULL DEFAULT '',
            markdown  TEXT NOT NULL DEFAULT '',
            printed   TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE sync_journal (
            id          INTEGER PRIMARY KEY,
            at          TEXT NOT NULL DEFAULT '',
            what        TEXT NOT NULL DEFAULT '',
            collection  TEXT NOT NULL DEFAULT '',
            page        TEXT NOT NULL DEFAULT '',
            title       TEXT NOT NULL DEFAULT '',
            detail      TEXT NOT NULL DEFAULT ''
        )
        """
    )
    stamps_file = _beside(connection, "sync.json")
    stamps = _read_json(stamps_file)
    if isinstance(stamps, dict):
        rows = []
        for page, known in stamps.items():
            known = [str(value or "") for value in known] if isinstance(known, list) else []
            known += [""] * (3 - len(known))
            rows.append((str(page), known[0], known[1], known[2]))
        connection.executemany(
            "INSERT OR REPLACE INTO sync_stamps (page, notion, markdown, printed) VALUES (?, ?, ?, ?)",
            rows,
        )
    journal_file = _beside(connection, "sync.jsonl")
    connection.executemany(
        "INSERT INTO sync_journal (at, what, collection, page, title, detail) VALUES (?, ?, ?, ?, ?, ?)",
        [
            tuple(
                str(entry.get(name) or "")
                for name in ("at", "what", "collection", "page", "title", "detail")
            )
            for entry in _read_lines(journal_file)
        ],
    )
    return _set_aside(stamps_file, journal_file)


def _images(connection: sqlite3.Connection) -> AfterCommit:
    """images/index.json — what was agreed on each project picture, by page and slot.

    An entry is kept as the JSON it was: its shape is `images.py`'s business
    (agreed, pending, conflict, the copy on disk), and nothing asks it questions.
    """
    connection.execute("CREATE TABLE images (key TEXT PRIMARY KEY, entry TEXT NOT NULL)")
    source = _beside(connection, "images/index.json")
    known = _read_json(source)
    if isinstance(known, dict):
        connection.executemany(
            "INSERT OR REPLACE INTO images (key, entry) VALUES (?, ?)",
            [
                (str(key), json.dumps(entry, ensure_ascii=False))
                for key, entry in known.items()
                if isinstance(entry, dict)
            ],
        )
    return _set_aside(source)


def _steps_name_their_tool(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE steps ADD COLUMN tool TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE steps ADD COLUMN cost_usd REAL")


def _runs_say_their_model(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE runs ADD COLUMN model TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE runs ADD COLUMN chosen INTEGER NOT NULL DEFAULT 0")
    connection.execute("ALTER TABLE runs ADD COLUMN escalated INTEGER NOT NULL DEFAULT 0")


def _runs_say_the_model_they_ran(connection: sqlite3.Connection) -> None:
    # What the session announced of itself, as opposed to `model`, what it was asked to run on.
    connection.execute("ALTER TABLE runs ADD COLUMN reported TEXT NOT NULL DEFAULT ''")


def _ideas(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE idea_batches (
            id          INTEGER PRIMARY KEY,
            scope       TEXT NOT NULL,
            project     TEXT NOT NULL DEFAULT '',
            model       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            count       INTEGER NOT NULL DEFAULT 0,
            cost_usd    REAL,
            error       TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ideas (
            id           INTEGER PRIMARY KEY,
            batch        INTEGER REFERENCES idea_batches (id) ON DELETE SET NULL,
            scope        TEXT NOT NULL,
            project      TEXT NOT NULL DEFAULT '',
            kind         TEXT NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT NOT NULL DEFAULT '',
            detail       TEXT NOT NULL DEFAULT '{}',
            status       TEXT NOT NULL DEFAULT 'proposed',
            ticket       TEXT NOT NULL DEFAULT '',
            created      TEXT NOT NULL DEFAULT '',
            cost_usd     REAL,
            created_at   TEXT NOT NULL,
            decided_at   TEXT
        )
        """
    )
    connection.execute("CREATE INDEX ideas_by_scope ON ideas (scope, project, status)")
    connection.execute("CREATE INDEX ideas_by_decision ON ideas (decided_at)")


def _mcp(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE mcp_clients (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL DEFAULT '',
            redirect_uris  TEXT NOT NULL DEFAULT '[]',
            secret         TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE mcp_tokens (
            id          INTEGER PRIMARY KEY,
            hash        TEXT NOT NULL UNIQUE,
            kind        TEXT NOT NULL,
            client      TEXT NOT NULL REFERENCES mcp_clients (id) ON DELETE CASCADE,
            scope       TEXT NOT NULL DEFAULT '',
            detail      TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL,
            expires_at  TEXT,
            revoked_at  TEXT
        )
        """
    )
    connection.execute("CREATE INDEX mcp_tokens_by_client ON mcp_tokens (client, kind)")
    connection.execute(
        """
        CREATE TABLE mcp_calls (
            id         INTEGER PRIMARY KEY,
            at         TEXT NOT NULL,
            client     TEXT NOT NULL DEFAULT '',
            name       TEXT NOT NULL DEFAULT '',
            tool       TEXT NOT NULL,
            arguments  TEXT NOT NULL DEFAULT '{}',
            outcome    TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute("CREATE INDEX mcp_calls_by_time ON mcp_calls (at)")


def _ideas_say_who_wrote_them(connection: sqlite3.Connection) -> None:
    for column in (
        "origin TEXT NOT NULL DEFAULT 'ponos'",
        "author TEXT NOT NULL DEFAULT ''",
        "author_avatar TEXT NOT NULL DEFAULT ''",
        "edited_by TEXT NOT NULL DEFAULT ''",
        "edited_by_avatar TEXT NOT NULL DEFAULT ''",
        "edited_at TEXT",
        "changed_at TEXT",
    ):
        connection.execute(f"ALTER TABLE ideas ADD COLUMN {column}")
    connection.execute("UPDATE ideas SET status = 'ticket' WHERE status = 'kept'")
    connection.execute("UPDATE ideas SET changed_at = COALESCE(decided_at, created_at)")


def _held(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE held (
            ticket  TEXT PRIMARY KEY,
            reason  TEXT NOT NULL,
            detail  TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _project_settings(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE project_settings (
            project   TEXT PRIMARY KEY,
            name      TEXT NOT NULL DEFAULT '',
            settings  TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def _red_bases(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE base_waits (
            ticket  TEXT PRIMARY KEY,
            base    TEXT NOT NULL,
            url     TEXT NOT NULL,
            names   TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE base_repairs (
            repository  TEXT NOT NULL,
            base        TEXT NOT NULL,
            ticket      TEXT NOT NULL,
            PRIMARY KEY (repository, base)
        )
        """
    )


def _stops_have_a_cause(connection: sqlite3.Connection) -> None:
    from . import blocks

    connection.execute("ALTER TABLE history ADD COLUMN code TEXT NOT NULL DEFAULT ''")
    connection.execute("ALTER TABLE runs ADD COLUMN code TEXT NOT NULL DEFAULT ''")
    stopped = connection.execute(
        "SELECT id, entry FROM history WHERE status IN ('blocked', 'failed')"
    ).fetchall()
    for identifier, raw in stopped:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        code = blocks.known(entry.get("code")) or blocks.classify(str(entry.get("reason") or ""))
        entry["code"] = code
        connection.execute(
            "UPDATE history SET code = ?, entry = ? WHERE id = ?",
            (code, json.dumps(entry, ensure_ascii=False), identifier),
        )
    for identifier, reason in connection.execute(
        "SELECT id, reason FROM runs WHERE status IN ('blocked', 'failed')"
    ).fetchall():
        connection.execute(
            "UPDATE runs SET code = ? WHERE id = ?",
            (blocks.classify(str(reason or "")), identifier),
        )


def _write_ups(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE write_ups (ticket TEXT PRIMARY KEY, at TEXT NOT NULL DEFAULT '')"
    )


def _mends(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE mends (ticket TEXT NOT NULL, head TEXT NOT NULL, "
        "at TEXT NOT NULL DEFAULT '', PRIMARY KEY (ticket, head))"
    )


def _ideas_have_a_category(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE ideas ADD COLUMN category TEXT NOT NULL DEFAULT ''")


def _ideas_have_a_score(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE ideas ADD COLUMN score INTEGER")


def _notifications(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            ticket TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            at TEXT NOT NULL,
            read_at TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _ci(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE ci (
            ticket  TEXT PRIMARY KEY,
            url     TEXT NOT NULL,
            head    TEXT NOT NULL DEFAULT '',
            state   TEXT NOT NULL DEFAULT '',
            checks  TEXT NOT NULL DEFAULT '[]',
            since   REAL NOT NULL DEFAULT 0,
            asked   REAL NOT NULL DEFAULT 0
        )
        """
    )


def _chats(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE chats (
            id        TEXT PRIMARY KEY,
            title     TEXT NOT NULL DEFAULT '',
            model     TEXT NOT NULL DEFAULT '',
            project   TEXT NOT NULL DEFAULT '',
            claude    TEXT NOT NULL DEFAULT '',
            turns     INTEGER NOT NULL DEFAULT 0,
            folder    TEXT NOT NULL DEFAULT '',
            created   TEXT NOT NULL DEFAULT '',
            updated   TEXT NOT NULL DEFAULT '',
            messages  TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    connection.execute("CREATE INDEX chats_updated ON chats (updated)")


def _transitions(connection: sqlite3.Connection) -> None:
    # `watched`: the last status seen on each ticket that carries a prompt, and
    # how many generations of executions it is from a ticket a person made.
    # `transitions`: one row per change of status met, written in the same
    # transaction that moves `watched` forward — which is the whole of the
    # idempotence: a change is either on both sides or on neither.
    connection.execute(
        """
        CREATE TABLE watched (
            ticket  TEXT PRIMARY KEY,
            status  TEXT NOT NULL DEFAULT '',
            depth   INTEGER NOT NULL DEFAULT 0,
            at      TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE transitions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket      TEXT NOT NULL,
            title       TEXT NOT NULL DEFAULT '',
            project     TEXT NOT NULL DEFAULT '',
            old         TEXT NOT NULL DEFAULT '',
            new         TEXT NOT NULL DEFAULT '',
            depth       INTEGER NOT NULL DEFAULT 0,
            state       TEXT NOT NULL DEFAULT 'pending',
            seen_at     TEXT NOT NULL DEFAULT '',
            started_at  TEXT NOT NULL DEFAULT '',
            ended_at    TEXT NOT NULL DEFAULT '',
            cost_usd    REAL,
            seconds     REAL,
            session     TEXT NOT NULL DEFAULT '',
            result      TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute("CREATE INDEX transitions_by_ticket ON transitions (ticket, id)")


# Appended to, never edited or renamed: a file remembers each of these by name,
# and the version of a file is how many of them it has been through. Statements go through `execute` one at a time — `executescript`
# commits whatever transaction is open before it starts, which would apply half
# a migration under the old version number. What a migration returns, if
# anything, runs once its transaction is committed.
AfterCommit = Callable[[], None]
Migration = Callable[[sqlite3.Connection], AfterCommit | None]
MIGRATIONS: tuple[Migration, ...] = (
    _runs_and_steps,
    _steps_name_their_tool,
    _history,
    _claims,
    _rebases,
    _conversations,
    _waits,
    _sync,
    _images,
    _runs_say_their_model,
    _runs_say_the_model_they_ran,
    _ideas,
    _mcp,
    _ideas_say_who_wrote_them,
    _held,
    _project_settings,
    _red_bases,
    _stops_have_a_cause,
    _write_ups,
    _mends,
    _ideas_have_a_category,
    _notifications,
    _ci,
    _ideas_have_a_score,
    _chats,
    _transitions,
)

# Any way a read or a write of the database can fail. A note the runner keeps
# for itself is never a reason to fail a run; those that used to swallow an
# OSError on their JSON file swallow these.
ERRORS = (sqlite3.Error, DatabaseError)


def version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def name(migration: Migration) -> str:
    """What a migration is known by in the file: its function's name, without the underscore."""
    return migration.__name__.lstrip("_")


def applied(connection: sqlite3.Connection) -> list[str] | None:
    """The migrations the file says it has been through, in the order it went
    through them — None for a file from before they were named."""
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'migrations'"
    ).fetchone():
        return None
    return [row[0] for row in connection.execute("SELECT name FROM migrations ORDER BY rowid")]


def _refuse_newer(connection: sqlite3.Connection, names: list[str]) -> None:
    """Raise TooNew when the file has been through what this code does not know."""
    found = version(connection)
    if found > len(names):
        raise TooNew(
            f"{path_of(connection)} is at schema version {found}, and this Ponos "
            f"only knows up to {len(names)} — it was written by a newer version. "
            "Update Ponos (ponos update) rather than let an older one write into it"
        )
    done = applied(connection)
    if done is None:
        return
    unknown = [migration for migration in done if migration not in names]
    if unknown:
        raise TooNew(
            f"{path_of(connection)} has been through {', '.join(unknown)}, which this "
            "Ponos does not know — it was written by a newer version, or by another "
            "branch's code. Update Ponos (ponos update) rather than let this one write into it"
        )
    if found > len(done):
        raise TooNew(
            f"{path_of(connection)} is at schema version {found} but names only {len(done)} "
            "of its migrations — the others were applied by a Ponos that does not name "
            "them, a newer version or an older branch's. Update Ponos (ponos update) "
            "rather than let this one guess which they were"
        )


def migrate(connection: sqlite3.Connection, migrations: Sequence[Migration] = MIGRATIONS) -> int:
    """Apply every migration the file has not been through, and return its version.

    Raises TooNew, before writing anything, when the file has been through a
    migration this code does not know.
    """
    names = [name(migration) for migration in migrations]
    _refuse_newer(connection, names)
    if applied(connection) is None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Read again under the write lock, as below.
            _refuse_newer(connection, names)
            if applied(connection) is None:
                connection.execute(
                    "CREATE TABLE migrations (name TEXT PRIMARY KEY, at TEXT NOT NULL DEFAULT '')"
                )
                connection.executemany(
                    "INSERT INTO migrations (name) VALUES (?)",
                    [(done,) for done in names[: version(connection)]],
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    for migration, called in zip(migrations, names, strict=True):
        if called in (applied(connection) or []):
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Read again under the write lock: another process may have applied
            # this one while we were waiting for it.
            _refuse_newer(connection, names)
            done = applied(connection) or []
            if called in done:
                connection.execute("COMMIT")
                continue
            after = migration(connection)
            connection.execute(
                "INSERT INTO migrations (name, at) VALUES (?, ?)",
                (called, time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())),
            )
            connection.execute(f"PRAGMA user_version = {len(done) + 1}")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        if after is not None:
            after()
    return version(connection)


def disorder(connection: sqlite3.Connection, migrations: Sequence[Migration] = MIGRATIONS) -> str:
    """How the migrations the file went through differ from this code's list — or nothing.

    A file brought up to date has them all, but not always in this order: one
    migrated by a branch whose list was not yet rebased went through them in
    that branch's, and was then given the missing ones. Nothing is missing, so
    nothing is wrong to the runner; `doctor` still says it, since a schema is
    only known to be the one the code expects once the migrations agree.
    """
    names = [name(migration) for migration in migrations]
    done = applied(connection) or []
    missing = [migration for migration in names if migration not in done]
    unknown = [migration for migration in done if migration not in names]
    if missing or unknown:
        said = [f"missing {', '.join(missing)}"] if missing else []
        said += [f"unknown to this code: {', '.join(unknown)}"] if unknown else []
        return "; ".join(said)
    for position, (expected, found) in enumerate(zip(names, done, strict=True), start=1):
        if expected != found:
            return (
                f"applied in another order than this code's — {found} as number {position}, "
                f"where this code has {expected}: migrated by another branch's code"
            )
    return ""


def path_of(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA database_list").fetchone()
    return row[2] if row and row[2] else "the database"


def _switch_to_wal(connection: sqlite3.Connection) -> None:
    """Put the file in WAL mode, waiting out another process doing the same.

    Leaving the rollback journal takes the file to itself, and SQLite answers
    "database is locked" at once rather than through the busy handler when a
    second process is reading it in the old mode — which is just what the
    timer and the console do when they start together on a new file. So the
    wait the busy timeout gives every other statement is given here by hand.
    """
    deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
    while True:
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) or time.monotonic() > deadline:
                raise
            time.sleep(0.01)


def open_at(location: Path, migrations: Sequence[Migration] = MIGRATIONS) -> sqlite3.Connection:
    """A new connection to `location`, set up and migrated. Prefer `connect()`.

    The file is created private before SQLite opens it: SQLite gives its `-wal`
    and `-shm` companions the database's own mode, so they are private too.
    """
    location.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(location, os.O_CREAT | os.O_RDWR, 0o600))
        # Autocommit at the driver's level: transactions are begun by hand, so
        # that `BEGIN IMMEDIATE` is what actually starts one.
        connection = sqlite3.connect(
            location, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None, check_same_thread=False
        )
    except (OSError, sqlite3.Error) as error:
        raise DatabaseError(f"cannot open {location}: {error}") from error
    try:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        _switch_to_wal(connection)
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        migrate(connection, migrations)
    except DatabaseError:
        connection.close()
        raise
    except sqlite3.Error as error:
        connection.close()
        raise DatabaseError(f"cannot open {location}: {error}") from error
    return connection


_connections: dict[Path, sqlite3.Connection] = {}
_locks: dict[Path, threading.RLock] = {}
_opening = threading.Lock()


def connect(location: Path | None = None) -> sqlite3.Connection:
    """This process's connection to the database, opened and migrated the first time.

    Keyed by path, so that a test — or anything else that moves
    `XDG_STATE_HOME` — gets the file it points at, not the one opened first.
    `location` names another file than the state directory's, for a test.
    """
    if location is None:
        try:
            refuse_real_state()
        except RealStateRefused as error:
            raise DatabaseError(str(error)) from error
        location = path()
    with _opening:
        connection = _connections.get(location)
        if connection is None:
            connection = open_at(location)
            _connections[location] = connection
            _locks[location] = threading.RLock()
        return connection


@contextmanager
def transaction(
    immediate: bool = True, location: Path | None = None
) -> Iterator[sqlite3.Connection]:
    """One transaction on this process's connection, committed if the block returns.

    `immediate` takes the write lock up front, so a transaction that reads and
    then writes cannot be refused half-way by the other process; a read-only
    block passes False and waits for nobody.
    """
    location = location or path()
    connection = connect(location)
    with _locks[location]:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")


def close() -> None:
    """Close every connection this process holds — for tests, and a clean exit."""
    with _opening:
        for connection in _connections.values():
            connection.close()
        _connections.clear()
        _locks.clear()


def check() -> tuple[Path, int, str]:
    """Open the database and say where it is, at which version, and how its
    migrations differ from the code's — for `doctor`."""
    connection = connect()
    return path(), version(connection), disorder(connection)
