"""Les skills Claude Code que Ponos donne à ses sessions : gardées dans `ponos.db`.

Une session Ponos est une session Claude Code, qui charge les skills de
`.claude/skills/<nom>/SKILL.md` de son dossier de travail. Une *skill de Ponos*
est un tel dossier (le SKILL.md et les fichiers à côté) que la console écrit,
et que le runner pose dans le worktree d'un ticket selon sa portée : toutes les
sessions, ou certains projets seulement.

**Dans `ponos.db`, pas dans un dossier de l'état.** Une skill est un petit
nombre de petits fichiers, écrits par la console et lus par le runner : une
table de fichiers (`skill_files`) les garde dans la même transaction que la
ligne qui les décrit, suit la sauvegarde de la base sans règle de plus, et
n'a pas de nom de dossier à valider contre un `..` sur le disque. Le
SKILL.md est un fichier comme les autres ; `name` et `description` de la ligne
n'en sont que la copie pour la liste.

**Le dépôt gagne.** Une skill que le dépôt fournit déjà (`.claude/skills/<nom>`
dans le worktree) n'est jamais écrasée : celle de Ponos n'est pas posée, et la
console le signale. Ce que Ponos a posé porte un fichier repère
(`MARKER`) : un worktree repris relit donc ses skills sans les confondre avec
celles du dépôt, et une skill désactivée depuis disparaît de la suite.

**Hors de git.** Chaque dossier posé porte un `.gitignore` qui vaut `*` : il
s'ignore lui-même, avec tout ce qu'il contient. `git add -A`, que Ponos et les
sessions font, ne le met donc pas dans le commit du ticket — sans toucher à la
configuration du dépôt principal ni à son `info/exclude`, que tous les worktrees
partagent.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import db

MAIN = "SKILL.md"
# Dans un dossier posé par Ponos, et nulle part ailleurs : voir `install`.
MARKER = ".ponos-skill"
SKILLS_DIR = Path(".claude") / "skills"

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FILE_LIMIT = 1_000_000
SKILL_LIMIT = 5_000_000
FILES_LIMIT = 100


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rows(cursor: Any) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def scope_key(project: str) -> str:
    """Un projet comme la table le range : sans tirets, en minuscules."""
    return project.replace("-", "").strip().lower()


# -- le SKILL.md ---------------------------------------------------------------


def split(markdown: str) -> tuple[list[str], str]:
    """Les lignes du frontmatter, et le corps. Pas de frontmatter : une liste vide."""
    text = markdown.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return [], text
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            return lines[1:index], "\n".join(lines[index + 1 :]).lstrip("\n")
    return [], text


def _fields(lines: list[str]) -> dict[str, str]:
    """Les clés de premier niveau du frontmatter : `clé: valeur`, avec ses suites indentées."""
    found: dict[str, str] = {}
    key = ""
    parts: list[str] = []

    def close() -> None:
        if key:
            joined = " ".join(part for part in parts if part).strip()
            found[key] = _unquote(joined)

    for line in lines:
        match = re.match(r"^([A-Za-z][\w-]*)\s*:\s*(.*)$", line)
        if match and not line.startswith((" ", "\t")):
            close()
            key = match.group(1)
            value = match.group(2).strip()
            parts = [] if value in (">", "|", ">-", "|-", ">+", "|+") else [value]
        elif key:
            parts.append(line.strip())
    close()
    return found


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            loaded = json.loads(value)
        except ValueError:
            return value[1:-1]
        return str(loaded)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def parse(markdown: str) -> tuple[str, str, str]:
    """(name, description, body) d'un SKILL.md."""
    head, body = split(markdown)
    found = _fields(head)
    return found.get("name", ""), found.get("description", ""), body


def compose(markdown: str, name: str, description: str, body: str) -> str:
    """Le SKILL.md avec ce nom, cette description et ce corps — le reste du frontmatter gardé."""
    head, _ = split(markdown)
    kept: list[str] = []
    skipping = False
    for line in head:
        starts = re.match(r"^([A-Za-z][\w-]*)\s*:", line) and not line.startswith((" ", "\t"))
        if starts:
            skipping = line.split(":", 1)[0].strip() in ("name", "description")
        if not skipping:
            kept.append(line)
    written = [
        f"name: {name}",
        f"description: {json.dumps(' '.join(description.split()), ensure_ascii=False)}",
        *kept,
    ]
    return "---\n" + "\n".join(written) + "\n---\n\n" + body.strip("\n") + "\n"


# -- les fichiers ----------------------------------------------------------------


