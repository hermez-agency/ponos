"""`models.py`: the model a ticket is run with."""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from support import _config, _nameless, _NamelessClient, _state_home, case

from ponos import config as C
from ponos import journal, models, naming, priority, store, voice, workspace
from ponos import ticket as ticket_module
from ponos.runner import Runner

# -- the model of a ticket ----------------------------------------------------


# Fable allowed, so the four levels are four models; see the use_fable cases.
_GRID = C.Runner(use_fable=True).model_grid()


def _chosen(title: str, body: str = "", **given: Any) -> models.Choice:
    given.setdefault("kind", "code")
    given.setdefault("code", True)
    return models.choose(title, body, grid=given.pop("grid", _GRID), **given)


@case
def a_small_change_runs_on_the_light_model_and_says_why() -> None:
    choice = _chosen("Retirer un paragraphe des Réglages", "Le texte sous le titre ne sert à rien.")
    assert (choice.model, choice.level) == ("haiku", "light"), choice
    assert ("model-small", {"words": "retirer"}) in choice.signals, choice.signals
    said = voice.Voice("fr")
    reason = ", ".join(said.say(key, **values) for key, values in choice.signals)
    assert reason == "ticket code, petite modification ciblée (retirer)", reason
    # As tickets are really written: the context, what to do, the criteria.
    explained = "\n".join(
        [" ".join(["La page affiche un paragraphe que plus personne ne lit."] * 18)]
        + [f"- critère {number} vérifié sur desktop et mobile" for number in range(6)]
    )
    real = _chosen("Réglages : retirer le paragraphe d'explication", explained, priority=25)
    assert real.model == "haiku", "a small change said in its title, however explained"
    drowned = _chosen("Retirer la phrase et animer le robot", " ".join(["mot"] * 400))
    assert drowned.model == "sonnet", "past a page, the title alone does not make it small"
    writing = _chosen(
        "Une phrase d'accroche", "Pour la page d'accueil.", kind="writing", code=False
    )
    assert writing.model == "haiku", "a short text is light from the start"


@case
def a_standard_bug_or_feature_runs_on_the_standard_model() -> None:
    body = " ".join(
        ["Le formulaire de connexion renvoie une erreur quand l'email a une majuscule."] * 12
    )
    choice = _chosen("Connexion impossible avec une majuscule", body)
    assert (choice.model, choice.level) == ("sonnet", "standard"), choice
    assert choice.signals[-1] == ("model-ordinary", {})
    short = _chosen("Ajouter un bouton d'export CSV")
    assert short.model == "sonnet", "short, and nothing small about it: the type's level"


@case
def heavy_work_runs_on_a_heavy_model_and_the_heaviest_when_it_is_long_too() -> None:
    audit = _chosen("Audit de sécurité complet", "Passer tout le dépôt en revue.")
    assert (audit.model, audit.level) == ("opus", "heavy"), audit
    assert audit.signals[1] == ("model-heavy", {"words": "audit, sécurité"}), audit.signals
    steps = "\n".join(f"- point {number} à vérifier" for number in range(30))
    full = _chosen("Audit complet et migration de l'architecture", steps)
    assert (full.model, full.level) == ("fable", "heaviest"), full
    long = _chosen("Nouvelle page Statistiques", steps)
    assert long.model == "opus" and long.signals[1][0] == "model-long", long
    words = _chosen("Refonte", "Retirer le vieux texte.")
    assert words.model == "opus", "a heavy word wins over a small one"


@case
def an_action_on_the_world_or_an_urgent_ticket_never_runs_on_the_lightest_model() -> None:
    post = _chosen("Retirer le post LinkedIn", "", kind="publication", code=False)
    assert post.model == "sonnet", post
    urgent = _chosen("Renommer le bouton", "", priority=75)
    assert urgent.model == "sonnet" and urgent.signals[-1][0] == "model-urgent", urgent
    assert _chosen("Renommer le bouton", "", priority=74).model == "haiku"


