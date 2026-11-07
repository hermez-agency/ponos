"""Converting a `config.toml` an older version wrote — once, and only when asked.

The file came down to some thirty keys in four steps: what nobody changes
became a constant of the code, `[projects]` and `[vault.projects]` became each
project's own settings in `ponos.db`, the secrets went into Ponos's vault, and
Notion left. The loader then stopped reading what it does not know: a key no
table reads is refused, with its line (`schema.read`), because a misspelt key
is a setting that does nothing while looking like one.

So yesterday's file needs one gesture, and it is `ponos config`. Not a launch:
a migration run by every start is a migration nobody sees, and it would have
to stay in the code for as long as an old file could still exist somewhere —
the tolerance this replaces. Here the file is rewritten once, its previous
text kept beside it (`config.toml.old.bak`), and what moved is said line by
line. Run again, it finds nothing to do and writes nothing.

The file is edited, never regenerated: it is one somebody reads and annotates
by hand, and a TOML writer would cost every comment in it (see
`config._write_line`). What is removed goes with its lines — a value written
over several lines included — and a table goes with the comment block written
right above its header. A key that is neither today's nor one this module knows
to have been retired is left where it is: it may be a typo of a real key, and
that is for the person to read; the loader names it with its line.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config as config_module
from . import db, disk, project_settings, store, vault
from .config import SECRETS, VALIDATED, ConfigError
from .schema import HEADER, KEY, dotted

# Every key the four steps took out of the file, table by table: each is now a
# constant of `config.py` (the default its dataclass has always had), or has no
# successor. `force_validated_<type>` became the one list `force_validated`,
# which `convert` writes from them before they go.
RETIRED: dict[str, tuple[str, ...]] = {
    "runner": (
        "max_concurrent_per_project",
        "relaunch_delay_seconds",
        "min_free_memory_mb",
        "max_load_per_core",
        "session_workers",
        "min_free_disk_mb",
        "credit_reserve_percent",
        "permission_mode",
        "branch_prefix",
        "fetch",
        "push",
        "open_pull_request",
        "rebase",
        "force_validated_code",
        "force_validated_writing",
        "force_validated_external",
        "force_validated_publication",
        "resolve_conflicts",
        "resolve_conflicts_except",
        "resolve_model",
        "checks_timeout_minutes",
        "local_ci_attempts",
        "local_ci_concurrent",
        "review_model",
        "setup_timeout_minutes",
        "keep_worktree_on_failure",
        "attach_sessions",
        "session_host",
        "dry_run",
        "prompt_file",
        "document_prompt_file",
        "delivery_prompt_file",
        "notify",
        "progress",
        "progress_interval_seconds",
        "reply",
        "reply_interval_seconds",
        "pr_review_comments",
        "pr_review_mention",
        "reply_scan",
        "reply_timeout_minutes",
        "reply_permission_mode",
        "on",
        "on_interval_seconds",
        "on_max_depth",
        "on_timeout_minutes",
        "on_permission_mode",
        "unblock_interval_seconds",
        "schedule",
        "update_interval_seconds",
        "log_retention_days",
        "clean_done_worktrees",
        "stale_worktree_days",
        "tmp_retention_hours",
        "docker_prune",
        "worktree_exclude",
        "classify",
        "classify_model",
        "classify_confidence",
        "auto_model",
        "auto_model_light",
        "auto_model_standard",
        "auto_model_heavy",
        "auto_model_heaviest",
        "auto_model_code",
        "auto_model_writing",
        "auto_model_external",
        "auto_model_publication",
        "auto_model_subtype_bug",
        "auto_model_subtype_feature",
        "auto_model_subtype_improvement",
        "auto_model_subtype_chore",
        "auto_model_subtype_refactor",
        "auto_model_subtype_perf",
        "auto_model_subtype_docs",
        "auto_model_subtype_security",
        "auto_model_escalate",
        "use_fable",
    ),
    "notify": ("replies", "digest_day", "digest_hour"),
    "notify.telegram": ("default_project",),
    "notify.slack": ("default_project",),
    "web": (
        "trusted_proxies",
        "poll_seconds",
        "chat_timeout_minutes",
        "chat_model",
        "attachment_max_mb",
        "attachment_days",
        "send_after_transcription",
    ),
    "budget": ("on_usd",),
}

# The tables that went whole: no model reads them any more. `[openrouter]`'s
# key is a secret, moved into the vault before its table goes; `[storage]` and
# `[issues]` left with the Markdown board, before these four steps, and were
# read without since.
RETIRED_TABLES = ("notion", "openrouter", "speech", "browser", "review", "storage", "issues")

BACKUP_SUFFIX = ".old.bak"


@dataclass
class Converted:
    """What `convert` did, each line already worded for `ponos config` to print."""

    moved: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    backup: Path | None = None

    @property
    def changed(self) -> bool:
        return bool(self.moved or self.removed or self.backup)


def backup_path(path: Path) -> Path:
    return path.parent / f"{path.name}{BACKUP_SUFFIX}"


def convert(path: Path) -> Converted:
    """Rewrite an older `config.toml` in today's format; nothing when it already is.

    The secrets go first, into Ponos's vault (`config.move_secrets`, what a
    launch does too): a vault that cannot take them stops the conversion before
    anything else moves — dropping `[openrouter]` must never drop its key.
    Then, under the lock a save takes: `[projects]` and `[vault.projects]` into
    each project's settings in `ponos.db`, the four `force_validated_<type>`
    booleans into the list, and every retired key and table out of the file.

    Raises ConfigError when the file is missing or is not TOML, or when the
    secrets cannot be moved.
    """
    if not path.exists():
        raise ConfigError(f"configuration not found: {path}")
    _parsed(path.read_text(encoding="utf-8"), path)
    done = Converted()
    try:
        secrets = config_module.move_secrets(path)
    except (OSError, vault.VaultError, sqlite3.Error) as error:
        raise ConfigError(
            f"the secrets {path.name} holds could not be moved into Ponos's vault — {error}. "
            "Nothing was converted"
        ) from error
    done.moved += [f"{name} → Ponos's vault" for name in secrets]
    with config_module._locked(path):
        _convert(path, done)
    return done


def _convert(path: Path, done: Converted) -> None:
    """`convert`, once the secrets are out and the lock is held."""
    original = path.read_text(encoding="utf-8")
    raw = _parsed(original, path)
    dropped: list[tuple[str, ...]] = []

    files_projects = raw.get("projects")
    if isinstance(files_projects, dict):
        dropped.append(("projects",))
        _move_paths(files_projects, done)
        if not files_projects:
            done.removed.append("[projects], empty")
    vault_table = raw.get("vault")
    if isinstance(vault_table, dict) and "projects" in vault_table:
        dropped.append(("vault", "projects"))
        if isinstance(vault_table["projects"], dict):
            _move_vault(vault_table["projects"], done)
        if not vault_table["projects"]:
            done.removed.append("[vault.projects], empty")

    runner = raw.get("runner")
    forced: list[str] | None = None
    if isinstance(runner, dict):
        booleans = [kind for kind in VALIDATED if f"force_validated_{kind}" in runner]
        if booleans and "force_validated" not in runner:
            forced = [kind for kind in VALIDATED if runner.get(f"force_validated_{kind}") is True]

    for table, keys in RETIRED.items():
        node = config_module._section(raw, table)
        for key in keys:
            if key in node:
                dropped.append((*table.split("."), key))
    dropped += [(table,) for table in RETIRED_TABLES if table in raw]
    # An empty secret is only where one used to go: the vault has nothing to take of it.
    for table, key in SECRETS:
        node = config_module._section(raw, table)
        if key in node and not str(node[key] or "").strip():
            dropped.append((*table.split("."), key))

    text = _drop(original, dropped)
    if forced:
        text = _set_list(text, "runner", "force_validated", forced)
        done.moved.append(
            "runner.force_validated_<type> → runner.force_validated = "
            + "["
            + ", ".join(f'"{kind}"' for kind in forced)
            + "]"
        )
    done.removed += [
        f"[{'.'.join(where)}]"
        if where[0] in RETIRED_TABLES and len(where) == 1
        else ".".join(where)
        for where in dropped
        if where not in (("projects",), ("vault", "projects"))
    ]
    if text != original:
        _parsed(text, path)
        backup = backup_path(path)
        disk.write_private(backup, original)
        done.backup = backup
        mode = path.stat().st_mode & 0o777
        scratch = path.parent / f".{path.name}.converting.{os.getpid()}.{threading.get_ident()}"
        disk.write_private(scratch, text)
        try:
            scratch.chmod(mode)
            os.replace(scratch, path)
        finally:
            if scratch.exists():
                scratch.unlink()


def _parsed(text: str, path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error


# -- what goes into ponos.db ------------------------------------------------------


def _projects() -> dict[str, tuple[str, str]]:
    """Every project of the board, by its name folded: its page id and its name as written."""
    from .pages import Pages

    try:
        pages = Pages().query("projects")
    except (store.StoreError, *db.ERRORS):
        return {}
    return {page.title.strip().casefold(): (page.id, page.title) for page in pages}


def _move_paths(table: dict[str, Any], done: Converted) -> None:
    """Each `[projects]` line into its project's Settings tab — its own path, if it has one, wins."""
    if not table:
        return  # an empty table, the example's: nothing to look up in ponos.db
    known = _projects()
    for name, value in table.items():
        found = known.get(str(name).strip().casefold())
        if found is None:
            done.notes.append(
                f'projects."{name}": no project of that name on the board — dropped '
                f"(the line is in {BACKUP_SUFFIX.lstrip('.')})"
            )
            continue
        page, title = found
        if project_settings.path(page):
            done.notes.append(
                f'projects."{name}": {title} already has a path of its own, which is kept'
            )
        else:
            project_settings.set_path(page, title, str(value))
        done.moved.append(f'projects."{name}" → the Settings tab of {title}')


