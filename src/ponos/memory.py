"""What Ponos remembers from one session to the next: short facts, in `ponos.db`.

Every session starts from nothing but the standing context, so a preference
given in answer to a ticket, a decision, a constraint of a project is lost — or
has to be said again. A *memory* is one such fact: a sentence, a kind (a person,
a preference or an instruction, a project, a reference), a scope (everywhere, or
one project), where it came from (a ticket, a console conversation, a hand) and
the dates.

**Proposed is not accepted.** The same rule as `notes.py`, for the same reason:
a prompt that grew by itself would be the quiet way for one wrong guess to steer
every later session. A session, an MCP client or the assistant only *proposes*;
a person accepts it in Context → Memory, and only an accepted memory reaches a
prompt. `auto_accept` is the switch that lifts the rule, for somebody who would
rather read afterwards than before. A refused proposal stays as a row with its
status, so the same fact learned again next week does not ask again.

**Bounded, so that the prompt stays short.** One fact is `FACT_LIMIT`
characters; the prompt carries `PROMPT_LIMIT` characters of them at most —
the project's own first, then the global ones, the most recently touched first
in each — and says how many it left out rather than cutting one in half.

**One memory, not two.** The console's assistant keeps files of its own
(`~/.claude/projects/<workspace>/memory/`, one per fact, `MEMORY.md` as the
index). `import_files` reads them into this table, once each: a file already
imported is recognised by its name and by its fact. After it, this table is the
memory — it is what the sessions, the assistant's opening frame and the MCP read.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db

KINDS = ("person", "preference", "project", "reference")
SOURCES = ("ticket", "chat", "manual")
ACCEPTED, PROPOSED, REFUSED = "accepted", "proposed", "refused"
STATUSES = (ACCEPTED, PROPOSED, REFUSED)

FACT_LIMIT = 300
PROMPT_LIMIT = 3000
# A proposal queue that nobody reads must not grow for ever.
PROPOSED_LIMIT = 50
# A session proposes a few facts, not a transcript.
PER_SESSION = 3

AUTO_ACCEPT = "auto_accept"

# What the assistant's files call their kinds.
_FILE_KINDS = {
    "user": "person",
    "feedback": "preference",
    "project": "project",
    "reference": "reference",
}


def clean(text: str) -> str:
    """A fact on one line, in single spaces, cut at the limit."""
    return " ".join(str(text or "").split())[:FACT_LIMIT].rstrip()


def fingerprint(text: str) -> str:
    """What makes two facts the same one: the words, not the case or the punctuation."""
    words = re.sub(r"[\W_]+", " ", text.casefold()).split()
    return hashlib.sha1(" ".join(words).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _scope(project: str) -> str:
    return project.replace("-", "").strip().lower()


def _check(kind: str, source: str = "manual") -> None:
    if kind not in KINDS:
        raise ValueError(f"a memory is one of: {', '.join(KINDS)}")
    if source not in SOURCES:
        raise ValueError(f"a memory comes from: {', '.join(SOURCES)}")


def _rows(cursor: Any) -> list[dict[str, Any]]:
    """The rows of a query as dicts: the connection hands out tuples."""
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _shown(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "text": row["text"],
        "kind": row["kind"],
        "scope": row["scope"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "status": row["status"],
        "created": row["created"],
        "updated": row["updated"],
    }


def options() -> dict[str, bool]:
    try:
        with db.transaction(immediate=False) as connection:
            rows = _rows(connection.execute("SELECT name, value FROM memory_options"))
    except db.ERRORS:
        return {AUTO_ACCEPT: False}
    held = {row["name"]: row["value"] for row in rows}
    return {AUTO_ACCEPT: held.get(AUTO_ACCEPT) == "1"}


def set_option(name: str, value: bool) -> None:
    if name != AUTO_ACCEPT:
        raise ValueError("this memory setting does not exist")
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO memory_options (name, value) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
            (name, "1" if value else "0"),
        )


def listing(
    *,
    scope: str | None = None,
    kind: str = "",
    status: str = "",
    search: str = "",
) -> list[dict[str, Any]]:
    """The memories, newest touched first. `scope` None is every scope, "" the global ones."""
    clauses, values = ["1 = 1"], []
    if scope is not None:
        clauses.append("scope = ?")
        values.append(_scope(scope))
    if kind:
        clauses.append("kind = ?")
        values.append(kind)
    if status:
        clauses.append("status = ?")
        values.append(status)
    if search.strip():
        clauses.append("text LIKE ? ESCAPE '\\'")
        needle = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.append(f"%{needle}%")
    try:
        with db.transaction(immediate=False) as connection:
            rows = _rows(
                connection.execute(
                    f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
                    "ORDER BY updated DESC, id DESC",
                    values,
                )
            )
    except db.ERRORS:
        return []
    return [_shown(row) for row in rows]


def get(identifier: int) -> dict[str, Any]:
    with db.transaction(immediate=False) as connection:
        rows = _rows(connection.execute("SELECT * FROM memories WHERE id = ?", (identifier,)))
    if not rows:
        raise ValueError("this memory does not exist any more")
    return _shown(rows[0])


def _insert(
    text: str, kind: str, scope: str, source: str, source_ref: str, status: str
) -> dict[str, Any] | None:
    """The new row, or None when the same fact is already there (whatever its status)."""
    text = clean(text)
    if not text:
        raise ValueError("a memory cannot be empty")
    _check(kind, source)
    scope = _scope(scope)
    now = _now()
    with db.transaction() as connection:
        if connection.execute(
            "SELECT 1 FROM memories WHERE scope = ? AND mark = ?", (scope, fingerprint(text))
        ).fetchone():
            return None
        made = connection.execute(
            "INSERT INTO memories (text, kind, scope, source, source_ref, status, mark, created, "
            "updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (text, kind, scope, source, source_ref, status, fingerprint(text), now, now),
        )
        identifier = int(made.lastrowid or 0)
        if status == PROPOSED:
            # The oldest waiting proposals make room, as the project's notes do.
            connection.execute(
                "DELETE FROM memories WHERE status = ? AND id NOT IN "
                "(SELECT id FROM memories WHERE status = ? ORDER BY id DESC LIMIT ?)",
                (PROPOSED, PROPOSED, PROPOSED_LIMIT),
            )
    return get(identifier)


def add(
    text: str, kind: str = "preference", scope: str = "", source: str = "manual", ref: str = ""
) -> dict[str, Any]:
    """A memory written by a person: accepted at once. Refused when the fact is already known."""
    made = _insert(text, kind, scope, source, ref, ACCEPTED)
    if made is None:
        raise ValueError("this memory is already known")
    return made


def propose(
    text: str, kind: str = "preference", scope: str = "", source: str = "manual", ref: str = ""
) -> dict[str, Any] | None:
    """Put a fact to the person. None when it is empty, known, or was refused before.

    Accepted at once when the `auto_accept` setting says so.
    """
    try:
        status = ACCEPTED if options()[AUTO_ACCEPT] else PROPOSED
        return _insert(text, kind, scope, source, ref, status)
    except (ValueError, *db.ERRORS):
        return None


def _change(identifier: int, **fields: Any) -> dict[str, Any]:
    names = list(fields)
    with db.transaction() as connection:
        found = _rows(connection.execute("SELECT * FROM memories WHERE id = ?", (identifier,)))
        if not found:
            raise ValueError("this memory does not exist any more")
        values = {**found[0], **fields}
        if "text" in fields:
            mark = fingerprint(values["text"])
            if connection.execute(
                "SELECT 1 FROM memories WHERE scope = ? AND mark = ? AND id <> ?",
                (values["scope"], mark, identifier),
            ).fetchone():
                raise ValueError("this memory is already known")
            values["mark"] = mark
            names.append("mark")
        names.append("updated")
        values["updated"] = _now()
        connection.execute(
            f"UPDATE memories SET {', '.join(f'{name} = ?' for name in names)} WHERE id = ?",
            [*(values[name] for name in names), identifier],
        )
    return get(identifier)


def edit(
    identifier: int,
    *,
    text: str | None = None,
    kind: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Rewrite a memory, whatever its status."""
    fields: dict[str, Any] = {}
    if text is not None:
        fields["text"] = clean(text)
        if not fields["text"]:
            raise ValueError("a memory cannot be empty")
    if kind is not None:
        _check(kind)
        fields["kind"] = kind
    if scope is not None:
        fields["scope"] = _scope(scope)
    return _change(identifier, **fields)


