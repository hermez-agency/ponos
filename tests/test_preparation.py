"""`preparation.py`: a ticket turned into a job, and claimed."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from support import _nameless, _NamelessClient, _naming_session, _TypedClient, case

from ponos import journal, models, store
from ponos.projects import Project
from ponos.runner import Runner
from ponos.ticket import Job, Ticket

# -- the claim ----------------------------------------------------------------


def _client(runner: Runner) -> _NamelessClient:
    """The fake `_nameless` gave the runner, to read what was written on it."""
    return cast(_NamelessClient, runner.client)


class _MovedClient(_NamelessClient):
    """The same ticket, which somebody can move while it is being prepared."""

    def __init__(self, body: str):
        super().__init__(body)
        self.status = "ready"
        self.said: list[str] = []

    def page(self, page_id: str) -> store.Page:
        return store.Page(
            id=page_id,
            url="",
            title="",
            properties={"statut": {"type": "status", "status": {"name": self.status}}},
        )

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.said.append(text)


@case
def a_ticket_moved_out_of_ready_while_it_is_prepared_is_not_run(state_home: Path) -> None:
    """Naming it took a session; it was cancelled meanwhile. The claim does not
    take, so no job comes out — and the cancellation is not failed over."""
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    ticket.page.properties["statut"] = {"type": "status", "status": {"name": "ready"}}
    client = _MovedClient("Le bandeau de la console reste blanc au chargement.")
    runner.client = client  # type: ignore[assignment]  # a fake: a ticket that moves
    with _naming_session("Réparer le bandeau blanc de la console") as asked:
        original = runner._name

        def cancelled_while_named(ticket: Ticket, body: str, short: str) -> None:
            original(ticket, body, short)
            client.status = "cancelled"

        runner._name = cancelled_while_named  # type: ignore[method-assign]  # a double: cancelled meanwhile
        job = runner.prepare(ticket)

    assert asked, "the naming session ran before the claim"
    assert job is None, "no session is started on a cancelled ticket"
    assert not [values for values in client.written if "statut" in values or "Agent" in values]
    # The model is chosen, and said, before the claim: only a failure is wrong here.
    assert [text for text in client.said if "Model chosen" not in text] == [], "no failure"


@case
def a_ticket_still_in_ready_is_claimed_as_ever(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    ticket.page.properties["statut"] = {"type": "status", "status": {"name": "ready"}}
    client = _MovedClient("Il coûte 12 % de CPU pour rien.")
    runner.client = client  # type: ignore[assignment]  # a fake: a ticket that moves
    with _naming_session(""):
        job = runner.prepare(ticket)

    assert job is not None
    assert [values for values in client.written if values.get("statut") == "progress"]


# -- a ticket that cannot be used ---------------------------------------------


def _failures(runner: Runner) -> list[dict[str, Any]]:
    """`_fail`, replaced by the list of what it was asked to say."""
    failed: list[dict[str, Any]] = []

    def fail(ticket: Ticket, reason: str, detail: str = "", *, code: str = "", **rest: Any) -> None:
        failed.append({"reason": reason, "detail": detail, "code": code, **rest})

    runner._fail = fail  # type: ignore[method-assign, assignment]  # a double: what it was asked to say is kept
    return failed


class _NowhereToBeFound:
    def resolve(self, client: Any, page_id: str, *, clone: bool = False) -> Project:
        raise LookupError("no path for project p-runner on this machine")


class _Unreadable(_NamelessClient):
    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        raise store.StoreError("GET /blocks/x/children: 502 bad gateway")


@case
def a_project_nobody_can_find_blocks_the_ticket_before_anything_is_read(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    runner.resolver = _NowhereToBeFound()  # type: ignore[assignment]  # a fake: no project anywhere
    failed = _failures(runner)
    with _naming_session("") as asked:
        assert runner.prepare(ticket) is None
    assert asked == [], "no session for a ticket with nowhere to run"
    assert [entry["code"] for entry in failed] == ["project.no-repo"]
    assert failed[0]["blocked"] is True
    assert "p-runner" in failed[0]["detail"], "the resolver's own words are kept"
    assert _client(runner).written == [], "nothing claimed"


@case
def a_body_the_board_will_not_hand_over_fails_the_ticket(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "")
    runner.client = _Unreadable("")  # type: ignore[assignment]  # a fake: a body that will not come
    failed = _failures(runner)
    assert runner.prepare(ticket) is None
    assert [entry["code"] for entry in failed] == ["board.read-failed"]
    assert "502" in failed[0]["detail"]
    assert not failed[0].get("blocked"), "a board that hiccups is a failure, not a question"


@case
def a_page_with_neither_title_nor_content_is_blocked_as_empty(state_home: Path) -> None:
    runner, ticket = _nameless("", "   \n")
    failed = _failures(runner)
    with _naming_session("Un titre") as asked:
        assert runner.prepare(ticket) is None
    assert asked == [], "nothing to name a ticket from"
    assert [entry["code"] for entry in failed] == ["ticket.empty"]


@case
def an_openrouter_model_without_its_key_blocks_the_ticket_on_credentials(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    ticket.page.properties["Model"] = {"type": "select", "select": {"name": "openai/gpt-5"}}
    runner.config.openrouter.key = ""
    failed = _failures(runner)
    with _naming_session(""):
        assert runner.prepare(ticket) is None
    assert [entry["code"] for entry in failed] == ["access.credentials"]
    assert "openai/gpt-5" in failed[0]["reason"]
    assert _client(runner).written == [], "not claimed"


@case
def a_dry_run_prepares_without_naming_or_claiming(state_home: Path) -> None:
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    runner.dry_run = True
    with _naming_session("Réparer le bandeau blanc") as asked:
        job = runner.prepare(ticket)
    assert asked == [], "a dry run pays for no session"
    assert job is not None and _client(runner).written == [], "and writes nowhere"


# -- the name of a nameless ticket --------------------------------------------


@case
def a_naming_session_that_cannot_start_names_the_ticket_from_its_content(state_home: Path) -> None:
    runner, ticket = _nameless("", "Le bandeau de la console reste blanc au chargement.")
    with _naming_session("", missing=True) as asked:
        job = runner.prepare(ticket)
    assert asked, "the session was tried"
    assert job is not None and ticket.page.title, "the content gave it a name all the same"
    assert {"Titre": ticket.page.title} in _client(runner).written


@case
def a_title_the_board_refuses_is_not_kept_and_the_ticket_still_runs(state_home: Path) -> None:
    runner, ticket = _nameless(
        "", "Le bandeau de la console reste blanc au chargement.", refuse=True
    )
    with _naming_session("Réparer le bandeau blanc de la console"):
        job = runner.prepare(ticket)
    assert job is not None
    assert ticket.page.title == "", "a name the board does not show is not the branch's"
    assert not [values for values in _client(runner).written if "Titre" in values]


@case
def a_body_that_gives_no_name_leaves_the_title_alone(state_home: Path) -> None:
    runner, ticket = _nameless("", "x")
    with _naming_session(""):
        runner._name(ticket, "", "118c3791")
    assert ticket.page.title == "" and _client(runner).written == []


# -- the model ----------------------------------------------------------------


@case
def a_model_the_runner_chose_last_time_reads_as_no_model_at_all(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "b")
    ticket.page.properties["Model"] = {"type": "select", "select": {"name": "sonnet"}}
    original = journal.chosen
    try:
        journal.chosen = lambda ticket: {"model": "sonnet", "status": "failed", "escalated": 0}
        assert runner._written_model(ticket) == "", "the runner's own pick may climb"
        journal.chosen = lambda ticket: {"model": "haiku", "status": "failed", "escalated": 0}
        assert runner._written_model(ticket) == "sonnet", "somebody changed it since: theirs"
        journal.chosen = lambda ticket: None
        assert runner._written_model(ticket) == "sonnet", "never chosen: written by somebody"
    finally:
        journal.chosen = original


class _RefusesTheModel(_NamelessClient):
    def schema(self, database_id: str) -> dict[str, str]:
        return {**super().schema(database_id), "Model": "select"}

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if "Model" in values:
            raise store.StoreError("PATCH /pages/x: 400 Model is not a property")
        super().update(database_id, page_id, values)


@case
def a_chosen_model_the_board_refuses_is_still_run_and_said(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "Il coûte 12 % de CPU pour rien.")
    runner.client = _RefusesTheModel("Il coûte 12 % de CPU pour rien.")  # type: ignore[assignment]  # a fake: no Model column to write
    runner.config.runner.auto_model = True
    said: list[str] = []

    def comment(ticket: Ticket, text: str, discussion: str = "") -> None:
        said.append(text)

    runner._comment = comment  # type: ignore[method-assign]  # a double: what it says is kept
    with _naming_session(""):
        job = runner.prepare(ticket)
    assert job is not None and job.model and job.chosen, "the choice holds without the column"
    assert len(said) == 1 and job.model in said[0], "the reason is still commented"


@case
def a_grid_with_no_model_chooses_nothing(state_home: Path) -> None:
    runner, ticket = _nameless("Retirer le shader", "b")
    original = models.choose
    try:
        models.choose = lambda *args, **kwargs: models.Choice(model="", level="", signals=())
        job = Job(ticket, Project(name="", path=None), "", "", Path("/w"), "b")
        runner._choose_model(ticket, job)
    finally:
        models.choose = original
    assert job.model == "" and not job.chosen
    assert _client(runner).written == [], "nothing written for a choice not made"


# -- the type, and the sub-type -----------------------------------------------


class _SubtypedClient(_TypedClient):
    """A board with a Type column and a Sous-type one, which may refuse writes."""

    def __init__(self, body: str, refuse: str = ""):
        super().__init__(body)
        self._refused = refuse

    def schema(self, database_id: str) -> dict[str, str]:
        return {**super().schema(database_id), "Sous-type": "select"}

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if self._refused in values:
            raise store.StoreError(f"PATCH /pages/x: 400 {self._refused} is locked")
        super().update(database_id, page_id, values)


def _typed(
    title: str, *, kind: str = "", refuse: str = "", body: str = "Le bouton ne répond plus."
) -> tuple[Runner, Ticket]:
    runner, ticket = _nameless(title, body)
    runner.client = _SubtypedClient(body, refuse)  # type: ignore[assignment]  # a fake: a Type and a Sous-type column
    if kind:
        ticket.page.properties["Type"] = {"type": "select", "select": {"name": kind}}
    return runner, ticket


@case
def a_type_that_is_none_of_the_four_runs_by_what_the_project_holds(state_home: Path) -> None:
    runner, ticket = _typed("Le bouton Envoyer", kind="Maintenance")
    with _naming_session("") as asked:
        assert runner._kind(ticket, "b", Project(name="ponos", path=Path("/repo"))) == ("", "")
    assert asked == [], "somebody's own option is not classified over"


@case
def no_type_and_no_classification_is_the_old_road(state_home: Path) -> None:
    runner, ticket = _typed("Le bouton Envoyer")
    runner.config.runner.classify = False
    with _naming_session("") as asked:
        assert runner._kind(ticket, "b", Project(name="ponos", path=Path("/repo"))) == ("", "")
    assert asked == []


@case
def a_dry_run_neither_classifies_nor_deduces_a_sub_type(state_home: Path) -> None:
    runner, ticket = _typed("Le bouton Envoyer")
    runner.dry_run = True
    project = Project(name="ponos", path=Path("/repo"))
    with _naming_session('{"type": "code", "confidence": "high"}') as asked:
        assert runner._kind(ticket, "b", project) == ("", "")
        assert runner._subtype(ticket, "b") == ("", "")
    assert asked == [] and _client(runner).written == []


@case
def a_classification_that_cannot_start_blocks_on_the_doubt(state_home: Path) -> None:
    runner, ticket = _typed("Le bouton Envoyer")
    failed = _failures(runner)
    with _naming_session("", missing=True):
        kind, answer = runner._kind(ticket, "b", Project(name="ponos", path=Path("/repo")))
    assert (kind, answer) == (None, "")
    assert [entry["code"] for entry in failed] == ["ticket.kind-unsure"]
    assert failed[0]["question"], "the question is what the ticket is blocked on"


@case
def a_type_the_board_refuses_to_keep_is_run_as_classified_all_the_same(state_home: Path) -> None:
    runner, ticket = _typed("Le bouton Envoyer", refuse="Type")
    answer = '{"type": "code", "reason": "Un bouton.", "confidence": "high", "alternative": ""}'
    with _naming_session(answer):
        kind, said = runner._kind(ticket, "b", Project(name="ponos", path=Path("/repo")))
    assert kind == "code" and said == answer
    commented = cast(_TypedClient, runner.client).said
    assert commented and "Un bouton." in commented[0], "the comment still says why"


@case
def a_sub_type_that_is_none_of_the_known_ones_is_left_out(state_home: Path) -> None:
    runner, ticket = _typed("Le bouton Envoyer", kind="Code")
    ticket.page.properties["Sous-type"] = {"type": "select", "select": {"name": "Spike"}}
    with _naming_session('{"subtype": "bug", "confidence": "high"}') as asked:
        assert runner._subtype(ticket, "b") == ("", "")
    assert asked == [] and _client(runner).written == [], "never rewritten"


@case
def a_board_without_a_sub_type_column_reads_the_prefix_and_asks_nobody(state_home: Path) -> None:
    runner, ticket = _nameless("Le bouton Envoyer", "b")
    runner.client = _TypedClient("b")  # type: ignore[assignment]  # a fake: no Sous-type column
    with _naming_session('{"subtype": "bug", "confidence": "high"}') as asked:
        assert runner._subtype(ticket, "b") == ("", "")
    assert asked == [], "nowhere to keep the answer"
    ticket.page.title = "[Bug] Le bouton Envoyer"
    assert runner._subtype(ticket, "b") == ("bug", "")
    assert _client(runner).written == [], "and nowhere to write the prefix's either"


@case
def a_sub_type_the_board_refuses_is_still_the_ticket_s(state_home: Path) -> None:
    runner, ticket = _typed("[Bug] Le bouton Envoyer", kind="Code", refuse="Sous-type")
    assert runner._subtype(ticket, "b") == ("bug", "")
    assert _client(runner).written == []


@case
def a_sub_type_session_that_says_nothing_writes_nothing_and_settles_in_doubt(
    state_home: Path,
) -> None:
    runner, ticket = _typed("Le bouton Envoyer", kind="Code")
    with _naming_session("", missing=True) as asked:
        key, note = runner._subtype(ticket, "b")
    assert asked, "the session was tried"
    assert key and note, "settled as the doubt, and said in the report"
    assert _client(runner).written == [], "no answer is not a doubt worth keeping"
