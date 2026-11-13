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

The secrets are no key of these models. They are read from Ponos's vault and
the environment by `config.secret`, with two precedences — the vault first,
the environment first for the console's password; pydantic-settings would
have taken one more dependency to say less, and was left out.
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
    UPDATE_CHANNELS,
    VALIDATED,
    WEEKDAYS,
    Budget,
    Claude,
    ConfigError,
    Permissions,
    Runner,
    Web,
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

    A key no table reads is refused, with its line (`read`): a misspelt key
    is a setting that does nothing, and the file that holds one is a file
    somebody believes says more than it does. What an older version wrote,
    `ponos config` converts once (conversion.py) — the loader does not read
    yesterday's format on the side. A number is read as text where text is wanted — a Telegram chat id is an
    integer to TOML and a string to everything downstream.
    """

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True, frozen=True)


# -- the tables -----------------------------------------------------------------


def _forced(value: object) -> tuple[str, ...]:
    """The types a list names, in the board's order; a word that is none of them is dropped.

    A string reads as well as a list, the console writing its lines as text.
    Filtered rather than refused, like the other lists here: a typo must not
    stop the runner, nor merge a type nobody named.
    """
    named = {str(word).strip().lower() for word in _words(value)}
    return tuple(kind for kind in VALIDATED if kind in named)


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
    # a list rather than one boolean a type.
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
    library_max_mb: AtLeast1 = Web.library_max_mb
    assistant_launches: bool = Web.assistant_launches


class ClaudeTable(Table):
    # A typo must not leave the sessions on an account nobody chose: an
    # unknown word is the file that says nothing.
    provider: Annotated[str, _one_of(PROVIDERS)] = ""
    attribution: bool = Claude.attribution


class BudgetTable(Table):
    daily_usd: Dollars = Budget.daily_usd
    per_ticket_usd: Dollars = Budget.per_ticket_usd


class PermissionsTable(Table):
    allowed: Sentences = Permissions.allowed
    ask: Sentences = Permissions.ask


class VaultTable(Table):
    """`[vault]`: where a project's keys are read. Which ones it is given is its own (ponos.db)."""

    provider: Annotated[str, BeforeValidator(lambda value: str(value).strip().lower() or "env")] = (
        "env"
    )


def _extras(value: object) -> tuple[str, ...]:
    """The extras a list names, lowercased, once each; a string reads as a one-item list."""
    words = [value] if isinstance(value, str) else _words(value)
    return tuple(dict.fromkeys(name for item in words if (name := str(item).strip().lower())))


class InstallTable(Table):
    """`[install]`: the optional extras of `pyproject.toml` every version is given."""

    extras: Annotated[tuple[str, ...], BeforeValidator(_extras)] = ()


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

    runner: RunnerTable = Field(default_factory=RunnerTable)
    web: WebTable = Field(default_factory=WebTable)
    notify: NotifyTable = Field(default_factory=NotifyTable)
    claude: ClaudeTable = Field(default_factory=ClaudeTable)
    budget: BudgetTable = Field(default_factory=BudgetTable)
    permissions: PermissionsTable = Field(default_factory=PermissionsTable)
    vault: VaultTable = Field(default_factory=VaultTable)
    install: InstallTable = Field(default_factory=InstallTable)
    github: Annotated[dict[str, str], AfterValidator(_owners)] = Field(default_factory=dict)
    github_access: GithubAccessTable = Field(default_factory=GithubAccessTable)


# -- what is said when it does not read -----------------------------------------


