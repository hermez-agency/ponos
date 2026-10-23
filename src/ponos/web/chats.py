"""The conversations of the console, kept in `ponos.db` and not in a file.

The chat used to be one conversation in `chat.json`: a new one buried the old,
and the old stayed resumable only by an identifier nobody wrote down. A person
who talks to the workspace every day wants what Claude or ChatGPT give — the
list of what was said, and the way back into any of it — so each conversation is
a row, whole: its title, the model it runs on, the project it is about, the
Claude Code session behind it and the transcript the page draws.

**The transcript is one JSON column.** It is only ever read to be drawn or
searched, never queried by message, and a row per message would turn opening a
conversation into a join for nothing. Searching the content is a `LIKE` over
that column: slow on a very long history, and a long history is a few hundred
short conversations here.

**What `ponos.db` cannot read is not a reason to fail.** Every function answers
"nothing" on a database error, as the other notes the runner keeps for itself
do: a console whose conversations cannot be listed still talks.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .. import db

# A title made of the first message is a label, not a quotation.
TITLE_LENGTH = 60


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def titled(text: str) -> str:
    """A title for a conversation, from what was first said in it."""
    line = next((part for part in text.strip().splitlines() if part.strip()), "")
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) <= TITLE_LENGTH:
        return line
    return line[: TITLE_LENGTH - 1].rstrip() + "…"


def _summary(row: tuple[Any, ...]) -> dict[str, Any]:
    identifier, title, model, project, turns, updated, created = row
    return {
        "id": identifier,
        "title": title,
        "model": model,
        "project": project,
        "turns": turns,
        "updated": updated or created,
    }


def save(chat: dict[str, Any]) -> None:
    """Write one conversation, whole — created by the first time it is saved."""
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO chats (id, title, model, project, claude, turns, folder, created, updated, messages) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET title = excluded.title, model = excluded.model, "
                "project = excluded.project, claude = excluded.claude, turns = excluded.turns, "
                "folder = excluded.folder, updated = excluded.updated, messages = excluded.messages",
                (
                    chat["id"],
                    chat.get("title", ""),
                    chat.get("model", ""),
                    chat.get("project", ""),
                    chat.get("claude", ""),
                    int(chat.get("turns", 0)),
                    chat.get("folder", ""),
                    chat.get("created") or now(),
                    chat.get("updated") or now(),
                    json.dumps(chat.get("messages", []), ensure_ascii=False),
                ),
            )
    except db.ERRORS:
        pass


def load(identifier: str) -> dict[str, Any] | None:
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT id, title, model, project, claude, turns, folder, created, updated, messages "
                "FROM chats WHERE id = ?",
                (identifier,),
            ).fetchone()
    except db.ERRORS:
        return None
    return _chat(row) if row else None


def latest() -> dict[str, Any] | None:
    """The conversation spoken in last, which is the one the console reopens on."""
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT id, title, model, project, claude, turns, folder, created, updated, messages "
                "FROM chats ORDER BY updated DESC, rowid DESC LIMIT 1"
            ).fetchone()
    except db.ERRORS:
        return None
    return _chat(row) if row else None


def _chat(row: tuple[Any, ...]) -> dict[str, Any]:
    identifier, title, model, project, claude, turns, folder, created, updated, messages = row
    try:
        said = json.loads(messages or "[]")
    except ValueError:
        said = []
    return {
        "id": identifier,
        "title": title,
        "model": model,
        "project": project,
        "claude": claude,
        "turns": turns,
        "folder": folder,
        "created": created,
        "updated": updated,
        "messages": said if isinstance(said, list) else [],
    }


def listing(query: str = "") -> list[dict[str, Any]]:
    """Every conversation, the latest first; those that mention `query` when there is one.

    `matched` says where the words were found — the title, or deeper in the
    transcript — because a title that does not contain them and a list that
    still shows the row would otherwise look like a mistake.
    """
    query = query.strip()
    try:
        with db.transaction(immediate=False) as connection:
            if query:
                like = (
                    "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                )
                rows = connection.execute(
                    "SELECT id, title, model, project, turns, updated, created, "
                    "title LIKE ? ESCAPE '\\' FROM chats "
                    "WHERE title LIKE ? ESCAPE '\\' OR project LIKE ? ESCAPE '\\' OR messages LIKE ? ESCAPE '\\' "
                    "ORDER BY updated DESC, rowid DESC",
                    (like, like, like, like),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, title, model, project, turns, updated, created, 1 FROM chats "
                    "ORDER BY updated DESC, rowid DESC"
                ).fetchall()
    except db.ERRORS:
        return []
    found = []
    for *row, in_title in rows:
        said = _summary(tuple(row))
        if query:
            said["matched"] = "title" if in_title else "content"
        found.append(said)
    return found


def remove(identifier: str) -> bool:
    try:
        with db.transaction() as connection:
            return connection.execute("DELETE FROM chats WHERE id = ?", (identifier,)).rowcount > 0
    except db.ERRORS:
        return False


def recent_models(limit: int = 8) -> list[str]:
    """The models conversations were last run on, the latest first, each once."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT model FROM chats WHERE model <> '' GROUP BY model "
                "ORDER BY MAX(updated) DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except db.ERRORS:
        return []
    return [row[0] for row in rows]


def empty() -> bool:
    try:
        with db.transaction(immediate=False) as connection:
            return connection.execute("SELECT 1 FROM chats LIMIT 1").fetchone() is None
    except db.ERRORS:
        return True