def _move_vault(table: dict[str, Any], done: Converted) -> None:
    """Each `[vault.projects]` table into its project's own keys — its own, for a variable, win."""
    if not table:
        return
    known = _projects()
    reserved = config_module.reserved_variables()
    for name, entries in table.items():
        found = known.get(str(name).strip().casefold())
        if found is None:
            done.notes.append(
                f'vault.projects."{name}": no project of that name on the board — dropped'
            )
            continue
        page, title = found
        if isinstance(entries, dict):
            pairs = [(str(key).strip(), str(item).strip()) for key, item in entries.items()]
        elif isinstance(entries, (list, tuple)):
            pairs = [(str(key).strip(), str(key).strip()) for key in entries]
        else:
            done.notes.append(f'vault.projects."{name}" is neither a table nor a list — dropped')
            continue
        kept: dict[str, str] = {}
        for variable, item in pairs:
            why = vault.problems(variable, item, reserved)
            if why:
                done.notes.append(f'vault.projects."{name}": {why} — dropped')
            else:
                kept[variable] = item
        project_settings.set_vault(page, title, {**kept, **project_settings.vault(page)})
        done.moved.append(f'vault.projects."{name}" → the Settings tab of {title}')


# -- what the text loses ----------------------------------------------------------


def _comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _extent(lines: list[str], start: int) -> int:
    """The line after the value that starts at `start` — several, for an array or a long string."""
    for end in range(start + 1, len(lines) + 1):
        try:
            tomllib.loads("\n".join(lines[start:end]))
        except tomllib.TOMLDecodeError:
            continue
        return end
    return start + 1


