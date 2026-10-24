"""`Api.create_goal` and its kin: the goals are written from the console, not only read."""

from __future__ import annotations

from support import _board, _markdown_api, case

from ponos import store


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
