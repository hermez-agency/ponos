"""`naming.py`: naming a ticket nobody titled."""

from __future__ import annotations

from pathlib import Path

from support import _nameless, _naming_session, _state_home, case

from ponos import projects, state

# -- naming a ticket nobody titled -------------------------------------------


@case
def a_ticket_with_no_title_is_named_from_what_it_says(state_home):
    """And named before the branch, which is what the title is first used for."""
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    with _naming_session("Réparer le bandeau blanc de la console") as asked:
        job = runner.prepare(ticket)

    assert asked and "Le bandeau de la console" in asked[0], "it names from the content"
    assert runner.client.written[0] == {"Titre": "Réparer le bandeau blanc de la console"}
    assert ticket.title == "Réparer le bandeau blanc de la console"
    assert job.branch == "ticket/reparer-le-bandeau-blanc-de-la-console-75f74ff5"


@case
def the_naming_session_counts_against_the_daily_limit(state_home):
    """Paid like any other, and spent before the ticket has even started."""
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    with _naming_session("Réparer le bandeau blanc de la console", cost=0.25):
        runner.prepare(ticket)
    assert state.spent_today() == 0.25, state.spent_today()


@case
def a_project_found_by_a_fallback_says_so_on_the_ticket(state_home):
    """The ticket runs, and the comment carries which declaration to correct —
    the alternative is a page that stays wrong for as long as the fallback holds."""

    class _StaleRepository:
        def resolve(self, client, page_id: str, *, clone: bool = False) -> projects.Project:
            return projects.Project(
                name="ponos",
                path=Path("/repo"),
                note="Repository found by its origin remote, x/y, but a more explicit "
                "declaration is wrong: /old, from the project's Path property, is not "
                "a git repository. Correct it: the fallback is what its tickets run on.",
            )

    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    runner.resolver = _StaleRepository()
    with _naming_session(""):
        job = runner.prepare(ticket)
    assert job is not None and job.project.path == Path("/repo"), "the ticket runs"
    assert len(job.notes) == 1 and "from the project's Path property" in job.notes[0]


@case
def a_repository_the_run_had_to_fetch_is_said_on_the_ticket():
    """A ticket running on a folder nobody made by hand deserves the sentence
    that says where it came from — and a dry run downloads nothing."""

    class _Fetching:
        def __init__(self) -> None:
            self.asked: list[bool] = []

        def resolve(self, client, page_id: str, *, clone: bool = False) -> projects.Project:
            self.asked.append(clone)
            return projects.Project(
                name="ponos",
                path=Path("/repo"),
                cloned="`Salva/site` was nowhere under ~/workspace — cloned into /repo.",
            )

    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    runner.resolver = resolver = _Fetching()
    with _state_home(), _naming_session(""):
        job = runner.prepare(ticket)
    assert resolver.asked == [True], "a run about to work on a ticket asks for the clone"
    assert job is not None and len(job.notes) == 1 and "cloned into" in job.notes[0]

    runner.dry_run = True
    with _state_home(), _naming_session(""):
        runner.prepare(ticket)
    assert resolver.asked == [True, False], "a dry run says what it would do, and fetches nothing"


@case
def a_ticket_that_already_has_a_title_costs_nothing_and_keeps_it(state_home):
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    with _naming_session("Un titre que personne n'a demandé") as asked:
        job = runner.prepare(ticket)

    assert asked == [], "the common case must not pay for a session"
    assert ticket.title == "Retirer le shader"
    assert all("Titre" not in values for values in runner.client.written)
    assert job.branch == "ticket/retirer-le-shader-75f74ff5"


@case
def a_ticket_with_neither_a_title_nor_content_is_asked_about_rather_than_named(state_home):
    """Nothing to name from is nothing to invent from: it stays the old question."""
    runner, ticket = _nameless("", "## Ce qu'il faut faire\n## Comment on saura\n")
    with _naming_session("Inventé de toutes pièces") as asked:
        job = runner.prepare(ticket)

    assert job is None and asked == []
    assert runner.client.written == [{"Status": "Blocked", "Blocage": "ticket.empty"}]


@case
def a_naming_that_fails_falls_back_on_the_first_line_of_the_content(state_home):
    """No claude on the PATH, and the ticket is still named — and still runs."""
    runner, ticket = _nameless(
        "",
        "## Ce qu'il faut faire\n"
        "Retirer le shader du bandeau de la console, il coûte 12 % de CPU pour rien.",
    )
    with _naming_session("", missing=True):
        job = runner.prepare(ticket)

    # The first line that says something, cut on a word rather than mid-word.
    assert runner.client.written[0] == {
        "Titre": "Retirer le shader du bandeau de la console, il coûte 12 %…"
    }
    assert job.branch.startswith("ticket/retirer-le-shader-du-bandeau")


@case
def a_title_notion_refuses_leaves_the_ticket_to_run_under_the_default_label(state_home):
    """A name is a comfort. Losing it must not cost the ticket its run."""
    runner, ticket = _nameless("", "Le bandeau reste blanc au chargement.", refuse=True)
    with _naming_session("Réparer le bandeau blanc"):
        job = runner.prepare(ticket)

    assert job is not None
    # Kept in memory it would name a branch the board cannot show.
    assert ticket.title == "(untitled ticket)"
    assert job.branch == "ticket/untitled-ticket-75f74ff5"
