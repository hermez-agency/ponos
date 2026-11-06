"""The Notion group, continued: what the board's databases hold.

`notion` asks whether the databases are there; this asks whether they are
shaped as the runner writes them — a column missing fails a ticket halfway,
not at the start. The fixes it offers are made by `fixing`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import config as config_module
from .. import provision, store, subtypes
from .. import schedules as schedules_module
from .. import workspace as workspace_module
from .check import ERROR, INFO, OK, WARN, Check, _check, _first_line, _fix

# The statuses the runner moves a ticket through, each one required.
RUNNER_STATUSES = ("ready", "running", "review", "validated", "done", "blocked")

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
        if not name:
            continue  # a setting turned off reads no column, so none can be missing
        kind = schema.get(name)
        if kind is None:
            # Two settings may name one property (`agent` and `role` both say "Agent"): said once.
            if name not in missing:
                missing.append(name)
            costs.setdefault(name, []).append(cost)
        elif kind not in accepted:
            # In Notion's words alone, the one language both pages speak.
            wrong.append(f"“{name}” ({kind} ≠ {' / '.join(accepted)})")
            costs.setdefault(name, []).append(cost)
    # « Après » and « Rôle » are optional — a board without them runs every
    # ready ticket, with no role, as it always did — but one under another type
    # is read as nothing at all.
    for key, cost in (
        ("after", "no ticket waits for the tickets it comes after"),
        ("role", "no agent, and so no role, per ticket"),
    ):
        name = settings.prop(key)
        if schema.get(name, "relation") != "relation":
            wrong.append(f"“{name}” ({schema[name]} ≠ relation)")
            costs.setdefault(name, []).append(cost)
    wanted_columns = provision.tickets_schema(settings, space.projects, space.agents, space.tickets)
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
                    [
                        "Rename or retype the property in Notion: Ponos reads it under this name only."
                    ]
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
        found.extend(_stray_statuses(options))
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


def _stray_statuses(options: list[str]) -> list[Check]:
    """The statuses the board offers that are none of `config.STATUS`.

    Not an error: the runner never moves a ticket there, and reads one that is
    there as a draft. But it is a column of the board that is none of Ponos's,
    and a ticket in it is one nobody will ever pick up.
    """
    known = set(config_module.STATUS.values())
    strays = [name for name in options if name not in known]
    if not strays:
        return []
    return [
        _check(
            "notion.statuses",
            WARN,
            "Tickets statuses",
            "Statuses Ponos does not know: {{strays}}. A ticket there is read as a draft.",
            params={"strays": ", ".join(f"“{name}”" for name in strays)},
            steps=["Move their tickets to another status, then remove the options in Notion."],
            evidence="known: " + ", ".join(config_module.STATUS.values()),
        )
    ]


def _other_statuses(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """The statuses the runner never moves a ticket to: cancelled, paused, and draft.

    Optional, all three: a board without cancelled has no way to give a ticket
    up but to call it done, one without paused none to stop one for later, and
    one without draft keeps the tickets still being written with no status.
    """
    settings = config.notion
    options = client.options(space.tickets, settings.prop("status"))
    if not options:
        return []
    found: list[Check] = []
    for key, check, title, offered, missing in (
        (
            "cancelled",
            "notion.cancelled",
            "Cancelled status",
            "“{{status}}”: a ticket there is never run.",
            "“{{status}}” is not offered: no column to give a ticket up in.",
        ),
        (
            "paused",
            "notion.paused",
            "Paused status",
            "“{{status}}”: a ticket there is never run by itself.",
            "“{{status}}” is not offered: no column to pause a ticket in.",
        ),
        (
            "draft",
            "notion.draft",
            "Draft status",
            "“{{status}}”: a ticket there is never picked up.",
            "“{{status}}” is not offered: a ticket being written has no status.",
        ),
    ):
        params = {"status": settings.state(key)}
        if settings.state(key) in options:
            found.append(_check(check, OK, title, offered, params=params))
        else:
            found.append(
                _check(
                    check,
                    WARN,
                    title,
                    missing,
                    params=params,
                    steps=[
                        "`ponos init` adds it to a select; on a Notion status, add the option by hand."
                    ],
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
    for key in config_module.TYPES:
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


def _subtypes(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """The options of the Sub-type property that are none of `subtypes.SUBTYPES`'.

    An older Ponos, or a hand, wrote « Improvement » beside « Amélioration »: the
    runner reads both as one sub-type, a Notion view filtered on one misses the
    tickets on the other. One that is a spelling of a sub-type is rewritten to
    its option; one that is no sub-type at all is somebody's to decide.
    """
    column = config.notion.prop("subtype")
    if column not in client.schema(space.tickets):
        return []
    strays = _stray_subtypes(client, space.tickets, column)
    if not strays:
        return [
            _check(
                "notion.subtypes",
                OK,
                "Sub-types",
                "Every sub-type option is one the runner writes.",
            )
        ]
    rewritable = [name for name, key, _ in strays if key]
    unknown = [name for name, key, _ in strays if not key]
    tickets = sum(count for _, _, count in strays)
    return [
        _check(
            "notion.subtypes",
            WARN,
            "Sub-types",
            "Sub-type options the runner does not write: {{options}}, on {{count}} ticket."
            if tickets == 1
            else "Sub-type options the runner does not write: {{options}}, on {{count}} tickets.",
            params={
                "options": ", ".join(f"“{name}” ({count})" for name, _, count in strays),
                "count": str(tickets),
                "unknown": ", ".join(f"“{name}”" for name in unknown),
            },
            cause="An older Ponos, or a hand, wrote another spelling: a Notion view filtered on one misses the others.",
            steps=[
                "Give the tickets on {{unknown}} a sub-type by hand, then remove the option in Notion."
            ]
            if unknown
            else [],
            evidence="offered: " + ", ".join(subtype.option for subtype in subtypes.SUBTYPES),
            fix=_fix(
                "notion_subtypes",
                "Rewrite",
                "Move the tickets on {{missing}} to the runner's option, then remove those options?",
                rewritable,
            )
            if rewritable
            else None,
        )
    ]


def _stray_subtypes(client: store.Store, database: str, column: str) -> list[tuple[str, str, int]]:
    """Each option of the column that is no sub-type's: its name, the sub-type it spells or "", its tickets."""
    written = {subtype.option for subtype in subtypes.SUBTYPES}
    return [
        (name, subtypes.of(name), len(_on_option(client, database, column, name)))
        for name in client.options(database, column)
        if name not in written
    ]