@case
def a_priority_is_a_score_from_0_to_100_and_the_old_words_still_read() -> None:
    """Urgent, High, Normal, Low read as the scores their migration gives them,
    so a board not migrated yet keeps its order; what a cell says outside 0–100
    is clamped, what somebody gives is refused."""
    assert [priority.score(word) for word in ("Urgent", "high", "Normal", "Low")] == [
        100,
        75,
        50,
        25,
    ]
    assert priority.score(None) == priority.score("") == 50, "empty is the middle"
    assert priority.score(150) == 100 and priority.score(-3) == 0 and priority.score(62.6) == 63
    assert priority.score("80") == 80 and priority.score("nonsense") == 50
    assert priority.given("") == 50 and priority.given(0) == 0 and priority.given("100") == 100
    for wrong in (101, -1, "vite", True):
        try:
            priority.given(wrong)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{wrong!r} is not a priority")
    assert [priority.word(score) for score in (100, 90, 75, 60, 50, 30, 0)] == [
        "Urgent",
        "Urgent",
        "High",
        "Normal",
        "Normal",
        "Low",
        "Low",
    ]
    assert priority.cell(80, "select") == "High" and priority.cell(80, "number") == 80


@case
def the_ready_tickets_run_by_score_highest_first_and_the_oldest_on_a_tie() -> None:
    def ready(identifier: str, created: str, cell: dict[str, Any] | None) -> store.Page:
        properties = {"Priorité": cell} if cell else {}
        return store.Page(
            id=identifier,
            url="",
            title=identifier,
            properties=properties,
            raw={"created_time": created},
        )

    pages = [
        ready("plain", "2026-10-01T09:00:00Z", None),
        ready("low", "2026-09-01T09:00:00Z", {"type": "number", "number": 10}),
        ready("tienew", "2026-10-02T09:00:00Z", {"type": "number", "number": 90}),
        ready("tieold", "2026-09-02T09:00:00Z", {"type": "number", "number": 90}),
        ready("worded", "2026-09-03T09:00:00Z", {"type": "select", "select": {"name": "High"}}),
        ready("middle", "2026-09-04T09:00:00Z", {"type": "number", "number": 60}),
    ]
    runner = Runner.__new__(Runner)
    runner.config = _config("")
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    runner.client = type("S", (), {"query": lambda self, database, query=None: pages})()
    runner._ready_filter = lambda: {}  # type: ignore[method-assign]  # a double: every page is ready
    runner.woken = lambda: []  # type: ignore[method-assign]  # a double: nothing woken
    runner.parked = lambda tickets: set()  # type: ignore[method-assign]  # a double: nothing parked
    eligible, waiting = runner.queue()
    assert [ticket.id for ticket in eligible] == [
        "tieold",
        "tienew",
        "worded",
        "middle",
        "plain",
        "low",
    ], [ticket.id for ticket in eligible]
    assert waiting == []


@case
def a_failed_choice_climbs_one_level_once_and_stays_there() -> None:
    earlier = models.Earlier("haiku", "failed")
    again = _chosen("Retirer le bandeau", earlier=earlier)
    assert (again.model, again.escalated) == ("sonnet", True), again
    assert again.signals[-1] == ("model-escalated", {"model": "haiku"})
    once = _chosen("Retirer le bandeau", earlier=models.Earlier("sonnet", "failed", escalated=True))
    assert (once.model, once.escalated) == ("sonnet", True), "climbed once, it stays there"
    assert once.signals == (("model-kept", {"model": "sonnet"}),)
    done = _chosen("Retirer le bandeau", earlier=models.Earlier("haiku", "done"))
    assert done.model == "haiku" and not done.escalated, "only a failure climbs"
    resumed = _chosen("Audit complet", earlier=models.Earlier("sonnet", "waiting"))
    assert resumed.model == "sonnet", "a session carried on keeps its model"
    off = _chosen("Retirer le bandeau", earlier=earlier, escalate=False)
    assert off.model == "haiku" and not off.escalated
    top = _chosen("Audit complet", earlier=models.Earlier("opus", "failed"))
    assert top.model == "fable" and top.escalated


@case
def the_grid_is_the_configurations_and_an_empty_level_borrows_the_nearest() -> None:
    settings = C.Runner(auto_model_light="", auto_model_heavy="anthropic/claude-opus")
    grid = settings.model_grid()
    assert grid.model("light") == "sonnet", "below is nothing, so the one above"
    assert grid.model("heavy") == "anthropic/claude-opus"
    writing = C.Runner(auto_model_light="", auto_model_writing="light").model_grid()
    text = models.choose("Un mot", "", kind="writing", code=False, grid=writing)
    assert text.model == "sonnet", text


