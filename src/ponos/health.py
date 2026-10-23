"""Whether the installation can run a ticket — and what to do when it cannot.

A badly configured Ponos fails without a word: the ticket does not start, or
starts and dies on a repository nobody can push to, and the only trace is a
line in a log. This module is the one place that asks, and it is asked by two
readers — `ponos doctor`, on a terminal, and the dashboard of the console — so
that the two cannot disagree about what "in place" means.

Three decisions shape it.

- **A check is data, and its sentences are templates.** Each one carries a
  `code`, a `state`, and sentences with `{{name}}` holes and the `params` that
  fill them. The terminal fills them in (`Check.text`); the console hands the
  template itself to its dictionary, as it does for every other sentence, so
  the French is a translation of the English and not a second implementation.
  What a tool printed — git's error, Notion's — travels in `evidence`, quoted
  as it came.
- **A fix is offered only when Ponos can make it, and never made unasked.**
  `Check.fix` names an action from `FIXES`; the console confirms it with a
  dialog and `fix()` refuses to run without `confirmed=True`, so the second
  guard holds even for a script that skipped the first. Everything else —
  sharing a page with the integration, installing the GitHub App — happens in
  somebody else's interface, and there the check says the exact steps and the
  link instead.
- **Nothing here fails the caller.** A check that cannot be made says so
  as a check (`unknown`), it does not raise: a health page that crashes on
  the first unreachable service is worse than none.

A fourth state sits beside the three verdicts: `info`, a setting said rather
than judged — the interval of a run, who may answer on a channel. `doctor`
prints it in grey, as it always has, and the dashboard's band, which lists
what is to be fixed, leaves it out.

Checks that wait on a network (a remote, `gh`, Notion) run side by side in
threads: ten projects asked one after the other is half a minute of a page
that looks hung. The one network question only `doctor` asks is the newest
version (`remote=True`): the dashboard reads what the last check found, as the
console's header does, rather than fetching on every page that opens.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from . import (
    __version__,
    channels,
    cleanup,
    conversation,
    db,
    environment,
    git,
    github_app,
    github_token,
    idea_schedule,
    kinds,
    leftovers,
    log,
    models,
    prerequisites,
    project_settings,
    projects,
    provider,
    provision,
    resources,
    session,
    store,
    systemd,
    vault,
    voice,
)
from . import config as config_module
from . import schedules as schedules_module
from . import update as update_module
from . import workspace as workspace_module

logger = logging.getLogger(__name__)

OK, WARN, ERROR, INFO = "ok", "warn", "error", "info"

GROUPS = ("notion", "github", "claude", "projects", "machine", "settings")

# A floor, not a measurement: Claude Code older than this is reported as too
# old before a ticket finds out. Raise it the day a flag the runner passes
# needs a newer one.
MINIMUM_CLAUDE = (2, 0, 0)

# One probe never holds a page for longer than this — `provider.CHECK_TIMEOUT`
# is for a single call, and a remote that does not answer is the case at hand.
PROBE_TIMEOUT = 15

# What a channel's error code means, for the codes Slack answers with — the code
# itself stays in the evidence, quoted.
NOTIFY_SAID = {
    "channel_not_found": "{{channel}} cannot find the channel, or the bot cannot see it.",
    "not_in_channel": "The bot is not in the {{channel}} channel.",
    "missing_scope": "The {{channel}} token lacks a permission.",
    "invalid_auth": "{{channel}} refused the bot token.",
}

NOTION_INTEGRATIONS = "https://www.notion.so/profile/integrations"
CLAUDE_INSTALL = "https://docs.claude.com/en/docs/claude-code/setup"

# The statuses the runner moves a ticket through, each one required.
RUNNER_STATUSES = ("ready", "running", "review", "validated", "done", "failed", "blocked")

# The properties of the Schedules database, what each is for, and the type it reads best as.
SCHEDULE_COLUMNS = (
    ("cadence", "select", "Hourly, Daily, Weekly or Monthly"),
    ("at", "rich_text", "the hour it happens at, written 09:00"),
    ("day", "rich_text", "Monday for a weekly one, 1 to 31 for a monthly one"),
    ("active", "checkbox", "unticked stops it without deleting anything"),
    ("next_run", "date", "written by the runner: when the next ticket is born"),
    ("last_run", "date", "written by the runner: when the last one was"),
    ("last_ticket", "relation", "written by the runner: how it knows the last one is over"),
    ("project", "relation", "the project every ticket it makes points at"),
    ("model", "select", "the model every ticket it makes runs on"),
    ("priority", "number", "the priority score, 0 to 100, every ticket it makes carries"),
    ("type", "select", "the type every ticket it makes is born with — empty, it is guessed"),
    ("subtype", "select", "the sub-type every code ticket it makes is born with"),
)

CLAUDE_MODELS = {"haiku", "sonnet", "opus", "fable"}


@dataclass
class Check:
    code: str
    group: str
    state: str
    title: str
    said: str
    params: dict[str, str] = field(default_factory=dict)
    # Why it is likely so, and what to do by hand: sentences like `said`.
    cause: str = ""
    steps: list[str] = field(default_factory=list)
    url: str = ""
    # What a tool printed, quoted — never translated.
    evidence: str = ""
    # What each name in a list is worth: {"name", "said": [sentences]}, the
    # sentences templates like the rest, the name a thing of the user's own.
    notes: list[dict[str, Any]] = field(default_factory=list)
    # {"action", "label", "confirm", "target"} when Ponos can make the fix.
    fix: dict[str, str] | None = None

    def text(self, template: str) -> str:
        """A sentence of this check with its holes filled, for the terminal."""
        return re.sub(
            r"\{\{(\w+)\}\}", lambda hole: str(self.params.get(hole[1], hole[0])), template
        )

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


def _check(code: str, state: str, title: str, said: str, **rest: Any) -> Check:
    return Check(code, code.split(".", 1)[0], state, title, said, **rest)


def _first_line(error: object) -> str:
    return (str(error).strip().splitlines() or [""])[0]


INSTALL_STEP = "Install it: `{{command}}`."


def _installing(tool: str, *steps: str) -> dict[str, Any]:
    """The steps of a check whose tool is missing: the command that installs it here first.

    Spread into `_check`, with the `params` that fill it — none when no package
    manager is known here.
    """
    command = prerequisites.install_command(tool)
    if not command:
        return {"steps": list(steps)}
    return {"steps": [INSTALL_STEP, *steps], "params": {"command": command}}


# -- Notion --------------------------------------------------------------------


def _board(
    config: config_module.Config, client: store.Store
) -> tuple[list[Check], workspace_module.Workspace | None]:
    """The board, Notion or files: reached, made of the pages it needs, shaped as the runner reads it."""
    found: list[Check] = []
    storage = config.storage
    if storage.markdown:
        found.append(
            _check(
                "notion.storage",
                OK,
                "Board",
                "A Markdown board at {{path}}.",
                params={"path": str(storage.path)},
            )
        )
        if not storage.path.is_dir():
            found.append(
                _check(
                    "notion.storage", INFO, "Board", "Not created yet: the first write makes it."
                )
            )
        if storage.mode == "both":
            found.append(
                _check(
                    "notion.storage",
                    INFO,
                    "Board",
                    "Mirrored with Notion, {{conflict}} wins a conflict, reconciled on every pass."
                    if storage.on_every_pass
                    else "Mirrored with Notion, {{conflict}} wins a conflict.",
                    params={"conflict": storage.conflict},
                )
            )
    if storage.notion:
        reached = _notion_token(config, client)
        found.extend(reached)
        if any(check.state == ERROR for check in reached):
            return found, None
    else:
        found.append(
            _check(
                "notion.storage",
                INFO,
                "Board",
                "storage.mode = “markdown”: Notion is never asked anything.",
            )
        )

    try:
        space = workspace_module.resolve(client, config.notion)
        schema = client.schema(space.tickets)
    except store.StoreError as error:
        found.append(
            _check(
                "notion.tickets",
                ERROR,
                "Tickets database",
                "The tickets database cannot be read.",
                cause="The database is not shared with the integration, or it was deleted or renamed."
                if storage.notion
                else "",
                steps=[
                    "Add the Ponos integration to your Notion page: ··· menu › Connections.",
                    "Check that the page or database named in the settings still exists.",
                ]
                if storage.notion
                else [],
                url=NOTION_INTEGRATIONS if storage.notion else "",
                evidence=str(error).strip(),
            )
        )
        return found, None
    if storage.notion and config.notion.workspace:
        found.extend(_workspace(config, space))
    found.append(
        _check(
            "notion.tickets",
            OK,
            "Tickets database",
            "Tickets database readable: {{count}} properties.",
            params={"count": str(len(schema))},
        )
    )
    reference = config.notion.tickets_database or config.notion.page("tickets")
    if storage.notion and space.tickets != reference:
        found.append(
            _check(
                "notion.tickets",
                WARN,
                "Tickets database",
                "Resolved from “{{reference}}” to the database {{database}}.",
                params={"reference": reference, "database": space.tickets},
            )
        )

    if storage.notion:
        found.append(_projects_database(client, space))
    found.extend(_schema(config, client, space))
    found.extend(_other_statuses(config, client, space))
    found.extend(_types(config, client, space))
    found.extend(_schedules(config, client, space))
    found.extend(_comments(config, client, space))
    # Only a Notion board's projects are looked through one by one.
    return found, space if storage.notion else None


def _notion_token(config: config_module.Config, client: store.Store) -> list[Check]:
    try:
        config.require_usable()
    except config_module.ConfigError as error:
        return [
            _check(
                "notion.token",
                ERROR,
                "Notion token",
                "No Notion token or tickets database is set.",
                cause="The integration was never created, or its token never reached the settings.",
                steps=[
                    "Create an integration on Notion and copy its secret.",
                    "Paste it in Settings › Notion (notion.token).",
                ],
                url=NOTION_INTEGRATIONS,
                evidence=_first_line(error),
            )
        ]
    try:
        name = client.my_name() or "integration"
    except store.StoreError as error:
        return [
            _check(
                "notion.token",
                ERROR,
                "Notion token",
                "Notion refused the token.",
                cause="The token was revoked, mistyped, or belongs to another workspace.",
                steps=[
                    "Open the integration on Notion and copy its secret again.",
                    "Paste it in Settings › Notion (notion.token).",
                ],
                url=NOTION_INTEGRATIONS,
                evidence=_first_line(error),
            )
        ]
    return [
        _check(
            "notion.token", OK, "Notion token", "Connected as “{{name}}”.", params={"name": name}
        )
    ]


def _workspace(config: config_module.Config, space: workspace_module.Workspace) -> list[Check]:
    """The pages a workspace is made of: what was found, and what is missing or unreadable."""
    settings = config.notion
    found = [
        _check(
            "notion.workspace",
            OK,
            "Notion workspace",
            "{{count}} pages found: {{pages}}.",
            params={
                "count": str(len(space.rows)),
                "pages": ", ".join(f"“{name}”" for name in sorted(space.rows)) or "—",
            },
        )
    ]
    for message in space.warnings:
        found.append(
            _check(
                "notion.workspace",
                WARN,
                "Notion workspace",
                "A page of the workspace is missing or cannot be read.",
                steps=["Every page must be shared with the integration: ··· menu › Connections."],
                evidence=message,
            )
        )
    if space.context:
        found.append(
            _check(
                "notion.workspace",
                OK,
                "Notion workspace",
                "“{{page}}”: {{count}} characters in every prompt.",
                params={"page": settings.page("context"), "count": str(len(space.context))},
                evidence=space.context.strip().splitlines()[0][:60],
            )
        )
    for key in ("projects", "agents", "schedules", "goals"):
        if resolved := getattr(space, key):
            found.append(
                _check(
                    "notion.workspace",
                    OK,
                    "Notion workspace",
                    "“{{page}}” is the database {{database}}.",
                    params={"page": settings.page(key), "database": resolved},
                )
            )
    return found


def _projects_database(client: store.Store, space: workspace_module.Workspace) -> Check:
    if not space.projects:
        return _check(
            "notion.projects",
            WARN,
            "Projects database",
            "No projects database was found.",
            cause="Without it no ticket is tied to a repository, so none can produce a pull request.",
            steps=["Create the Projects database under your Ponos page, or run `ponos init`."],
        )
    try:
        client.schema(space.projects)
    except store.StoreError as error:
        return _check(
            "notion.projects",
            ERROR,
            "Projects database",
            "The projects database cannot be read.",
            cause="The database is not shared with the integration.",
            steps=["Add the Ponos integration to the Projects page: ··· menu › Connections."],
            url=NOTION_INTEGRATIONS,
            evidence=_first_line(error),
        )
    return _check("notion.projects", OK, "Projects database", "Projects database found and shared.")


def _schema(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """The tickets board against what the runner works with: columns, then statuses."""
    settings = config.notion
    # Asked again, not remembered: the console outlives the column somebody just added.
    client.forget_database(space.tickets)
    schema = client.schema(space.tickets)
    missing: list[str] = []
    wrong: list[str] = []
    costs: dict[str, list[str]] = {}
    for key, (accepted, cost) in store.COLUMNS.items():
        name = settings.prop(key)
        kind = schema.get(name)
        if kind is None:
            # Two settings may name one property (`agent` and `role` both say "Agent"): said once.
            if name not in missing:
                missing.append(name)
            costs.setdefault(name, []).append(cost)
        elif kind not in accepted:
            wrong.append(f"“{name}” is a {kind}, not {' or '.join(accepted)}")
            costs.setdefault(name, []).append(cost)
    wanted_columns = provision.tickets_schema(settings, space.projects, space.agents)
    addable = sorted(provision.missing_properties(schema, wanted_columns))
    found: list[Check] = []
    if not missing and not wrong:
        found.append(
            _check(
                "notion.columns",
                OK,
                "Tickets properties",
                "Every property the runner uses is there.",
            )
        )
    else:
        said = (
            "Properties missing on the tickets database: {{missing}}."
            if missing
            else ("Properties of the wrong type on the tickets database: {{wrong}}.")
        )
        found.append(
            _check(
                "notion.columns",
                ERROR,
                "Tickets properties",
                said,
                params={
                    "missing": ", ".join(f"“{name}”" for name in missing),
                    "wrong": "; ".join(wrong),
                },
                cause="The board predates a version of Ponos, or a property was renamed or retyped.",
                steps=(
                    ["Rename the property in Notion, or its name under [notion.properties]."]
                    if wrong
                    else []
                ),
                notes=[{"name": name, "said": said} for name, said in costs.items()],
                # What `init` would add: a relation to a database that does not exist is not on the list.
                fix=_fix(
                    "notion_columns",
                    "Configure",
                    "Add {{missing}} to the tickets database? Existing properties are left as they are.",
                    addable,
                )
                if addable
                else None,
            )
        )

    found.extend(_shared_names(settings))

    options = client.options(space.tickets, settings.prop("status"))
    wanted = {key: settings.state(key) for key in RUNNER_STATUSES}
    absent = [name for name in wanted.values() if name not in options]
    if not options:
        found.append(
            _check(
                "notion.statuses",
                WARN,
                "Tickets statuses",
                "The Status property offers no options: nothing to check against.",
            )
        )
        return found
    if not absent:
        found.append(
            _check(
                "notion.statuses",
                OK,
                "Tickets statuses",
                "Every status the runner moves tickets through is offered.",
            )
        )
        return found
    database = getattr(client, "database", None)
    board = database(space.tickets) if database else {}
    is_select = ((board.get("properties") or {}).get(settings.prop("status")) or {}).get(
        "type"
    ) == "select"
    found.append(
        _check(
            "notion.statuses",
            ERROR,
            "Tickets statuses",
            "Statuses missing: {{missing}}.",
            params={"missing": ", ".join(f"“{name}”" for name in absent)},
            cause="The board was built by hand, or by an older Ponos.",
            steps=[]
            if is_select
            else [
                "Notion cannot add a status option from outside: add {{missing}} in the Status property, by hand.",
            ],
            evidence="available: " + ", ".join(options),
            fix=_fix(
                "notion_statuses",
                "Configure",
                "Add the statuses {{missing}} to the Status property? The existing ones are kept.",
                absent,
            )
            if is_select
            else None,
        )
    )
    return found


def _other_statuses(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """The statuses the runner never moves a ticket to: Cancelled, Paused, and a draft's.

    Cancelled and Paused are optional — a board without them has no way to give
    a ticket up but to call it done, nor to stop one for later — and the draft is
    named or not at all. Any one that is also a status the runner moves tickets
    through would be a ticket given up on, paused, or still being written, and
    run anyway.
    """
    settings = config.notion
    options = client.options(space.tickets, settings.prop("status"))
    if not options:
        return []
    moved = [settings.state(key) for key in RUNNER_STATUSES]
    found: list[Check] = []
    cancelled = settings.state("cancelled")
    params = {"status": cancelled}
    if cancelled in moved:
        found.append(
            _check(
                "notion.cancelled",
                ERROR,
                "Cancelled status",
                "“{{status}}” is also a status the runner moves tickets through.",
                params=params,
                steps=["Give [notion.status] cancelled a name of its own."],
            )
        )
    elif cancelled in options:
        found.append(
            _check(
                "notion.cancelled",
                OK,
                "Cancelled status",
                "“{{status}}”: a ticket there is never run.",
                params=params,
            )
        )
    else:
        found.append(
            _check(
                "notion.cancelled",
                WARN,
                "Cancelled status",
                "“{{status}}” is not offered: no column to give a ticket up in.",
                params=params,
                steps=[
                    "`ponos init` adds it to a select; on a Notion status, add the option by hand."
                ],
            )
        )
    # Optional too, and for the same reason: a board without it has no
    # gesture to stop a ticket for later, and the console offers none.
    paused = settings.state("paused")
    params = {"status": paused}
    if paused in moved:
        found.append(
            _check(
                "notion.paused",
                ERROR,
                "Paused status",
                "“{{status}}” is also a status the runner moves tickets through.",
                params=params,
                steps=["Give [notion.status] paused a name of its own."],
            )
        )
    elif paused in options:
        found.append(
            _check(
                "notion.paused",
                OK,
                "Paused status",
                "“{{status}}”: a ticket there is never run by itself.",
                params=params,
            )
        )
    else:
        found.append(
            _check(
                "notion.paused",
                WARN,
                "Paused status",
                "“{{status}}” is not offered: no column to pause a ticket in.",
                params=params,
                steps=[
                    "`ponos init` adds it to a select; on a Notion status, add the option by hand."
                ],
            )
        )
    # The one status the runner never writes nor reads, and that nothing
    # defaults: named, it has to be an option the board already offers, and
    # one apart from the runner's own — a draft that is `ready` is taken.
    draft = settings.state("draft")
    params = {"status": draft}
    if not draft:
        found.append(
            _check(
                "notion.draft",
                INFO,
                "Draft status",
                "None named: a ticket being written has no status.",
            )
        )
    elif draft in moved:
        found.append(
            _check(
                "notion.draft",
                ERROR,
                "Draft status",
                "“{{status}}” is also a status the runner moves tickets through.",
                params=params,
                steps=["Give [notion.status] draft a name of its own."],
            )
        )
    elif draft in options:
        found.append(
            _check(
                "notion.draft",
                OK,
                "Draft status",
                "“{{status}}”: a ticket there is never picked up.",
                params=params,
            )
        )
    else:
        found.append(
            _check(
                "notion.draft",
                ERROR,
                "Draft status",
                "“{{status}}” is not offered by the tickets database.",
                params=params,
                steps=["Add the option to the Status property, or name another one."],
                evidence="available: " + ", ".join(options),
            )
        )
    return found


def _types(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """The kinds of work offered on the Type property, and who fills an empty one."""
    settings = config.notion
    column = settings.prop("type")
    if column not in client.schema(space.tickets):
        return []
    offered = client.options(space.tickets, column)
    absent = []
    for key in ("code", "writing", "external", "publication"):
        names = settings.kind_names(key)
        if not any(name in offered for name in names):
            absent.append(names[0])
    found: list[Check] = []
    if absent:
        # Not a problem: Notion adds a select option the first time a value is
        # written into it. Said so it is not a surprise.
        found.append(
            _check(
                "notion.types",
                WARN,
                "Types",
                "Types not offered yet: {{missing}}. Each is added the first time it is written.",
                params={"missing": ", ".join(f"“{name}”" for name in absent)},
            )
        )
    else:
        found.append(_check("notion.types", OK, "Types", "Every type is offered."))
    runner = config.runner
    if runner.classify:
        found.append(
            _check(
                "settings.classify",
                OK,
                "Classification",
                "An empty {{column}} is classified by {{model}}, acted on from {{confidence}} confidence.",
                params={
                    "column": column,
                    "model": runner.classify_model or "the CLI's default model",
                    "confidence": str(runner.classify_confidence),
                },
            )
        )
    else:
        found.append(
            _check(
                "settings.classify",
                WARN,
                "Classification",
                "runner.classify is off: a ticket with no {{column}} runs by its project.",
                params={"column": column},
            )
        )
    return found


def _schedules(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """The Schedules database, and what would keep a ticket from being born.

    Optional throughout: an installation without the database is an installation
    where nothing repeats, which is a fine way to run and worth one grey line
    rather than a warning.
    """
    database = space.schedules
    if not database:
        return [
            _check(
                "notion.schedules",
                INFO,
                "Schedules",
                "No schedules database: nothing repeats here. `ponos init <page-url>` adds it.",
            )
        ]
    found: list[Check] = []
    if not config.runner.schedule:
        found.append(
            _check(
                "notion.schedules",
                WARN,
                "Schedules",
                "runner.schedule = false: the schedules database is read by nobody.",
            )
        )
    settings = config.notion
    try:
        schema = client.schema(database)
    except store.StoreError as error:
        found.append(
            _check(
                "notion.schedules",
                WARN,
                "Schedules",
                "The schedules database cannot be read.",
                evidence=_first_line(error),
            )
        )
        return found
    missing: list[dict[str, Any]] = []
    for key, preferred, why in SCHEDULE_COLUMNS:
        name = settings.prop(key)
        kind = schema.get(name)
        if kind is None:
            missing.append({"name": name, "said": [why]})
        elif kind != preferred:
            found.append(
                _check(
                    "notion.schedules",
                    INFO,
                    "Schedules",
                    "“{{name}}” is a {{kind}}: a {{preferred}} would be better.",
                    params={"name": name, "kind": kind, "preferred": preferred},
                    notes=[{"name": name, "said": [why]}],
                )
            )
    if missing:
        found.append(
            _check(
                "notion.schedules",
                WARN,
                "Schedules",
                "Properties missing on the schedules database: {{missing}}.",
                params={"missing": ", ".join(f"“{note['name']}”" for note in missing)},
                notes=missing,
            )
        )
    else:
        found.append(
            _check(
                "notion.schedules",
                OK,
                "Schedules",
                "Schedules database readable: {{count}} properties.",
                params={"count": str(len(schema))},
            )
        )

    try:
        rows = [schedules_module.read(page, settings) for page in client.query(database)]
    except store.StoreError as error:
        found.append(
            _check(
                "notion.schedules",
                WARN,
                "Schedules",
                "The schedules could not be read.",
                evidence=_first_line(error),
            )
        )
        return found
    if not rows:
        found.append(_check("notion.schedules", INFO, "Schedules", "No schedule written yet."))
        return found
    now = datetime.now().astimezone()
    for schedule in rows:
        params = {"schedule": schedule.name}
        title = "Schedule “{{schedule}}”"
        if schedule.problem:
            found.append(
                _check(
                    "notion.schedule",
                    ERROR,
                    title,
                    "This schedule cannot make a ticket.",
                    params=params,
                    evidence=schedule.problem,
                )
            )
        elif not schedule.active:
            found.append(_check("notion.schedule", INFO, title, "Unticked.", params=params))
        # A `Next` a day behind is not a schedule running late: it is a runner
        # that has stopped, and this is the only place that would say so.
        elif schedule.next and (now - schedule.next).total_seconds() > 86400:
            found.append(
                _check(
                    "notion.schedule",
                    ERROR,
                    title,
                    "Due since {{since}} and never born: the runner is not passing.",
                    params={**params, "since": schedule.next.strftime("%Y-%m-%d %H:%M")},
                    steps=["Check that the runner runs: `ponos status`."],
                )
            )
        elif schedule.next:
            found.append(
                _check(
                    "notion.schedule",
                    OK,
                    title,
                    "{{cadence}}, next on {{when}}.",
                    params={
                        **params,
                        "cadence": schedule.cadence,
                        "when": schedule.next.strftime("%Y-%m-%d %H:%M"),
                    },
                )
            )
        else:
            found.append(
                _check(
                    "notion.schedule",
                    OK,
                    title,
                    "{{cadence}}, next on the next pass.",
                    params={**params, "cadence": schedule.cadence},
                )
            )
    return found


def _comments(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """Whether a discussion can be read, and what the runner does with one.

    The one capability that is off by default, and the one whose absence is
    silent: a ticket runs perfectly well while its discussion is invisible.
    """
    found: list[Check] = []
    sample = client.query(space.tickets)[:1]
    if not sample:
        found.append(
            _check(
                "notion.comments",
                INFO,
                "Comments",
                "No ticket yet: nothing to read a discussion on.",
            )
        )
    else:
        try:
            client.comments(sample[0].id)
            found.append(
                _check(
                    "notion.comments",
                    OK,
                    "Comments",
                    "Comments are readable: answers wake a ticket, and can be answered back.",
                )
            )
        except store.StoreError as error:
            if "403" in str(error):
                found.append(
                    _check(
                        "notion.comments",
                        ERROR,
                        "Comments",
                        "Comments cannot be read: an answer in a comment reaches nothing.",
                        cause="The integration was created without the comment capabilities.",
                        steps=[
                            "Open your integration on Notion › Capabilities, and tick Read comments (and Insert comments)."
                        ],
                        url=NOTION_INTEGRATIONS,
                        evidence=_first_line(error),
                    )
                )
            else:
                found.append(
                    _check(
                        "notion.comments",
                        WARN,
                        "Comments",
                        "Comments could not be read this time.",
                        evidence=_first_line(error),
                    )
                )
    runner = config.runner
    if runner.reply:
        found.append(
            _check(
                "settings.reply",
                OK,
                "Replies",
                "It answers when you write to it: {{names}}.",
                params={
                    "names": ", ".join(conversation.names(config.notion.mention, client.my_name()))
                },
            )
        )
        found.append(
            _check(
                "settings.reply",
                INFO,
                "Replies",
                "Every {{every}}s, {{scan}} pages a pass, permission_mode = {{mode}}.",
                params={
                    "every": str(runner.reply_interval_seconds),
                    "scan": str(runner.reply_scan),
                    "mode": runner.reply_permission_mode,
                },
            )
        )
    else:
        found.append(
            _check(
                "settings.reply",
                INFO,
                "Replies",
                "runner.reply = false: a comment can wake a ticket, not start a talk.",
            )
        )
    if runner.unblock:
        found.append(
            _check(
                "settings.unblock",
                OK,
                "Unblocking",
                "Blocked tickets are looked at again: the ones whose cause is gone go back to ready.",
            )
        )
        found.append(
            _check(
                "settings.unblock",
                INFO,
                "Unblocking",
                "Each ticket every {{every}}s, permission_mode = {{mode}}.",
                params={
                    "every": str(runner.unblock_interval_seconds),
                    "mode": runner.reply_permission_mode,
                },
            )
        )
    else:
        found.append(
            _check(
                "settings.unblock",
                INFO,
                "Unblocking",
                "runner.unblock = false: a blocked ticket stays blocked until you move it.",
            )
        )
    return found


def _shared_names(settings: config_module.Notion) -> list[Check]:
    """Two settings that name one property of the tickets database, if any.

    Not an error Notion would ever raise: the column is there, it is read — as
    whatever the other setting expects. `agent = "Agent"` next to the default
    `role` reads a text as a relation, and asks Notion for a page named after
    its first character on every ticket taken back.
    """
    keys: dict[str, list[str]] = {}
    for key in (*store.COLUMNS, "goal"):
        keys.setdefault(settings.prop(key), []).append(key)
    shared = {name: names for name, names in keys.items() if len(names) > 1}
    if not shared:
        return []
    return [
        _check(
            "notion.shared",
            WARN,
            "Tickets properties",
            "Several settings name the same property: {{shared}}.",
            params={
                "shared": "; ".join(
                    f"“{name}” ({', '.join(names)})" for name, names in shared.items()
                )
            },
            cause="Each setting reads the property as something else, so at most one of them is right.",
            steps=["Give each one its own name under [notion.properties]."],
        )
    ]


def _fix(
    action: str, label: str, confirm: str, names: list[str], target: str = ""
) -> dict[str, str]:
    return {
        "action": action,
        "label": label,
        "confirm": confirm,
        "missing": ", ".join(f"“{name}”" for name in names),
        "target": target,
    }


def _project_rows(
    client: store.Store, space: workspace_module.Workspace | None
) -> list[dict[str, str]]:
    """The projects that have a repository or a path, as the board declares them."""
    if space is None or not space.projects:
        return []
    rows = []
    try:
        for page in client.query(space.projects):
            repository = str(
                projects._property(page, "Repository", "repository", "github", "repo") or ""
            )
            path = str(projects._property(page, "Path", "path") or "")
            if repository or path:
                rows.append(
                    {
                        "id": page.id.replace("-", ""),
                        "name": page.title or "(untitled project)",
                        "repository": repository,
                        "path": path,
                    }
                )
    except store.StoreError:
        pass
    return rows


# -- Claude Code ---------------------------------------------------------------


def _claude(config: config_module.Config) -> list[Check]:
    binary = session.available()
    found: list[Check] = []
    if not binary:
        found.append(
            _check(
                "claude.installed",
                ERROR,
                "Claude Code",
                "Claude Code is not installed on this machine.",
                cause="`claude` is not on the PATH of the runner.",
                url=CLAUDE_INSTALL,
                **_installing(
                    "claude", "Install Claude Code, then check that `claude --version` answers."
                ),
            )
        )
    else:
        found.append(_claude_version(binary))
    found.extend(_provider(config, installed=bool(binary)))
    return found


def _claude_version(binary: str) -> Check:
    try:
        printed = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=PROBE_TIMEOUT
        ).stdout
    except (OSError, subprocess.SubprocessError):
        printed = ""
    version = re.search(r"\d+(?:\.\d+){1,2}", printed)
    if not version:
        return _check(
            "claude.version",
            WARN,
            "Claude Code version",
            "The version of Claude Code could not be read.",
            evidence=printed.strip(),
        )
    numbers = tuple(int(part) for part in version.group(0).split("."))
    numbers += (0,) * (3 - len(numbers))
    needed = ".".join(str(part) for part in MINIMUM_CLAUDE)
    if numbers < MINIMUM_CLAUDE:
        return _check(
            "claude.version",
            ERROR,
            "Claude Code version",
            "Claude Code {{version}} is older than {{needed}}.",
            params={"version": version.group(0), "needed": needed},
            cause="The runner passes flags that older versions do not know.",
            steps=["Update Claude Code: run `claude update`."],
            url=CLAUDE_INSTALL,
        )
    return _check(
        "claude.version",
        OK,
        "Claude Code version",
        "Claude Code {{version}} is installed at {{path}}.",
        params={"version": version.group(0), "path": binary},
    )


def _provider(config: config_module.Config, *, installed: bool) -> list[Check]:
    """Which account the sessions run on, and whether it would answer — see provider.py.

    No key leaves this machine here: the CLI's sign-in is asked of the CLI, and
    a key is said to be there or not. Whether Anthropic or OpenRouter accept it
    is the first connection's question, asked while somebody is there to fix it.
    """
    which = provider.chosen(config)
    name, detail = provider.describe(config)
    stated = config.claude.provider
    found = [
        _check(
            "claude.provider",
            OK,
            "Claude provider",
            "{{name}}: {{detail}} ({{origin}}).",
            params={
                "name": name,
                "detail": detail,
                "origin": f'claude.provider = "{stated}"' if stated else "claude.provider not set",
            },
        )
    ]
    if reason := provider.problem(config):
        found.append(
            _check(
                "claude.login",
                ERROR,
                "Claude connection",
                "Sessions have no way to answer: {{reason}}.",
                params={"reason": reason},
                cause="The provider the settings name is missing its key.",
                steps=["Choose a provider and give its key in Settings › Claude."],
            )
        )
    elif which == "cli":
        if not installed:
            return found
        login = provider.cli_login()
        if login.ok:
            found.append(
                _check(
                    "claude.login",
                    OK,
                    "Claude connection",
                    "Signed in: {{who}}.",
                    params={"who": login.said},
                )
            )
        else:
            found.append(
                _check(
                    "claude.login",
                    ERROR,
                    "Claude connection",
                    "Claude Code is not signed in.",
                    cause="No account was connected to the CLI on this machine.",
                    steps=[
                        "In a terminal on this machine, run `claude auth login` and follow the link."
                    ],
                    evidence=login.said,
                )
            )
    else:
        found.append(
            _check(
                "claude.login",
                OK,
                "Claude connection",
                "Sessions are answered by {{name}}: no Claude in Chrome, nothing to wait for, billed as it is used.",
                params={"name": provider.NAMES[which]},
            )
        )
        if which == "openrouter" and not config.openrouter.route_sessions:
            found.append(
                _check(
                    "claude.login",
                    WARN,
                    "Claude connection",
                    "openrouter.route_sessions = false: the sessions still run on the CLI's sign-in.",
                )
            )
    return found


def _models(config: config_module.Config) -> list[Check]:
    """Which model a ticket runs on when it names none, and who finds the ideas."""
    runner = config.runner
    routed = bool(config.openrouter.key and config.openrouter.route_sessions)
    found: list[Check] = []
    if runner.auto_model:
        grid = runner.model_grid()
        found.append(
            _check(
                "claude.model",
                OK,
                "Models",
                "An empty Model is chosen by the rules: {{levels}}.",
                params={
                    "levels": ", ".join(
                        f"{level} {grid.model(level) or '—'}" for level in models.LEVELS
                    )
                },
            )
        )
        if not runner.auto_model_escalate:
            found.append(
                _check(
                    "claude.model",
                    INFO,
                    "Models",
                    "runner.auto_model_escalate = false: a failed run comes back on the same model.",
                )
            )
        if routed and any(grid.model(level) in CLAUDE_MODELS for level in models.LEVELS):
            found.append(
                _check(
                    "claude.model",
                    WARN,
                    "Models",
                    "Sessions go through OpenRouter: name its slugs in runner.auto_model_*.",
                )
            )
    else:
        found.append(
            _check(
                "claude.model",
                INFO,
                "Models",
                "runner.auto_model = false: an empty Model runs on {{model}}.",
                params={"model": runner.model or "the CLI's default model"},
            )
        )
    found.append(
        _check(
            "claude.ideas",
            OK,
            "Ideas model",
            "Ideas are found by {{model}}, ten at a batch (runner.ideas_model).",
            params={"model": runner.ideas_model or "the CLI's default model"},
        )
    )
    if routed and runner.ideas_model in CLAUDE_MODELS:
        found.append(
            _check(
                "claude.ideas",
                WARN,
                "Ideas model",
                "Sessions go through OpenRouter: name its slug in runner.ideas_model.",
            )
        )
    # Off, Fable never runs, whatever a level or a ticket says.
    if runner.use_fable:
        found.append(
            _check(
                "claude.fable",
                OK,
                "Claude Fable",
                "Claude Fable is allowed (runner.use_fable = true).",
            )
        )
    else:
        found.append(
            _check(
                "claude.fable",
                INFO,
                "Claude Fable",
                "runner.use_fable = false: Claude Fable is not allowed, {{instead}} runs in its place.",
                params={"instead": models.INSTEAD_OF_FABLE},
            )
        )
    return found


# -- GitHub --------------------------------------------------------------------

_WRITING = {"WRITE", "MAINTAIN", "ADMIN"}


def _github_access(config: config_module.Config) -> list[Check]:
    """The apps connected from the console, then `gh`, then the accounts `[github]` names."""
    found: list[Check] = []
    connected = github_app.describe(with_repositories=False)
    for app in connected:
        params = {"slug": app["slug"]}
        if app["error"]:
            found.append(
                _check(
                    "github.access",
                    ERROR,
                    "GitHub access",
                    "The GitHub App {{slug}} gets no answer from GitHub.",
                    params=params,
                    evidence=app["error"],
                    cause="The App was deleted on GitHub, or its key no longer matches.",
                    steps=["Connect the App again from Settings › GitHub."],
                )
            )
            continue
        if not app["installations"]:
            found.append(
                _check(
                    "github.access",
                    ERROR,
                    "GitHub access",
                    "The GitHub App {{slug}} is installed nowhere.",
                    params=params,
                    cause="The App exists, but no account or organisation gave it a repository.",
                    steps=["Install the GitHub App on your account, and choose the repositories."],
                    url=app["install_url"],
                )
            )
            continue
        for installation in app["installations"]:
            reached = {**params, "account": installation["account"]}
            if not github_app.token(installation["account"]):
                found.append(
                    _check(
                        "github.access",
                        ERROR,
                        "GitHub access",
                        "GitHub gives the App {{slug}} no token on {{account}}.",
                        params=reached,
                        cause="The installation was suspended or removed on GitHub.",
                        steps=["Install the GitHub App on this account again."],
                        url=app["install_url"],
                    )
                )
            else:
                found.append(
                    _check(
                        "github.access",
                        OK,
                        "GitHub access",
                        "GitHub App {{slug}} on {{account}}: token obtained, every repository."
                        if installation["selection"] == "all"
                        else "GitHub App {{slug}} on {{account}}: token obtained, the repositories chosen.",
                        params=reached,
                    )
                )
    found.extend(_gh(config, apps=bool(connected)))
    return found


def _gh(config: config_module.Config, *, apps: bool) -> list[Check]:
    """`gh`: what opens pull requests without an App, and the fallback beside one.

    Without an App it is the only way, and missing or signed out is an error;
    beside one, only a repository the App does not reach needs it.
    """
    if not shutil.which("gh"):
        if apps:
            return [
                _check(
                    "github.access",
                    WARN,
                    "GitHub access",
                    "`gh` is not installed: a repository the GitHub App does not reach gets no pull request.",
                    url="https://cli.github.com",
                    **_installing("gh"),
                )
            ]
        return [
            _check(
                "github.access",
                ERROR,
                "GitHub access",
                "No GitHub App is connected and `gh` is not installed.",
                cause="Pull requests are opened with a GitHub App or with the `gh` command.",
                url="https://cli.github.com",
                **_installing(
                    "gh",
                    "Connect a GitHub App from Settings › GitHub, or install `gh` and run `gh auth login`.",
                ),
            )
        ]
    found: list[Check] = []
    answered = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, timeout=PROBE_TIMEOUT
    )
    if answered.returncode == 0:
        found.append(_check("github.access", OK, "GitHub access", "`gh` is signed in."))
    else:
        found.append(
            _check(
                "github.access",
                WARN if apps else ERROR,
                "GitHub access",
                "`gh` is not signed in.",
                cause="Without a token Ponos can neither push nor open a pull request.",
                steps=["In a terminal on this machine, run `gh auth login`."],
                evidence=_first_line(answered.stderr or answered.stdout),
            )
        )
    # The one place where a `[github]` line that names an account nobody
    # logged in is worth saying out loud: everywhere else it falls back on
    # the active account, which is deliberate — a ticket does not fail over
    # a line of configuration — and silent by the same token.
    for owner, account in sorted(config.github.items()):
        params = {"owner": owner, "account": account}
        if git.account_token(account):
            found.append(
                _check(
                    "github.account",
                    OK,
                    "GitHub account for {{owner}}",
                    "{{owner}}/* is worked as {{account}}.",
                    params=params,
                )
            )
        else:
            found.append(
                _check(
                    "github.account",
                    ERROR,
                    "GitHub account for {{owner}}",
                    "`gh` is not signed in as {{account}}, the account [github] names for {{owner}}/*.",
                    params=params,
                    steps=["In a terminal on this machine, run `gh auth login` as {{account}}."],
                )
            )
    return found


def _github_token() -> list[Check]:
    """The personal access token, if one is given: who it is, and what it lacks."""
    if why := github_token.unavailable():
        return [
            _check(
                "github.token",
                ERROR,
                "GitHub token",
                "The token [github_access] token_item names cannot be read.",
                evidence=why,
            )
        ]
    held = github_token.token()
    if not held:
        return [
            _check(
                "github.token",
                INFO,
                "GitHub token",
                "No personal token (Settings › GitHub, or PONOS_GITHUB_TOKEN).",
            )
        ]
    params = {"source": github_token.source()}
    try:
        checked = github_token.check(held)
    except github_token.GithubTokenError as error:
        return [
            _check(
                "github.token",
                ERROR,
                "GitHub token",
                "The token from {{source}} is refused.",
                params=params,
                evidence=str(error),
            )
        ]
    params["login"] = checked["login"]
    found: list[Check] = []
    if checked["missing"]:
        found.append(
            _check(
                "github.token",
                ERROR,
                "GitHub token",
                "The token of {{login}} from {{source}} lacks {{needs}}.",
                params={
                    **params,
                    "needs": ", ".join(
                        f"{one['permission']} ({one['level']})" for one in checked["missing"]
                    ),
                },
                steps=["Give the token these permissions on GitHub, or make a new one."],
            )
        )
    else:
        found.append(
            _check(
                "github.token",
                OK,
                "GitHub token",
                "The token of {{login}} from {{source}}: {{kind}}, {{count}} repositories, {{writable}} writable.",
                params={
                    **params,
                    "kind": checked["kind"],
                    "count": str(len(checked["repositories"])),
                    "writable": str(len(checked["writable"])),
                },
            )
        )
    for warning in checked["warnings"]:
        found.append(
            _check(
                "github.token",
                WARN,
                "GitHub token",
                "The token of {{login}} lacks what some tickets need.",
                params=params,
                evidence=warning,
            )
        )
    return found


def _repository(remote: str) -> tuple[str, str]:
    """(owner/name, owner) of a remote, or empty when it is not a GitHub one."""
    parts = git.reference_parts(remote)
    if len(parts) < 3 or "github.com" not in remote:
        return "", ""
    return "/".join(parts[1:3]), git.owner(remote)


def _github_rights(config: config_module.Config, name: str, owner: str) -> Check:
    """May the runner read, push and open a pull request on that repository?"""
    title = "GitHub rights on {{repository}}"
    params = {"repository": name}
    if github_app.apps():
        reached = github_app.covers(name, owner)
        if reached is False:
            app = github_app.apps()[0]
            return _check(
                "github.repository",
                ERROR,
                title,
                "The GitHub App does not reach {{repository}}.",
                params=params,
                cause="The App is installed without this repository, or on another account.",
                steps=[
                    "Install the GitHub App on this repository: choose it in the installation's list."
                ],
                url=app.install_url,
            )
        if reached:
            granted = (github_app.installation_for(owner) or (None, {}))[1].get("permissions") or {}
            weak = [
                name
                for name in ("contents", "pull_requests")
                if granted and granted.get(name) != "write"
            ]
            if weak:
                return _check(
                    "github.repository",
                    ERROR,
                    title,
                    "The GitHub App cannot write {{rights}} on {{repository}}.",
                    params={**params, "rights": " or ".join(weak)},
                    cause="The App was created with read-only permissions, or the installation was not accepted again.",
                    steps=["Open the App's installation on GitHub and accept its new permissions."],
                    url=github_app.apps()[0].install_url,
                )
            return _check(
                "github.repository",
                OK,
                title,
                "The GitHub App reaches {{repository}}.",
                params=params,
            )
    token = git.token_for(name, config.github)
    answered = (
        git.run(
            [
                "gh",
                "repo",
                "view",
                "--json",
                "viewerPermission",
                "--jq",
                ".viewerPermission",
                "--",
                name,
            ],
            timeout=PROBE_TIMEOUT,
            token=token,
        )
        if shutil.which("gh")
        else None
    )
    if answered is None:
        return _check(
            "github.repository",
            WARN,
            title,
            "{{repository}} cannot be checked without `gh`.",
            params=params,
        )
    if not answered.ok:
        return _check(
            "github.repository",
            ERROR,
            title,
            "{{repository}} cannot be reached with this GitHub account.",
            params=params,
            evidence=_first_line(answered.err or answered.out),
            cause="The repository does not exist, or the account has no access to it.",
            steps=[
                "Check the Repository property of the project, and that the account can open it on GitHub."
            ],
        )
    permission = answered.out.strip()
    if permission in _WRITING:
        return _check(
            "github.repository",
            OK,
            title,
            "Push and pull requests allowed on {{repository}}.",
            params=params,
        )
    return _check(
        "github.repository",
        ERROR,
        title,
        "The account can only {{permission}} {{repository}}.",
        params={**params, "permission": "read" if permission == "READ" else permission.lower()},
        cause="Pushing a branch and opening a pull request need write access.",
        steps=["Ask for write access on this repository, or connect an account that has it."],
        url=f"https://github.com/{name}",
    )


# -- Projects ------------------------------------------------------------------


def _project(config: config_module.Config, row: dict[str, str]) -> list[Check]:
    name = row["name"]
    params = {"project": name}
    resolver = projects.Resolver(config.runner.workspace_root, config.projects, config.github)
    path = resolver.locate(name, row["path"], row["repository"])
    found: list[Check] = []
    if path is None:
        if row["repository"]:
            found.append(
                _check(
                    "projects.path",
                    WARN,
                    "Local copy of {{project}}",
                    "No local copy of {{project}} yet: it is cloned when its first ticket starts.",
                    params=params,
                )
            )
            return found
        found.append(
            _check(
                "projects.path",
                ERROR,
                "Local copy of {{project}}",
                "The path of {{project}} is not a git repository: {{path}}.",
                params={**params, "path": row["path"]},
                cause="The folder was moved or deleted, or the Path property is mistyped.",
                steps=[
                    "Correct the Path property of the project, or give its Repository so it can be cloned."
                ],
            )
        )
        return found
    found.append(
        _check(
            "projects.path",
            OK,
            "Local copy of {{project}}",
            "{{project}} is in {{path}}.",
            params={**params, "path": str(path)},
        )
    )

    remote = git.remote_url(path)
    if not remote:
        found.append(
            _check(
                "projects.remote",
                ERROR,
                "Remote of {{project}}",
                "{{project}} has no origin remote.",
                params=params,
                cause="Without it nothing can be pushed and no pull request opened.",
                steps=["In the repository, run `git remote add origin <url>`."],
            )
        )
        return found
    probe = git.run(
        ["git", "ls-remote", "--exit-code", "origin", "HEAD"], path, timeout=PROBE_TIMEOUT
    )
    if probe.ok:
        found.append(
            _check(
                "projects.remote",
                OK,
                "Remote of {{project}}",
                "The remote of {{project}} answers.",
                params=params,
            )
        )
    else:
        found.append(
            _check(
                "projects.remote",
                ERROR,
                "Remote of {{project}}",
                "The remote of {{project}} cannot be reached.",
                params=params,
                evidence=_first_line(probe.err or probe.out),
                cause="No network, a repository that moved, or credentials git does not have.",
                steps=["In the repository, run `git ls-remote origin` and fix what it prints."],
            )
        )
    if git.git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], path).ok:
        found.append(
            _check(
                "projects.branch",
                OK,
                "Default branch of {{project}}",
                "{{project}} starts from {{branch}}.",
                params={**params, "branch": git.default_branch(path)},
            )
        )
    else:
        found.append(
            _check(
                "projects.branch",
                WARN,
                "Default branch of {{project}}",
                "The default branch of {{project}} is not known: {{branch}} is assumed.",
                params={**params, "branch": git.default_branch(path)},
                cause="The clone never recorded which branch the origin treats as its default.",
                steps=["In the repository, run `git remote set-head origin --auto`."],
                fix=_fix(
                    "project_branch",
                    "Configure",
                    "Ask the origin of {{project}} for its default branch (git remote set-head origin --auto)?",
                    [name],
                    target=row["id"],
                )
                if probe.ok
                else None,
            )
        )
    owner_repo, owner = _repository(remote)
    if owner_repo and probe.ok:
        found.append(_github_rights(config, owner_repo, owner))
    return found


def _workspace_root(config: config_module.Config) -> list[Check]:
    """The folder the repositories are looked for in, and each repository found there.

    Every one of them, on the board or not: a base whose CI never runs at push
    breaks silently, and the first pull request to find it red is the one that
    pays. A repository the GitHub App does not reach falls back on `gh`, which a
    machine connected through the App may well not have signed in.
    """
    root = config.runner.workspace_root
    params = {"root": str(root)}
    if not root.is_dir():
        return [
            _check(
                "projects.workspace",
                ERROR,
                "Workspace folder",
                "{{root}} does not exist (runner.workspace_root).",
                params=params,
                steps=[
                    "Create it: `mkdir -p {{root}}`, or pick another folder in the console's first connection."
                ],
            )
        ]
    resolver = projects.Resolver(root, config.projects, config.github)
    index = resolver._index()  # noqa: SLF001 — diagnostics
    found = [
        _check(
            "projects.workspace",
            OK,
            "Workspace folder",
            "{{root}}: {{count}} repositories found.",
            params={**params, "count": str(sum(len(repos) for repos in index.values()))},
        )
    ]
    repositories = sorted({path for repos in index.values() for path in repos})
    with ThreadPoolExecutor(max_workers=8) as pool:
        for checks in pool.map(lambda repo: _local_repository(config, repo), repositories):
            found.extend(checks)
    return found


def _local_repository(config: config_module.Config, repo: Path) -> list[Check]:
    found: list[Check] = []
    params = {"repository": repo.name}
    base, ran = _ci_at_push(repo, config.github)
    if ran in ("none", "skipped"):
        found.append(
            _check(
                "projects.ci",
                WARN,
                "CI of {{repository}}",
                "{{base}} has no CI run at push: a red base would go unseen."
                if ran == "none"
                else "{{base}} has only skipped CI runs at push: a red base would go unseen.",
                params={**params, "base": base},
            )
        )
    remote = git.remote_url(repo)
    name = "/".join(git.reference_parts(remote)[1:3]) if "." in remote else ""
    if name and github_app.covers(name, git.owner(remote)) is False:
        found.append(
            _check(
                "github.reach",
                WARN,
                "GitHub App on {{repository}}",
                "{{repository}} is not reached by the GitHub App.",
                params={"repository": name},
                steps=["Add the repository to the App's installation on GitHub."],
            )
        )
    return found


def _ci_at_push(repo: Path, accounts: git.Accounts | None = None) -> tuple[str, str]:
    """The base of that repository, and what its CI does at push — see `git.ci_at_push`."""
    base = git.default_branch(repo)
    return base, git.ci_at_push(repo, base, accounts)


def base_without_ci(repo: Path, accounts: git.Accounts | None = None) -> str:
    """Why the base of that repository goes unwatched, or nothing when it is.

    Said for a base with no push run at all and for one whose runs are all
    skipped; a repository GitHub cannot be asked about says nothing.
    """
    base, found = _ci_at_push(repo, accounts)
    if found == "none":
        return f"{base} has no CI run at push — a red base would go unseen"
    if found == "skipped":
        return f"{base} has only skipped CI runs at push — a red base would go unseen"
    return ""


# -- Machine -------------------------------------------------------------------


def _machine(config: config_module.Config) -> list[Check]:
    return [*_tools(), *_disk(config), *_memory(config), *_runner(config)]


def _tools() -> list[Check]:
    """git, without which nothing runs, and ffmpeg, without which a video is not looked at."""
    found: list[Check] = []
    if shutil.which("git"):
        found.append(
            _check(
                "machine.git",
                OK,
                "git",
                "{{version}}.",
                params={"version": (git.run(["git", "--version"]).out.splitlines() or [""])[0]},
            )
        )
    else:
        found.append(
            _check(
                "machine.git",
                ERROR,
                "git",
                "git is not installed.",
                cause="Every ticket works in a git worktree.",
                **_installing("git"),
            )
        )
    if shutil.which("ffmpeg"):
        found.append(
            _check(
                "machine.ffmpeg",
                OK,
                "ffmpeg",
                "A video sent to the workspace is looked at through its frames.",
            )
        )
    else:
        found.append(
            _check(
                "machine.ffmpeg",
                WARN,
                "ffmpeg",
                "ffmpeg is missing: a video sent to the workspace cannot be looked at.",
                **_installing("ffmpeg"),
            )
        )
    return found


def _disk(config: config_module.Config) -> list[Check]:
    found: list[Check] = []
    runner = config.runner
    state = config_module.state_dir()
    found.append(
        _check(
            "machine.disk",
            INFO,
            "Disk space",
            "{{state}} holds {{sizes}}.",
            params={
                "state": str(state),
                "sizes": ", ".join(
                    f"{place} {cleanup.human(size)}" for place, size in cleanup.sizes().items()
                ),
            },
        )
    )
    days = {"days": str(runner.log_retention_days)}
    if runner.log_retention_days <= 0:
        found.append(
            _check(
                "machine.tidy",
                WARN,
                "Tidying",
                "runner.log_retention_days = 0: nothing is ever tidied on its own.",
            )
        )
    elif runner.clean_done_worktrees:
        found.append(
            _check(
                "machine.tidy",
                OK,
                "Tidying",
                "Tidied once a day: logs, and the worktrees of tickets done, older than {{days}} days.",
                params=days,
            )
        )
    else:
        found.append(
            _check(
                "machine.tidy",
                OK,
                "Tidying",
                "Logs older than {{days}} days are dropped once a day.",
                params=days,
            )
        )
        found.append(
            _check(
                "machine.tidy",
                INFO,
                "Tidying",
                "runner.clean_done_worktrees = false: worktrees stay until `ponos clean --force`.",
            )
        )
    room = resources.disk_mb(state)
    minimum = runner.min_free_disk_mb
    if room is None:
        found.append(
            _check(
                "machine.disk",
                WARN,
                "Disk space",
                "The free disk space cannot be read here: the disk guard cannot tell.",
            )
        )
    elif minimum <= 0:
        found.append(
            _check(
                "machine.disk",
                INFO,
                "Disk space",
                "runner.min_free_disk_mb = 0: no disk guard; {{free}} MB free.",
                params={"free": str(room[0])},
            )
        )
    elif room[0] < minimum:
        found.append(
            _check(
                "machine.disk",
                ERROR,
                "Disk space",
                "{{free}} MB free, under the {{minimum}} MB a ticket needs to start.",
                params={"free": str(room[0]), "minimum": str(minimum)},
                cause="Worktrees and logs of past tickets fill the disk; no ticket is started until it has room.",
                steps=[
                    "Free some room: Settings › Disk tidies the logs and the finished worktrees."
                ],
            )
        )
    else:
        found.append(
            _check(
                "machine.disk",
                OK,
                "Disk space",
                "{{free}} MB free (a ticket starts above {{minimum}} MB).",
                params={"free": str(room[0]), "minimum": str(minimum)},
            )
        )
    leftover = git.residues(state / "worktrees")
    if leftover:
        found.append(
            _check(
                "machine.residue",
                WARN,
                "Worktrees",
                "{{count}} worktree directories are only residue (no .git: files a container created).",
                params={"count": str(len(leftover))},
                steps=["Run `ponos clean --force` to empty them."],
            )
        )
    else:
        found.append(
            _check("machine.residue", OK, "Worktrees", "No residue in the worktrees directory.")
        )
    if last := cleanup.tidied_at():
        found.append(
            _check(
                "machine.tidy",
                INFO,
                "Tidying",
                "Last tidied {{at}}.",
                params={"at": f"{datetime.fromtimestamp(last):%Y-%m-%d %H:%M}"},
            )
        )
    return found


def _memory(config: config_module.Config) -> list[Check]:
    free, minimum = resources.available_mb(), config.runner.min_free_memory_mb
    params = {"free": str(free), "minimum": str(minimum)}
    if free is None:
        return [
            _check(
                "machine.memory",
                INFO,
                "Memory",
                "/proc/meminfo is unreadable here: the memory guard cannot tell.",
            )
        ]
    if minimum <= 0:
        return [
            _check(
                "machine.memory",
                INFO,
                "Memory",
                "runner.min_free_memory_mb = 0: no memory guard; {{free}} MB available.",
                params=params,
            )
        ]
    if free < minimum:
        return [
            _check(
                "machine.memory",
                WARN,
                "Memory",
                "{{free}} MB available, under runner.min_free_memory_mb ({{minimum}} MB): no session is started until it is back.",
                params=params,
            )
        ]
    return [
        _check(
            "machine.memory",
            OK,
            "Memory",
            "{{free}} MB available (a session starts above {{minimum}} MB).",
            params=params,
        )
    ]


def _runner(config: config_module.Config) -> list[Check]:
    """What starts a run, how often, and how a session is let loose."""
    runner = config.runner
    every = {"interval": str(runner.interval_seconds)}
    found: list[Check] = []
    if config_module.in_container():
        found.append(
            _check(
                "machine.runner",
                OK,
                "Runner",
                "The runner starts with the container: one run every {{interval}}s (`ponos run --every`).",
                params=every,
            )
        )
    elif not shutil.which("systemctl"):
        # Not a fault: a machine without systemd runs the runner some other way, and nothing here can see it.
        found.append(
            _check(
                "machine.runner",
                OK,
                "Runner",
                "No systemd here: the runner is started with `ponos run --every`.",
            )
        )
    else:
        found.append(
            _check(
                "machine.runner",
                INFO,
                "Runner",
                "One run every {{interval}}s (`ponos enable` applies a change).",
                params=every,
            )
        )
        found.append(_timer(systemd.read()))
    found.append(
        _check(
            "settings.permissions",
            INFO,
            "Sessions",
            "permission_mode = {{mode}}.",
            params={"mode": runner.permission_mode},
        )
    )
    if runner.progress:
        found.append(
            _check(
                "settings.progress",
                INFO,
                "Sessions",
                "Live steps are written into the ticket every {{every}}s.",
                params={"every": str(runner.progress_interval_seconds)},
            )
        )
    else:
        found.append(
            _check(
                "settings.progress",
                INFO,
                "Sessions",
                "runner.progress = false: the ticket says nothing until the end.",
            )
        )
    return found


def _timer(timer: systemd.Timer) -> Check:
    """The timer, and an error when it will never fire.

    `enabled` is what `is-enabled` says, and it stayed true for the two hours the
    runner was silent: the timer was loaded, active, and had no next run. That
    state is the fault, and it is the only visible sign of it.
    """
    if timer.enabled != "enabled":
        return _check(
            "machine.runner",
            ERROR,
            "Runner",
            "The runner's timer is {{state}}: no ticket is picked up.",
            params={"state": timer.enabled},
            cause="`ponos enable` was never run, or the timer was disabled.",
            steps=["In a terminal on this machine, run `ponos enable`."],
            evidence=timer.row,
        )
    if timer.stalled:
        return _check(
            "machine.runner",
            ERROR,
            "Runner",
            "The runner's timer is enabled but will never fire.",
            cause="systemd holds no next run for it.",
            steps=["In a terminal on this machine, run `ponos enable` to arm it again."],
            evidence=timer.row,
        )
    return _check(
        "machine.runner",
        OK,
        "Runner",
        "The runner's timer is active, and a run is in progress."
        if timer.running
        else "The runner's timer is active.",
        evidence=timer.row,
    )


def _notifications(config: config_module.Config) -> list[Check]:
    settings = config.notify
    found: list[Check] = []
    if not settings.desktop:
        found.append(
            _check(
                "machine.desktop",
                INFO,
                "Desktop notifications",
                "Desktop notifications are off.",
            )
        )
    elif config_module.in_container():
        found.append(
            _check(
                "machine.desktop",
                INFO,
                "Desktop notifications",
                "No desktop in a container: Telegram or Slack are the way to be told.",
            )
        )
    elif shutil.which("notify-send"):
        found.append(
            _check("machine.desktop", OK, "Desktop notifications", "Sent through notify-send.")
        )
    else:
        found.append(
            _check(
                "machine.desktop",
                WARN,
                "Desktop notifications",
                "Desktop notifications are asked for, but notify-send is missing.",
                **_installing("notify-send"),
            )
        )
    live = channels.open(settings)
    if not live:
        found.append(
            _check(
                "machine.notify",
                INFO,
                "Notifications",
                "No messaging channel: [notify.telegram] or [notify.slack] to be told, and to answer, from your phone.",
            )
        )
    for channel in live:
        params = {"channel": channel.name.capitalize()}
        try:
            found.append(
                _check(
                    "machine.notify",
                    OK,
                    "{{channel}} notifications",
                    "{{channel}}: {{said}}.",
                    params={**params, "said": channel.check()},
                )
            )
        except channels.ChannelError as error:
            code = _first_line(error).split(" ", 1)[0]
            found.append(
                _check(
                    "machine.notify",
                    ERROR,
                    "{{channel}} notifications",
                    NOTIFY_SAID.get(code, "{{channel}} does not answer."),
                    params=params,
                    evidence=_first_line(error),
                    cause="The token was revoked, or the chat or channel is wrong.",
                    steps=["Check the {{channel}} token and chat in Settings › Notifications."],
                )
            )
        found.extend(_answerers(channel, settings))
    if live:
        found.append(
            _check(
                "machine.notify",
                INFO,
                "Notifications",
                "Sent on: {{moments}}.",
                params={"moments": ", ".join(settings.events) or "nothing"},
            )
        )
        found.append(
            _check(
                "machine.notify",
                INFO,
                "Notifications",
                "Answers come back as comments on the ticket."
                if settings.replies
                else "Replies are not read (notify.replies = false).",
            )
        )
    return found


def _answerers(channel: channels.Channel, settings: config_module.Notify) -> list[Check]:
    """Who may answer on this channel — said, because an answer can run code.

    An answer becomes a comment, a comment wakes a ticket, and a ticket runs a
    session with `bypassPermissions`. Nobody named is anybody who can write
    there: fine in a private chat, a door left open in a group or a channel.
    """
    if not settings.replies:
        return []
    params = {"channel": channel.name.capitalize(), "table": f"notify.{channel.name}"}
    title = "{{channel}} answers"
    if channel.allowed:
        return [
            _check(
                "machine.answerers",
                OK,
                title,
                "Answers are read from {{count}} users only ({{table}}.allowed_users).",
                params={**params, "count": str(len(channel.allowed))},
            )
        ]
    chat = str(settings.telegram.get("chat", "")) if channel.name == "telegram" else ""
    if channel.name == "telegram" and chat and not chat.startswith("-"):
        return [
            _check(
                "machine.answerers",
                INFO,
                title,
                "A private chat: only you write in it.",
                params=params,
            )
        ]
    return [
        _check(
            "machine.answerers",
            WARN,
            title,
            "Anybody who can write on {{channel}} can answer, and an answer can wake a ticket.",
            params=params,
            steps=["Name the people allowed in {{table}}.allowed_users."],
        )
    ]


def _version(config: config_module.Config, remote: bool) -> list[Check]:
    """This version, the newest one, and how the one is followed by the other."""
    found = [
        _check(
            "machine.version",
            INFO,
            "Version",
            "Ponos {{version}}: what changed is in CHANGELOG.md.",
            params={"version": __version__},
        )
    ]
    # In a container there is nothing to follow: the image is the version.
    if config_module.in_container():
        found.append(
            _check(
                "machine.version",
                INFO,
                "Version",
                "A container is updated by pulling a new image.",
                evidence=update_module.CONTAINER,
            )
        )
        return found
    runner = config.runner
    channel = runner.update_channel
    status = update_module.check(channel=channel) if remote else update_module.remembered()
    if status.reason:
        found.append(
            _check(
                "machine.version",
                WARN,
                "Version",
                "The newest version could not be compared with this one.",
                evidence=status.reason,
            )
        )
    elif status.stale:
        found.append(
            _check(
                "machine.version",
                WARN,
                "Version",
                "{{current}} installed, {{available}} available.",
                params={
                    "current": status.current[:8],
                    "available": f"{status.tag} ({status.latest[:8]})"
                    if status.tag
                    else status.latest[:8],
                },
                steps=["Run `ponos update`, or Update in the console's header."],
            )
        )
    elif status.current:
        found.append(
            _check(
                "machine.version",
                OK,
                "Version",
                "The newest version is installed ({{newest}}).",
                params={
                    "newest": f"{status.tag}, {status.current[:8]}"
                    if status.tag
                    else status.current[:8]
                },
            )
        )
    else:
        found.append(
            _check("machine.version", INFO, "Version", "No version check has been made yet.")
        )
    found.append(
        _check(
            "machine.update",
            INFO,
            "Updates",
            "runner.update_channel = “main”: every commit of the branch it was installed from is followed."
            if channel == "main"
            else "runner.update_channel = “{{channel}}”: the newest release tag (vX.Y.Z) is followed, never a commit in between.",
            params={"channel": channel},
        )
    )
    if runner.auto_update:
        found.append(
            _check(
                "machine.update",
                INFO,
                "Updates",
                "Checked by a run every {{every}}s (runner.auto_update).",
                params={"every": str(runner.update_interval_seconds)},
            )
        )
    else:
        found.append(
            _check(
                "machine.update",
                INFO,
                "Updates",
                "runner.auto_update = false: `ponos update` updates by hand.",
            )
        )
    return found


def _environment() -> list[Check]:
    """The `.venv` of the version in use: there, runnable, and holding what it requires."""
    title = "Python environment"
    if config_module.in_container():
        return [
            _check(
                "machine.environment",
                INFO,
                title,
                "The image's Python: requirements.txt was installed when it was built.",
            )
        ]
    version = update_module.installed_version()
    if version is None:
        return [
            _check(
                "machine.environment",
                INFO,
                title,
                "Not installed by install.sh: {{where}} runs on whatever started it.",
                params={"where": str(update_module.app_dir())},
            )
        ]
    state, said = environment.diagnose(version)
    if state == "ok":
        return [
            _check(
                "machine.environment",
                OK,
                title,
                "The environment of this version is in place.",
                evidence=said,
            )
        ]
    if state == "warn":
        return [
            _check(
                "machine.environment",
                WARN,
                title,
                "This version has no environment of its own: the machine's Python runs it.",
                evidence=said,
            )
        ]
    return [
        _check(
            "machine.environment",
            ERROR,
            title,
            "The environment of this version cannot run it.",
            steps=["Run `{{repair}}` to make it again."],
            params={"repair": environment.REPAIR},
            evidence=said,
        )
    ]


def _database() -> list[Check]:
    """The local database opens, and is at the schema this code knows — or why not.

    Opening it is what brings it up to date, so this is also what migrates it
    on purpose. A file newer than the code is the case worth an error: every
    part of the runner that writes into it would stop on it. Migrations applied
    in another order than the code's are a warning: the file has every table,
    but was once written by another branch's code.
    """
    title = "Local database"
    try:
        location, found, disorder = db.check()
    except db.DatabaseError as error:
        return [
            _check(
                "machine.database",
                ERROR,
                title,
                "The local database cannot be used.",
                evidence=str(error),
            )
        ]
    checks = [
        _check(
            "machine.database",
            OK,
            title,
            "{{location}}: schema version {{version}} of {{count}}.",
            params={
                "location": str(location),
                "version": str(found),
                "count": str(len(db.MIGRATIONS)),
            },
        )
    ]
    if disorder:
        checks.append(
            _check(
                "machine.database",
                WARN,
                title,
                "Its migrations do not match this code's list.",
                evidence=disorder,
            )
        )
    return checks


def _stray() -> list[Check]:
    """The containers and processes a session started in its worktree and left running."""
    root = leftovers.worktrees()
    composed, held = leftovers.compose_projects(root), leftovers.processes(root)
    title = "Left running"
    if not composed and not held:
        return [
            _check(
                "machine.stray",
                OK,
                title,
                "No container or process left running from a worktree.",
            )
        ]
    steps = ["Run `ponos clean --force` to stop them, once no run is in progress."]
    found = [
        _check(
            "machine.stray",
            WARN,
            title,
            "The Compose project {{name}} still has containers.",
            params={"name": project.name},
            steps=steps,
            evidence=str(project.directory),
        )
        for project in composed
    ]
    found.extend(
        _check(
            "machine.stray",
            WARN,
            title,
            "The process {{pid}} still runs in a worktree.",
            params={"pid": str(pid)},
            steps=steps,
            evidence=command[:100],
        )
        for pid, command in held
    )
    return found


# -- Settings ------------------------------------------------------------------


def _settings(config: config_module.Config) -> list[Check]:
    return [
        *_secrets(config),
        *_languages(config.runner),
        *_validation(config.runner),
        *_vault(config),
        *_console(config),
        *_ideas(config.runner),
    ]


def _secrets(config: config_module.Config) -> list[Check]:
    """Where the secrets are: never in config.toml, and nobody else's to read."""
    found: list[Check] = []
    target = config_module.secrets_path(config.path)
    title = "Secrets"
    if config.exposed:
        found.append(
            _check(
                "settings.secrets",
                ERROR,
                title,
                "{{file}} still holds {{keys}}: ignored, and moved to {{target}} at the next launch.",
                params={
                    "file": str(config.path),
                    "keys": ", ".join(config.exposed),
                    "target": str(target),
                },
                steps=["Start Ponos once (`ponos run`, or the console) to move them."],
            )
        )
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        found.append(
            _check(
                "settings.secrets",
                OK,
                title,
                "No secret in {{file}}, none in {{target}} either: the environment holds them.",
                params={"file": config.path.name, "target": target.name},
            )
        )
        return found
    if mode & 0o077:
        found.append(
            _check(
                "settings.secrets",
                ERROR,
                title,
                "{{target}} can be read by others ({{mode}}).",
                params={"target": str(target), "mode": oct(mode)[2:]},
                steps=["Run `chmod 600 {{target}}`."],
            )
        )
    elif not config.exposed:
        found.append(
            _check(
                "settings.secrets",
                OK,
                title,
                "Secrets in {{target}} (600), none in {{file}}.",
                params={"target": str(target), "file": config.path.name},
            )
        )
    return found


