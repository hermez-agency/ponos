"""What `config.toml` may say, table by table — pydantic models of the file.

`config.load` used to read the file with `raw.get()` and a conversion per
key, and what it could not convert it either replaced in silence or let fall
as a traceback that named no key. The rules it applied are kept, one by one,
and written here as types: a floor is a floor (`interval_seconds = 0` is still
one second), a word that is none of the choices is still the default (a typo in
`update_channel` still means `release`, never `main`), and an amount left blank
is still no limit. What changes is the rest: a value no rule reads — a port
that is not a number, a table that is a string — stops the load with the key
and the line it is written on (`read`), which is what `ponos doctor` prints.

Defaults are not written twice. Each field takes the one of the dataclass
`config.load` hands the runner, and the dataclasses stay what the rest of the
code holds: they are imported everywhere, `web/server.py` included, and that
module must import with a Python that has no pydantic (see its docstring). So
this one is imported by `load`, when the file is read, and not before — a
Python without pydantic can still start, say what it is missing, and make the
environment that has it (`__main__.command_run`).

The secrets are no key of these models. They are read from `secrets.env` and
the environment by `config.secret`, with two precedences — the file first,
the environment first for the console's password — and a writer that keeps
the file's comments; pydantic-settings would have taken one more dependency
to say less, and was left out.
"""

from __future__ import annotations

import difflib
import math
import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
)
from pydantic_core import ErrorDetails, PydanticUseDefault

from .config import (
    DIGESTS,
    EVENTS,
    GITHUB_MODES,
    IDEAS_SCHEDULES,
    IDEAS_SCOPES,
    MERGE_METHODS,
    PROVIDERS,
    SECRETS,
    TYPES,
    UPDATE_CHANNELS,
    WEEKDAYS,
    Budget,
    ConfigError,
    Permissions,
    Runner,
    Web,
    identifier,
)

# -- how a value is read ------------------------------------------------------


def _truncated(value: object) -> object:
    """A whole number from a float, cut as `int()` always cut it here."""
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    return value


def _at_least(least: int) -> AfterValidator:
    return AfterValidator(lambda value: max(least, value))


Integer = Annotated[int, BeforeValidator(_truncated)]
# Each floor is said where its field is, with the reason it is that one.
AtLeast0 = Annotated[Integer, _at_least(0)]
AtLeast1 = Annotated[Integer, _at_least(1)]

Text = Annotated[str, AfterValidator(str.strip)]


def _or_default(value: str) -> str:
    """An empty value is the file saying nothing: the default answers."""
    if not value:
        raise PydanticUseDefault()
    return value


Filled = Annotated[Text, AfterValidator(_or_default)]
# A trailing slash would make `…/v1//messages` of what is joined to it.
Address = Annotated[Text, AfterValidator(lambda value: value.rstrip("/"))]


def _one_of(choices: tuple[str, ...] | dict[str, Any]) -> BeforeValidator:
    """A word, lowercased, and the default for one that is none of `choices`.

    Filtered rather than refused, as the loader always did: a typo there must
    neither stop the runner nor be read as some other choice.
    """

    def chosen(value: object) -> str:
        word = str(value).strip().lower()
        if word not in choices:
            raise PydanticUseDefault()
        return word

    return BeforeValidator(chosen)


def _names(value: object) -> str:
    """A list in the file reads as well as the comma-separated line the console writes."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(name).strip() for name in value)
    return str(value).strip()


Names = Annotated[str, BeforeValidator(_names)]


def _dollars(value: object) -> float:
    """An amount, or 0.0 for a limit that is empty, negative or not a number.

    Empty is the line left blank in the file, and it must read as "no limit"
    rather than as a ceiling of nothing that stops every session.
    """
    try:
        return max(0.0, float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


Dollars = Annotated[float, BeforeValidator(_dollars)]


def _per_core(value: object) -> float:
    """A load per core, the default for one that is no number, none under zero.

    The console writes it as text, as it does an amount: a blank there is the
    file saying nothing, and a typo must not stop the runner. A negative ceiling
    is a typo for none at all, as zero is.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise PydanticUseDefault() from None
    return max(0.0, number)


PerCore = Annotated[float, BeforeValidator(_per_core)]


def _sentences(value: object) -> tuple[str, ...]:
    """A list of sentences as the file wrote it, or the default when it wrote none.

    A value that is not a list is the default; a list — even an empty one — is
    the answer. Blank entries are dropped, not kept as empty rules.
    """
    if not isinstance(value, list):
        raise PydanticUseDefault()
    return tuple(text for item in value if (text := str(item).strip()))