@case
def without_use_fable_the_heaviest_level_and_an_escalation_stop_at_opus() -> None:
    steps = "\n".join(f"- point {number} à vérifier" for number in range(30))
    heavy = "Audit complet et migration de l'architecture"
    assert C.Runner().use_fable is False, "Fable is a choice somebody makes"
    allowed = _chosen(heavy, steps, grid=C.Runner(use_fable=True).model_grid())
    assert (allowed.model, allowed.level) == ("fable", "heaviest"), allowed
    off = C.Runner().model_grid()
    refused = _chosen(heavy, steps, grid=off)
    assert (refused.model, refused.level) == ("opus", "heaviest"), refused
    named = C.Runner(auto_model_standard="claude-fable-5-1").model_grid()
    assert named.model("standard") == "opus", "any level named after Fable"
    top = _chosen("Audit complet", grid=off, earlier=models.Earlier("opus", "failed"))
    assert (top.model, top.escalated) == ("opus", False), top
    assert all(key != "model-escalated" for key, _ in top.signals)


@case
def a_config_has_no_fable_and_only_the_constant_brings_it_back() -> None:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[runner]\n", encoding="utf-8")
    settings = C.load(path).runner
    assert settings.use_fable is False
    assert settings.auto_model_heaviest == "fable", "the level keeps its name"
    assert settings.model_grid().model("heaviest") == "opus"
    assert settings.allowed("fable") == "opus" and settings.allowed("sonnet") == "sonnet"
    assert C.Runner(use_fable=True).allowed("fable") == "fable"


def _modelled(title: str, body: str, **properties: Any) -> tuple[Runner, ticket_module.Ticket]:
    runner, ticket = _nameless(title, body)
    client = cast(Any, runner.client)  # a fake: it learns to remember comments here
    client.said = []
    client.comment = lambda page_id, text, discussion_id="": client.said.append(text)
    ticket.page.properties.update(properties)
    return runner, ticket


def _said(runner: Runner) -> list[str]:
    """The comments `_modelled` taught its fake to remember."""
    return cast(list[str], cast(Any, runner.client).said)


def _written(runner: Runner) -> list[dict[str, Any]]:
    return cast(_NamelessClient, runner.client).written


@case
def a_ticket_with_no_model_is_given_one_and_told_why_in_a_comment(state_home: Path) -> None:
    runner, ticket = _modelled("Retirer un paragraphe des Réglages", "Le texte sous le titre.")
    runner.config.runner.language = "fr"
    job = runner.prepare(ticket)
    assert job is not None
    assert (job.model, job.chosen, job.escalated) == ("haiku", True, False), job
    assert _said(runner) == [
        "🧠 Modèle choisi automatiquement — haiku\n"
        "Ticket Code, petite modification ciblée (retirer)."
    ], _said(runner)
    assert [values["Model"] for values in _written(runner) if "Model" in values] == ["haiku"], (
        "the pick is written on the ticket, with the value the comment announces"
    )


@contextlib.contextmanager
def _failed_pick(model: str) -> Iterator[None]:
    """The journal remembering a run the runner chose `model` for, and lost."""
    original = journal.chosen
    journal.chosen = lambda ticket: {"model": model, "status": "failed", "escalated": False}
    try:
        yield
    finally:
        journal.chosen = original


@case
def a_model_written_by_the_runner_is_not_taken_for_one_somebody_chose() -> None:
    """The column holds the runner's pick on the next attempt: it must still
    be chosen for, or a run that failed could never climb. Another model there
    is somebody's, and is left alone."""

    def column(name: str) -> dict[str, Any]:
        return {"Model": {"type": "select", "select": {"name": name}}}

    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.", **column("haiku"))
    with _state_home(), _failed_pick("haiku"):
        job = runner.prepare(ticket)
        assert job is not None
    assert job.chosen and job.model == "sonnet", (job.model, job.chosen)
    assert [values["Model"] for values in _written(runner) if "Model" in values] == ["sonnet"]

    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.", **column("opus"))
    with _state_home(), _failed_pick("haiku"):
        job = runner.prepare(ticket)
        assert job is not None
    assert (job.model, job.chosen) == ("opus", False)
    assert not any("Model" in values for values in _written(runner))