def _languages(settings: config_module.Runner) -> list[Check]:
    """Which language the reports and the console are in — and a name nobody speaks.

    A language the runner does not know is read as English rather than refused,
    which is right for a run and wrong to keep quiet about: `de` would otherwise
    look like a setting that does nothing.
    """
    found: list[Check] = []
    for key, asked in (("language", settings.language), ("app_language", settings.app_language)):
        if asked and not voice.known(asked):
            found.append(
                _check(
                    "settings.language",
                    WARN,
                    "Language",
                    "runner.{{key}} = “{{asked}}” is not a language spoken here: it is read as English.",
                    params={"key": key, "asked": asked},
                )
            )
    names = {"en": "English", "fr": "French"}
    shown = settings.interface_language()
    params = {
        "reports": names[voice.understood(settings.language)] if settings.language else "English",
        "console": names[voice.understood(shown)] if shown else "the browser's language",
    }
    found.append(
        _check(
            "settings.language",
            INFO,
            "Language",
            "Reports in {{reports}}, sessions told to write in it; the console in {{console}}."
            if settings.language
            else "Reports in English, sessions answer in the ticket's language; the console in {{console}}.",
            params=params,
        )
    )
    return found


def _validation(settings: config_module.Runner) -> list[Check]:
    """How far work goes on its own once validated: conflicts resolved, review skipped."""
    found: list[Check] = []
    if settings.rebase and settings.resolve_conflicts:
        excepted = settings.resolve_conflicts_except.strip()
        found.append(
            _check(
                "settings.validation",
                OK,
                "Validation",
                "A validated merge that conflicts is resolved by {{model}}, except on {{excepted}}."
                if excepted
                else "A validated merge that conflicts is resolved by {{model}}.",
                params={
                    "model": settings.resolve_model or "the ticket’s own model",
                    "excepted": excepted,
                },
            )
        )
    else:
        found.append(
            _check(
                "settings.validation",
                WARN,
                "Validation",
                "{{setting}} is off: a validated merge that conflicts blocks its ticket.",
                params={
                    "setting": "runner.rebase"
                    if not settings.rebase
                    else "runner.resolve_conflicts"
                },
            )
        )
    # Not a problem, since it is a choice — but the one setting that lets work
    # leave the machine for good without anybody having read it, so it is said.
    forced = [kind for kind in kinds.KINDS if settings.forces_validation(kind)]
    if forced:
        found.append(
            _check(
                "settings.validation",
                WARN,
                "Validation",
                "Force validated: {{kinds}}. Merged or published as soon as the session succeeds, without waiting for review.",
                params={"kinds": ", ".join(forced)},
            )
        )
        if "code" in forced and not (settings.push and settings.open_pull_request):
            found.append(
                _check(
                    "settings.validation",
                    WARN,
                    "Validation",
                    "runner.force_validated_code is on, but no pull request is opened to merge.",
                )
            )
    # And the projects that decide for themselves, in either direction: the
    # lines above are not the whole story for them.
    owning = project_settings.owning_validation()
    if owning:
        found.append(
            _check(
                "settings.validation",
                OK,
                "Validation",
                "An automatic validation of their own, over the lines above: {{names}}.",
                params={"names": ", ".join(project["name"] or project["id"] for project in owning)},
            )
        )
    return found