def clean_path(path: str) -> str:
    """Un chemin relatif au dossier de la skill, sûr à écrire : ni `..`, ni absolu, ni caché."""
    pure = PurePosixPath(path.replace("\\", "/"))
    parts = [part for part in pure.parts if part not in ("", ".")]
    if pure.is_absolute() or not parts or ".." in parts or ".git" in parts:
        raise ValueError(f"« {path} » n'est pas un chemin de la skill")
    if parts[-1] == MARKER:
        raise ValueError(f"« {MARKER} » est réservé à Ponos")
    return "/".join(parts)


def _check_name(name: str) -> str:
    name = name.strip()
    if not NAME.match(name):
        raise ValueError(
            "le nom d'une skill est en minuscules, chiffres et tirets (64 caractères au plus)"
        )
    return name


def _scope_list(scope: Any) -> list[str]:
    if scope in (None, "", "global"):
        return []
    if isinstance(scope, str):
        scope = [scope]
    if not isinstance(scope, list):
        raise ValueError("la portée d'une skill est « toutes les sessions » ou des projets")
    return sorted({scope_key(str(item)) for item in scope if str(item).strip()})


def _shown(row: dict[str, Any], files: int = 0) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "scope": json.loads(row["scope"] or "[]"),
        "files": files,
        "created": row["created"],
        "updated": row["updated"],
    }