Sentences = Annotated[tuple[str, ...], BeforeValidator(_sentences)]


class Table(BaseModel):
    """One table of the file.

    A key nobody reads is left alone, as it always was: an installation keeps
    lines an older version wrote, and its secrets until the launch moves them.
    It is not kept quiet for all that — a misspelt key is a setting that does
    nothing: `unknown` names it, for `ponos doctor` and the health band.
    A number is read as text where text is wanted — a Telegram chat id is an
    integer to TOML and a string to everything downstream.
    """

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True, frozen=True)


# -- the tables -----------------------------------------------------------------


class NotionTable(Table):
    # A bare ID, a dashed ID or a full URL: see `config.identifier`.
    workspace: Annotated[str, AfterValidator(identifier)] = ""
    tickets_database: Annotated[str, AfterValidator(identifier)] = ""
    mention: Text = ""
    # As the file writes them, and only those: `config.Notion` needs to know
    # which names the file gives to tell them from the ones it falls back on.
    pages: dict[str, str] = Field(default_factory=dict)


def _forced(value: object) -> tuple[str, ...]:
    """The types a list names, in the board's order; a word that is none of them is dropped.

    A string reads as well as a list, the console writing its lines as text.
    Filtered rather than refused, like the other lists here: a typo must not
    stop the runner, nor merge a type nobody named.
    """
    named = {str(word).strip().lower() for word in _words(value)}
    return tuple(kind for kind in TYPES if kind in named)


def _words(value: object) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return str(value).replace(",", " ").split()


class RunnerTable(Table):
    workspace_root: str = str(Runner.workspace_root)
    # systemd refuses a zero interval, and anything below a second would
    # only spin: one second is the floor that means anything here.
    interval_seconds: AtLeast1 = Runner.interval_seconds
    max_concurrent: AtLeast1 = Runner.max_concurrent
    timeout_minutes: AtLeast1 = Runner.timeout_minutes
    wait_for_credits: bool = Runner.wait_for_credits

    model: Text = Runner.model
    # Kept as the file wrote it: `voice` reads it down to a language it
    # speaks, and the difference between "nothing was said" and "English was
    # asked for" is one the loader must not flatten.
    language: Text = Runner.language
    app_language: Text = Runner.app_language
    base_branch: Text = Runner.base_branch
    # The types of ticket the runner merges without waiting for a review, as
    # a list rather than one boolean a type. `config.load` reads the four
    # booleans a file still holds when this one is not written.
    force_validated: Annotated[tuple[str, ...], BeforeValidator(_forced)] = ()
    merge_method: Annotated[str, _one_of(MERGE_METHODS)] = Runner.merge_method
    local_ci: bool = Runner.local_ci
    self_review: bool = Runner.self_review
    unblock: bool = Runner.unblock

    # The ideas schedule: the Planned page's dialog writes these, so they stay
    # keys of the file though Settings no longer draws a card for them.
    ideas_model: Text = Runner.ideas_model
    ideas_schedule: Annotated[str, _one_of(IDEAS_SCHEDULES)] = Runner.ideas_schedule
    ideas_at: Text = Runner.ideas_at
    ideas_day: Annotated[
        str, _one_of(tuple(day.lower() for day in WEEKDAYS)), AfterValidator(str.capitalize)
    ] = Runner.ideas_day
    ideas_every_hours: AtLeast1 = Runner.ideas_every_hours
    ideas_cron: Text = Runner.ideas_cron
    ideas_scope: Annotated[str, _one_of(IDEAS_SCOPES)] = Runner.ideas_scope
    ideas_projects: Names = Runner.ideas_projects
    ideas_workspace: bool = Runner.ideas_workspace
    # Ten is what a batch asks for; more than twenty is a prompt the model
    # answers badly, and none is a pass that does nothing.
    ideas_per_batch: Annotated[Integer, AfterValidator(lambda value: min(20, max(1, value)))] = (
        Runner.ideas_per_batch
    )
    # Zero: never skipped, however many are waiting.
    ideas_skip_above: AtLeast0 = Runner.ideas_skip_above
    ideas_budget_usd: Dollars = Runner.ideas_budget_usd
    ideas_notify: bool = Runner.ideas_notify

    auto_update: bool = Runner.auto_update
    # A typo here must not quietly put an installation on every commit of
    # `main`: anything unknown is the careful answer.
    update_channel: Annotated[str, _one_of(UPDATE_CHANNELS)] = Runner.update_channel


def _users(value: object) -> str:
    """`allowed_users`, as the one comma-separated string a channel's table holds."""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item).strip() for item in value).strip()
    return str(value).strip()


