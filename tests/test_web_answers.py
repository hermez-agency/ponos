"""`web/answers.py`: what the schema says the API answers, for the page's types."""

from __future__ import annotations

import http.client
import json
import threading

from support import _bare_api, case

from ponos import notion, workspace
from ponos.web import answers


@case
def the_schema_says_what_each_route_answers_and_what_the_stream_carries():
    """A route names its answer, and a key that may be missing is not a key with a default.

    `openapi-typescript` reads a default as "always there": a key the answer
    may leave out must be out of `required` without one, or the page would be
    told it can count on it.
    """
    from ponos.web import app

    schema = app.schema()
    ok = schema["paths"]["/api/board"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/Board"), ok
    events = schema["paths"]["/api/events"]["get"]["responses"]["200"]["content"]
    assert events["application/json"]["schema"]["$ref"].endswith("/Stream"), events
    shapes = schema["components"]["schemas"]
    ticket = shapes["Ticket"]
    assert "project_id" not in ticket["required"] and "column" in ticket["required"]
    assert "default" not in ticket["properties"]["project_id"], ticket["properties"]["project_id"]
    assert "default" not in ticket["properties"]["block"], ticket["properties"]["block"]
    assert ticket["properties"]["project_id"]["description"].startswith("The project's page id")
    # The names the page reads, not the ones Python could not use.
    assert "validate" in shapes["Board"]["properties"], shapes["Board"]["properties"]
    assert "from" in shapes["Statistics"]["required"], shapes["Statistics"]["required"]
    assert "global" in shapes["Validation"]["required"], shapes["Validation"]["required"]
    # A body the API reads and a shape it answers never share a name.
    assert "Decision" in shapes and "Chosen" in shapes, sorted(shapes)


@case
def every_route_that_answers_json_names_its_shape():
    """No route left for the page to type by hand — but the three that answer bytes.

    A picture, a file of the board (a redirect to it) and a file of the
    conversation are not JSON, and their schema does not say they are.
    """
    from ponos.web import app

    unnamed = []
    for path, operations in app.schema()["paths"].items():
        for method, operation in operations.items():
            content = operation["responses"]["200"].get("content", {})
            if not content.get("application/json", {}).get("schema"):
                assert not content, (method, path, content)
                unnamed.append(f"{method} {path}")
    assert sorted(unnamed) == [
        "get /api/chat/attachments/{identifier}",
        "get /api/files/{file_id}",
        "get /api/projects/{project_id}/image/{slot}",
    ], unnamed


# -- the goals -----------------------------------------------------------------


def _row(page_id: str, title: str, **columns: dict) -> notion.Page:
    return notion.Page(
        id=page_id, url=f"https://notion.so/{page_id}", title=title, properties=columns
    )


def _text(value: str) -> dict:
    return {"type": "rich_text", "rich_text": [{"plain_text": value}]}


class _GoalsClient:
    """A workspace with two goals and a project, and nothing that reaches out."""

    def schema(self, database: str) -> dict[str, str]:
        return {"Statut": "status"} if database == "goals-db" else {}

    def options(self, database: str, name: str) -> list[str]:
        return ["À faire", "En cours", "Fait"] if (database, name) == ("goals-db", "Statut") else []

    def query(self, database: str, *args, **kwargs) -> list[notion.Page]:
        if database == "goals-db":
            return [
                _row(
                    "aaaa-goal",
                    "Lancer la v1",
                    Critère=_text("dix clients payants"),
                    Échéance={"type": "date", "date": {"start": "2026-12-31", "end": None}},
                    Statut={"type": "status", "status": {"name": "En cours"}},
                    Priorité={"type": "select", "select": {"name": "Haute"}},
                    Projets={"type": "relation", "relation": [{"id": "pppp-site"}]},
                ),
                _row("bbbb-goal", "Ranger"),
                # A row nobody named is no goal: nothing to call it by.
                _row("cccc-goal", ""),
            ]
        if database == "projects-db":
            return [_row("pppp-site", "Website")]
        return []


def _goals_api():
    api = _bare_api(_GoalsClient())
    api._runner._workspace = workspace.Workspace(
        tickets="tickets-db", projects="projects-db", goals="goals-db"
    )
    api._goals = {}
    api._goals_at = 0.0
    return api


@case
def a_goal_counts_the_tickets_the_board_lists_column_by_column():
    """The progress is the board's, counted: no rollup read, a Markdown board has none."""
    api = _goals_api()
    tickets = [
        {"id": "t1", "goal_id": "aaaagoal", "column": "done"},
        {"id": "t2", "goal_id": "aaaagoal", "column": "done"},
        {"id": "t3", "goal_id": "aaaagoal", "column": "running"},
        {"id": "t4", "goal_id": "", "column": "done"},
        {"column": "ready"},
    ]
    api.board = lambda max_age=0.0: {"tickets": tickets}
    said = api.goals()
    assert said["configured"] is True
    # Which board, for the page that would say "Notion" on a board of files.
    assert said["storage"] == "notion", said
    assert said["statuses"] == ["À faire", "En cours", "Fait"], said
    assert [goal["name"] for goal in said["goals"]] == ["Lancer la v1", "Ranger"], said
    launch, tidy = said["goals"]
    assert launch["tickets"] == {"done": 2, "running": 1}, launch
    assert launch["criterion"] == "dix clients payants" and launch["due"] == "2026-12-31"
    # A word `priority.WORDS` does not know is read as an empty cell would be.
    assert launch["status"] == "En cours" and launch["priority"] == 50
    assert launch["projects"] == ["Website"] and launch["id"] == "aaaagoal"
    assert [ticket["id"] for ticket in launch["linked"]] == ["t1", "t2", "t3"], launch
    assert tidy["tickets"] == {} and tidy["description"] == "" and tidy["projects"] == []
    answers.Goals.model_validate(said)


@case
def a_card_names_the_goal_it_serves_and_a_card_without_one_says_nothing():
    api = _goals_api()
    goals = api._goal_index()
    pointing = _row("t-1", "un", Objectif={"type": "relation", "relation": [{"id": "aaaa-goal"}]})
    elsewhere = _row("t-2", "deux", Objectif={"type": "relation", "relation": [{"id": "zzzz"}]})
    card = api._ticket(pointing, {}, {}, "", goals)
    assert (card["goal"], card["goal_id"]) == ("Lancer la v1", "aaaagoal"), card
    for page in (elsewhere, _row("t-3", "trois")):
        card = api._ticket(page, {}, {}, "", goals)
        assert (card["goal"], card["goal_id"]) == ("", ""), card


class _ClosedGoalsClient(_GoalsClient):
    """The same goals, a met one beside them, on a board that can point at a goal."""

    def query(self, database: str, *args, **kwargs) -> list[notion.Page]:
        found = super().query(database, *args, **kwargs)
        if database == "goals-db":
            met = {"type": "status", "status": {"name": "Atteint"}}
            found.append(_row("dddd-goal", "Livrer la bêta", Statut=met))
        return found

    def schema(self, database: str) -> dict[str, str]:
        return {"Objectif": "relation"} if database == "tickets-db" else {}


@case
def a_new_ticket_is_offered_the_goals_still_worked_toward_with_their_projects():
    """A met goal waits on no ticket; one without a status is not one that is over."""
    api = _goals_api()
    api._runner.client = _ClosedGoalsClient()
    index = api._goal_index()
    assert index["dddd-goal"]["status"] == "Atteint" and not index["dddd-goal"]["active"]
    assert index["aaaa-goal"]["project_ids"] == ["ppppsite"], index
    offered = api._choices()["goal"]
    assert offered == [
        {"value": "aaaagoal", "label": "Lancer la v1", "projects": ["ppppsite"]},
        {"value": "bbbbgoal", "label": "Ranger", "projects": []},
    ], offered
    answers.TicketChoices.model_validate({"goal": offered})
    # The goals page still lists it, and says it is over.
    api.board = lambda max_age=0.0: {"tickets": []}
    rows = {goal["name"]: goal["active"] for goal in api.goals()["goals"]}
    assert rows == {"Lancer la v1": True, "Ranger": True, "Livrer la bêta": False}, rows


@case
def the_goals_route_answers_the_goals_with_their_counts(state_home):
    """`GET /api/goals`, through the console: the shape it names is the one it sends."""
    from ponos.web import app

    schema = app.schema()
    ok = schema["paths"]["/api/goals"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/Goals"), ok
    shapes = schema["components"]["schemas"]
    assert "goal" not in shapes["Ticket"]["required"], "a ticket serves no goal by default"
    assert "goal" in shapes["TicketChoices"]["properties"]
    assert "goal" in shapes["NewTicket"]["properties"]

    api = _goals_api()
    api.config.web.token = "tok"
    api.board = lambda max_age=0.0: {
        "tickets": [{"id": "t1", "goal_id": "bbbbgoal", "column": "done"}]
    }
    console = app.Console(("127.0.0.1", 0), api, "tok", None, "")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", console.server_address[1], timeout=10)
        connection.request(
            "GET",
            "/api/goals",
            headers={"Host": "127.0.0.1", "X-Ponos": "1", "Authorization": "Bearer tok"},
        )
        answer = connection.getresponse()
        said = json.loads(answer.read())
        connection.close()
    finally:
        console.shutdown()
        console.server_close()
    assert answer.status == 200, said
    assert [goal["tickets"] for goal in said["goals"]] == [{}, {"done": 1}], said