def read(raw: dict[str, Any], text: str, path: Path) -> File:
    """The file, validated — or a ConfigError with a line per value that is not read.

    The first line is the one the console shows when a save is refused; the
    others are indented under it, as `ponos doctor` prints them. A key or a
    table no model knows is one of them, named with its line.

    A secret the file still holds is the one exception, left out before the
    file is read: the launch moves it into the vault (`config.move_secrets`),
    and one that could not be moved is ignored and said (`config.exposed`), so
    that a vault whose key is gone leaves Ponos on the environment rather than
    stopped.
    """
    if "notion" in raw:
        line = line_of(text, ("notion",))
        at = f"{path}, line {line}" if line else str(path)
        raise ConfigError(
            f"{at}: [notion] — Ponos no longer works with Notion: the board is ponos.db. "
            "Remove this table and every [notion.…] one from the file (ponos config does)"
        )
    try:
        return File.model_validate(without_secrets(raw))
    except ValidationError as error:
        # In the order of the file rather than of the model: read top to bottom.
        said = [_said(detail, text, path) for detail in error.errors()]
        raise ConfigError("\n  ".join(sorted(said, key=lambda line: _line(line, path)))) from None


def without_secrets(raw: dict[str, Any]) -> dict[str, Any]:
    """The parsed file less the secrets it may still hold, and the tables only they made.

    `[openrouter]` was a table for its key alone: the key gone, nothing of it is left.
    """
    kept = {name: _copied(value) for name, value in raw.items()}
    for table, key in SECRETS:
        parts = table.split(".")
        trail: list[dict[str, Any]] = [kept]
        for part in parts:
            node = trail[-1].get(part)
            if not isinstance(node, dict):
                break
            trail.append(node)
        else:
            trail[-1].pop(key, None)
            for depth in range(len(parts), 0, -1):
                if trail[depth]:
                    break
                del trail[depth - 1][parts[depth - 1]]
    return kept


def _copied(value: object) -> Any:
    return (
        {name: _copied(item) for name, item in value.items()} if isinstance(value, dict) else value
    )


def _line(said: str, path: Path) -> int:
    """The line one of `_said`'s sentences is about; 0 when it names none."""
    found = re.match(rf"{re.escape(str(path))}, line (\d+):", said)
    return int(found.group(1)) if found else 0


def _said(detail: ErrorDetails, text: str, path: Path) -> str:
    """“config.toml, line 12: runner.port = 'x' — Input should be a valid integer…”."""
    where = tuple(str(part) for part in detail["loc"])
    line = line_of(text, where)
    at = f"{path}, line {line}" if line else str(path)
    if detail["type"] == "extra_forbidden":
        return f"{at}: {_unknown(where, detail['input'])}"
    given = repr(detail["input"])
    if len(given) > 60:
        given = given[:57] + "…"
    shown = f"{'.'.join(where)} = {given}" if detail["type"] != "missing" else ".".join(where)
    return f"{at}: {shown} — {detail['msg']}"


# A table header, `[notify.telegram]`, and the key a line sets, quoted or dotted.
HEADER = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$")
_PART = r""""([^"]*)"|'([^']*)'|([A-Za-z0-9_-]+)"""
KEY = re.compile(rf"^\s*((?:{_PART})(?:\s*\.\s*(?:{_PART}))*)\s*=")


def dotted(written: str) -> tuple[str, ...]:
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
        if header := HEADER.match(line):
            table = dotted(header.group(1))
            path = table
        elif key := KEY.match(line):
            path = table + dotted(key.group(1))
        else:
            continue
        if len(path) > depth and where[: len(path)] == path:
            found, depth = number, len(path)
    return found


def _unknown(where: tuple[str, ...], given: object) -> str:
    """What is said of a key, or a table, that is no part of the file."""
    name = ".".join(where)
    shown = f"[{name}]" if isinstance(given, dict) else name
    what = "table" if isinstance(given, dict) else "key"
    model: type[BaseModel] = File
    for part in where[:-1]:
        kind = model.model_fields[part].annotation if part in model.model_fields else None
        if not (isinstance(kind, type) and issubclass(kind, Table)):
            break
        model = kind
    close = difflib.get_close_matches(where[-1], list(model.model_fields), n=1)
    hint = f" (did you mean {'.'.join((*where[:-1], close[0]))}?)" if close else ""
    return (
        f"{shown} is not a {what} of config.toml{hint} — "
        "ponos config converts a file an older version wrote"
    )