def listing() -> list[dict[str, Any]]:
    """Les skills de Ponos, par nom."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = _rows(connection.execute("SELECT * FROM skills ORDER BY name"))
            counts = dict(
                connection.execute(
                    "SELECT skill, COUNT(*) FROM skill_files WHERE path != ? GROUP BY skill",
                    (MAIN,),
                ).fetchall()
            )
    except db.ERRORS:
        return []
    return [_shown(row, int(counts.get(row["id"], 0))) for row in rows]


def get(identifier: int) -> dict[str, Any]:
    """Une skill : sa ligne, son SKILL.md, et ses fichiers (le contenu texte seulement)."""
    with db.transaction(immediate=False) as connection:
        rows = _rows(connection.execute("SELECT * FROM skills WHERE id = ?", (identifier,)))
        if not rows:
            raise LookupError("cette skill n'existe plus")
        files = _rows(
            connection.execute(
                "SELECT path, content FROM skill_files WHERE skill = ? ORDER BY path",
                (identifier,),
            )
        )
    markdown = ""
    attached = []
    for item in files:
        raw = bytes(item["content"])
        if item["path"] == MAIN:
            markdown = raw.decode("utf-8", errors="replace")
        else:
            attached.append({"path": item["path"], "size": len(raw)})
    _, _, body = parse(markdown)
    return {
        **_shown(rows[0], len(attached)),
        "markdown": markdown,
        "body": body,
        "attached": attached,
    }


def read_file(identifier: int, path: str) -> bytes:
    with db.transaction(immediate=False) as connection:
        found = connection.execute(
            "SELECT content FROM skill_files WHERE skill = ? AND path = ?",
            (identifier, clean_path(path)),
        ).fetchone()
    if found is None:
        raise LookupError("ce fichier n'existe plus")
    return bytes(found[0])


def _write(
    connection: Any, identifier: int, files: dict[str, bytes], *, replace: bool = False
) -> None:
    if replace:
        connection.execute("DELETE FROM skill_files WHERE skill = ?", (identifier,))
    for path, content in files.items():
        connection.execute(
            "INSERT INTO skill_files (skill, path, content) VALUES (?, ?, ?) "
            "ON CONFLICT (skill, path) DO UPDATE SET content = excluded.content",
            (identifier, path, content),
        )
    total = connection.execute(
        "SELECT COALESCE(SUM(LENGTH(content)), 0), COUNT(*) FROM skill_files WHERE skill = ?",
        (identifier,),
    ).fetchone()
    if int(total[0]) > SKILL_LIMIT or int(total[1]) > FILES_LIMIT:
        raise ValueError(
            f"une skill tient dans {FILES_LIMIT} fichiers et {SKILL_LIMIT // 1_000_000} Mo au plus"
        )


def _files_checked(files: dict[str, bytes]) -> dict[str, bytes]:
    checked: dict[str, bytes] = {}
    for path, content in files.items():
        if len(content) > FILE_LIMIT:
            raise ValueError(f"« {path} » dépasse {FILE_LIMIT // 1_000_000} Mo")
        checked[clean_path(path)] = content
    return checked


def create(
    name: str,
    description: str,
    body: str,
    scope: Any = None,
    *,
    enabled: bool = True,
    files: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Une skill neuve. Un SKILL.md donné dans `files` fournit le frontmatter qu'on ne dit pas."""
    name = _check_name(name)
    description = " ".join(description.split())
    if not description:
        raise ValueError("une skill dit à quoi elle sert : sa description ne peut pas être vide")
    attached = _files_checked(files or {})
    given = attached.pop(MAIN, b"").decode("utf-8", errors="replace")
    markdown = compose(given, name, description, body)
    now = _now()
    with db.transaction() as connection:
        if connection.execute("SELECT 1 FROM skills WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"une skill s'appelle déjà « {name} »")
        made = connection.execute(
            "INSERT INTO skills (name, description, enabled, scope, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, 1 if enabled else 0, json.dumps(_scope_list(scope)), now, now),
        )
        identifier = int(made.lastrowid or 0)
        _write(connection, identifier, {MAIN: markdown.encode(), **attached})
    return get(identifier)


def update(
    identifier: int,
    *,
    name: str | None = None,
    description: str | None = None,
    body: str | None = None,
    scope: Any = None,
    enabled: bool | None = None,
    scope_given: bool = False,
) -> dict[str, Any]:
    """Change ce qui est donné. `scope_given` : la portée est dite, même vide (= toutes)."""
    current = get(identifier)
    new_name = _check_name(name) if name is not None else current["name"]
    new_description = (
        " ".join(description.split()) if description is not None else current["description"]
    )
    if not new_description:
        raise ValueError("une skill dit à quoi elle sert : sa description ne peut pas être vide")
    new_body = body if body is not None else current["body"]
    markdown = compose(current["markdown"], new_name, new_description, new_body)
    with db.transaction() as connection:
        clash = connection.execute(
            "SELECT 1 FROM skills WHERE name = ? AND id != ?", (new_name, identifier)
        ).fetchone()
        if clash:
            raise ValueError(f"une skill s'appelle déjà « {new_name} »")
        connection.execute(
            "UPDATE skills SET name = ?, description = ?, enabled = ?, scope = ?, updated = ? "
            "WHERE id = ?",
            (
                new_name,
                new_description,
                int(current["enabled"] if enabled is None else enabled),
                json.dumps(_scope_list(scope) if scope_given else current["scope"]),
                _now(),
                identifier,
            ),
        )
        _write(connection, identifier, {MAIN: markdown.encode()})
    return get(identifier)


def delete(identifier: int) -> None:
    with db.transaction() as connection:
        connection.execute("DELETE FROM skill_files WHERE skill = ?", (identifier,))
        connection.execute("DELETE FROM skills WHERE id = ?", (identifier,))


def put_file(identifier: int, path: str, content: bytes) -> dict[str, Any]:
    """Un fichier joint, créé ou remplacé. Le SKILL.md se change par `update`."""
    get(identifier)
    clean = clean_path(path)
    if clean == MAIN:
        raise ValueError("le SKILL.md se modifie dans l'éditeur, pas comme un fichier joint")
    files = _files_checked({clean: content})
    with db.transaction() as connection:
        _write(connection, identifier, files)
        connection.execute("UPDATE skills SET updated = ? WHERE id = ?", (_now(), identifier))
    return get(identifier)


def remove_file(identifier: int, path: str) -> dict[str, Any]:
    clean = clean_path(path)
    if clean == MAIN:
        raise ValueError("le SKILL.md ne se retire pas : supprimez la skill")
    with db.transaction() as connection:
        connection.execute(
            "DELETE FROM skill_files WHERE skill = ? AND path = ?", (identifier, clean)
        )
        connection.execute("UPDATE skills SET updated = ? WHERE id = ?", (_now(), identifier))
    return get(identifier)


# -- importer ----------------------------------------------------------------------


def _common_root(paths: list[str]) -> str:
    """Le dossier qui contient le SKILL.md le moins profond, ou ''."""
    mains = [path for path in paths if PurePosixPath(path).name == MAIN]
    if not mains:
        raise ValueError(f"il n'y a pas de {MAIN} dans ce dossier")
    top = min(mains, key=lambda path: len(PurePosixPath(path).parts))
    return str(PurePosixPath(top).parent) if "/" in top else ""


def import_files(files: dict[str, bytes], *, scope: Any = None) -> dict[str, Any]:
    """Une skill lue d'un dossier ou d'une archive : un SKILL.md et ce qui est à côté.

    Le dossier choisi peut être la skill, ou le dossier qui la contient : le
    SKILL.md le moins profond dit où elle commence. Le nom vient du frontmatter,
    à défaut du nom du dossier. Une skill du même nom est refusée, jamais écrasée.
    """
    cleaned = {clean_path(path): content for path, content in files.items()}
    root = _common_root(list(cleaned))
    prefix = f"{root}/" if root else ""
    inside = {
        path[len(prefix) :]: content for path, content in cleaned.items() if path.startswith(prefix)
    }
    inside = {path: content for path, content in inside.items() if not path.endswith(MARKER)}
    markdown = inside[MAIN].decode("utf-8", errors="replace")
    name, description, body = parse(markdown)
    name = name or (PurePosixPath(root).name if root else "")
    if not name:
        raise ValueError("cette skill n'a pas de nom : ajoutez `name:` à son frontmatter")
    if not description:
        raise ValueError(
            "cette skill n'a pas de description : ajoutez `description:` au frontmatter"
        )
    return create(name, description, body, scope, files=inside)


def import_archive(data: bytes, *, scope: Any = None) -> dict[str, Any]:
    """Une skill lue d'une archive .zip, sans rien en extraire sur le disque."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ValueError("ce n'est pas une archive .zip") from error
    files: dict[str, bytes] = {}
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > FILES_LIMIT * 4 or sum(info.file_size for info in infos) > SKILL_LIMIT * 4:
            raise ValueError("cette archive est trop grosse pour une skill")
        for info in infos:
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
                continue
            if info.file_size > FILE_LIMIT:
                raise ValueError(f"« {info.filename} » dépasse {FILE_LIMIT // 1_000_000} Mo")
            files[info.filename] = archive.read(info)
    return import_files(files, scope=scope)


def decode(items: Any) -> dict[str, bytes]:
    """`[{path, data}]` de l'API (data en base64) en {chemin: contenu}."""
    if not isinstance(items, list):
        raise ValueError("des fichiers : une liste de {path, data}")
    files: dict[str, bytes] = {}
    for item in items:
        try:
            files[str(item["path"])] = base64.b64decode(str(item["data"]), validate=True)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("un fichier envoyé est illisible") from error
    return files


# -- celles des dépôts -------------------------------------------------------------


def in_repository(root: Path) -> list[dict[str, str]]:
    """Les skills qu'un dépôt fournit : (nom, description) de chaque `.claude/skills/*/SKILL.md`."""
    found: list[dict[str, str]] = []
    folder = root / SKILLS_DIR
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return found
    for entry in entries:
        try:
            markdown = (entry / MAIN).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name, description, _ = parse(markdown)
        found.append({"name": entry.name, "title": name or entry.name, "description": description})
    return found


# -- poser dans un worktree ---------------------------------------------------------


@dataclass
class Placed:
    """Ce qu'une pose a fait : les skills posées, et celles que le dépôt avait déjà."""

    placed: list[str] = field(default_factory=list)
    kept_from_repository: list[str] = field(default_factory=list)


def applies(row: dict[str, Any], project: str) -> bool:
    """Cette skill est-elle pour ce projet : active, et pour tous ou pour lui ?"""
    scope = row["scope"]
    return bool(row["enabled"]) and (not scope or scope_key(project) in scope)


def _remove_ours(folder: Path) -> None:
    if (folder / MARKER).is_file():
        shutil.rmtree(folder, ignore_errors=True)


def install(workdir: Path, project: str) -> Placed:
    """Pose dans `workdir/.claude/skills/` les skills qui valent pour ce projet.

    Un dossier du même nom sans repère est celui du dépôt : on n'y touche pas.
    Un dossier avec repère est le nôtre d'une pose précédente : il est refait,
    ou retiré si la skill n'est plus pour ce projet.
    """
    result = Placed()
    base = workdir / SKILLS_DIR
    wanted = {row["name"]: row for row in listing() if applies(row, project)}
    if base.is_dir():
        for entry in base.iterdir():
            if entry.name not in wanted and entry.is_dir():
                _remove_ours(entry)
    for name, row in wanted.items():
        target = base / name
        if target.exists() and not (target / MARKER).is_file():
            result.kept_from_repository.append(name)
            continue
        _remove_ours(target)
        with db.transaction(immediate=False) as connection:
            files = connection.execute(
                "SELECT path, content FROM skill_files WHERE skill = ?", (row["id"],)
            ).fetchall()
        target.mkdir(parents=True, exist_ok=True)
        for path, content in files:
            where = target / clean_path(path)
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_bytes(bytes(content))
        (target / ".gitignore").write_text("*\n", encoding="utf-8")
        (target / MARKER).write_text("Posé par Ponos (Contexte › Skills).\n", encoding="utf-8")
        result.placed.append(name)
    return result
