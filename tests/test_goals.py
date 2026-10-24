"""`goals.py`: the goal a ticket serves."""

from __future__ import annotations

from support import case

from ponos import goals, notion

# -- the goal a ticket serves ------------------------------------------------


class _GoalClient:
    def __init__(self, page: notion.Page | None, brief: str = "", broken: bool = False):
        self._page, self._brief, self._broken = page, brief, broken

    def page(self, page_id: str) -> notion.Page:
        if self._page is None:
            raise notion.NotionError("object not found")
        return self._page

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        if self._broken:
            raise notion.NotionError("object not found")
        return self._brief


def _goal_page(title: str, criterion: str = "", due: str = "") -> notion.Page:
    properties: dict = {"Nom": {"type": "title", "title": [{"plain_text": title}]}}
    if criterion:
        properties["Critère"] = {"type": "rich_text", "rich_text": [{"plain_text": criterion}]}
    if due:
        properties["Échéance"] = {"type": "date", "date": {"start": due, "end": None}}
    return notion.Page(id="p-goal", url="", title=title, properties=properties)


def _ticket(properties: dict) -> notion.Page:
    return notion.Page(id="p-ticket", url="", title="t", properties=properties)


@case
def a_goal_is_a_page_with_its_criterion_and_its_date():
    client = _GoalClient(
        _goal_page("Lancer la v1", "Dix clients payants", "2026-12-31"),
        brief="La version que l'on montre.",
    )
    goal = goals.resolve(client, "p-goal")
    assert goal.name == "Lancer la v1"
    assert goal.brief == "La version que l'on montre."
    assert goal.criterion == "Dix clients payants"
    assert goal.due == "2026-12-31"
    assert goal, "a named goal is truthy"


@case
def an_unreadable_goal_is_no_goal_rather_than_a_failed_ticket():
    assert not goals.resolve(_GoalClient(None), "p-goal")
    # The page reads but its body does not: the brief is lost, the goal is not.
    partial = goals.resolve(_GoalClient(_goal_page("Lancer la v1"), broken=True), "p-goal")
    assert partial.name == "Lancer la v1" and partial.brief == ""
    assert not goals.Goal(), "no goal at all is falsy"


@case
def a_board_without_the_goal_column_points_at_nothing():
    assert goals.pointed(_ticket({}), "Objectif") == ""
    # A column of another type under that name is not a relation to read.
    text = {"Objectif": {"type": "rich_text", "rich_text": [{"plain_text": "p-goal"}]}}
    assert goals.pointed(_ticket(text), "Objectif") == ""


@case
def an_empty_relation_points_at_nothing_and_a_full_one_at_its_first_page():
    empty = {"Objectif": {"type": "relation", "relation": []}}
    assert goals.pointed(_ticket(empty), "Objectif") == ""
    full = {"Objectif": {"type": "relation", "relation": [{"id": "p-a"}, {"id": "p-b"}]}}
    assert goals.pointed(_ticket(full), "Objectif") == "p-a"


class _GoalsDatabase:
    def __init__(self, pages: list[notion.Page], broken: bool = False):
        self._pages, self._broken = pages, broken

    def query(self, database_id: str, filter_: dict | None = None) -> list[notion.Page]:
        if self._broken:
            raise notion.NotionError("object not found")
        return self._pages


def _cap(title: str, status: str = "", projects: tuple[str, ...] | None = None) -> notion.Page:
    page = _goal_page(title, "Dix clients payants", "2026-12-31")
    if status:
        page.properties["Statut"] = {"type": "select", "select": {"name": status}}
    if projects is not None:
        page.properties["Projets"] = {
            "type": "relation",
            "relation": [{"id": project} for project in projects],
        }
    return page


@case
def only_the_goals_being_worked_toward_are_active():
    database = _GoalsDatabase(
        [
            _cap("Lancer la v1", "Actif"),
            _cap("Sans statut"),
            _cap("Plus tard", "En pause"),
            _cap("Fait", "Atteint"),
            _cap("Laissé", "Abandonné"),
        ]
    )
    assert [goal.name for goal in goals.active(database, "db")] == ["Lancer la v1", "Sans statut"]
    assert goals.active(database, "db")[0].criterion == "Dix clients payants"
    assert goals.active(database, "") == [], "no goals database, no goal"
    assert goals.active(_GoalsDatabase([], broken=True), "db") == []


@case
def a_project_only_sees_the_goals_that_name_it():
    database = _GoalsDatabase(
        [
            _cap("Pour Usine", "Actif", ("aaaa-bbbb",)),
            _cap("Pour une autre", "Actif", ("cccc",)),
            _cap("Sans projet", "Actif", ()),
            _cap("Sans colonne", "Actif"),
        ]
    )
    assert [goal.name for goal in goals.active(database, "db", "aaaabbbb")] == ["Pour Usine"]
    assert len(goals.active(database, "db")) == 4, "the workspace sees them all"


def _english_goal(title: str) -> notion.Page:
    """A goals database whose columns were written in English, as the console accepts them."""
    return notion.Page(
        id="p-goal",
        url="",
        title=title,
        properties={
            "Name": {"type": "title", "title": [{"plain_text": title}]},
            "Criterion": {"type": "rich_text", "rich_text": [{"plain_text": "Ten paying clients"}]},
            "Due": {"type": "date", "date": {"start": "2026-12-31", "end": None}},
            "Status": {"type": "select", "select": {"name": "Active"}},
            "Projects": {"type": "relation", "relation": [{"id": "aaaa-bbbb"}]},
        },
    )


@case
def a_goal_written_in_english_reads_as_the_console_shows_it():
    goal = goals.resolve(_GoalClient(_english_goal("Ship v1")), "p-goal")
    assert (goal.criterion, goal.due) == ("Ten paying clients", "2026-12-31")
    database = _GoalsDatabase([_english_goal("Ship v1"), _cap("Plus tard", "En pause")])
    [found] = goals.active(database, "db", "aaaabbbb")
    assert (found.name, found.criterion, found.due) == (
        "Ship v1",
        "Ten paying clients",
        "2026-12-31",
    )
    paused = _english_goal("Later")
    paused.properties["Status"] = {"type": "select", "select": {"name": "On hold"}}
    assert goals.active(_GoalsDatabase([paused]), "db") == [], "an English status is read too"