Users = Annotated[str, BeforeValidator(_users)]


class TelegramTable(Table):
    chat: Text = ""
    allowed_users: Users = ""


class SlackTable(Table):
    channel: Text = ""
    allowed_users: Users = ""


class NotifyTable(Table):
    # None is the file saying nothing: `runner.notify` answers, as it did
    # before this table existed.
    desktop: bool | None = None
    # Filtered rather than trusted: a typo in this list would otherwise
    # silence a moment without ever saying so.
    events: Annotated[
        tuple[str, ...],
        AfterValidator(
            lambda names: tuple(
                name for name in (value.strip().lower() for value in names) if name in EVENTS
            )
        ),
    ] = EVENTS
    # The summary of a period sent on its own — see digest.py. Off unless asked.
    digest: Annotated[str, _one_of(DIGESTS)] = "off"
    telegram: TelegramTable = Field(default_factory=TelegramTable)
    slack: SlackTable = Field(default_factory=SlackTable)


class WebTable(Table):
    host: Filled = Web.host
    port: Integer = Web.port
    url: Address = Web.url
    email: Text = Web.email


class ClaudeTable(Table):
    # A typo must not leave the sessions on an account nobody chose: an
    # unknown word is the file that says nothing.
    provider: Annotated[str, _one_of(PROVIDERS)] = ""


class BudgetTable(Table):
    daily_usd: Dollars = Budget.daily_usd
    per_ticket_usd: Dollars = Budget.per_ticket_usd


class PermissionsTable(Table):
    allowed: Sentences = Permissions.allowed
    ask: Sentences = Permissions.ask


class VaultTable(Table):
    """`[vault]`: what each project is given. `config._vault` checks what it can hand over.

    An entry that cannot be handed over is said by `ponos doctor` rather than
    refused here: the rest of the file, and the other projects, still work.
    """

    provider: Annotated[str, BeforeValidator(lambda value: str(value).strip().lower() or "env")] = (
        "env"
    )
    projects: dict[str, Any] = Field(default_factory=dict)


class GithubAccessTable(Table):
    mode: Annotated[str, _one_of(GITHUB_MODES)] = ""
    token_item: Text = ""


def _owners(table: dict[str, str]) -> dict[str, str]:
    """`[github]`, lowercased on the way in: GitHub does not care how an owner is spelled."""
    return {
        name.strip().lower(): account.strip() for name, account in table.items() if account.strip()
    }


class File(Table):
    """The whole of `config.toml`."""

    notion: NotionTable = Field(default_factory=NotionTable)
    runner: RunnerTable = Field(default_factory=RunnerTable)
    projects: dict[str, str] = Field(default_factory=dict)
    web: WebTable = Field(default_factory=WebTable)
    notify: NotifyTable = Field(default_factory=NotifyTable)
    claude: ClaudeTable = Field(default_factory=ClaudeTable)
    budget: BudgetTable = Field(default_factory=BudgetTable)
    permissions: PermissionsTable = Field(default_factory=PermissionsTable)
    vault: VaultTable = Field(default_factory=VaultTable)
    github: Annotated[dict[str, str], AfterValidator(_owners)] = Field(default_factory=dict)
    github_access: GithubAccessTable = Field(default_factory=GithubAccessTable)


# -- what is said when it does not read -----------------------------------------


def read(raw: dict[str, Any], text: str, path: Path) -> File:
    """The file, validated — or a ConfigError with a line per value that is not read.

    The first line is the one the console shows when a save is refused; the
    others are indented under it, as `ponos doctor` prints them.
    """
    try:
        return File.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(
            "\n  ".join(_said(detail, text, path) for detail in error.errors())
        ) from None


def _said(detail: ErrorDetails, text: str, path: Path) -> str:
    """“config.toml, line 12: runner.port = 'x' — Input should be a valid integer…”."""
    where = tuple(str(part) for part in detail["loc"])
    line = line_of(text, where)
    at = f"{path}, line {line}" if line else str(path)
    given = repr(detail["input"])
    if len(given) > 60:
        given = given[:57] + "…"
    shown = f"{'.'.join(where)} = {given}" if detail["type"] != "missing" else ".".join(where)
    return f"{at}: {shown} — {detail['msg']}"


# A table header, `[notify.telegram]`, and the key a line sets, quoted or dotted.
_HEADER = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$")
_PART = r""""([^"]*)"|'([^']*)'|([A-Za-z0-9_-]+)"""
_KEY = re.compile(rf"^\s*((?:{_PART})(?:\s*\.\s*(?:{_PART}))*)\s*=")


