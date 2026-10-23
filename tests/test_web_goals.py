"""`Api.create_goal` and its kin: the goals are written from the console, not only read."""

from __future__ import annotations

import json

import httpx
from support import _bare_api, _board, _http_answering, _markdown_api, case

from ponos import notion, store, workspace


class _Watch:
    """The watcher of the board, which only has to be asked to look again."""

    def nudge(self) -> None:
        pass


def _api(board):
    """An Api over a board of files, whose tickets are listed as the card would say them."""
    api = _markdown_api(board)
    api.watch = _Watch()
    api._goals, api._goals_at = {}, 0.0

    def tickets(max_age: float = 0.0) -> dict:
        return {
            "tickets": [
                {
                    "id": page.id,
                    "short": page.id[:6],
                    "title": page.title,
                    "column": "ready",
                    "goal_id": (store.read(page, "Objectif") or [""])[0],
                }
                for page in board.query("tickets")
            ]
        }

    api.board = tickets
    return api


def _ticket(board, title: str) -> str:
    return board.create_row("tickets", title)


@case
def the_console_creates_and_edits_a_goal_in_its_database():
    with _board() as board:
        api = _api(board)
        site = board.create_row("projects", "Website")
        created = api.create_goal(
            "Lancer la v1",
            {
                "description": "La première version",
                "criterion": "dix clients payants",
                "due": "2026-12-31",
                "status": "actif",
                "priority": 80,
                "projects": [site],
            },
        )
        row = next(goal for goal in api.goals()["goals"] if goal["id"] == created["id"])
        assert row["name"] == "Lancer la v1" and row["description"] == "La première version"
        assert row["criterion"] == "dix clients payants" and row["due"] == "2026-12-31"
        assert row["status"] == "actif" and row["priority"] == 80
        assert row["projects"] == ["Website"] and row["project_ids"] == [site]

        api.save_goal(created["id"], {"name": "Lancer la v2", "status": "en pause", "due": ""})
        row = api.goals()["goals"][0]
        assert (row["name"], row["status"], row["due"]) == ("Lancer la v2", "en pause", "")
        assert row["criterion"] == "dix clients payants", "what the form left out is kept"

        for bad in ({}, {"name": " "}, {"priority": 101}):
            try:
                api.save_goal(created["id"], bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{bad} must be refused")
        try:
            api.create_goal("  ", {})
        except ValueError:
            pass
        else:
            raise AssertionError("a goal needs a name")


@case
def tickets_are_tied_to_a_goal_from_the_goal_and_from_the_ticket():
    with _board() as board:
        api = _api(board)
        goal = api.create_goal("Lancer la v1", {})["id"]
        other = api.create_goal("Ranger", {})["id"]
        one, two, three = (_ticket(board, name) for name in ("un", "deux", "trois"))

        api.save_goal(goal, {"tickets": [one, two]})
        row = {item["name"]: item for item in api.goals()["goals"]}["Lancer la v1"]
        assert sorted(ticket["id"] for ticket in row["linked"]) == sorted([one, two]), row
        assert sum(row["tickets"].values()) == 2, row
        # The goal's page lists them by column, each a way into its window.
        first = next(ticket for ticket in row["linked"] if ticket["id"] == one)
        assert first == {"id": one, "short": one[:6], "title": "un", "column": "ready"}, first

        # From the ticket: moved to the other goal, then released.
        api.set_ticket_goal(one, other)
        rows = {item["name"]: item for item in api.goals()["goals"]}
        assert [t["id"] for t in rows["Ranger"]["linked"]] == [one]
        assert [t["id"] for t in rows["Lancer la v1"]["linked"]] == [two]

        # Untying from the goal leaves alone a ticket that points elsewhere.
        api.save_goal(goal, {"tickets": [three]})
        rows = {item["name"]: item for item in api.goals()["goals"]}
        assert [t["id"] for t in rows["Lancer la v1"]["linked"]] == [three]
        assert [t["id"] for t in rows["Ranger"]["linked"]] == [one]

        api.set_ticket_goal(one, "")
        rows = {item["name"]: item for item in api.goals()["goals"]}
        assert rows["Ranger"]["linked"] == []
        try:
            api.set_ticket_goal(one, "f" * 32)
        except LookupError:
            pass
        else:
            raise AssertionError("a goal that does not exist is refused")


@case
def a_goal_is_archived_and_leaves_the_list():
    with _board() as board:
        api = _api(board)
        goal = api.create_goal("Lancer la v1", {})["id"]
        assert api.delete_goal(goal)["name"] == "Lancer la v1"
        assert api.goals()["goals"] == []
        try:
            api.delete_goal(goal)
        except LookupError:
            pass
        else:
            raise AssertionError("an archived goal is not there to archive again")


@case
def renaming_a_goal_with_no_priority_gives_it_none():
    with _board() as board:
        api = _api(board)
        goal = api.create_goal("Lancer la v1", {"priority": ""})["id"]
        assert api.goals()["goals"][0]["priority"] is None

        # The form sends every field back, the empty priority with the rest.
        api.save_goal(goal, {"name": "Lancer la v2", "priority": "", "status": ""})
        row = api.goals()["goals"][0]
        assert row["name"] == "Lancer la v2" and row["priority"] is None, row
        page = next(page for page in board.query("goals") if page.id.replace("-", "") == goal)
        assert store.read(page, "Priorité") in (None, ""), "no priority is written"


@case
def a_goal_s_priority_is_read_as_a_score_whatever_its_column_holds():
    with _board() as board:
        api = _api(board)
        goal = api.create_goal("Lancer la v1", {})["id"]
        for cell, score in (("High", 75), ("haute", 50), ("150", 100), ("80", 80)):
            board.update("goals", goal, {"Priorité": cell})
            assert api.goals()["goals"][0]["priority"] == score, (cell, api.goals())


# -- on Notion -----------------------------------------------------------------

# An Objectifs database as it is made by hand in Notion: its status a column of
# the status type, its priority still a select, its title under a name of its own.
_GOALS_SCHEMA = {
    "Nom": "title",
    "Description": "rich_text",
    "Critère": "rich_text",
    "Échéance": "date",
    "Statut": "status",
    "Priorité": "select",
    "Projets": "relation",
}


class _Notion:
    """Notion's API reduced to the goals and projects databases, behind a `MockTransport`.

    It keeps what it is sent — the rows, and the body of every PATCH — because
    what is under test is what the console asks of Notion, not what it shows.
    `refuse` makes the next PATCH of a page's columns answer 400, as Notion
    does to an option a status column does not offer — a refusal `update` does
    not ask again, unlike a column whose type changed. `options` are those of
    the goals' status column: given, a row is made with the first, as Notion
    does with a column's default, and a name it does not offer is a 400.
    """

    def __init__(self, schema: dict[str, str], options: list[str] | None = None) -> None:
        self.schemas = {"goals": schema, "projects": {"Name": "title"}}
        self.options = options
        self.pages: dict[str, dict] = {}
        self.patches: list[tuple[str, dict]] = []
        self.refuse = False

    def row(self, database: str, title: str) -> str:
        page_id = f"{len(self.pages) + 1:032x}"
        self.pages[page_id] = {
            "id": page_id,
            "url": f"https://www.notion.so/{page_id}",
            "parent": database,
            "archived": False,
            "properties": {
                name: {"type": "title", "title": [{"plain_text": title}]}
                for name, kind in self.schemas[database].items()
                if kind == "title"
            },
        }
        if self.options and database == "goals":
            for name, kind in self.schemas[database].items():
                if kind == "status":
                    self.pages[page_id]["properties"][name] = {
                        "type": kind,
                        "status": {"name": self.options[0]},
                    }
        return page_id

    def _write(self, page: dict, properties: dict) -> None:
        for name, value in properties.items():
            kind = self.schemas[page["parent"]][name]
            if kind in ("title", "rich_text"):
                value = {kind: [{"plain_text": part["text"]["content"]} for part in value[kind]]}
            page["properties"][name] = {"type": kind, **value}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/v1", 1)[-1]
        body = json.loads(request.content or b"{}")
        parts = path.strip("/").split("/")
        if request.method == "GET" and parts[0] == "databases":
            schema = self.schemas[parts[1]]
            return httpx.Response(
                200,
                json={
                    "id": parts[1],
                    "properties": {
                        name: {"type": kind}
                        if kind != "status" or self.options is None
                        else {"type": kind, kind: {"options": [{"name": o} for o in self.options]}}
                        for name, kind in schema.items()
                    },
                },
            )
        if request.method == "POST" and parts[0] == "databases" and parts[-1] == "query":
            rows = [
                page
                for page in self.pages.values()
                if page["parent"] == parts[1] and not page["archived"]
            ]
            return httpx.Response(200, json={"results": rows, "has_more": False})
        if request.method == "POST" and path == "/pages":
            database = body["parent"]["database_id"]
            title = next(
                value["title"][0]["text"]["content"]
                for name, value in body["properties"].items()
                if self.schemas[database][name] == "title"
            )
            page_id = self.row(database, title)
            self._write(self.pages[page_id], body["properties"])
            return httpx.Response(200, json=self.pages[page_id])
        if request.method == "PATCH" and parts[0] == "pages":
            page = self.pages[parts[1]]
            self.patches.append((parts[1], body))
            if "properties" in body:
                if self.refuse:
                    self.refuse = False
                    return httpx.Response(400, json={"message": "Invalid status option."})
                offered = self.options
                for name, value in body["properties"].items():
                    if offered is not None and "status" in value:
                        if (value["status"] or {}).get("name", "") not in offered:
                            return httpx.Response(400, json={"message": "Invalid status option."})
                self._write(page, body["properties"])
            if body.get("archived"):
                page["archived"] = True
            return httpx.Response(200, json=page)
        raise AssertionError(f"{request.method} {path} is not something the goals ask")


def _notion_api(fake: _Notion):
    """An Api whose Notion is `fake`, read through the real client."""
    api = _bare_api(notion.Client("ntn_x"))
    api._runner._workspace = workspace.Workspace(
        tickets="tickets", projects="projects", goals="goals"
    )
    api.watch = _Watch()
    api._goals, api._goals_at = {}, 0.0
    api.board = lambda max_age=0.0: {"tickets": []}
    return api


@case
def a_goal_is_created_edited_and_archived_on_a_notion_database():
    fake = _Notion(_GOALS_SCHEMA)
    with _http_answering(fake):
        api = _notion_api(fake)
        site = fake.row("projects", "Website")
        created = api.create_goal(
            "Lancer la v1",
            {
                "description": "La première version",
                "criterion": "dix clients payants",
                "due": "2026-12-31",
                "status": "Actif",
                "priority": 80,
                "projects": [site],
            },
        )
        goal = created["id"]
        assert [page["id"] for page in fake.pages.values() if page["parent"] == "goals"] == [goal]
        [(patched, body)] = fake.patches
        assert patched == goal
        assert body == {
            "properties": {
                "Description": {
                    "rich_text": [{"type": "text", "text": {"content": "La première version"}}]
                },
                "Critère": {
                    "rich_text": [{"type": "text", "text": {"content": "dix clients payants"}}]
                },
                "Échéance": {"date": {"start": "2026-12-31"}},
                # A status column is written as one, and the priority as the
                # select's nearest word, never as "80".
                "Statut": {"status": {"name": "Actif"}},
                "Priorité": {"select": {"name": "High"}},
                "Projets": {"relation": [{"id": site}]},
                "Nom": {"title": [{"type": "text", "text": {"content": "Lancer la v1"}}]},
            }
        }, body
        [row] = api.goals()["goals"]
        assert (row["name"], row["status"], row["active"]) == ("Lancer la v1", "Actif", True)
        assert row["priority"] == 75 and row["due"] == "2026-12-31", row
        assert row["projects"] == ["Website"] and row["project_ids"] == [site], row

        fake.patches.clear()
        api.save_goal(goal, {"status": "En pause", "priority": 20, "due": ""})
        assert fake.patches == [
            (
                goal,
                {
                    "properties": {
                        "Échéance": {"date": None},
                        "Statut": {"status": {"name": "En pause"}},
                        "Priorité": {"select": {"name": "Low"}},
                    }
                },
            )
        ], fake.patches
        [row] = api.goals()["goals"]
        assert (row["status"], row["active"], row["priority"], row["due"]) == (
            "En pause",
            False,
            25,
            "",
        ), row
        assert row["criterion"] == "dix clients payants", "what the form left out is kept"

        fake.patches.clear()
        assert api.delete_goal(goal) == {"id": goal, "name": "Lancer la v1"}
        assert fake.patches == [(goal, {"archived": True})], fake.patches
        assert api.goals()["goals"] == []


@case
def a_column_the_goals_database_lacks_is_left_out_of_the_patch():
    fake = _Notion({name: kind for name, kind in _GOALS_SCHEMA.items() if name != "Critère"})
    with _http_answering(fake):
        api = _notion_api(fake)
        goal = api.create_goal("Ranger", {"criterion": "plus rien", "status": "Actif"})["id"]
        [(_, body)] = fake.patches
        assert set(body["properties"]) == {"Statut", "Nom"}, body
        assert api.goals()["goals"][0]["status"] == "Actif"
        assert api.goals()["goals"][0]["id"] == goal


@case
def a_goal_whose_columns_cannot_be_written_is_not_left_behind():
    fake = _Notion(_GOALS_SCHEMA)
    with _http_answering(fake):
        api = _notion_api(fake)
        fake.refuse = True
        try:
            api.create_goal("Lancer la v1", {"status": "Actif", "priority": 80})
        except notion.NotionError:
            pass
        else:
            raise AssertionError("a refused write is said")
        assert api.goals()["goals"] == [], "the row made before the refusal is not kept"

        # Asked again, as whoever saw the error would: one goal, not two.
        api.create_goal("Lancer la v1", {"status": "Actif", "priority": 80})
        assert [row["name"] for row in api.goals()["goals"]] == ["Lancer la v1"]


@case
def a_goal_created_without_a_status_takes_the_one_its_notion_status_column_defaults_to():
    fake = _Notion(_GOALS_SCHEMA, options=["Actif", "En pause", "Atteint"])
    with _http_answering(fake):
        api = _notion_api(fake)
        # What the form sends when "No status" is left: every field, the status empty.
        values = {"name": "Lancer la v1", "description": "", "status": "", "projects": []}
        created = api.create_goal("Lancer la v1", values)
        listed = api.goals()
        assert [row["name"] for row in listed["goals"]] == ["Lancer la v1"], listed
        assert listed["goals"][0]["status"] == "Actif", "the status column's own default"
        # The form offers the column's own options, not a word list of its own.
        assert listed["statuses"] == ["Actif", "En pause", "Atteint"], listed

        api.save_goal(created["id"], {"status": "Atteint"})
        assert api.goals()["goals"][0]["status"] == "Atteint"
        # A status cannot be emptied: saying none leaves the one it has.
        api.save_goal(created["id"], {"status": "", "name": "Lancer la v2"})
        assert api.goals()["goals"][0]["status"] == "Atteint"
