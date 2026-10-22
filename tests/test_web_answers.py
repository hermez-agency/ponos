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


# -- the goals -----------------------------------------------------------------


def _row(page_id: str, title: str, **columns: dict) -> notion.Page:
    return notion.Page(
        id=page_id, url=f"https://notion.so/{page_id}", title=title, properties=columns
    )


def _text(value: str) -> dict:
    return {"type": "rich_text", "rich_text": [{"plain_text": value}]}


class _GoalsClient:
    """A workspace with two goals and a project, and nothing that reaches out."""

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
        {"goal_id": "aaaagoal", "column": "done"},
        {"goal_id": "aaaagoal", "column": "done"},
        {"goal_id": "aaaagoal", "column": "running"},
        {"goal_id": "", "column": "done"},
        {"column": "ready"},
    ]
    api.board = lambda: {"tickets": tickets}
    said = api.goals()
    assert said["configured"] is True
    assert [goal["name"] for goal in said["goals"]] == ["Lancer la v1", "Ranger"], said
    launch, tidy = said["goals"]
    assert launch["tickets"] == {"done": 2, "running": 1}, launch
    assert launch["criterion"] == "dix clients payants" and launch["due"] == "2026-12-31"
    assert launch["status"] == "En cours" and launch["priority"] == "Haute"
    assert launch["projects"] == ["Website"] and launch["id"] == "aaaagoal"
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
    api.board = lambda: {"tickets": [{"goal_id": "bbbbgoal", "column": "done"}]}
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