def _vault(config: config_module.Config) -> list[Check]:
    """The keys `[vault]` grants each project, and whether they can be read now.

    Each one is read, as a session would — and only said to be there or not:
    no value, and not even its length, is said. See vault.py.
    """
    settings = config.vault
    title = "Vault"
    found = [
        _check(
            "settings.vault",
            ERROR,
            title,
            "A line of [vault] cannot be used as written.",
            evidence=problem,
        )
        for problem in settings.problems
    ]
    if not settings.projects:
        found.append(
            _check(
                "settings.vault",
                INFO,
                title,
                "No [vault] secret: no project is given a key.",
            )
        )
        return found
    used = {settings.provider} | {
        vault.where(item, settings.provider)[0]
        for granted in settings.projects.values()
        for item in granted.values()
    }
    for name in sorted(used & set(vault.PROVIDERS)):
        missing = vault.provider(name).available() if name != "env" else ""
        if missing:
            found.append(
                _check(
                    "settings.vault",
                    ERROR,
                    title,
                    "The secret provider {{provider}} cannot be asked.",
                    params={"provider": name},
                    evidence=missing,
                )
            )
        else:
            found.append(
                _check(
                    "settings.vault",
                    OK,
                    title,
                    "The secret provider {{provider}} answers.",
                    params={"provider": name},
                )
            )
    stored = config_module.read_secrets(config_module.secrets_path(config.path))
    for project, granted in sorted(settings.projects.items()):
        read = vault.read(granted, settings.provider, stored)
        if read.values:
            found.append(
                _check(
                    "settings.vault",
                    OK,
                    title,
                    "{{project}} is given {{keys}}.",
                    params={"project": project, "keys": ", ".join(sorted(read.values))},
                )
            )
        for missing in read.missing:
            found.append(
                _check(
                    "settings.vault",
                    ERROR,
                    title,
                    "{{project}} is not given a key it was granted.",
                    params={"project": project},
                    evidence=missing,
                )
            )
    return found


