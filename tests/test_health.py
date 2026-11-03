"""`health.py`: what the dashboard and `ponos doctor` check, and offer to correct."""

from __future__ import annotations

import contextlib
import io
import json
import re
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from support import FRONTEND, _config, _environment, _git_answering, case

from ponos import config as C
from ponos import db, provision, store, update, workspace

if TYPE_CHECKING:
    from ponos.health import Check

# -- the vault ---------------------------------------------------------------


def _french() -> str:
    """The console's French: its dictionary, and the one the health band fetches for itself."""
    return "".join(
        (FRONTEND / "src/lib" / name).read_text(encoding="utf-8")
        for name in ("french.ts", "health-french.ts")
    )


class _HealthBoard:
    """The few calls `health` makes of a Notion board, over a database held in memory."""

    def __init__(self, properties: dict[str, dict[str, Any]]) -> None:
        self.properties = properties
        self.added: dict[str, Any] = {}

    def forget_database(self, database_id: str) -> None:
        pass

    def database(self, database_id: str) -> dict[str, Any]:
        return {"properties": self.properties}

    def schema(self, database_id: str) -> dict[str, str]:
        return {name: prop["type"] for name, prop in self.properties.items()}

    def options(self, database_id: str, name: str) -> list[str]:
        prop = self.properties.get(name) or {}
        return [
            option["name"] for option in (prop.get(prop.get("type", "")) or {}).get("options", [])
        ]

    def add_properties(self, database_id: str, properties: dict[str, Any]) -> None:
        self.added.update(properties)


def _health_board(
    skip: tuple[str, ...] = (), statuses: tuple[str, ...] = ()
) -> tuple[C.Notion, _HealthBoard]:
    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    schema = provision.tickets_schema(settings, "projects", "agents")
    properties = {
        name: {"type": next(iter(shape)), **shape}
        for name, shape in schema.items()
        if name not in skip
    }
    if statuses:
        properties[settings.prop("status")] = {
            "type": "select",
            "select": {"options": [{"name": name} for name in statuses]},
        }
    return settings, _HealthBoard(properties)


@case
def health_says_nothing_of_a_board_that_is_complete() -> None:
    from ponos import health

    settings, board = _health_board()
    config = _config("")
    config.notion = settings
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    assert [check.state for check in found] == [health.OK, health.OK], found


@case
def health_offers_to_add_the_missing_properties_and_does_it_only_once_confirmed() -> None:
    from ponos import health

    settings, board = _health_board(skip=("Runner", "Progress"))
    config = _config("")
    config.notion = settings
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    columns = next(check for check in found if check.code == "notion.columns")
    assert columns.state == health.ERROR
    assert "“Runner”" in columns.params["missing"] and "“Progress”" in columns.params["missing"]
    assert columns.fix and columns.fix["action"] == "notion_columns"
    assert "“Runner”" in columns.text(
        columns.fix["confirm"].replace("{{missing}}", columns.fix["missing"])
    ), "the dialog names them"

    class Client(_HealthBoard):
        def resolve_database(self, identifier: str) -> str:
            return "db"

    client = Client(board.properties)
    original = workspace.resolve
    workspace.resolve = lambda backend, settings: workspace.Workspace(
        tickets="db", projects="projects", agents="agents"
    )
    try:
        try:
            health.fix(config, client, "notion_columns")  # type: ignore[arg-type]  # a fake: a board in memory
        except PermissionError:
            pass
        else:
            raise AssertionError("a fix is never made unasked")
        assert not client.added, "nothing was written before the confirmation"
        health.fix(config, client, "notion_columns", confirmed=True)  # type: ignore[arg-type]  # a fake: a board in memory
    finally:
        workspace.resolve = original
    assert set(client.added) == {"Runner", "Progress"}, client.added


@case
def health_adds_the_missing_properties_of_a_mirrored_board_on_its_notion_side() -> None:
    from ponos import files, health, sync

    settings, board = _health_board(skip=("Runner",))
    config = _config("")
    config.notion = settings
    mirrored = sync.Mirror(board, files.Board(Path(tempfile.mkdtemp())))  # type: ignore[arg-type]  # a fake: a board in memory
    original = workspace.resolve
    workspace.resolve = lambda backend, settings: workspace.Workspace(
        tickets="db", projects="projects", agents="agents"
    )
    try:
        # A mirror has no `add_properties` of its own: the fix used to stop on it.
        done = health.fix(config, mirrored, "notion_columns", confirmed=True)
    finally:
        workspace.resolve = original
    assert done == "added Runner" and set(board.added) == {"Runner"}, (done, board.added)


@case
def health_adds_a_missing_status_to_a_select_and_only_says_how_on_a_real_status() -> None:
    from ponos import health

    settings, board = _health_board(statuses=("Ready", "In progress", "Done"))
    config = _config("")
    config.notion = settings
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    statuses = next(check for check in found if check.code == "notion.statuses")
    assert (
        statuses.state == health.ERROR
        and statuses.fix
        and statuses.fix["action"] == "notion_statuses"
    )
    assert "“Failed”" in statuses.params["missing"]

    name = settings.prop("status")
    board.properties[name] = {"type": "status", "status": {"options": [{"name": "Ready"}]}}
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    statuses = next(check for check in found if check.code == "notion.statuses")
    assert statuses.fix is None and statuses.steps, "Notion cannot widen a status from outside"


class _SubtypeBoard(_HealthBoard):
    """A board whose Sub-type column carries tickets, for the check and its fix."""

    def __init__(self, options: tuple[str, ...], tickets: dict[str, str]) -> None:
        settings, board = _health_board()
        super().__init__(board.properties)
        self.settings = settings
        self.column = settings.prop("subtype")
        self.properties[self.column] = {
            "type": "select",
            "select": {"options": [{"name": name, "color": "blue"} for name in options]},
        }
        self.tickets = dict(tickets)

    def resolve_database(self, identifier: str) -> str:
        return "db"

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[store.Page]:
        wanted = ((filter_ or {}).get("select") or {}).get("equals")
        return [
            store.Page(id=page, url="", title=page)
            for page, value in self.tickets.items()
            if wanted is None or value == wanted
        ]

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        self.tickets[page_id] = values[self.column]

    def add_properties(self, database_id: str, properties: dict[str, Any]) -> None:
        super().add_properties(database_id, properties)
        for name, shape in properties.items():
            self.properties[name] = {"type": next(iter(shape)), **shape}