def _header(line: str) -> tuple[str, ...] | None:
    """The table a header line opens; `()` for an array of tables, None for no header."""
    if line.lstrip().startswith("[["):
        return ()
    found = HEADER.match(line)
    return dotted(found.group(1)) if found else None


def _drop(text: str, paths: Iterable[tuple[str, ...]]) -> str:
    """The text without every table and key under those paths.

    A table goes with its body, and with the comment block written right above
    its header; the comments right above the next header stay, being that one's.
    """
    wanted = [tuple(path) for path in paths]
    if not wanted:
        return text

    def gone(path: tuple[str, ...]) -> bool:
        return any(path[: len(one)] == one for one in wanted)

    lines = text.splitlines()
    keep = [True] * len(lines)
    table: tuple[str, ...] = ()
    number = 0
    while number < len(lines):
        line = lines[number]
        opened = _header(line)
        if opened is not None:
            table = opened
            if opened and gone(opened):
                keep[number] = False
                above = number - 1
                while above >= 0 and keep[above] and _comment(lines[above]):
                    keep[above] = False
                    above -= 1
            number += 1
            continue
        if _comment(line):
            # The comments right above a header are that table's, whatever goes before them.
            following = number
            while following < len(lines) and _comment(lines[following]):
                following += 1
            nxt = _header(lines[following]) if following < len(lines) else None
            if table and gone(table) and not (nxt is not None and not (nxt and gone(nxt))):
                for each in range(number, following):
                    keep[each] = False
            number = following
            continue
        key = KEY.match(line)
        end = _extent(lines, number) if key else number + 1
        path = (*table, *dotted(key.group(1))) if key else table
        if path and gone(path):
            for each in range(number, end):
                keep[each] = False
        number = end

    kept = [line for line, stays in zip(lines, keep, strict=True) if stays]
    tidy: list[str] = []
    for line in kept:
        if not line.strip() and tidy and not tidy[-1].strip():
            continue
        tidy.append(line)
    while tidy and not tidy[-1].strip():
        tidy.pop()
    return "\n".join(tidy) + "\n" if tidy else ""


def _set_list(text: str, table: str, key: str, values: list[str]) -> str:
    """`key = [...]` under `[table]`, the way a save writes it (`config._write_line`)."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory) / "config.toml"
        scratch.write_text(text, encoding="utf-8")
        config_module._write_line(scratch, table, key, values)
        return scratch.read_text(encoding="utf-8")