def _dotted(written: str) -> tuple[str, ...]:
    return tuple(
        next(part for part in match.groups() if part is not None)
        for match in re.finditer(_PART, written)
    )


def line_of(text: str, where: tuple[str, ...]) -> int:
    """The line a key is written on — or its table's header, or 0 when neither is.

    TOML says what the file holds, not where: the key is looked for again in
    the text, under the table it belongs to. An item of a list is its key's line.
    """
    found, depth = 0, 0
    table: tuple[str, ...] = ()
    for number, line in enumerate(text.splitlines(), 1):
        if header := _HEADER.match(line):
            table = _dotted(header.group(1))
            path = table
        elif key := _KEY.match(line):
            path = table + _dotted(key.group(1))
        else:
            continue
        if len(path) > depth and where[: len(path)] == path:
            found, depth = number, len(path)
    return found


# -- what is written and read by nobody -----------------------------------------

# Keys an older version read and this one does not, as their paths: a file that
# still holds one is not wrong for it. The secrets `config.py` moves to
# `secrets.env` are exempt beside them, read from `SECRETS`.
# The names of the board's columns, statuses and types were settings until they
# were fixed in `config.PROPERTIES`: a file that still names them is read
# without them, and `doctor` says what the board itself is missing.
RETIRED: frozenset[tuple[str, ...]] = frozenset(
    {("notion", "properties"), ("notion", "status"), ("notion", "types")}
)


# The keys this version stopped reading when `config.toml` came down to what
# somebody actually changes: each is now a constant of `config.py` (the default
# its dataclass has always had), and a file that still writes one is read all
# the same — `retired` names it for `ponos doctor`. The refusal of what no
# table knows comes with the command that converts the file, not before: an
# installation updated on its own must not stop on the line it was left with.
# `force_validated_<type>` became the one list `force_validated`; the rest has
# no successor. Tables whole — `[openrouter]`, `[speech]`, `[review]` — are here
# key by key and have no model any more.
REMOVED: dict[str, tuple[str, ...]] = {
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
    "notify.telegram": ("default_project",),
    "notify.slack": ("default_project",),
    "notify": (
        "replies",
        "digest_day",
        "digest_hour",
    ),
    "web": (
        "trusted_proxies",
        "poll_seconds",
        "chat_timeout_minutes",
        "chat_model",
        "attachment_max_mb",
        "attachment_days",
        "send_after_transcription",
    ),
    "openrouter": (
        "base_url",
        "route_sessions",
        "transcription_model",
    ),
    "speech": (
        "enabled",
        "voice_fr",
        "voice_en",
        "speed",
    ),
    "browser": ("default", "headless"),
    "review": ("ci_retries",),
    "budget": ("on_usd",),
}


def retired(raw: dict[str, Any], text: str) -> list[tuple[int, str]]:
    """Each key the file still holds that is a constant now: its line and its dotted name."""
    secrets = {(*table.split("."), key) for table, key in SECRETS}
    found: list[tuple[int, str]] = []
    for table, keys in REMOVED.items():
        where = tuple(table.split("."))
        node: object = raw
        for part in where:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            continue
        for key in keys:
            if key in node and (*where, key) not in secrets:
                found.append((line_of(text, (*where, key)), f"{table}.{key}"))
    return sorted(found)


def unknown(raw: dict[str, Any], text: str) -> list[tuple[int, str, str]]:
    """Each key no table reads: its line, its dotted name, and the known one it is closest to.

    `read` ignores them; this is what says so. A table whose keys are the
    file's to choose — `[projects]`, `[github]`, `[notion.pages]` — has none,
    and a table nobody knows is one key, its contents left unread.
    """
    exempt = (
        RETIRED
        | {(*table.split("."), key) for table, key in SECRETS}
        | {(*table.split("."), key) for table, keys in REMOVED.items() for key in keys}
        # A table that has no model any more: its keys are said by `retired`.
        | {(table,) for table in REMOVED if table not in File.model_fields}
    )
    found: list[tuple[int, str, str]] = []

    def walk(model: type[Table], node: dict[str, Any], where: tuple[str, ...]) -> None:
        for key, value in node.items():
            path = (*where, key)
            known = model.model_fields.get(key)
            if known is None:
                if path not in exempt:
                    close = difflib.get_close_matches(key, model.model_fields, n=1)
                    found.append((line_of(text, path), ".".join(path), close[0] if close else ""))
            elif (
                isinstance(kind := known.annotation, type)
                and issubclass(kind, Table)
                and isinstance(value, dict)
            ):
                walk(kind, value, path)

    walk(File, raw, ())
    return sorted(found)