def accept(identifier: int) -> dict[str, Any]:
    return _change(identifier, status=ACCEPTED)


def refuse(identifier: int) -> dict[str, Any]:
    """Throw a proposal away for good: the row stays, so it is not proposed again."""
    return _change(identifier, status=REFUSED)


def delete(identifier: int) -> None:
    """Delete a memory. Learned again, it is proposed again: only a refusal is remembered."""
    with db.transaction() as connection:
        gone = connection.execute("DELETE FROM memories WHERE id = ?", (identifier,))
    if not gone.rowcount:
        raise ValueError("this memory does not exist any more")


def for_prompt(project: str = "") -> list[str]:
    """The accepted memories a session of `project` is told, one line each, within the limit.

    The project's own, then the global ones; others' never.
    """
    scope = _scope(project)
    try:
        with db.transaction(immediate=False) as connection:
            rows = _rows(
                connection.execute(
                    "SELECT text, kind, scope FROM memories WHERE status = ? "
                    "AND scope IN (?, '') ORDER BY (scope = '') ASC, updated DESC, id DESC",
                    (ACCEPTED, scope),
                )
            )
    except db.ERRORS:
        return []
    lines: list[str] = []
    used = 0
    for row in rows:
        line = f"[{row['kind']}] {row['text']}"
        if used + len(line) > PROMPT_LIMIT:
            break
        lines.append(line)
        used += len(line)
    if len(lines) < len(rows):
        lines.append(f"({len(rows) - len(lines)} more kept memories were left out to stay short)")
    return lines


