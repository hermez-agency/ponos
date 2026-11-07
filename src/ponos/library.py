"""The files Ponos keeps for the sessions: a charter, a contract, a brief, screenshots.

A console attachment belongs to one conversation and leaves with it after
`web.attachment_days`; a reference file is the opposite — dropped once, kept
until somebody deletes it, and handed to every session it concerns. The bytes
live in a folder of the state directory (`library/`, `0700`, never in a
repository: a client's contract has no business in somebody's commit), the
metadata in `ponos.db`: a name, a description, tags, and a *scope* — every
project, or the few that are listed.

**Told, not copied.** A session is given the list — absolute path, name,
description — and reads a file with the tool it reads source with; nothing is
copied into its worktree. The list holds only what the session's project is in
scope for, so a file dropped for project X is nowhere in another project's
prompt. It is bounded (`PROMPT_LIMIT` characters), and says how many it left
out rather than cutting a line in half.

**The same kinds as the console's attachments** (`web/attachments.ACCEPTED`),
for the same reason: the folder is served back to the page from the console's
own origin, and a kind it never meant to hold — an HTML page, an SVG — would
be served from there. Where the file goes is the one difference: it is stored
under its row's id, never under the name it came with, so a rename is a row
edit and a name cannot walk out of the folder.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db, disk
from .config import state_dir
from .project_settings import key as project_key
from .web import attachments

PROMPT_LIMIT = 3000
TAG_LIMIT = 12
TAG_LENGTH = 30
DESCRIPTION_LIMIT = 500
DEFAULT_MAX_MB = 50

# The most the listing in a prompt names, whatever its length.
PROMPT_FILES = 40


def folder() -> Path:
    return disk.private_dir(state_dir() / "library")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def tags_of(raw: Any) -> list[str]:
    """Tags as kept: lower case, trimmed, no duplicate, at most `TAG_LIMIT`."""
    if isinstance(raw, str):
        raw = raw.split(",")
    kept: list[str] = []
    for item in raw if isinstance(raw, list | tuple) else []:
        tag = " ".join(str(item).split()).lower()[:TAG_LENGTH]
        if tag and tag not in kept:
            kept.append(tag)
    return kept[:TAG_LIMIT]


def projects_of(raw: Any) -> list[str]:
    """The projects a file is for, as the table keys them; empty is every project."""
    if isinstance(raw, str):
        raw = [raw] if raw and raw != "global" else []
    kept: list[str] = []
    for item in raw if isinstance(raw, list | tuple) else []:
        project = project_key(str(item))
        if project and project != "global" and project not in kept:
            kept.append(project)
    return kept


def _shown(row: Any) -> dict[str, Any]:
    name = row["name"]
    suffix = attachments.extension(name)
    kind, media = attachments.ACCEPTED.get(suffix, ("document", "application/octet-stream"))
    return {
        "id": int(row["id"]),
        "name": name,
        "description": row["description"],
        "tags": json.loads(row["tags"] or "[]"),
        "projects": json.loads(row["projects"] or "[]"),
        "kind": kind,
        "type": media.split(";", 1)[0],
        "size": int(row["size"]),
        "created": row["created"],
        "updated": row["updated"],
        "stored": row["stored"],
    }


def _rows(cursor: Any) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def path_of(item: dict[str, Any]) -> Path:
    return folder() / str(item["stored"])


def listing(*, project: str = "", tag: str = "", search: str = "") -> list[dict[str, Any]]:
    """The files, the latest touched first.

    `project` keeps the files a session of that project is told: the ones for
    every project and the ones that name it. `tag` and `search` (name,
    description, tags) narrow the rest.
    """
    try:
        with db.transaction(immediate=False) as connection:
            rows = _rows(
                connection.execute("SELECT * FROM library_files ORDER BY updated DESC, id DESC")
            )
    except db.ERRORS:
        return []
    found = [_shown(row) for row in rows]
    if project:
        wanted = project_key(project)
        found = [item for item in found if not item["projects"] or wanted in item["projects"]]
    if tag:
        found = [item for item in found if tag.strip().lower() in item["tags"]]
    needle = search.strip().lower()
    if needle:
        found = [
            item
            for item in found
            if needle in f"{item['name']} {item['description']} {' '.join(item['tags'])}".lower()
        ]
    return found


def get(identifier: int) -> dict[str, Any]:
    with db.transaction(immediate=False) as connection:
        rows = _rows(connection.execute("SELECT * FROM library_files WHERE id = ?", (identifier,)))
    if not rows:
        raise LookupError("this file is not in the library any more")
    return _shown(rows[0])


def used() -> tuple[int, int]:
    """(how many files, how many bytes) the library holds."""
    try:
        with db.transaction(immediate=False) as connection:
            count, size = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM library_files"
            ).fetchone()
    except db.ERRORS:
        return 0, 0
    return int(count), int(size)


def tags() -> list[str]:
    """Every tag in use, sorted."""
    return sorted({tag for item in listing() for tag in item["tags"]})


def save(
    name: str,
    source: attachments.Source,
    length: int,
    limit: int,
    *,
    description: str = "",
    tag_list: Any = (),
    project_list: Any = (),
) -> dict[str, Any]:
    """Keep `length` bytes from `source` as a library file, or refuse them.

    Checked against what the request announces and against what arrives, as an
    attachment is: a length that lied is caught at the first byte past it, and
    what was written is removed.
    """
    if not attachments.accepted(name):
        offered = ", ".join(sorted(attachments.ACCEPTED))
        raise ValueError(f"“{name}” is not a kind of file the library takes — only {offered}")
    if length > limit:
        raise attachments.TooLarge(
            f"“{name}” is {megabytes(length)}, past the {megabytes(limit)} a library file may "
            "be (web.library_max_mb)"
        )
    if length <= 0:
        raise ValueError(f"“{name}” is empty")
    kept = attachments.safe_name(name)
    if not attachments.accepted(kept):
        kept = f"{attachments.UNNAMED}.{attachments.extension(name)}"
    stored = f"{secrets.token_hex(6)}-{kept}"
    target = folder() / stored
    written = 0
    try:
        with open(target, "wb", opener=disk.opener()) as out:
            while written < length:
                chunk = source.read(min(1 << 16, length - written))
                if not chunk:
                    break
                written += len(chunk)
                out.write(chunk)
    except OSError:
        target.unlink(missing_ok=True)
        raise
    if written < length:
        target.unlink(missing_ok=True)
        raise ValueError(f"“{name}” arrived cut short ({written} of {length} bytes)")
    now = _now()
    try:
        with db.transaction() as connection:
            made = connection.execute(
                "INSERT INTO library_files (name, description, tags, projects, stored, size, "
                "created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kept,
                    " ".join(description.split())[:DESCRIPTION_LIMIT],
                    json.dumps(tags_of(tag_list)),
                    json.dumps(projects_of(project_list)),
                    stored,
                    written,
                    now,
                    now,
                ),
            )
            identifier = int(made.lastrowid or 0)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return get(identifier)


def keep_file(
    path: Path, name: str, limit: int, *, description: str = "", project_list: Any = ()
) -> dict[str, Any]:
    """Copy a file that is already on this machine — a conversation's attachment — into the library."""
    with open(path, "rb") as source:
        return save(
            name,
            source,
            path.stat().st_size,
            limit,
            description=description,
            project_list=project_list,
        )


