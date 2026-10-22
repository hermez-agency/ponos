"""`health.py`: what the dashboard and `ponos doctor` check, and offer to correct."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from support import FRONTEND, _config, case

from ponos import config as C
from ponos import provision, store, workspace

# -- the vault ---------------------------------------------------------------


class _HealthBoard:
    """The few calls `health` makes of a Notion board, over a database held in memory."""

    def __init__(self, properties: dict[str, dict]) -> None:
        self.properties = properties
        self.added: dict = {}

    def forget_database(self, database_id: str) -> None:
        pass

    def database(self, database_id: str) -> dict:
        return {"properties": self.properties}

    def schema(self, database_id: str) -> dict[str, str]:
        return {name: prop["type"] for name, prop in self.properties.items()}

    def options(self, database_id: str, name: str) -> list[str]:
        prop = self.properties.get(name) or {}
        return [
            option["name"] for option in (prop.get(prop.get("type", "")) or {}).get("options", [])
        ]

    def add_properties(self, database_id: str, properties: dict) -> None:
        self.added.update(properties)


def _health_board(skip: tuple[str, ...] = (), statuses: tuple[str, ...] = ()):
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
def health_says_nothing_of_a_board_that_is_complete():
    from ponos import health

    settings, board = _health_board()
    config = _config("")
    config.notion = settings
    found = health._schema(
        config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents")
    )
    assert [check.state for check in found] == [health.OK, health.OK], found


@case
def health_offers_to_add_the_missing_properties_and_does_it_only_once_confirmed():
    from ponos import health

    settings, board = _health_board(skip=("Runner", "Progress"))
    config = _config("")
    config.notion = settings
    found = health._schema(
        config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents")
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
    workspace.resolve = lambda backend, notion_settings: workspace.Workspace(
        tickets="db", projects="projects", agents="agents"
    )
    try:
        try:
            health.fix(config, client, "notion_columns")
        except PermissionError:
            pass
        else:
            raise AssertionError("a fix is never made unasked")
        assert not client.added, "nothing was written before the confirmation"
        health.fix(config, client, "notion_columns", confirmed=True)
    finally:
        workspace.resolve = original
    assert set(client.added) == {"Runner", "Progress"}, client.added


@case
def health_adds_a_missing_status_to_a_select_and_only_says_how_on_a_real_status():
    from ponos import health

    settings, board = _health_board(statuses=("Ready", "In progress", "Done"))
    config = _config("")
    config.notion = settings
    found = health._schema(
        config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents")
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
        config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents")
    )
    statuses = next(check for check in found if check.code == "notion.statuses")
    assert statuses.fix is None and statuses.steps, "Notion cannot widen a status from outside"


@case
def health_names_a_property_once_and_says_what_each_costs_in_french_too():
    from ponos import health

    settings, board = _health_board(skip=("Agent", "Progress"))
    settings.properties["agent"] = "Agent"  # two settings, one property
    config = _config("")
    config.notion = settings
    found = health._schema(
        config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents")
    )
    columns = next(check for check in found if check.code == "notion.columns")
    names = [note["name"] for note in columns.notes]
    assert len(names) == len(set(names)) and "Agent" in names, names
    assert columns.params["missing"].count("“Agent”") == 1, columns.params
    assert not columns.evidence, "the costs are sentences, not what a tool printed"
    french = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    for _, cost in store.COLUMNS.values():
        assert f'"{cost}"' in french, f"nothing translates “{cost}” — add it to french.ts"
    for sentence in health.NOTIFY_SAID.values():
        assert f'"{sentence}"' in french, f"nothing translates “{sentence}” — add it to french.ts"


@case
def health_reports_a_project_whose_folder_is_gone_and_one_with_no_remote():
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
def health_warns_when_two_settings_name_one_property():
    from ponos import health

    settings, board = _health_board()
    settings.properties["agent"] = "Agent"  # the machine, read off the agent's relation
    config = _config("")
    config.notion = settings
    found = health._schema(
        config, board, workspace.Workspace(tickets="db", projects="projects", agents="agents")
    )
    shared = next(check for check in found if check.code == "notion.shared")
    assert shared.state == health.WARN
    assert "“Agent” (agent, role)" in shared.params["shared"], shared.params
    french = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    for sentence in (shared.said, shared.cause, *shared.steps):
        assert f'"{sentence}"' in french, f"nothing translates “{sentence}” — add it to french.ts"