@case
def health_says_the_sub_type_options_nobody_writes_and_rewrites_their_tickets_once_confirmed() -> (
    None
):
    from ponos import health

    board = _SubtypeBoard(
        ("Bug", "Amélioration", "Improvement", "Security", "Later"),
        {"a": "Improvement", "b": "Improvement", "c": "Security", "d": "Bug", "e": "Later"},
    )
    config = _config("")
    config.notion = board.settings
    space = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    (check,) = health._subtypes(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert check.state == health.WARN, check
    assert check.params["count"] == "4", check.params
    assert "“Improvement” (2)" in check.params["options"], check.params
    assert check.params["unknown"] == "“Later”" and check.steps, "no sub-type to rewrite it to"
    assert check.fix and check.fix["action"] == "notion_subtypes"
    assert check.fix["missing"] == "“Improvement”, “Security”", check.fix

    original = workspace.resolve
    workspace.resolve = lambda backend, settings: space
    try:
        try:
            health.fix(config, board, "notion_subtypes")  # type: ignore[arg-type]  # a fake: a board in memory
            raise AssertionError("a fix is never made unasked")
        except PermissionError:
            pass
        assert board.tickets["a"] == "Improvement", "nothing was written before the confirmation"
        done = health.fix(config, board, "notion_subtypes", confirmed=True)  # type: ignore[arg-type]  # a fake: a board in memory
    finally:
        workspace.resolve = original
    assert board.tickets == {
        "a": "Amélioration",
        "b": "Amélioration",
        "c": "Sécurité",
        "d": "Bug",
        "e": "Later",
    }, board.tickets
    assert board.options("db", board.column) == ["Bug", "Amélioration", "Later"], board.properties
    assert done.startswith("3 ticket(s) rewritten"), done

    (check,) = health._subtypes(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert check.fix is None, "only “Later” is left, and it is nobody's to rewrite"
    board.tickets["e"] = "Bug"
    board.properties[board.column]["select"]["options"].pop()
    (check,) = health._subtypes(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert check.state == health.OK, check


@case
def health_names_a_property_once_and_says_what_each_costs_in_french_too() -> None:
    from ponos import health

    settings, board = _health_board(skip=("Agent", "Progress"))
    settings.properties["agent"] = "Agent"  # two settings, one property
    config = _config("")
    config.notion = settings
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    columns = next(check for check in found if check.code == "notion.columns")
    names = [note["name"] for note in columns.notes]
    assert len(names) == len(set(names)) and "Agent" in names, names
    assert columns.params["missing"].count("“Agent”") == 1, columns.params
    assert not columns.evidence, "the costs are sentences, not what a tool printed"
    french = _french()
    for _, cost in store.COLUMNS.values():
        assert f'"{cost}"' in french, f"nothing translates “{cost}” — add it to health-french.ts"
    for sentence in health.NOTIFY_SAID.values():
        assert f'"{sentence}"' in french, (
            f"nothing translates “{sentence}” — add it to health-french.ts"
        )


@case
def health_reports_a_project_whose_folder_is_gone_and_one_with_no_remote() -> None:
    from ponos import health

    config = _config("")
    gone = health._project(
        config, {"id": "1", "name": "Ghost", "repository": "", "path": "/nonexistent/ghost"}
    )
    assert [check.state for check in gone] == [health.ERROR] and gone[0].code == "projects.path"
    assert "Ghost" in gone[0].text(gone[0].said)

    # A repository to clone is not a mistake: it is fetched when its first ticket starts.
    cloned = health._project(
        config, {"id": "2", "name": "Later", "repository": "acme/later", "path": ""}
    )
    assert [check.state for check in cloned] == [health.WARN]

    repo = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    bare = health._project(config, {"id": "3", "name": "Bare", "repository": "", "path": str(repo)})
    assert [check.code for check in bare] == ["projects.path", "projects.remote"]
    assert bare[1].state == health.ERROR and bare[1].steps


@case
def health_warns_when_two_settings_name_one_property() -> None:
    from ponos import health

    settings, board = _health_board()
    settings.properties["agent"] = "Agent"  # the machine, read off the agent's relation
    config = _config("")
    config.notion = settings
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    shared = next(check for check in found if check.code == "notion.shared")
    assert shared.state == health.WARN
    assert "“Agent” (agent, role)" in shared.params["shared"], shared.params
    french = _french()
    for sentence in (shared.said, shared.cause, *shared.steps):
        assert f'"{sentence}"' in french, (
            f"nothing translates “{sentence}” — add it to health-french.ts"
        )
    assert shared.fix is None, "the column is a relation: the role reads it right"


@case
def health_offers_to_take_the_role_off_a_text_column_the_agent_reads() -> None:
    from ponos import health

    settings, board = _health_board()
    board.properties["Agent"] = {"type": "rich_text", "rich_text": {}}
    config = _config('[notion.properties]\nagent = "Agent"\nrole = "Agent"\n')
    config.notion.properties = {**settings.properties, "agent": "Agent", "role": "Agent"}
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    shared = next(check for check in found if check.code == "notion.shared")
    assert shared.fix and shared.fix["action"] == "notion_shared", shared
    assert shared.fix["missing"] == "“Agent”"
    french = _french()
    for sentence in (shared.fix["label"], shared.fix["confirm"]):
        assert f'"{sentence}"' in french, f"nothing translates “{sentence}”"

    try:
        health.fix(config, board, "notion_shared")  # type: ignore[arg-type]  # a fake: a board in memory
    except PermissionError:
        pass
    else:
        raise AssertionError("a fix is never made unasked")
    assert C.load(config.path).notion.prop("role") == "Agent", "nothing written unasked"
    health.fix(config, board, "notion_shared", confirmed=True)  # type: ignore[arg-type]  # a fake: a board in memory
    fixed = C.load(config.path)
    assert fixed.notion.prop("role") == "" and fixed.notion.prop("agent") == "Agent"

    config.notion.properties["role"] = ""
    again = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    assert [check.code for check in again if check.state != health.OK] == [], again


# -- what `doctor` used to ask on its own, asked here ---------------------------


@contextmanager
def _patched(target: object, **values: Any) -> Iterator[None]:
    """Some attributes of a module replaced for the length of a block."""
    original = {name: getattr(target, name) for name in values}
    for name, value in values.items():
        setattr(target, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(target, name, value)


def _doctor_said(function: Callable[..., int], *args: Any) -> tuple[int, str]:
    """What a `doctor` command returns, and what it printed, colours taken out."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        returned = function(*args)
    return returned, re.sub(r"\x1b\[[0-9;]*m", "", out.getvalue())


def _verdicts(checks: Iterable[Check]) -> list[tuple[str, str]]:
    return [(check.code, check.state) for check in checks]


def _lines(checks: Iterable[Check]) -> str:
    """Every check as `doctor` reads it, its evidence and notes too — for `in`."""
    return "\n".join(
        f"{check.state} {check.code} {check.text(check.title)}: {check.text(check.said)} "
        f"{check.evidence} {[note['said'] for note in check.notes]}"
        for check in checks
    )


def _columns(settings: C.Notion, schema: dict[str, str]) -> Check:
    """The check of the tickets properties, on a board with those columns."""
    from ponos import health

    config = _config("")
    config.notion = settings
    board = _HealthBoard({name: {"type": kind} for name, kind in schema.items()})
    found = health._schema(
        config,
        board,  # type: ignore[arg-type]  # a fake: a board in memory
        workspace.Workspace(tickets="db", projects="projects", agents="agents"),
    )
    return next(check for check in found if check.code == "notion.columns")


class _DoctorBoard(_HealthBoard):
    """A tickets database that offers these statuses — or refuses, or hides its comments."""

    def __init__(self, offered: list[str], *, refusal: str = "", unread: str = "") -> None:
        super().__init__({"Status": {"type": "status", "status": {"options": []}}})
        self.offered = offered
        self.refusal = refusal
        self.unread = unread
        self.tickets = [type("Page", (), {"id": "p1"})()]

    def my_name(self) -> str:
        if self.refusal:
            raise store.StoreError(self.refusal)
        return "Ponos"

    def schema(self, database_id: str) -> dict[str, str]:
        if self.refusal:
            raise store.StoreError(self.refusal)
        return {"Status": "status"}

    def options(self, database_id: str, name: str) -> list[str]:
        return self.offered

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Any]:
        return self.tickets

    def comments(self, page_id: str) -> list[store.Comment]:
        if self.unread:
            raise store.StoreError(self.unread)
        return []


EVERY_STATUS = [
    "Ready",
    "In progress",
    "In review",
    "Validated",
    "Done",
    "Failed",
    "Blocked",
    "Cancelled",
    "Paused",
]
SPACE = workspace.Workspace(tickets="db")


@case
def health_names_every_column_the_board_lacks_and_what_each_costs() -> None:
    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    complete = {
        settings.prop(key): kinds_accepted[0] for key, (kinds_accepted, _) in store.COLUMNS.items()
    }
    assert _columns(settings, complete).state == "ok"

    lacking = {name: kind for name, kind in complete.items() if name not in ("Runner", "Progress")}
    columns = _columns(settings, lacking)
    assert columns.state == "error" and columns.params["missing"] == "“Runner”, “Progress”"
    costs = {note["name"]: " ".join(note["said"]) for note in columns.notes}
    assert "which machine took a ticket is not written" in costs["Runner"], costs
    assert "nothing says what a session is doing" in costs["Progress"], costs
    assert columns.fix and columns.fix["action"] == "notion_columns", "init adds the missing ones"

    retyped = _columns(settings, {**complete, "Cost": "rich_text"})
    assert retyped.state == "error"
    assert "“Cost” (rich_text ≠ number)" in retyped.params["wrong"], retyped.params

    # The configuration of the 1st of October: `agent = "Agent"`, on a board
    # that has no column by that name — nor by the Runner one.
    renamed = C.Notion(properties={**C._DEFAULT_PROPERTIES, "agent": "Agent"})
    board = {name: kind for name, kind in complete.items() if name not in ("Agent", "Runner")}
    columns = _columns(renamed, board)
    assert columns.params["missing"] == "“Agent”", "named once, though two settings read it"
    agent = next(note for note in columns.notes if note["name"] == "Agent")["said"]
    assert len(agent) == 2 and "which machine took a ticket" in " ".join(agent), agent


@case
def health_counts_a_missing_status_and_says_what_cancelled_and_a_draft_are() -> None:
    from ponos import health

    config = _config("")

    def statuses(offered: list[str], settings: C.Config = config) -> list[Check]:
        board = _DoctorBoard(offered)
        found = health._schema(settings, board, SPACE) + health._other_statuses(  # type: ignore[arg-type]  # a fake: a board in memory
            settings,
            board,  # type: ignore[arg-type]  # a fake: a board in memory
            SPACE,
        )
        return [check for check in found if check.code != "notion.columns"]

    found = statuses(EVERY_STATUS)
    assert _verdicts(found) == [
        ("notion.statuses", "ok"),
        ("notion.cancelled", "ok"),
        ("notion.paused", "ok"),
        ("notion.draft", "info"),
    ], found

    # Validated is one of the statuses the runner moves a ticket through: the
    # dashboard always counted it missing, and so did `doctor` since it read the
    # dashboard's checks — the one verdict kept where the two disagreed.
    found = statuses([s for s in EVERY_STATUS if s != "Validated"])
    assert ("notion.statuses", "error") in _verdicts(found)
    assert "“Validated”" in found[0].params["missing"]

    found = statuses([s for s in EVERY_STATUS if s != "Cancelled"])
    assert ("notion.statuses", "ok") in _verdicts(found)
    assert ("notion.cancelled", "warn") in _verdicts(found)
    assert "no column to give a ticket up in" in _lines(found)

    found = statuses([s for s in EVERY_STATUS if s != "Ready"])
    assert found[0].state == "error" and found[0].params["missing"] == "“Ready”"
    assert "available: In progress" in found[0].evidence

    drafted = _config('[notion.status]\ndraft = "Ready"\n')
    assert ("notion.draft", "error") in _verdicts(statuses(EVERY_STATUS, drafted))
    elsewhere = _config('[notion.status]\ndraft = "Idea"\n')
    assert ("notion.draft", "error") in _verdicts(statuses(EVERY_STATUS, elsewhere))
    assert ("notion.draft", "ok") in _verdicts(statuses([*EVERY_STATUS, "Idea"], elsewhere))
    gave_up = _config('[notion.status]\ncancelled = "Done"\n')
    assert ("notion.cancelled", "error") in _verdicts(statuses(EVERY_STATUS, gave_up))
    found = statuses([s for s in EVERY_STATUS if s != "Paused"])
    assert ("notion.paused", "warn") in _verdicts(found)
    assert "no column to pause a ticket in" in _lines(found)
    stopped = _config('[notion.status]\npaused = "Blocked"\n')
    assert ("notion.paused", "error") in _verdicts(statuses(EVERY_STATUS, stopped))

    found = statuses([])
    assert _verdicts(found) == [("notion.statuses", "warn")], "nothing to check against"


@case
def health_says_a_type_not_offered_yet_and_whether_an_empty_one_is_classified() -> None:
    from ponos import health

    settings, board = _health_board()
    config = _config("")
    config.notion = settings
    space = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    found = health._types(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert ("notion.types", "ok") in _verdicts(found), found
    assert ("settings.classify", "ok") in _verdicts(found)

    board.properties[settings.prop("type")] = {"type": "select", "select": {"options": []}}
    config.runner.classify = False
    found = health._types(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert _verdicts(found) == [("notion.types", "warn"), ("settings.classify", "warn")], found
    assert "“Code”" in found[0].params["missing"]
    assert health._types(config, _DoctorBoard([]), SPACE) == [], "no Type property, no line"  # type: ignore[arg-type]  # a fake: a board in memory


@case
def health_counts_comments_it_is_refused_but_not_one_it_could_not_read_once() -> None:
    from ponos import health

    config = _config("")
    found = health._comments(config, _DoctorBoard([], unread="403 restricted"), SPACE)  # type: ignore[arg-type]  # a fake: a board in memory
    assert found[0].state == "error" and "Read comments" in found[0].steps[0]
    found = health._comments(config, _DoctorBoard([], unread="502 bad gateway"), SPACE)  # type: ignore[arg-type]  # a fake: a board in memory
    assert found[0].state == "warn" and found[0].evidence == "502 bad gateway"
    found = health._comments(config, _DoctorBoard([]), SPACE)  # type: ignore[arg-type]  # a fake: a board in memory
    assert found[0].state == "ok"
    assert ("settings.reply", "ok") in _verdicts(found), "it answers by default"
    empty = _DoctorBoard([])
    empty.tickets = []
    quiet = _config("[runner]\nreply = false\nunblock = false\n")
    found = health._comments(quiet, empty, SPACE)  # type: ignore[arg-type]  # a fake: a board in memory
    assert {check.state for check in found} == {"info"}, found


@case
def health_says_what_keeps_a_schedule_from_making_its_ticket() -> None:
    from support import _schedule_page

    from ponos import health

    class Schedules(_DoctorBoard):
        def __init__(self, pages: list[store.Page], schema: dict[str, str]) -> None:
            super().__init__(EVERY_STATUS)
            self.pages, self.properties_of = pages, schema

        def schema(self, database_id: str) -> dict[str, str]:
            return self.properties_of if database_id == "schedules" else {"Status": "status"}

        def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[Any]:
            return self.pages if database_id == "schedules" else self.tickets

    config = _config("")
    assert _verdicts(health._schedules(config, Schedules([], {}), SPACE)) == [  # type: ignore[arg-type]  # a fake: a board in memory
        ("notion.schedules", "info")
    ], "no database, nothing repeats: not a fault"

    space = workspace.Workspace(tickets="db", schedules="schedules")
    shape = {
        config.notion.prop(key): kind for key, kind, _ in health.SCHEDULE_COLUMNS if key != "day"
    }
    late = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    soon = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    pages = [
        _schedule_page("s1", name="Weekly review", next=soon),
        _schedule_page("s2", name="Forgotten", next=late),
        _schedule_page("s3", name="Paused", next=late, active=False),
        _schedule_page("s4", name="Nonsense", cadence="Fortnightly"),
    ]
    found = health._schedules(config, Schedules(pages, shape), space)  # type: ignore[arg-type]  # a fake: a board in memory
    missing = next(check for check in found if check.state == "warn")
    assert missing.params["missing"] == "“Day”" and missing.notes[0]["said"], missing
    by_name = {check.params.get("schedule"): check for check in found if "schedule" in check.params}
    assert by_name["Weekly review"].state == "ok"
    assert by_name["Forgotten"].state == "error" and "never born" in by_name["Forgotten"].said
    assert by_name["Paused"].state == "info"
    assert by_name["Nonsense"].state == "error" and by_name["Nonsense"].evidence
    assert health.problems(found) == 2

    computed = {**shape, config.notion.prop("next_run"): "formula"}
    found = health._schedules(config, Schedules(pages, computed), space)  # type: ignore[arg-type]  # a fake: a board in memory
    unwritable = [check for check in found if check.params.get("kind") == "formula"]
    assert unwritable and unwritable[0].state == "warn", "a Next nobody can write never moves"
    assert unwritable[0].params["name"] == config.notion.prop("next_run")
    linked = {**shape, config.notion.prop("last_ticket"): "rollup"}
    found = health._schedules(config, Schedules(pages, linked), space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert any(c.state == "warn" and c.params.get("kind") == "rollup" for c in found)

    unread = _config("[runner]\nschedule = false\n")
    found = health._schedules(unread, Schedules([], shape), space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert ("notion.schedules", "warn") in _verdicts(found), "read by nobody"


@case
def health_reads_a_markdown_board_to_the_end_and_finds_nothing_wrong_with_a_new_one() -> None:
    from ponos import health

    directory = Path(tempfile.mkdtemp())
    config = _config(f'[storage]\nmode = "markdown"\npath = "{directory}/board"\n')
    found, space = health._board(config, store.open(config))
    assert health.problems(found) == 0, _lines(found)
    assert space is None, "only a Notion board's projects are looked through one by one"
    said = _lines(found)
    assert "Not created yet" in said and "Notion is never asked anything" in said
    assert "No ticket yet: nothing to read a discussion on" in said
    for code in ("notion.tickets", "notion.columns", "notion.statuses", "notion.comments"):
        assert code in said, code
    assert "notion.token" not in said and "notion.workspace" not in said


@case
def health_stops_on_a_board_it_cannot_reach_and_says_why() -> None:
    from ponos import health

    config = _config("")
    found, space = health._board(config, _DoctorBoard([], refusal="401 unauthorized"))  # type: ignore[arg-type]  # a fake: a board in memory
    assert space is None and _verdicts(found) == [("notion.token", "error")]
    assert found[0].evidence == "401 unauthorized"

    class Unshared(_DoctorBoard):
        def schema(self, database_id: str) -> dict[str, str]:
            raise store.StoreError("404 object not found\nshare it with the integration")

    with _patched(workspace, resolve=lambda client, settings: workspace.Workspace(tickets="abc")):
        found, space = health._board(config, Unshared(EVERY_STATUS))  # type: ignore[arg-type]  # a fake: a board in memory
        assert _verdicts(found)[-1] == ("notion.tickets", "error"), found
        assert "share it with the integration" in found[-1].evidence, "every line of it"
        found, space = health._board(config, _DoctorBoard(EVERY_STATUS))  # type: ignore[arg-type]  # a fake: a board in memory
    assert ("notion.tickets", "ok") in _verdicts(found)
    assert "readable: 1 properties" in _lines(found)


@case
def health_says_which_provider_answers_and_counts_one_that_cannot() -> None:
    from support import _saved

    from ponos import health

    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        found = health._provider(_saved('\n[claude]\nprovider = "api_key"\n')[1], installed=True)
        assert health.problems(found) == 1
        said = _lines(found)
        assert "Anthropic API key" in said and "ANTHROPIC_API_KEY" in said, said
        routed = '\n[claude]\nprovider = "openrouter"\n[openrouter]\nkey = "sk-or-1234567890"\n'
        found = health._provider(_saved(routed)[1], installed=True)
    assert health.problems(found) == 0
    said = _lines(found)
    assert 'claude.provider = "openrouter"' in said and "sk-or-…7890" in said
    assert "route_sessions = false" in said, "a provider whose sessions are not on it is said"


@case
def health_says_claude_is_missing_and_asks_the_cli_who_is_signed_in() -> None:
    from ponos import health

    config = _config("")
    with _patched(health.session, available=lambda: None):
        found = health._claude(config)
    assert _verdicts(found) == [("claude.installed", "error"), ("claude.provider", "ok")]

    answers = {
        "--version": subprocess.CompletedProcess([], 0, "1.0.5 (Claude Code)\n", ""),
    }
    with (
        _patched(health.session, available=lambda: "/opt/claude"),
        _patched(health.subprocess, run=lambda command, **_: answers[command[-1]]),
        _patched(
            health.provider,
            cli_login=lambda: type("Login", (), {"ok": False, "said": "not logged in"})(),
        ),
    ):
        found = health._claude(config)
    assert _verdicts(found) == [
        ("claude.version", "error"),
        ("claude.provider", "ok"),
        ("claude.login", "error"),
    ], found
    assert found[0].params == {"version": "1.0.5", "needed": "2.0.0"}


@case
def health_says_which_model_runs_an_empty_ticket_and_whether_fable_is_allowed() -> None:
    from ponos import health

    found = health._models(_config("[runner]\nuse_fable = false\n"))
    fable = next(check for check in found if check.code == "claude.fable")
    assert fable.state == "info" and fable.params["instead"] == "opus"
    found = health._models(_config("[runner]\nuse_fable = true\n"))
    assert ("claude.fable", "ok") in _verdicts(found)
    assert ("claude.model", "ok") in _verdicts(found), "the rules choose an empty model"

    routed = _config(
        '[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n'
        '[runner]\nideas_model = "sonnet"\n'
    )
    found = health._models(routed)
    assert ("claude.ideas", "warn") in _verdicts(found), "a Claude name OpenRouter cannot route"


@case
def health_merges_the_github_app_and_gh_into_one_way_to_reach_github() -> None:
    from ponos import health

    config = _config('[github]\nacme = "acme-bot"\n')
    app = {"slug": "ponos", "install_url": "https://github.com/apps/ponos/installations/new"}
    signed = subprocess.CompletedProcess([], 0, "", "")
    unsigned = subprocess.CompletedProcess([], 1, "", "You are not logged into any GitHub hosts")

    def access(
        apps: list[dict[str, Any]],
        gh: bool,
        answered: subprocess.CompletedProcess[str] = signed,
        token: str = "ghs_x",
        account: str = "",
        code: bool = True,
    ) -> list[Check]:
        with (
            _patched(health.github_app, describe=lambda with_repositories=True: apps),
            _patched(health.github_app, token=lambda owner: token),
            _patched(health.shutil, which=lambda name: f"/usr/bin/{name}" if gh else None),
            _patched(health.subprocess, run=lambda command, **_: answered),
            _patched(health.git, account_token=lambda name: account),
        ):
            return health._github_access(config, code=code)

    installed = [{**app, "error": "", "installations": [{"account": "acme", "selection": "all"}]}]
    assert _verdicts(access(installed, gh=True, account="gho_x")) == [
        ("github.access", "ok"),
        ("github.access", "ok"),
        ("github.account", "ok"),
    ]
    # Beside an App, `gh` missing or signed out is a warning; alone, an error.
    assert _verdicts(access(installed, gh=False)) == [
        ("github.access", "ok"),
        ("github.access", "warn"),
    ]
    assert ("github.access", "warn") in _verdicts(access(installed, gh=True, answered=unsigned))
    assert _verdicts(access([], gh=False)) == [("github.access", "error")]
    alone = access([], gh=True, answered=unsigned)
    assert ("github.access", "error") in _verdicts(alone)
    assert ("github.account", "error") in _verdicts(alone), "[github] names nobody signed in"
    # Without a project that has a repository, GitHub not connected is only said.
    assert _verdicts(access([], gh=False, code=False)) == [("github.access", "info")]
    assert ("github.access", "info") in _verdicts(
        access([], gh=True, answered=unsigned, code=False)
    )

    nowhere = [{**app, "error": "", "installations": []}]
    assert _verdicts(access(nowhere, gh=True, account="x"))[0] == ("github.access", "error")
    broken = [{**app, "error": "401 bad credentials", "installations": []}]
    assert access(broken, gh=True, account="x")[0].evidence == "401 bad credentials"
    tokenless = access(installed, gh=True, token="", account="x")
    assert tokenless[0].state == "error" and tokenless[0].params["account"] == "acme"


@case
def doctor_counts_github_missing_only_once_a_project_has_a_repository() -> None:
    """gh is optional: a board of writing tickets does not need it, a code project does."""
    from ponos import health

    config = _config("")
    nothing: Callable[..., list[Check]] = lambda *_, **__: []  # noqa: E731
    project = {"id": "p1", "name": "Site", "repository": "acme/site", "path": ""}

    def checked(rows: list[dict[str, str]]) -> list[Check]:
        with (
            _patched(health, _guard_notion=lambda config, client: ([], None)),
            _patched(health, _project_rows=lambda client, space: rows),
            _patched(health, _project=nothing),
            _patched(health, _claude=nothing, _models=nothing, _github_token=nothing),
            _patched(health, _github_billing=nothing, _workspace_root=nothing),
            _patched(health, _machine=nothing, _notifications=nothing, _version=nothing),
            _patched(health, _environment=nothing, _database=nothing, _stray=nothing),
            _patched(health, _settings=nothing),
            _patched(health.github_app, describe=lambda with_repositories=True: []),
            _patched(health.shutil, which=lambda name: None),
        ):
            return health.run(config, object())  # type: ignore[arg-type]

    alone = checked([])
    assert _verdicts(alone) == [("github.access", "info")]
    assert health.problems(alone) == 0, "doctor exits 0 when nothing else is missing"
    assert "no pull request" in alone[0].said
    coded = checked([project])
    assert _verdicts(coded) == [("github.access", "error")]
    assert health.problems(coded) == 1


@case
def health_says_who_the_github_token_is_and_what_it_lacks() -> None:
    from ponos import health

    def said(**answers: Callable[..., Any]) -> list[Check]:
        values = {
            "unavailable": lambda: "",
            "token": lambda: "github_pat_x",
            "source": lambda: "PONOS_GITHUB_TOKEN",
            **answers,
        }
        with _patched(health.github_token, **values):
            return health._github_token()

    assert _verdicts(said(token=lambda: "")) == [("github.token", "info")]
    assert said(unavailable=lambda: "pass: no such item")[0].state == "error"

    def refused(value: str) -> dict[str, Any]:
        raise health.github_token.GithubTokenError("401 Bad credentials")

    assert said(check=refused)[0].evidence == "401 Bad credentials"
    lacking = {
        "login": "salva",
        "kind": "fine-grained",
        "repositories": ["a/b"],
        "writable": [],
        "missing": [{"permission": "contents", "level": "write"}],
        "warnings": ["no workflows permission"],
    }
    found = said(check=lambda value: lacking)
    assert _verdicts(found) == [("github.token", "error"), ("github.token", "warn")]
    assert found[0].params["needs"] == "contents (write)"
    found = said(check=lambda value: {**lacking, "missing": [], "warnings": []})
    assert _verdicts(found) == [("github.token", "ok")]


@case
def health_looks_through_every_repository_of_the_workspace_folder() -> None:
    from ponos import health

    missing = _config('[runner]\nworkspace_root = "/nonexistent/workspace"\n')
    assert _verdicts(health._workspace_root(missing)) == [("projects.workspace", "error")]

    root = Path(tempfile.mkdtemp())
    repo = root / "site"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/site.git"],
        check=True,
    )
    config = _config(f'[runner]\nworkspace_root = "{root}"\n')
    with (
        _git_answering(default_branch=lambda repo: "dev", ci_at_push=lambda *_: "none"),
        _patched(health.github_app, covers=lambda name, owner: False),
    ):
        found = health._workspace_root(config)
    assert _verdicts(found) == [
        ("projects.workspace", "ok"),
        ("projects.ci", "warn"),
        ("github.reach", "warn"),
    ], found
    assert found[1].params == {"repository": "site", "base": "dev"}
    assert found[2].params == {"repository": "acme/site"}


@case
def health_says_the_tools_the_machine_lacks() -> None:
    from ponos import health

    with _patched(health.shutil, which=lambda name: None):
        found = health._tools()
    assert _verdicts(found) == [("machine.git", "error"), ("machine.ffmpeg", "info")]
    with _patched(health.shutil, which=lambda name: f"/usr/bin/{name}"):
        found = health._tools()
    assert _verdicts(found) == [("machine.git", "ok"), ("machine.ffmpeg", "ok")]
    assert found[0].params["version"].startswith("git version"), found[0].params


@case
def health_warns_about_ffmpeg_only_once_a_video_was_sent(state_home: Path) -> None:
    from ponos import health

    with _patched(health.shutil, which=lambda name: None):
        assert ("machine.ffmpeg", "info") in _verdicts(health._tools())
        folder = state_home / "web" / "attachments" / "chat"
        folder.mkdir(parents=True)
        (folder / "1-notes.txt").write_text("x")
        assert ("machine.ffmpeg", "info") in _verdicts(health._tools()), "a document is no video"
        (folder / "2-demo.mp4").write_bytes(b"x")
        assert ("machine.ffmpeg", "warn") in _verdicts(health._tools())


@case
def health_calls_desktop_notifications_not_applicable_without_a_display() -> None:
    from ponos import health

    desktop = _config("[notify]\ndesktop = true\n")
    for display, state in ((False, "info"), (True, "warn")):
        with (
            _patched(health.channels, open=lambda settings: []),
            _patched(health.shutil, which=lambda name: None),
            _patched(health.installation, _has_display=lambda display=display: display),
            _patched(C, in_container=lambda: False),
        ):
            found = health._notifications(desktop)
        assert found[0].code == "machine.desktop" and found[0].state == state, found[0]
    with _patched(health.sys, platform="linux"), _patched(health.os, environ={}):
        assert not health._has_display()
    with _patched(health.sys, platform="linux"), _patched(health.os, environ={"DISPLAY": ":0"}):
        assert health._has_display()


@case
def health_says_the_disk_space_and_what_tidies_it(state_home: Path) -> None:
    from ponos import health

    def disk(body: str, room: tuple[int, int] | None) -> list[Check]:
        with _patched(health.resources, disk_mb=lambda path: room):
            return health._disk(_config(body))

    found = disk("[runner]\nmin_free_disk_mb = 5120\n", (90000, 100000))
    assert ("machine.disk", "ok") in _verdicts(found) and health.problems(found) == 0
    assert ("machine.residue", "ok") in _verdicts(found)
    found = disk("[runner]\nmin_free_disk_mb = 5120\n", (1000, 100000))
    assert ("machine.disk", "error") in _verdicts(found), "no ticket starts under the floor"
    found = disk("[runner]\nmin_free_disk_mb = 0\n", (1000, 100000))
    assert ("machine.disk", "info") in _verdicts(found) and health.problems(found) == 0
    assert ("machine.disk", "warn") in _verdicts(disk("", None)), "the guard cannot tell"
    found = disk("[runner]\nlog_retention_days = 0\n", (90000, 100000))
    assert ("machine.tidy", "warn") in _verdicts(found)

    (state_home / "worktrees" / "leftover" / "node_modules").mkdir(parents=True)
    found = disk("", (90000, 100000))
    assert ("machine.residue", "warn") in _verdicts(found), _lines(found)


@case
def health_reports_what_others_can_read_in_the_state_and_tightens_it(state_home: Path) -> None:
    from ponos import health

    config = _config("")
    talk = state_home / "web" / "attachments" / "talk"
    talk.mkdir(parents=True)
    for directory in (talk, *talk.parents):
        if directory == state_home.parent:
            break
        directory.chmod(0o700)
    found = health._private_state()
    assert _verdicts(found) == [("machine.private", "ok")], _lines(found)

    shot = state_home / "web" / "attachments" / "talk" / "abc-screenshot.png"
    shot.write_bytes(b"png")
    shot.chmod(0o664)
    (state_home / "web" / "attachments").chmod(0o775)
    checkout = state_home / "worktrees" / "ticket" / "README.md"
    checkout.parent.mkdir(parents=True)
    checkout.write_text("the project's own file\n")
    checkout.chmod(0o644)
    found = health._private_state()
    assert _verdicts(found) == [("machine.private", "warn")], _lines(found)
    assert found[0].params["count"] == "2", "a clone's files are the project's: not walked"
    assert found[0].fix and found[0].fix["action"] == "state_private"

    state_home.chmod(0o755)
    assert _verdicts(health._private_state()) == [("machine.private", "error")]

    done = health.fix(config, None, "state_private", confirmed=True)  # type: ignore[arg-type]  # a fake: a board in memory
    assert done == "3 entries tightened", done
    assert shot.stat().st_mode & 0o777 == 0o600
    assert state_home.stat().st_mode & 0o777 == 0o700
    assert checkout.stat().st_mode & 0o777 == 0o644
    assert _verdicts(health._private_state()) == [("machine.private", "ok")]
    french = _french()
    for check in found:
        for sentence in (check.title, check.said, check.cause, *check.steps):
            assert f'"{sentence}"' in french, f"nothing translates “{sentence}”"


@case
def health_says_when_memory_is_short_and_when_it_cannot_tell() -> None:
    from ponos import health

    config = _config("[runner]\nmin_free_memory_mb = 2048\n")
    for free, expected, words in (
        (100, "warn", "100 MB available, under runner.min_free_memory_mb (2048 MB)"),
        (4096, "ok", "4096 MB available (a session starts above 2048 MB)"),
        (None, "info", "the memory guard cannot tell"),
    ):
        with _patched(health.resources, available_mb=lambda free=free: free):
            found = health._memory(config)
        assert found[0].state == expected and words in _lines(found), _lines(found)


@case
def health_says_when_the_load_is_too_high_and_when_it_cannot_tell() -> None:
    from ponos import health

    config = _config("[runner]\nmax_load_per_core = 1.5\n")
    for measured, expected, words in (
        ((74.0, 20), "warn", "Load 74.0 on 20 cores, above runner.max_load_per_core (1.5, so 30)"),
        ((12.0, 20), "ok", "Load 12.0 on 20 cores (a session starts at 30 or below)"),
        (None, "info", "the load guard cannot tell"),
    ):
        with _patched(health.resources, load=lambda measured=measured: measured):
            found = health._load(config)
        assert found[0].state == expected and words in _lines(found), _lines(found)
    off = _config("[runner]\nmax_load_per_core = 0\n")
    with _patched(health.resources, load=lambda: (74.0, 20)):
        assert health._load(off)[0].state == "info"


@case
def health_says_how_many_workers_a_session_is_given() -> None:
    from ponos import health

    for written, words in (
        (
            "max_concurrent = 7\n",
            "take 2 workers at most: 20 cores shared by runner.max_concurrent (7)",
        ),
        ("session_workers = 6\n", "runner.session_workers = 6"),
    ):
        with _patched(health.resources, cores=lambda: 20):
            found = health._workers(_config("[runner]\n" + written).runner)
        assert found.state == "info" and words in _lines([found]), _lines([found])


@case
def health_says_a_timer_that_will_never_fire_and_how_often_a_run_comes() -> None:
    from ponos import health
    from ponos.systemd import Timer

    assert health._timer(Timer("enabled", substate="waiting", armed=True)).state == "ok"
    running = health._timer(Timer("enabled", substate="running"))
    assert running.state == "ok" and "in progress" in running.said
    assert health._timer(Timer("enabled", substate="elapsed")).state == "error", "stalled"
    assert health._timer(Timer("disabled")).state == "error"

    config = _config("[runner]\ninterval_seconds = 120\nprogress = false\n")
    with (
        _patched(health.shutil, which=lambda name: f"/usr/bin/{name}"),
        _patched(
            health.systemd,
            read=lambda: Timer("enabled", substate="waiting", armed=True),
            priority=lambda: {"Nice": "10", "IOSchedulingClass": "3"},
        ),
    ):
        found = health._runner(config)
    assert _verdicts(found) == [
        ("machine.runner", "info"),
        ("machine.runner", "ok"),
        ("machine.priority", "ok"),
        ("settings.permissions", "info"),
        ("settings.workers", "info"),
        ("settings.progress", "info"),
    ], found
    assert found[0].params["interval"] == "120"


@case
def health_does_not_tick_a_machine_without_systemd_and_without_a_loop() -> None:
    from ponos import health

    config = _config("[runner]\ninterval_seconds = 120\n")
    for looping, state in ((False, "warn"), (True, "ok")):
        with (
            _patched(health.shutil, which=lambda name: None),
            _patched(health.systemd, looping=lambda looping=looping: looping),
        ):
            found = health._runner(config)
        assert found[0].code == "machine.runner" and found[0].state == state, found[0]
        assert "ponos run --every" in found[0].said


@case
def health_says_the_rank_the_sessions_run_at() -> None:
    from ponos import health

    shown = {
        "Nice": "10",
        "CPUWeight": "20",
        "IOSchedulingClass": "3",
        "MemoryHigh": str(18 * 2**30),
    }
    background = health._priority(shown)
    assert background and background.state == "ok", background
    assert background.text(background.said) == (
        "Sessions in the background: nice 10, CPUWeight 20, I/O idle, MemoryHigh 18.0 GB."
    )
    former = health._priority(
        {"Nice": "0", "CPUWeight": "[not set]", "IOSchedulingClass": "2", "MemoryHigh": "infinity"}
    )
    assert former and former.state == "warn" and "ponos enable" in former.steps[0], former
    assert "MemoryHigh infinity" in former.text(former.said)
    assert health._priority({}) is None, "no systemd, nothing to say"
    french = _french()
    for check in (background, former):
        for sentence in (check.title, check.said, check.cause, *check.steps):
            assert not sentence or f'"{sentence}"' in french, (
                f"nothing translates “{sentence}” — add it to health-french.ts"
            )


@case
def health_says_who_may_answer_on_each_channel() -> None:
    from support import _StubChannel

    from ponos import health

    open_group = _StubChannel([])
    open_group.check = lambda: "@ponos_bot in Team"  # type: ignore[method-assign]  # a double: who the bot is
    config = _config('[notify]\ndesktop = false\n[notify.telegram]\ntoken = "1:a"\nchat = "-100"\n')
    with _patched(health.channels, open=lambda settings: [open_group]):
        found = health._notifications(config)
    assert ("machine.desktop", "info") in _verdicts(found)
    assert ("machine.notify", "ok") in _verdicts(found)
    assert ("machine.answerers", "warn") in _verdicts(found), "a group anybody can write in"

    private = _config('[notify.telegram]\ntoken = "1:a"\nchat = "42"\n')
    with _patched(health.channels, open=lambda settings: [open_group]):
        assert ("machine.answerers", "info") in _verdicts(health._notifications(private))
    open_group.allowed = frozenset({"7"})
    with _patched(health.channels, open=lambda settings: [open_group]):
        assert ("machine.answerers", "ok") in _verdicts(health._notifications(config))

    def refusing() -> str:
        raise health.channels.ChannelError("not_in_channel — invite the bot")

    open_group.check = refusing  # type: ignore[method-assign]  # a double: refused
    with _patched(health.channels, open=lambda settings: [open_group]):
        found = health._notifications(config)
    refused = next(check for check in found if check.state == "error")
    assert refused.said == health.NOTIFY_SAID["not_in_channel"]

    desktop = _config("[notify]\ndesktop = true\n")
    with (
        _patched(health.channels, open=lambda settings: []),
        _patched(health.shutil, which=lambda name: None),
        _patched(health.installation, _has_display=lambda: True),
    ):
        found = health._notifications(desktop)
    assert _verdicts(found) == [("machine.desktop", "warn"), ("machine.notify", "info")]


@case
def health_says_the_version_and_asks_the_remote_only_for_doctor() -> None:
    from ponos import health

    config = _config("")
    asked: list[str] = []
    current, newer = "a" * 40, "b" * 40

    def check(**_: Any) -> update.Status:
        asked.append("remote")
        return update.Status(current=current, latest=newer, tag="v9.9.9")

    with _patched(
        update,
        check=check,
        remembered=lambda: update.Status(current=current, latest=current),
    ):
        stale = health._version(config, remote=True)
        known = health._version(config, remote=False)
    assert asked == ["remote"], "the dashboard reads what the last check found"
    assert ("machine.version", "warn") in _verdicts(stale)
    assert "v9.9.9 (bbbbbbbb) available" in _lines(stale)
    assert ("machine.version", "ok") in _verdicts(known)
    with _patched(
        update,
        remembered=lambda: update.Status(reason="git fetch: no network"),
    ):
        found = health._version(config, remote=False)
    assert found[1].state == "warn" and found[1].evidence == "git fetch: no network"
    with _environment(PONOS_CONTAINER="1"):
        found = health._version(config, remote=True)
    assert {check.state for check in found} == {"info"}, "an image is its version"


@case
def health_says_whether_the_environment_of_the_version_runs_it() -> None:
    from ponos import health

    with _patched(update, installed_version=lambda: None):
        assert _verdicts(health._environment()) == [("machine.environment", "info")]
    for state, expected in (("ok", "ok"), ("warn", "warn"), ("error", "error")):
        with (
            _patched(update, installed_version=lambda: Path("/opt/app-1234")),
            _patched(health.environment, diagnose=lambda app, state=state: (state, "it says")),
        ):
            found = health._environment()
        assert found[0].state == expected and found[0].evidence == "it says"
    assert found[0].steps, "the command that makes it again"


@case
def health_says_the_database_version_and_refuses_a_newer_one(state_home: Path) -> None:
    from ponos import health

    try:
        found = health._database()
        assert _verdicts(found) == [("machine.database", "ok")]
        assert f"schema version {len(db.MIGRATIONS)} of {len(db.MIGRATIONS)}" in _lines(found)
        db.close()
        raw = sqlite3.connect(state_home / "ponos.db")
        raw.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
        raw.close()
        found = health._database()
        assert found[0].state == "error" and "newer version" in found[0].evidence
    finally:
        db.close()


@case
def health_says_how_to_put_back_the_copy_taken_before_a_migration(state_home: Path) -> None:
    from ponos import health

    location = state_home / "ponos.db"
    try:
        db.open_at(location, db.MIGRATIONS[:-1]).close()
        found = health._database()
        assert _verdicts(found) == [("machine.database", "ok"), ("machine.database", "info")]
        backup = location.with_name(f"ponos.db.v{len(db.MIGRATIONS) - 1}.bak")
        assert found[1].params["backup"] == str(backup)
        assert found[1].params["restore"] == (
            f"rm -f {location}-wal {location}-shm && cp {backup} {location}"
        )
        db.close()
        raw = sqlite3.connect(location)
        raw.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
        raw.close()
        found = health._database()
        assert found[0].state == "error" and "newer version" in found[0].evidence
        assert found[0].params["restore"].endswith(f"cp {backup} {location}"), found[0].params
        assert any("{{restore}}" in step for step in found[0].steps), found[0].steps
    finally:
        db.close()


@case
def health_says_when_the_migrations_are_not_in_the_codes_order(state_home: Path) -> None:
    from test_db import _migrated_by_a_branch

    from ponos import health

    try:
        _migrated_by_a_branch(state_home / "ponos.db")
        found = health._database()
        assert health.problems(found) == 0, "every table is there: a warning, not an error"
        assert found[-1].state == "warn"
        assert "another order" in found[-1].evidence and "stops_have_a_cause" in found[-1].evidence
    finally:
        db.close()


@case
def health_says_what_a_session_left_running() -> None:
    from ponos import health

    with _patched(
        health.leftovers, compose_projects=lambda root: [], processes=lambda root, spared=(): []
    ):
        assert _verdicts(health._stray()) == [("machine.stray", "ok")]
    left = health.leftovers.Project("ponos-1a2b", Path("/state/worktrees/1a2b"))
    with _patched(
        health.leftovers,
        compose_projects=lambda root: [left],
        processes=lambda root, spared=(): [(4242, "npm run dev")],
    ):
        found = health._stray()
    assert _verdicts(found) == [("machine.stray", "warn"), ("machine.stray", "warn")]
    assert found[0].params["name"] == "ponos-1a2b" and found[1].evidence == "4242 npm run dev"
    assert found[1].fix is None, "a process outside any worktree is `clean`'s to decide"


@case
def health_leaves_alone_what_a_session_still_going_runs(state_home: Path) -> None:
    """A live session's `claude`, its MCP servers, its dev server are not left behind yet."""
    import os

    from ponos import health, stopping

    going = health.leftovers.worktrees() / "ponos-0a1b2c3d"
    finished = health.leftovers.worktrees() / "ponos-9f8e7d6c"
    for worktree in (going, finished):
        worktree.mkdir(parents=True)
    stopping._write("40c45168-0af4-8106-bf14-c2f60a1b2c3d", "live", str(os.getpid()))
    children = [subprocess.Popen(["sleep", "300"], cwd=worktree) for worktree in (going, finished)]
    try:
        with _patched(
            health.leftovers,
            compose_projects=lambda root: [
                health.leftovers.Project("ponos-0a1b2c3d", going),
                health.leftovers.Project("ponos-9f8e7d6c", finished),
            ],
        ):
            found = health._stray()
    finally:
        for child in children:
            child.kill()
            child.wait()
    assert _verdicts(found) == [("machine.stray", "warn"), ("machine.stray", "warn")]
    assert found[0].params["name"] == "ponos-9f8e7d6c"
    assert found[1].params == {"name": "ponos-9f8e7d6c", "count": "1"}
    assert found[1].evidence.startswith(str(children[1].pid))


@case
def health_leaves_alone_a_ticket_in_progress_between_two_sessions(state_home: Path) -> None:
    """Its local CI, its rebase: no session is live, the ticket is still this host's."""
    from ponos import health, state

    going = health.leftovers.worktrees() / "ponos-0a1b2c3d"
    going.mkdir(parents=True)
    state.claim("40c45168-0af4-8106-bf14-c2f60a1b2c3d", "Ready")
    child = subprocess.Popen(["sleep", "300"], cwd=going)
    try:
        with _patched(health.leftovers, compose_projects=lambda root: []):
            found = health._stray()
    finally:
        child.kill()
        child.wait()
    assert _verdicts(found) == [("machine.stray", "ok")]


@case
def health_says_a_worktree_s_leftover_processes_in_one_line_and_stops_them(
    state_home: Path,
) -> None:
    from ponos import health

    finished = health.leftovers.worktrees() / "opoil-f0ee7aa7"
    (finished / "frontend").mkdir(parents=True)
    children = [
        subprocess.Popen(["sleep", "300"], cwd=finished / ("frontend" if n % 2 else "."))
        for n in range(5)
    ]
    try:
        with _patched(health.leftovers, compose_projects=lambda root: []):
            found = health._stray()
        assert _verdicts(found) == [("machine.stray", "warn")]
        assert found[0].params == {"name": "opoil-f0ee7aa7", "count": "5"}
        assert found[0].fix is not None
        assert (found[0].fix["action"], found[0].fix["target"]) == (
            "stray_processes",
            "opoil-f0ee7aa7",
        )
        for target, confirmed, refused in (
            ("opoil-f0ee7aa7", False, PermissionError),
            ("../elsewhere", True, LookupError),
        ):
            try:
                health.fix(None, None, "stray_processes", target, confirmed=confirmed)  # type: ignore[arg-type]  # a process, not a board
            except refused:
                pass
            else:
                raise AssertionError(f"{target} stopped (confirmed: {confirmed})")
        assert all(child.poll() is None for child in children), "nothing stopped unasked"
        done = health.fix(None, None, "stray_processes", "opoil-f0ee7aa7", confirmed=True)  # type: ignore[arg-type]  # a process, not a board
        assert done == "5 process(es) stopped"
        assert all(child.wait(timeout=10) is not None for child in children)
    finally:
        for child in children:
            child.kill()
            child.wait()


@case
def health_says_where_the_secrets_are_and_who_can_read_them() -> None:
    from ponos import health

    config = _config("")
    secrets = C.secrets_path(config.path)
    assert _verdicts(health._secrets(config)) == [("settings.secrets", "ok")]
    secrets.chmod(0o644)
    found = health._secrets(config)
    assert found[0].state == "error" and found[0].params["mode"] == "644"
    config.exposed = ("notion.token",)
    secrets.chmod(0o600)
    assert _verdicts(health._secrets(config)) == [("settings.secrets", "error")]


@case
def health_says_a_language_nobody_speaks_here() -> None:
    from ponos import health

    found = health._languages(C.Runner(language="de"))
    assert _verdicts(found) == [("settings.language", "warn"), ("settings.language", "info")]
    assert found[0].params == {"key": "language", "asked": "de"}
    assert _verdicts(health._languages(C.Runner(language="fr"))) == [("settings.language", "info")]


@case
def health_says_what_leaves_the_machine_unread_and_what_cannot_be_merged() -> None:
    from ponos import health

    found = health._validation(
        _config("[runner]\nforce_validated_code = true\npush = false\n").runner
    )
    said = _lines(found)
    assert "Force validated: code" in said
    assert "no pull request is opened to merge" in said
    found = health._validation(_config("[runner]\nrebase = false\n").runner)
    said = _lines(found)
    assert "runner.rebase is off" in said and "Force validated" not in said
    assert health.problems(found) == 0, "a choice, said, never counted"


@case
def health_says_which_key_each_project_is_given_by_the_vault() -> None:
    from ponos import health

    assert _verdicts(health._vault(_config(""))) == [("settings.vault", "info")]
    assert health._vault(_config('[vault]\nprovider = "1pass"\n'))[0].state == "error"
    granted = _config('[vault.projects.Ponos]\nNPM_TOKEN = "env:PONOS_TEST_NPM"\n')
    with _environment(PONOS_TEST_NPM="npm_0123456789abcdef"):
        found = health._vault(granted)
    assert ("settings.vault", "ok") in _verdicts(found) and health.problems(found) == 0
    assert "Ponos is given NPM_TOKEN" in _lines(found) and "npm_0123" not in _lines(found)
    with _environment(PONOS_TEST_NPM=None):
        found = health._vault(granted)
    assert health.problems(found) == 1 and "NPM_TOKEN" in _lines(found)


@case
def health_says_half_a_sign_in_and_a_connector_address_claude_ai_cannot_add() -> None:
    from ponos import health

    found = health._console(_config('[web]\nemail = "me@example.com"\nurl = "http://box.lan"\n'))
    said = _lines(found)
    assert "is opened with its token" in said and "Half a sign-in" in said
    assert "web.url is http://box.lan: claude.ai only adds a connector at an https:// address" in (
        said
    )
    signed = health._console(
        _config(
            '[web]\nemail = "me@example.com"\npassword = "a long one"\nurl = "https://box.ts.net"\n'
        )
    )
    assert health.problems(signed) == 0 and ("settings.mcp", "ok") in _verdicts(signed)
    routed = health._console(_config('[web]\nchat_model = "openai/gpt-5"\n'))
    assert ("settings.chat", "warn") in _verdicts(routed), "an OpenRouter model with no key"


@case
def health_says_whether_the_ideas_schedule_can_fire() -> None:
    from ponos import health

    assert _verdicts(health._ideas(C.Runner())) == [("settings.ideas", "info")]
    found = health._ideas(C.Runner(ideas_schedule="cron", ideas_cron="every day"))
    assert _verdicts(found) == [("settings.ideas", "error")] and "cron line" in found[0].evidence
    found = health._ideas(
        C.Runner(ideas_schedule="daily", ideas_at="09:00", ideas_scope="selected")
    )
    assert ("settings.ideas", "ok") in _verdicts(found)
    assert ("settings.ideas", "warn") in _verdicts(found), "selected, and nothing selected"


# -- `doctor`, the terminal's reading ------------------------------------------


@contextmanager
def _machine(*, healthy: bool = True) -> Iterator[None]:
    """Every probe of the machine answered: a sound one, or one where three things are wrong."""
    from ponos import health
    from ponos.systemd import Timer

    version = subprocess.CompletedProcess([], 0, "2.1.0 (Claude Code)\n", "")
    signed_out = subprocess.CompletedProcess([], 1, "", "You are not logged into any GitHub hosts")
    same = update.Status(current="a" * 40, latest="a" * 40, tag="v1.0.0")
    with (
        _patched(health.session, available=(lambda: "/opt/claude") if healthy else lambda: None),
        _patched(
            health.subprocess,
            run=lambda command, **_: version if healthy or command[0] != "gh" else signed_out,
        ),
        _patched(
            health.provider,
            cli_login=lambda: type("Login", (), {"ok": True, "said": "me@example.com"})(),
        ),
        _patched(health.shutil, which=lambda name: f"/usr/bin/{name}"),
        _patched(
            health.systemd,
            read=lambda: Timer("enabled", substate="waiting", armed=True),
            priority=lambda: {"Nice": "10", "IOSchedulingClass": "3"},
        ),
        _patched(health.github_app, describe=lambda with_repositories=True: []),
        _patched(health.github_token, unavailable=lambda: "", token=lambda: ""),
        _patched(update, check=lambda **_: same, installed_version=lambda: None),
        _patched(
            health.leftovers, compose_projects=lambda root: [], processes=lambda root, spared=(): []
        ),
        _patched(
            health.resources,
            disk_mb=lambda path: (90000 if healthy else 100, 100000),
            available_mb=lambda: 90000,
            load=lambda: (1.0, 8),
        ),
    ):
        yield


@case
def doctor_stops_with_2_on_a_configuration_it_cannot_read() -> None:
    from ponos import __main__ as cli

    with _environment(PONOS_CONFIG=str(Path(tempfile.mkdtemp()) / "config.toml")):
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 2
    assert "configuration not found" in said
    assert "Machine" not in said, "nothing after it is asked"


@case
def doctor_finds_a_sound_installation_in_place_and_a_broken_one_wrong(state_home: Path) -> None:
    from ponos import __main__ as cli

    C.private_state()  # as a launch leaves it, see `__main__`
    root = Path(tempfile.mkdtemp())
    path = root / "config.toml"
    path.write_text(
        f'[storage]\nmode = "markdown"\npath = "{root}/board"\n'
        f'[runner]\nworkspace_root = "{root}"\nmin_free_disk_mb = 5120\n'
    )
    with _environment(PONOS_CONFIG=str(path)), _machine():
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 0, said
    assert said.rstrip().endswith("Everything is in place."), said
    assert "✗" not in said
    for heading in ("Board", "Claude", "GitHub", "Projects", "Machine", "Settings"):
        assert f"\n{heading}\n" in said, heading
    assert "✓ Claude Code version: Claude Code 2.1.0 is installed at /opt/claude." in said

    with _environment(PONOS_CONFIG=str(path)), _machine(healthy=False):
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 1, said
    for line in (
        "✗ Claude Code: Claude Code is not installed on this machine.",
        "✗ Disk space: 100 MB free, under the 5120 MB a ticket needs to start.",
    ):
        assert line in said, line
    # No project has a repository: `gh` signed out is said, not counted.
    assert "  GitHub access: `gh` is not signed in." in said
    assert said.rstrip().endswith("2 problem(s) to fix."), said


@case
def every_sentence_of_a_check_is_translated() -> None:
    """The console hands each template to its dictionary: one missing is English on a French page.

    Every sentence the band can draw, that is: a check that is only ever green,
    or only ever said in grey, never reaches it — and its French would be
    weight in the first load of every French page, for nothing.
    """
    import ast

    from ponos import health

    package = Path(health.__file__).parent
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in package.glob("*.py")]
    sentences: set[str] = set()

    def strings(node: ast.AST) -> Iterator[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.IfExp):
            yield from strings(node.body)
            yield from strings(node.orelse)
        elif isinstance(node, ast.List):
            for item in node.elts:
                yield from strings(item)

    for node in (node for tree in trees for node in ast.walk(tree)):
        # A title or steps said once for several checks are a name's.
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in (
            "title",
            "steps",
        ):
            sentences.update(strings(node.value))
        if not isinstance(node, ast.Call):
            continue
        state = node.args[1] if len(node.args) > 1 else None
        if getattr(node.func, "id", "") == "_check" and getattr(state, "id", "") in ("OK", "INFO"):
            continue
        texts = {
            "_check": node.args[2:4],
            "_fix": node.args[1:3],
            "_installing": node.args[1:],
        }.get(getattr(node.func, "id", ""))
        if texts is None:
            continue
        texts += [keyword.value for keyword in node.keywords if keyword.arg in ("cause", "steps")]
        for text in texts:
            sentences.update(strings(text))
    sentences.add(health.INSTALL_STEP)
    sentences.discard("")
    for _, _, why in health.SCHEDULE_COLUMNS:
        sentences.add(why)
    sentences.update(health.NOTIFY_SAID.values())
    french = _french()

    def translated(sentence: str) -> bool:
        key = re.escape(json.dumps(sentence, ensure_ascii=False))
        if sentence.isidentifier():
            key = f"(?:{key}|{sentence})"
        return re.search(rf"^\s*{key}\s*:", french, re.MULTILINE) is not None

    untranslated = sorted(sentence for sentence in sentences if not translated(sentence))
    assert len(sentences) > 100, len(sentences)
    assert not untranslated, "add them to health-french.ts:\n" + "\n".join(untranslated)


@case
def health_adds_the_type_and_subtype_a_schedules_database_lacks_and_then_says_ok() -> None:
    """“Master Scheluder” had no Type nor Sous-type, and doctor only said so:
    its tickets were born untyped and classified, a code one as « Rédaction »."""
    from ponos import health

    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    config = _config("")
    config.notion = settings
    wanted = provision.schedules_schema(settings, "db", "projects")
    properties = {
        name: {"type": next(iter(shape)), **shape}
        for name, shape in wanted.items()
        if name not in ("Type", "Sous-type")
    }

    class Schedules(_HealthBoard):
        def query(
            self, database_id: str, filter_: dict[str, Any] | None = None
        ) -> list[store.Page]:
            return []

        def resolve_database(self, identifier: str) -> str:
            return identifier

    board = Schedules(properties)
    space = workspace.Workspace(tickets="db", projects="projects", schedules="schedules")
    found = health._schedules(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    missing = next(check for check in found if check.state == health.WARN)
    assert missing.params["missing"] == "“Type”, “Sous-type”", missing
    assert missing.fix and missing.fix["action"] == "notion_schedule_columns", missing

    with _patched(workspace, resolve=lambda backend, settings: space):
        done = health.fix(config, board, "notion_schedule_columns", confirmed=True)  # type: ignore[arg-type]  # a fake: a board in memory
    assert set(board.added) == {"Type", "Sous-type"}, board.added
    assert board.added["Type"] == provision.type_select(settings), "the options of the tickets"
    assert board.added["Sous-type"] == provision.subtype_select()
    assert done == "added Sous-type, Type", done

    board.properties.update(
        {name: {"type": next(iter(shape)), **shape} for name, shape in board.added.items()}
    )
    found = health._schedules(config, board, space)  # type: ignore[arg-type]  # a fake: a board in memory
    assert ("notion.schedules", "ok") in _verdicts(found), found
    assert health.problems(found) == 0


@case
def the_runner_loop_is_told_by_its_pid_file_and_its_command_line(state_home: Path) -> None:
    import subprocess
    import sys

    from ponos import systemd

    web = state_home / "web"
    web.mkdir(parents=True)
    assert not systemd.looping(), "no pid file"
    (web / "run.pid").write_text("not a number\n", encoding="utf-8")
    assert not systemd.looping()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    loop = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "run", "--every"])
    try:
        (web / "run.pid").write_text(f"{sleeper.pid}\n", encoding="utf-8")
        assert not systemd.looping(), "a live process that is not the loop"
        (web / "run.pid").write_text(f"{loop.pid}\n", encoding="utf-8")
        assert systemd.looping()
    finally:
        for process in (sleeper, loop):
            process.kill()
            process.wait()