def edit(
    identifier: int,
    *,
    name: str | None = None,
    description: str | None = None,
    tag_list: Any = None,
    project_list: Any = None,
) -> dict[str, Any]:
    """Rename, describe, tag or move a file between scopes. The bytes never move."""
    current = get(identifier)
    fields: dict[str, Any] = {}
    if name is not None:
        renamed = attachments.safe_name(name)
        if not renamed or attachments.extension(renamed) != attachments.extension(current["name"]):
            # A rename keeps the kind: the type a file is served under follows its extension.
            raise ValueError(
                f"a file keeps its extension (.{attachments.extension(current['name'])}) when renamed"
            )
        fields["name"] = renamed
    if description is not None:
        fields["description"] = " ".join(description.split())[:DESCRIPTION_LIMIT]
    if tag_list is not None:
        fields["tags"] = json.dumps(tags_of(tag_list))
    if project_list is not None:
        fields["projects"] = json.dumps(projects_of(project_list))
    if fields:
        fields["updated"] = _now()
        with db.transaction() as connection:
            connection.execute(
                f"UPDATE library_files SET {', '.join(f'{field} = ?' for field in fields)} "
                "WHERE id = ?",
                [*fields.values(), identifier],
            )
    return get(identifier)


def delete(identifier: int) -> None:
    current = get(identifier)
    with db.transaction() as connection:
        connection.execute("DELETE FROM library_files WHERE id = ?", (identifier,))
    path_of(current).unlink(missing_ok=True)


def for_prompt(project: str = "") -> list[str]:
    """What a session of `project` is told of the library: one line per file, within the limit.

    Files for every project and files for this one; a project's own never reach
    another. A session without a project is told the files of every project
    only.
    """
    lines: list[str] = []
    used_up = 0
    if project:
        shown = listing(project=project)
    else:
        shown = [item for item in listing() if not item["projects"]]
    for item in shown[:PROMPT_FILES]:
        about = f" — {item['description']}" if item["description"] else ""
        line = f"{path_of(item)} — {item['name']}{about}"
        if used_up + len(line) > PROMPT_LIMIT:
            break
        lines.append(line)
        used_up += len(line)
    if len(lines) < len(shown):
        lines.append(f"({len(shown) - len(lines)} more files were left out to stay short)")
    return lines


def megabytes(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".0 MB", " MB")