def _console(config: config_module.Config) -> list[Check]:
    """How the console is opened, what reaches it, and what a message there can carry."""
    web = config.web
    found: list[Check] = []
    params = {"address": f"http://{web.host}:{web.port}"}
    # "We have a sign-in, and the page still asks me for a token" is the
    # ordinary shape of a console whose `web.email` and `web.password` were
    # never both set — the sign-in is dormant until they are, and the token
    # never goes away anyway. Said here rather than left to be guessed from a
    # login page that does not appear.
    if web.email and web.password:
        found.append(
            _check(
                "settings.console",
                OK,
                "Console",
                "{{address}} is opened by signing in as {{email}}; the token keeps working for a script.",
                params={**params, "email": web.email},
            )
        )
    else:
        found.append(
            _check(
                "settings.console",
                OK,
                "Console",
                "{{address}} is opened with its token (`ponos serve --print-token`).",
                params=params,
            )
        )
        if web.email or web.password:
            found.append(
                _check(
                    "settings.console",
                    WARN,
                    "Console",
                    "Half a sign-in: web.email without web.password, or the other way round, is not a way in.",
                    steps=["Set both web.email and web.password, or neither."],
                )
            )
        found.append(
            _check(
                "settings.console",
                INFO,
                "Console",
                "web.email and web.password, the two, to sign in instead.",
            )
        )
    # The MCP connector is pasted by its address: the one claude.ai reaches
    # has to be HTTPS, and Claude Code on this machine takes the loopback one.
    public = web.url
    if public.startswith("https://"):
        found.append(
            _check(
                "settings.mcp",
                OK,
                "MCP connector",
                "{{public}}/mcp for claude.ai; {{address}}/mcp for Claude Code here.",
                params={**params, "public": public},
            )
        )
    elif public:
        found.append(
            _check(
                "settings.mcp",
                WARN,
                "MCP connector",
                "web.url is {{public}}: claude.ai only adds a connector at an https:// address.",
                params={**params, "public": public},
            )
        )
    else:
        found.append(
            _check(
                "settings.mcp",
                INFO,
                "MCP connector",
                "{{address}}/mcp for Claude Code here; web.url for claude.ai.",
                params=params,
            )
        )
    # What a message typed there can carry, and the two things that need
    # something this machine may not have: a video needs ffmpeg to be looked at
    # (see `_tools`), and dictation needs somebody to transcribe it.
    found.append(
        _check(
            "settings.attachments",
            OK,
            "Attachments",
            "Up to {{size}} MB a file, kept {{days}} days.",
            params={"size": str(web.attachment_max_mb), "days": str(web.attachment_days)},
        )
    )
    openrouter = config.openrouter
    if openrouter.key:
        found.append(
            _check(
                "settings.dictation",
                OK,
                "Dictation",
                "Transcribed by {{model}}.",
                params={"model": openrouter.transcription_model},
            )
        )
    else:
        found.append(
            _check(
                "settings.dictation",
                INFO,
                "Dictation",
                "Off: it is transcribed by OpenRouter (openrouter.key).",
            )
        )
    chat_model = web.chat_model
    model = {"model": chat_model}
    if chat_model and "/" in chat_model and not openrouter.key:
        found.append(
            _check(
                "settings.chat",
                WARN,
                "Console sessions",
                "web.chat_model = {{model}} is an OpenRouter model, and openrouter.key is empty.",
                params=model,
            )
        )
    elif chat_model:
        found.append(
            _check(
                "settings.chat",
                OK,
                "Console sessions",
                "New console sessions start on {{model}}.",
                params=model,
            )
        )
    elif openrouter.key:
        found.append(
            _check(
                "settings.chat",
                OK,
                "Console sessions",
                "Claude models, and every OpenRouter model.",
            )
        )
    return found


