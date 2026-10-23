"""Every run, and every step of it, kept where the console can ask for them.

A run's detail used to have two homes, and neither was right for it. The
ticket's page got a bullet per tool call, until a ticket became a log nobody
reads twice — and a page rewritten every ten seconds, which is a page no cache
can keep (see progress.py, which now writes only what the agent says). The
session's `.jsonl` holds everything, but as a stream: the console read a whole
file to show its last thousand lines, could not page back through it, and knew
of no run but by its file name.

So each run is a row of the local database (db.py) and each step a row under
it, written as the session goes: what the console's « live » section reads,
page by page, for the run going on and for every run before it, and what
`ponos logs` looks a ticket's runs up in. It sits beside the board, not on it:
a Notion board, a Markdown one or both are written by a run the same way, and
the journal is the same for the three.

**A step is what `progress.describe` makes of an event**, the same reading the
page and the console have always used: what the agent said, which tool it
called on what, which call failed. Not the payload — what a command printed, a
file's content — which stays in the `.jsonl`, the complete record; a row is the
line you scan, the log is what you open once you know where to look.

**It never fails a ticket.** Every write is caught, and a database that refuses
one switches the journal off for the rest of the run: the session goes on, and
its log holds everything all the same.

A run's `status` is what the ticket came to — done, blocked, failed, waiting —
not only what its session did: a session that ended well and committed nothing
is a blocked ticket, and that is what its run says. `reason` is the sentence
beside it, or the pull request it opened; `code` is the cause of a run that
stopped, from blocks.py. A run the runner never got to close
— killed mid-session — keeps a NULL status, and reads as such.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db, progress

# How many steps one page of the console holds. A long session takes a few
# thousand; the end of it is what is read first, the rest a click away.
PAGE = 200

# What a step's text is cut to. Prose is already capped by `progress.SAID`,
# a tool's detail by `progress.LINE`; this is only a floor under both.
TEXT = 8000

_FAILURES = (db.DatabaseError, sqlite3.Error, OSError)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row(step: progress.Step) -> tuple[str, str, str]:
    """(kind, tool, text) for one step — the three things it can be."""
    if step.said:
        return "said", "", step.label[:TEXT]
    if step.label == "Error":
        return "error", "", step.detail[:TEXT]
    return "tool", step.label, step.detail[:TEXT]


class Run:
    """One run being written down: opened before its session, closed after its report.

    Held by the job, fed every event of the session, and told at the end what
    the ticket came to. Every method can be called on a journal that could not
    be opened, and does nothing then.
    """

    def __init__(
        self, identifier: int | None, say: Callable[[str], None] = lambda message: None
    ) -> None:
        self.id = identifier
        self.say = say
        self.position = 0
        # What the run has cost so far, from the `result` line each session
        # ends on — two when a lost session was started again.
        self.cost: float | None = None

    @classmethod
    def start(
        cls,
        *,
        ticket: str,
        title: str = "",
        kind: str = "",
        project: str = "",
        agent: str = "",
        session: str = "",
        log: Path | str = "",
        model: str = "",
        chosen: bool = False,
        escalated: bool = False,
        say: Callable[[str], None] = lambda message: None,
    ) -> Run:
        try:
            with db.transaction() as connection:
                identifier = connection.execute(
                    "INSERT INTO runs (ticket, title, kind, project, agent, session, log, started_at,"
                    " model, chosen, escalated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ticket.replace("-", ""),
                        title,
                        kind,
                        project,
                        agent,
                        session,
                        str(log),
                        _now(),
                        model,
                        int(chosen),
                        int(escalated),
                    ),
                ).lastrowid
        except _FAILURES as error:
            say(f"    ! run journal off for this ticket: {error}")
            return cls(None, say)
        return cls(identifier, say)

    @property
    def open(self) -> bool:
        return self.id is not None

    def event(self, payload: dict[str, Any]) -> None:
        """One stream-json event: its steps, and its price when it is the last one."""
        if not self.open:
            return
        if payload.get("type") == "system" and payload.get("subtype") == "init":
            # The model the session says it runs on: what was asked (`--model`,
            # or nothing) is not always what answers.
            announced = payload.get("model")
            if isinstance(announced, str) and announced.strip():
                self._write(
                    "UPDATE runs SET reported = ? WHERE id = ?", (announced.strip(), self.id)
                )
            return
        if payload.get("type") == "result":
            spent = payload.get("total_cost_usd")
            if isinstance(spent, (int, float)):
                self.cost = (self.cost or 0.0) + float(spent)
                self._write("UPDATE runs SET cost_usd = ? WHERE id = ?", (self.cost, self.id))
            return
        steps = progress.describe(payload)
        if not steps:
            return
        at = _now()
        rows = []
        for step in steps:
            self.position += 1
            rows.append((self.id, self.position, at, *_row(step), self.cost))
        self._write(
            "INSERT INTO steps (run, position, at, kind, tool, text, cost_usd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
            many=True,
        )

    def again(self, session: str, log: Path | str) -> None:
        """The session was started over: same run, a new session and its own log."""
        if self.open:
            self._write(
                "UPDATE runs SET session = ?, log = ? WHERE id = ?", (session, str(log), self.id)
            )

    def end(self, status: str, reason: str = "", code: str = "") -> None:
        """What the ticket came to, and the cause it stopped on. Once: a run closed is not reopened."""
        if not self.open:
            return
        self._write(
            "UPDATE runs SET ended_at = ?, status = ?, reason = ?, code = ?, cost_usd = ?"
            " WHERE id = ? AND ended_at IS NULL",
            (_now(), status, str(reason or "")[:TEXT], code, self.cost, self.id),
        )

    def _write(
        self, statement: str, values: tuple[Any, ...] | list[Any], many: bool = False
    ) -> None:
        try:
            with db.transaction() as connection:
                if many:
                    connection.executemany(statement, values)
                else:
                    connection.execute(statement, values)
        except _FAILURES as error:
            self.say(f"    ! run journal off for this ticket: {error}")
            self.id = None


# -- reading ------------------------------------------------------------------


def _ticket_key(reference: str) -> str:
    """A ticket however it was given — full id, dashed, a URL, the short form."""
    return (
        reference.strip().rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1].replace("-", "").lower()
    )


def _run(row: sqlite3.Row | tuple[Any, ...], names: list[str]) -> dict[str, Any]:
    entry = dict(zip(names, row, strict=True))
    entry["log"] = Path(entry["log"]).name if entry.get("log") else ""
    return entry


_RUN = (
    "SELECT runs.id, runs.ticket, runs.title, runs.kind, runs.project, runs.agent, runs.session,"
    " runs.log, runs.started_at, runs.ended_at, runs.status, runs.reason, runs.code, runs.cost_usd,"
    " runs.model, runs.reported,"
    " (SELECT count(*) FROM steps WHERE steps.run = runs.id) AS steps FROM runs"
)


def runs(ticket: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """The runs of one ticket — or of every ticket — newest first."""
    key = _ticket_key(ticket) if ticket else ""
    with db.transaction(immediate=False) as connection:
        if key:
            cursor = connection.execute(
                _RUN + " WHERE runs.ticket = ? OR substr(runs.ticket, -8) = ?"
                " ORDER BY runs.started_at DESC, runs.id DESC LIMIT ?",
                (key, key[-8:], limit),
            )
        else:
            cursor = connection.execute(
                _RUN + " ORDER BY runs.started_at DESC, runs.id DESC LIMIT ?", (limit,)
            )
        names = [column[0] for column in cursor.description]
        return [_run(row, names) for row in cursor.fetchall()]


def spans(ticket: str = "") -> dict[str, list[dict[str, Any]]]:
    """{ticket: its runs as intervals} — one ticket's, or every ticket's — for worktime.py.

    A run still open carries the moment of its last step as `last`, which is
    all that is known of it if the runner was killed. Empty when the journal
    cannot be read: a card without its time is still a card.
    """
    key = _ticket_key(ticket) if ticket else ""
    query = (
        "SELECT runs.ticket, runs.started_at, runs.ended_at, runs.status, runs.code,"
        " CASE WHEN runs.ended_at IS NULL THEN"
        " (SELECT max(steps.at) FROM steps WHERE steps.run = runs.id) END FROM runs"
    )
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                query + (" WHERE runs.ticket = ? OR substr(runs.ticket, -8) = ?" if key else ""),
                (key, key[-8:]) if key else (),
            ).fetchall()
    except _FAILURES:
        return {}
    found: dict[str, list[dict[str, Any]]] = {}
    for ticket_id, start, end, status, code, last in rows:
        found.setdefault(ticket_id, []).append(
            {
                "start": start,
                "end": end,
                "status": status,
                "code": code or "",
                "last": last or start,
            }
        )
    return found


def chosen(ticket: str) -> dict[str, Any] | None:
    """The last run of a ticket whose model the runner chose, and how it ended.

    What models.py climbs from. None when there is no such run — or no journal
    to ask: a choice made without it is the rules' alone, never a failure.
    """
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT model, status, escalated FROM runs WHERE ticket = ? AND chosen = 1"
                " ORDER BY started_at DESC, id DESC LIMIT 1",
                (ticket.replace("-", ""),),
            ).fetchone()
    except _FAILURES:
        return None
    if row is None:
        return None
    return {"model": row[0], "status": row[1] or "", "escalated": bool(row[2])}


def run(identifier: int) -> dict[str, Any] | None:
    with db.transaction(immediate=False) as connection:
        cursor = connection.execute(_RUN + " WHERE runs.id = ?", (identifier,))
        names = [column[0] for column in cursor.description]
        row = cursor.fetchone()
    return _run(row, names) if row else None


def steps(identifier: int, *, before: int = 0, after: int = 0, limit: int = PAGE) -> dict[str, Any]:
    """One page of a run's steps, in reading order.

    The last `limit` of them by default — a run is read from where it is — or
    those just before `before`, scrolling back, or every one after `after`,
    which is how a page following a live run asks for what is new. `more`
    says whether there are older ones than the first returned.
    """
    limit = max(1, min(int(limit), 1000))
    with db.transaction(immediate=False) as connection:
        if after:
            rows = connection.execute(
                "SELECT position, at, kind, tool, text, cost_usd FROM steps"
                " WHERE run = ? AND position > ? ORDER BY position LIMIT ?",
                (identifier, after, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT position, at, kind, tool, text, cost_usd FROM steps"
                " WHERE run = ? AND (? = 0 OR position < ?) ORDER BY position DESC LIMIT ?",
                (identifier, before, before, limit),
            ).fetchall()[::-1]
        count = connection.execute(
            "SELECT count(*) FROM steps WHERE run = ?", (identifier,)
        ).fetchone()[0]
        first = connection.execute(
            "SELECT min(position) FROM steps WHERE run = ?", (identifier,)
        ).fetchone()[0]
    found = [
        {
            "position": position,
            "at": at,
            "kind": kind,
            # What the console has always drawn a step from — see `progress.Step`.
            "label": text if kind == "said" else "Error" if kind == "error" else tool,
            "detail": "" if kind == "said" else text,
            "said": kind == "said",
            **({"cost_usd": cost} if cost is not None else {}),
        }
        for position, at, kind, tool, text, cost in rows
    ]
    return {
        "run": identifier,
        "count": count,
        "steps": found,
        "more": bool(found) and first is not None and found[0]["position"] > first,
    }