def _on_option(client: store.Store, database: str, column: str, name: str) -> list[store.Page]:
    return client.query(database, {"property": column, "select": {"equals": name}})


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
        elif kind in store.READ_ONLY and why.startswith("written by the runner"):
            # Not refused by Notion, dropped: `Next` would never move, and
            # `recur` takes no occurrence it cannot write down.
            found.append(
                _check(
                    "notion.schedules",
                    WARN,
                    "Schedules",
                    "“{{name}}” is a {{kind}}, which the runner cannot write: "
                    "make it a {{preferred}}.",
                    params={"name": name, "kind": kind, "preferred": preferred},
                    notes=[{"name": name, "said": [why]}],
                )
            )
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
        # What `init` would add, options included: a schedule without its Type
        # makes tickets the classifier types, a code one as « Rédaction ».
        wanted = provision.schedules_schema(settings, space.tickets, space.projects)
        addable = sorted(provision.missing_properties(schema, wanted))
        found.append(
            _check(
                "notion.schedules",
                WARN,
                "Schedules",
                "Properties missing on the schedules database: {{missing}}.",
                params={"missing": ", ".join(f"“{note['name']}”" for note in missing)},
                notes=missing,
                steps=[
                    "`ponos init <page-url>` adds them, as does Configure on the console's health band."
                ]
                if addable
                else [],
                fix=_fix(
                    "notion_schedule_columns",
                    "Configure",
                    "Add {{missing}} to the schedules database? Existing properties are left as they are.",
                    addable,
                )
                if addable
                else None,
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