def _ideas(settings: config_module.Runner) -> list[Check]:
    """Finding ideas on a schedule: that it can fire, and that it has projects to fire on."""
    wanted = idea_schedule.plan(settings)
    title = "Ideas schedule"
    if not wanted.on:
        return [
            _check(
                "settings.ideas",
                INFO,
                title,
                "runner.ideas_schedule = off: ideas are found when asked.",
            )
        ]
    params = {"schedule": wanted.schedule}
    if cause := idea_schedule.problem(wanted):
        return [
            _check(
                "settings.ideas",
                ERROR,
                title,
                "runner.ideas_schedule = {{schedule}} never fires.",
                params=params,
                evidence=cause,
            )
        ]
    following = idea_schedule.next_after(wanted, datetime.now().astimezone())
    found = [
        _check(
            "settings.ideas",
            OK,
            title,
            "Ideas are found on a schedule ({{schedule}}), next pass on {{when}}.",
            params={**params, "when": following.strftime("%Y-%m-%d %H:%M")},
        )
        if following
        else _check(
            "settings.ideas",
            OK,
            title,
            "Ideas are found on a schedule ({{schedule}}), with no pass to come.",
            params=params,
        )
    ]
    if wanted.scope == "selected" and not wanted.projects and not wanted.workspace:
        found.append(
            _check(
                "settings.ideas",
                WARN,
                title,
                "runner.ideas_scope = selected names no project: only a project's own switch counts.",
            )
        )
    if wanted.budget_usd:
        found.append(
            _check(
                "settings.ideas",
                INFO,
                title,
                "A pass spends ${{budget}} at the most.",
                params={"budget": f"{wanted.budget_usd:.2f}"},
            )
        )
    found.append(
        _check(
            "settings.ideas",
            INFO,
            title,
            "The passes run in the console (`ponos serve`), not in the timer's run.",
        )
    )
    return found