@case
def a_model_the_board_refuses_is_a_line_in_the_log_and_the_run_goes_on(state_home: Path) -> None:
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    lines: list[str] = []
    runner.say = lines.append  # type: ignore[method-assign,assignment]  # a double: the log, kept
    update = runner.client.update

    def refuse(database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if "Model" in values:
            raise store.StoreError("Model is expected to be rich_text")
        update(database_id, page_id, values)

    runner.client.update = refuse  # type: ignore[method-assign]  # a double: the board refuses
    job = runner.prepare(ticket)
    assert job is not None
    assert (job.model, job.chosen) == ("haiku", True)
    assert any("model could not be written" in line for line in lines), lines


@case
def a_model_somebody_chose_or_a_switched_off_choice_is_the_runner_as_before() -> None:
    forced = {"Model": {"type": "select", "select": {"name": "opus"}}}
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.", **forced)
    with _state_home():
        job = runner.prepare(ticket)
        assert job is not None
    assert (job.model, job.chosen) == ("opus", False) and _said(runner) == []

    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    runner.config.runner.auto_model = False
    with _state_home():
        job = runner.prepare(ticket)
        assert job is not None
    assert (job.model, job.chosen) == ("", False) and _said(runner) == [], (
        "empty: runner.model, as every ticket had it"
    )


@case
def a_fable_written_on_a_ticket_runs_on_opus_and_its_report_says_why() -> None:
    fable = {"Model": {"type": "select", "select": {"name": "fable"}}}
    runner, ticket = _modelled("Audit complet", "Tout le dépôt.", **fable)
    runner.config.runner.language = "fr"
    with _state_home():
        job = runner.prepare(ticket)
        assert job is not None
    assert (job.model, job.chosen) == ("opus", False), job
    assert job.notes == ["Fable désactivé dans les réglages : lancé sur Opus."], job.notes

    runner, ticket = _modelled("Audit complet", "Tout le dépôt.", **fable)
    runner.config.runner.use_fable = True
    with _state_home():
        job = runner.prepare(ticket)
        assert job is not None
    assert (job.model, job.notes) == ("fable", []), "allowed, taken as written"


@case
def a_run_begun_on_fable_carries_on_on_opus_once_it_is_turned_off(state_home: Path) -> None:
    runner, ticket = _modelled("Audit complet", "Tout le dépôt.")
    journal.Run.start(ticket=ticket.id, model="fable", chosen=True, escalated=True).end("failed")
    job = runner.prepare(ticket)
    assert job is not None
    assert job.model == "opus", job
    runner, ticket = _modelled("Audit complet", "Tout le dépôt.")
    journal.Run.start(ticket=ticket.id, model="fable", chosen=True).end("waiting")
    again = runner.prepare(ticket)
    assert again is not None and again.model == "opus"


@case
def a_chosen_model_that_failed_comes_back_one_level_up_from_the_journal(state_home: Path) -> None:
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    first = runner.prepare(ticket)
    assert first is not None
    journal.Run.start(ticket=ticket.id, model=first.model, chosen=True).end("failed")
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    second = runner.prepare(ticket)
    assert second is not None
    assert (second.model, second.escalated) == ("sonnet", True), second
    assert "one level up after a failed run on haiku" in _said(runner)[-1]
    journal.Run.start(ticket=ticket.id, model=second.model, chosen=True, escalated=True).end(
        "failed"
    )
    runner, ticket = _modelled("Retirer un paragraphe", "Le texte.")
    third = runner.prepare(ticket)
    assert third is not None
    assert third.model == "sonnet", "once, not to the top of the price list"
    assert journal.chosen(ticket.id) == {
        "model": "sonnet",
        "status": "failed",
        "escalated": True,
    }


@case
def a_title_is_one_line_however_the_session_wrapped_it() -> None:
    assert (
        naming.clean('Voici le titre :\n\n"Réparer le bandeau blanc"') == "Réparer le bandeau blanc"
    )
    assert naming.clean("**Retirer le shader du bandeau.**") == "Retirer le shader du bandeau"
    assert naming.clean("   ") == ""
    assert len(naming.clean("mot " * 40)) <= naming.LIMIT + 1, "a title is a line"
    assert "language the content is written in" in naming.prompt("Le bandeau reste blanc.")


@case
def a_fallback_title_is_the_first_line_that_says_something() -> None:
    body = "# Ce qu'il faut faire\n\n---\n- Retirer le shader.\nEt aussi le reste."
    assert naming.fallback(body) == "Retirer le shader"
    assert naming.fallback("## Titre\n## Autre\n") == "", "a bare template names nothing"
    assert naming.fallback("") == ""