def parse(text: str) -> tuple[str, str, str] | None:
    """A `MEMORY:` line of a session's report: (kind, scope word, fact), or None.

    `<kind> | <project|global> | <fact>`; the scope may be left out, and is then
    the ticket's project. A kind it does not know is a preference.
    """
    parts = [part.strip() for part in text.split("|", 2)]
    if len(parts) == 2:
        parts.insert(1, "project")
    if len(parts) != 3 or not parts[2]:
        return None
    kind = parts[0].casefold()
    scope = "global" if parts[1].casefold() == "global" else "project"
    return (kind if kind in KINDS else "preference", scope, parts[2])


# -- the assistant's files ---------------------------------------------------------


def files_folder(workspace_root: str | Path) -> Path:
    """Where Claude Code keeps the memory of a session opened in the workspace."""
    mangled = re.sub(r"[^A-Za-z0-9]", "-", str(Path(workspace_root).expanduser()))
    return Path.home() / ".claude" / "projects" / mangled / "memory"


def _read_file(path: Path) -> tuple[str, str] | None:
    """(kind, fact) of one memory file: the frontmatter's description and type."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    description = kind = ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        stripped = line.strip()
        if stripped.startswith("description:"):
            description = stripped.removeprefix("description:").strip().strip("\"'")
        elif stripped.startswith("type:"):
            kind = stripped.removeprefix("type:").strip()
    if not description:
        return None
    return _FILE_KINDS.get(kind, "preference"), description


def importable(folder: Path) -> list[Path]:
    """The memory files not imported yet."""
    if not folder.is_dir():
        return []
    try:
        with db.transaction(immediate=False) as connection:
            known = {
                row["name"]
                for row in _rows(
                    connection.execute("SELECT name FROM memory_options WHERE name LIKE 'file:%'")
                )
            }
    except db.ERRORS:
        return []
    return [
        path
        for path in sorted(folder.glob("*.md"))
        if path.name != "MEMORY.md" and f"file:{path.name}" not in known
    ]


def import_files(folder: Path) -> int:
    """Read the assistant's memory files into the table, once each; returns how many were new.

    A file is marked as read even when its fact was already known, so that the
    count of what is left to import reaches zero.
    """
    taken = 0
    for path in importable(folder):
        read = _read_file(path)
        if read is None:
            continue
        kind, fact = read
        try:
            made = _insert(fact, kind, "", "chat", f"file:{path.name}", ACCEPTED)
        except ValueError:
            continue
        taken += made is not None
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO memory_options (name, value) VALUES (?, '1')",
                (f"file:{path.name}",),
            )
    return taken