# -- running them --------------------------------------------------------------


def run(
    config: config_module.Config, client: store.Store | None = None, *, remote: bool = False
) -> list[Check]:
    """Every check, in the order the dashboard lists them (`GROUPS`).

    `remote`: ask the remote for the newest version, as `doctor` does, rather
    than read what the last check found.
    """
    client = client or store.open(config)
    jobs: list[tuple[str, Callable[[], list[Check]]]] = [
        ("claude", lambda: _claude(config)),
        ("claude", lambda: _models(config)),
        ("github", lambda: _github_access(config)),
        ("github", _github_token),
        ("projects", lambda: _workspace_root(config)),
        ("machine", lambda: _machine(config)),
        ("machine", lambda: _notifications(config)),
        ("machine", lambda: _version(config, remote)),
        ("machine", _environment),
        ("machine", _database),
        ("machine", _stray),
        ("settings", lambda: _settings(config)),
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_guarded(group, job)) for group, job in jobs]
        notion_found, space = _guard_notion(config, client)
        rows = _project_rows(client, space)
        per_project = [
            pool.submit(_guarded("projects", partial(_project, config, row))) for row in rows
        ]
        found = [check for future in futures for check in future.result()]
        project_found = [check for future in per_project for check in future.result()]
    # A repository the board's projects already answered for is said once, there.
    covered = {
        check.params.get("repository")
        for check in project_found
        if check.code == "github.repository"
    }
    found = [
        check
        for check in found
        if not (check.code == "github.reach" and check.params.get("repository") in covered)
    ]
    every = [*notion_found, *project_found, *found]
    # Sorted by group alone: within one, each check keeps its place.
    return [check for group in GROUPS for check in every if check.group == group]


def _guard_notion(
    config: config_module.Config, client: store.Store
) -> tuple[list[Check], workspace_module.Workspace | None]:
    try:
        return _board(config, client)
    except Exception as error:  # a check that cannot be made is a line, not a crash
        logger.exception("health: the Notion checks could not be made", extra=log.FILE_ONLY)
        return [_unknown("notion", error)], None


def _guarded(group: str, job: Callable[[], list[Check]]) -> Callable[[], list[Check]]:
    def guarded() -> list[Check]:
        try:
            return job()
        except Exception as error:
            logger.exception("health: the %s checks could not be made", group, extra=log.FILE_ONLY)
            return [_unknown(group, error)]

    return guarded


def _unknown(group: str, error: object) -> Check:
    return Check(
        f"{group}.unknown",
        group,
        WARN,
        "Check",
        "This check could not be made.",
        evidence=_first_line(error),
    )


def problems(checks: list[Check]) -> int:
    return sum(check.state == ERROR for check in checks)


# -- fixing --------------------------------------------------------------------


@runtime_checkable
class _Shaped(Protocol):
    """A board whose databases can be read whole and given new properties: Notion's."""

    def database(self, database_id: str) -> dict[str, Any]: ...

    def add_properties(self, database_id: str, properties: dict[str, Any]) -> None: ...


def _shaped(client: store.Store) -> _Shaped:
    """The board a column or a status is added to: Notion, mirrored or not.

    A mirrored board reads its schema from Notion, so it is offered the same
    fixes as a Notion one — and makes them on its Notion side, the only one
    with a schema to change.
    """
    from .sync import Mirror

    board: object = client.primary if isinstance(client, Mirror) else client
    if not isinstance(board, _Shaped):
        raise ValueError("this board has no properties to add")
    return board


def fix(
    config: config_module.Config,
    client: store.Store,
    action: str,
    target: str = "",
    *,
    confirmed: bool = False,
) -> str:
    """Make one of the fixes a check offered, and say what was done.

    Refuses without `confirmed`: a fix changes somebody's Notion or somebody's
    clone, and the console asks first, but this does not rely on it.
    """
    if not confirmed:
        raise PermissionError("a fix is made only once it is confirmed")
    if action in ("notion_columns", "notion_statuses"):
        space = workspace_module.resolve(client, config.notion)
        settings = config.notion
        board = _shaped(client)
        if action == "notion_columns":
            wanted = provision.tickets_schema(settings, space.projects, space.agents)
            absent = provision.missing_properties(client.schema(space.tickets), wanted)
            board.add_properties(space.tickets, absent)
            return "added " + ", ".join(sorted(absent)) if absent else "nothing to add"
        widened = provision.missing_options(
            board.database(space.tickets),
            settings.prop("status"),
            provision.status_options(settings),
        )
        board.add_properties(space.tickets, widened)
        return "statuses added" if widened else "nothing to add"
    if action == "project_branch":
        space = workspace_module.resolve(client, config.notion)
        row = next((row for row in _project_rows(client, space) if row["id"] == target), None)
        if row is None:
            raise LookupError("that project is not on the board")
        resolver = projects.Resolver(config.runner.workspace_root, config.projects, config.github)
        path = resolver.locate(row["name"], row["path"], row["repository"])
        if path is None:
            raise LookupError("that project has no local copy")
        result = git.git(["remote", "set-head", "origin", "--auto"], path, timeout=PROBE_TIMEOUT)
        if not result.ok:
            raise RuntimeError(
                _first_line(result.err or result.out) or "git remote set-head failed"
            )
        return git.default_branch(path)
    raise ValueError(f"unknown fix: {action}")
