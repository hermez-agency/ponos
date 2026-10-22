"""`ideas.py`: ideas."""

from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from support import FRONTEND, _bare_api, _board, _ideas_api, _markdown_api, _state_home, case

from ponos import (
    db,
    files,
    goals,
    ideas,
    kinds,
    markdown,
    notion,
    progress,
    schedules,
    session,
    store,
    voice,
)

# -- ideas -------------------------------------------------------------------


def _proposing(answers: list[list[dict]], cost: float = 0.02):
    """A `session.run` that answers each batch in turn, and keeps what it was asked."""
    asked: list[dict] = []

    def fake_run(text, **rest):
        asked.append({"prompt": text, **rest})
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s-ideas",
            summary="",
            log=Path("/dev/null"),
            cost_usd=cost,
            answer="Voici :\n```json\n"
            + json.dumps(answers[len(asked) - 1], ensure_ascii=False)
            + "\n```",
        )

    return fake_run, asked


def _idea(title: str, kind: str = "ticket", **more) -> dict:
    return {
        "title": title,
        "description": more.pop("description", f"Parce que {title.lower()}."),
        "kind": kind,
        "where": more.pop("where", "frontend/src"),
        "done": more.pop("done", ["Les tests passent"]),
        "out": more.pop("out", ["Le reste"]),
    }


@case
def an_idea_answer_is_read_whatever_wraps_it():
    """A fence, a sentence, a kind a project cannot have, a description too long."""
    answer = (
        'Sure!\n```json\n[{"title": "  Mode   sombre ", "kind": "project",'
        ' "description": "un\\ndeux\\ntrois\\nquatre", "done": "ça marche"},'
        ' {"title": ""}, "rien"]\n```\nVoilà.'
    )
    found = ideas.parse(answer, "project")
    assert [idea["title"] for idea in found] == ["Mode sombre"]
    assert found[0]["kind"] == "ticket", "a project's ideas are tickets, always"
    assert found[0]["description"] == "un\ndeux\ntrois", "three lines at most"
    assert found[0]["detail"]["done"] == ["ça marche"]
    assert ideas.parse(answer, "global")[0]["kind"] == "project"
    assert ideas.parse("no JSON here", "global") == []

    assert ideas.similar("Ajouter un mode sombre", "ajouter un mode sombre !")
    assert ideas.similar("Add a dark mode", "Add dark mode")
    assert not ideas.similar("Add a dark mode", "Add an export to CSV")
    assert not ideas.similar("Export to CSV", "Export to PDF"), "ideas share their openings"
    assert ideas.similar("Mode sombre de la console", "La console en mode sombre")
    kept, dropped = ideas.fresh(
        [_idea("Exporter en CSV"), _idea("Exporter en CSV."), _idea("Créer un mode sombre")],
        ["Créer un mode sombre"],
    )
    assert [idea["title"] for idea in kept] == ["Exporter en CSV"]
    assert len(dropped) == 2


@case
def an_idea_is_sorted_into_one_category_or_left_unsorted(state_home):
    """UX/UI, feature, security or technical — one of the four, or "" rather than a guess."""
    assert '"category"' in ideas.prompt(project="Usine"), "the model is asked to choose"
    answer = json.dumps(
        [
            {"title": "Un thème sombre", "category": " UX "},
            {"title": "Échapper le HTML", "category": "security"},
            {"title": "Deux catégories", "category": ["feature", "technical"]},
            {"title": "Une catégorie inventée", "category": "marketing"},
        ]
    )
    assert [idea["category"] for idea in ideas.parse(answer, "project")] == [
        "ux",
        "security",
        "",
        "",
    ]
    _, stored = ideas.record("p", "haiku", None, ideas.parse(answer, "project"))
    assert [idea.shown()["category"] for idea in stored] == ["ux", "security", "", ""]
    written = ideas.written("p", "Un cache", category="technical")
    assert written.category == "technical"
    assert ideas.written("p", "Autre", category="tout").category == ""
    assert ideas.edit(written.id, "Un cache, enfin", "").category == "technical", (
        "rewording it keeps its category"
    )
    assert ideas.edit(written.id, "Un cache", "", category="feature").category == "feature"
    assert ideas.edit(written.id, "Un cache", "", category="").category == ""


@case
def an_idea_comes_with_a_score_bounded_by_the_grid_or_none_at_all(state_home):
    """Out of 100, by the grid written in the prompt; bounded, and "not scored" for anything else."""
    asked = ideas.prompt(project="Usine")
    for line in ('"score"', '"score_reason"', "up to 40", "up to 25", "up to 20", "up to 15"):
        assert line in asked, line
    answer = json.dumps(
        [
            {"title": "Noté", "score": 85, "score_reason": "  Beaucoup   d'impact. "},
            {"title": "Trop haut", "score": 150},
            {"title": "Trop bas", "score": -5},
            {"title": "En texte", "score": "72"},
            {"title": "Arrondi", "score": 69.6},
            {"title": "Pas un nombre", "score": "high"},
            {"title": "Un booléen", "score": True},
            {"title": "Une liste", "score": [80]},
            {"title": "Sans score"},
        ]
    )
    found = ideas.parse(answer, "project")
    assert [idea["score"] for idea in found] == [85, 100, 0, 72, 70, None, None, None, None]
    assert found[0]["detail"]["score_reason"] == "Beaucoup d'impact."
    assert found[-1]["detail"]["score_reason"] == ""
    _, stored = ideas.record("p", "haiku", None, found)
    shown = [idea.shown() for idea in stored]
    assert [one["score"] for one in shown] == [85, 100, 0, 72, 70, None, None, None, None]
    assert shown[0]["score_reason"] == "Beaucoup d'impact." and shown[0]["tone"] == "green"
    assert shown[-1]["tone"] == "" and shown[-1]["scoring"] is False, "not scored, and not being"
    assert [idea.title for idea in ideas.unscored("p")] == [
        "Pas un nombre",
        "Un booléen",
        "Une liste",
        "Sans score",
    ]
    ideas.decide(stored[-1].id, "discarded")
    assert len(ideas.unscored("p")) == 3, "a thrown idea is not worth paying a score for"

    scores = ideas.parse_scores(
        'Voilà : [{"id": 3, "score": 120, "score_reason": "Oui."}, {"id": "4", "score": "x"},'
        ' {"id": 9, "score": 50}, {"id": 5, "score": 41}]',
        [3, 4, 5],
    )
    assert scores == {3: (100, "Oui."), 5: (41, "")}, "only those asked for, and only numbers"


@case
def a_score_is_green_orange_or_red_by_the_same_two_thresholds_on_both_sides():
    """39 is red, 40 and 69 orange, 70 green — and the console reads the same numbers."""
    assert [ideas.tone(score) for score in (0, 39, 40, 69, 70, 100)] == [
        "red",
        "red",
        "orange",
        "orange",
        "green",
        "green",
    ]
    assert ideas.tone(None) == ""
    search = (FRONTEND / "src/lib/idea-search.ts").read_text(encoding="utf-8")
    assert f"export const GREEN = {ideas.GREEN}\n" in search, (
        "the page and the server disagree on green"
    )
    assert f"export const ORANGE = {ideas.ORANGE}\n" in search, (
        "the page and the server disagree on orange"
    )


@case
def the_ideas_from_before_scores_are_not_scored(state_home):
    """The migration adds a score to every idea, NULL — not a zero."""
    location = db.path()
    before = db.MIGRATIONS.index(db._ideas_have_a_score)
    raw = db.open_at(location, db.MIGRATIONS[:before])
    raw.execute(
        "INSERT INTO ideas (scope, project, kind, title, status, created_at)"
        " VALUES ('project', 'p', 'ticket', 'Ancienne', 'proposed', '2026-10-01')"
    )
    raw.close()
    db.close()
    old = ideas.every("p")[0]
    assert old.score is None and old.shown()["tone"] == ""
    assert ideas.scored(old.id, 55, "Moyen.").shown()["score"] == 55
    with db.transaction(immediate=False) as connection:
        assert connection.execute("SELECT score FROM ideas").fetchone() == (55,)


@case
def an_idea_written_by_hand_is_scored_behind_the_answer_that_saved_it(state_home):
    """Saved, it says "…"; the light model scores it by the grid; a failed answer leaves it not scored."""
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        board.replace_markdown(project, "Un jeu d'usine en navigateur.")
        api = _ideas_api(board)
        api.ideas._person = ("Salva", "")
        put_aside: list = []
        api.ideas.later = put_aside.append
        ideas.written(project, "Un mode sombre")
        written = api.ideas.create(
            {"project": project, "title": "Une carte des usines", "description": "Pour voir."}
        )
        assert written["score"] is None and written["scoring"] is True, "the pill says …"
        assert len(put_aside) == 1, "scored behind the answer, not before it"

        asked: list[dict] = []

        def fake_run(text, **rest):
            asked.append({"prompt": text, **rest})
            return session.Outcome(
                ok=True,
                blocked=False,
                session_id="s-score",
                summary="",
                log=Path("/dev/null"),
                cost_usd=0.001,
                answer=json.dumps(
                    [{"id": written["id"], "score": 82, "score_reason": "Utile et petit."}]
                ),
            )

        original, session.run = session.run, fake_run
        try:
            put_aside.pop()()
        finally:
            session.run = original
        assert len(asked) == 1 and asked[0]["model"] == "haiku", "the light model, classify_model's"
        assert asked[0]["max_budget_usd"] == ideas.SCORE_CEILING_USD
        call = asked[0]["prompt"]
        assert "up to 40" in call and f"{written['id']}. Une carte des usines\nPour voir." in call
        assert "Un jeu d'usine en navigateur." in call, "scored against the brief"
        assert "- Un mode sombre" in call, "and against the other ideas"
        scored = ideas.get(written["id"]).shown()
        assert (scored["score"], scored["tone"], scored["scoring"]) == (82, "green", False)
        assert scored["score_reason"] == "Utile et petit."

        mcp_one = api.ideas.write(project, "ticket", "Un tutoriel")
        assert mcp_one["scoring"] is True, "an idea an MCP client wrote is scored the same way"
        original, session.run = (
            session.run,
            lambda text, **rest: session.Outcome(
                ok=True,
                blocked=False,
                session_id="s",
                summary="",
                log=Path("/dev/null"),
                answer="Je ne sais pas.",
            ),
        )
        try:
            put_aside.pop()()
        finally:
            session.run = original
        failed = ideas.get(mcp_one["id"]).shown()
        assert failed["score"] is None and failed["scoring"] is False, "not scored, and said so"


@case
def a_scoring_that_fails_says_why_on_the_idea_instead_of_staying_silent(state_home):
    """Over budget, unreadable, or too big to start: the cause stays on the idea, and the pass tells the page."""
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        put_aside: list = []
        api.ideas.later = put_aside.append
        published: list = []
        original_publish = api.hub.publish
        api.hub.publish = lambda topic, **rest: published.append((topic, rest))
        first = ideas.written(project, "Une carte des usines")
        second = ideas.written(project, "Un tutoriel")
        assert ideas.SCORE_CEILING_USD >= 0.5, (
            "a call costs 0.12 to 0.14 dollars: 0.10 stopped every one"
        )

        def outcome(**rest):
            return session.Outcome(
                ok=False, blocked=True, session_id="s", summary="", log=Path("/dev/null"), **rest
            )

        original, session.run = (
            session.run,
            lambda text, **rest: outcome(over_budget=True, cost_usd=0.1356),
        )
        try:
            api.ideas.score_unscored(project)
            put_aside.pop()()
        finally:
            session.run = original
        shown = ideas.get(first.id).shown()
        assert shown["score"] is None and shown["scoring"] is False
        assert "may spend" in shown["score_error"], shown["score_error"]
        assert ("ideas", {"project": project, "failed": shown["score_error"]}) in published

        original, session.run = (
            session.run,
            lambda text, **rest: outcome(error="credit balance too low"),
        )
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        assert ideas.get(second.id).shown()["score_error"] == "credit balance too low"

        original, session.run = (
            session.run,
            lambda text, **rest: session.Outcome(
                ok=True,
                blocked=False,
                session_id="s",
                summary="",
                log=Path("/dev/null"),
                answer="Je ne sais pas.",
            ),
        )
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        assert "could not be read" in ideas.get(second.id).shown()["score_error"]

        def crash(text, **rest):
            raise OSError("no claude")

        original, session.run = session.run, crash
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        assert "no claude" in ideas.get(second.id).shown()["score_error"], (
            "an exception is kept, not swallowed"
        )

        original, session.run = (
            session.run,
            lambda text, **rest: session.Outcome(
                ok=True,
                blocked=False,
                session_id="s",
                summary="",
                log=Path("/dev/null"),
                answer=json.dumps([{"id": second.id, "score": 60, "score_reason": "Bien."}]),
            ),
        )
        try:
            api.ideas.score([second.id])
        finally:
            session.run = original
        done = ideas.get(second.id).shown()
        assert (done["score"], done["score_error"]) == (60, ""), "a score clears the error"
        api.hub.publish = original_publish


@case
def a_scoring_prompt_of_the_real_size_fits_under_the_ceiling_and_a_huge_one_is_not_started():
    """The estimate is checked before the session starts: a call that would be stopped is not paid for."""
    big = [
        ideas.Idea(
            id=n,
            batch=None,
            scope="global",
            project="",
            kind="ticket",
            title=f"Idée {n} " + "x" * 80,
            description="d" * 600,
        )
        for n in range(ideas.SCORE_BATCH)
    ]
    prompt = ideas.score_prompt(
        big,
        brief="b" * 10000,
        context="c" * 10000,
        tickets=[("t" * 90, "ready")] * 100,
        known=["k" * 90] * 400,
    )
    assert ideas.score_estimate(prompt) < ideas.SCORE_CEILING_USD, (
        "even at its limits, a prompt is under the ceiling"
    )
    assert ideas.score_estimate("x" * 400000) > ideas.SCORE_CEILING_USD


@case
def the_ideas_with_no_score_are_scored_in_batches_under_a_ceiling_said_first(state_home):
    """A ceiling before it starts, twenty to a call, a scope per call — and one pass at a time."""
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        for number in range(25):
            ideas.written(project, f"Idée du projet {number}")
        ideas.written("", "Idée de l'espace")
        told = api.ideas.unscored(None)
        assert (told["count"], told["calls"]) == (26, 3), (
            "two calls for the project, one for the workspace"
        )
        assert (
            told["ceiling_usd"] == round(3 * ideas.SCORE_CEILING_USD, 2)
            and told["model"] == "haiku"
        )
        assert api.ideas.unscored("")["count"] == 1

        put_aside: list = []
        api.ideas.later = put_aside.append
        started = api.ideas.score_unscored(None)
        assert started["running"] is True and started["count"] == 26
        try:
            api.ideas.score_unscored(None)
        except RuntimeError:
            pass
        else:
            raise AssertionError("a second pass waits for the first")

        sizes: list[int] = []

        def fake_run(text, **rest):
            numbers = [int(found) for found in re.findall(r"^(\d+)\. ", text, re.M)]
            sizes.append(len(numbers))
            return session.Outcome(
                ok=True,
                blocked=False,
                session_id="s",
                summary="",
                log=Path("/dev/null"),
                answer=json.dumps(
                    [
                        {"id": number, "score": 30 + number, "score_reason": "."}
                        for number in numbers
                    ]
                ),
            )

        original, session.run = session.run, fake_run
        try:
            put_aside.pop()()
        finally:
            session.run = original
        assert sorted(sizes) == [1, 5, 20], sizes
        assert api.ideas.unscored(None) == {
            "count": 0,
            "calls": 0,
            "ceiling_usd": 0,
            "model": "haiku",
            "running": False,
        }
        assert all(idea.score is not None for idea in ideas.every(None))


@case
def ideas_for_a_project_are_found_in_one_call_and_never_proposed_twice(state_home):
    """Ten in one light session, given the brief, the README and the tickets.

    What was thrown away goes into the next prompt, and what the model proposes
    again anyway is dropped on the way in. Every batch's cost is written down.
    """
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        board.replace_markdown(project, "Un jeu d'usine en navigateur.")
        done = board.create_row("tickets", "Ajouter le tutoriel", {"Status": "Done"})
        board.update("tickets", done, {"Project": [project]})
        clone = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        (clone / "README.md").write_text("# Usine\n\nConstruire des chaînes de production.\n")
        api = _ideas_api(board)
        api._config.projects["Usine"] = str(clone)

        first = [
            _idea(f"Idée numéro {word}")
            for word in ("un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf")
        ] + [_idea("Ajouter le tutoriel")]
        again = [_idea("Idée numéro un !"), _idea("Une sauvegarde dans le cloud")]
        fake_run, asked = _proposing([first, again])
        original, session.run = session.run, fake_run
        try:
            batch = api.ideas.generate(project)
            listed = api.ideas.proposed(project)
            thrown = listed["ideas"][0]
            api.ideas.discard(thrown["id"])
            second = api.ideas.generate(project)
        finally:
            session.run = original
            shutil.rmtree(clone, ignore_errors=True)

        assert len(asked) == 2, "one call per batch"
        call = asked[0]
        assert call["model"] == "haiku", "a light model unless the file says otherwise"
        assert "Un jeu d'usine en navigateur." in call["prompt"]
        assert "Construire des chaînes de production." in call["prompt"]
        assert "Ajouter le tutoriel (done)" in call["prompt"]
        assert "exactly 10 ideas" in call["prompt"]
        assert '"ticket", always' in call["prompt"]

        assert len(batch["ideas"]) == 9, "a ticket already on the board is not an idea"
        assert batch["dropped"] == ["Ajouter le tutoriel"]
        assert len(listed["ideas"]) == 9 and listed["scope"] == "project"
        assert all(idea["project"] == project.replace("-", "") for idea in listed["ideas"])

        assert thrown["title"] in asked[1]["prompt"], "a thrown idea is named to the model"
        assert [idea["title"] for idea in second["ideas"]] == ["Une sauvegarde dans le cloud"]
        assert second["dropped"] == ["Idée numéro un !"], "and never proposed again"
        assert ideas.get(thrown["id"]).status == "discarded"
        assert thrown["id"] not in [idea["id"] for idea in api.ideas.proposed(project)["ideas"]]
        history = api.ideas.proposed(project)["decided"]
        assert [idea["id"] for idea in history] == [thrown["id"]], (
            "the history holds what was decided"
        )
        assert history[0]["status"] == "discarded"

        with db.transaction(immediate=False) as connection:
            costs = connection.execute(
                "SELECT count, cost_usd FROM idea_batches ORDER BY id"
            ).fetchall()
        assert costs == [(9, 0.02), (1, 0.02)], costs
        assert api.ideas.proposed(project)["cost_usd"] == 0.04
        assert api.ideas.proposed("")["ideas"] == [], "the workspace's ideas are another scope"


@case
def an_idea_turned_into_a_ticket_is_a_draft_and_a_project_idea_a_project(state_home):
    """Turned into a ticket: a draft in the tickets database, What / Where / Done when / Out of
    scope, attached to its project, no model. A new project's idea creates the
    project, its description as the brief, and a first ticket to frame it.
    Taking it back proposes it again — and turning it again writes nothing twice."""
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        api._config.runner.ideas_model = "sonnet"
        fake_run, asked = _proposing(
            [
                [_idea("Un mode sombre", where="Les feuilles de style", done=["Le thème bascule"])],
                [
                    _idea(
                        "Un site pour le club",
                        "project",
                        description="Les horaires.\nLes inscriptions.",
                    ),
                    _idea("Un journal des coûts", "ticket"),
                ],
            ]
        )
        original, session.run = session.run, fake_run
        try:
            mine = api.ideas.generate(project)["ideas"][0]
            general = api.ideas.generate("")["ideas"]
        finally:
            session.run = original
        assert asked[0]["model"] == "sonnet", "the model is a setting"
        assert "Usine" in asked[1]["prompt"], "the workspace is told its projects"
        assert '"project" for a new project' in asked[1]["prompt"]

        settings = api.config.notion
        kept = api.ideas.ticket(mine["id"])
        assert kept["status"] == "ticket" and kept["ticket"]
        ticket = board.page(kept["ticket"])
        assert ticket.title == "Un mode sombre"
        assert store.read(ticket, settings.prop("project")) == [project]
        assert not store.read(ticket, settings.prop("status")), "a draft"
        assert not store.read(ticket, settings.prop("model")), "Model left empty"
        text = board.blocks_text(kept["ticket"])
        for heading in ("## What", "## Where", "## Done when", "## Out of scope"):
            assert heading in text, text
        assert "- [ ] Le thème bascule" in text

        club = next(idea for idea in general if idea["kind"] == "project")
        made = api.ideas.ticket(club["id"])
        assert made["created"], "the project itself"
        assert board.page(made["created"]).title == "Un site pour le club"
        assert "Les inscriptions." in board.blocks_text(made["created"])
        framing = board.page(made["ticket"])
        assert framing.title == "Frame the project Un site pour le club"
        assert store.read(framing, settings.prop("project")) == [made["created"]]
        assert "## Done when" in board.blocks_text(made["ticket"])

        thrown = next(idea for idea in general if idea["kind"] == "ticket")
        assert api.ideas.discard(thrown["id"])["status"] == "discarded"
        tickets_before = len(board.query("tickets"))

        undone = api.ideas.undo()
        assert undone["was"] == "discarded" and undone["idea"]["status"] == "proposed"
        assert len(board.query("tickets")) == tickets_before, "throwing away wrote nothing"
        back = api.ideas.undo("")
        assert back["idea"]["id"] == club["id"] and back["was"] == "ticket"
        assert club["id"] in [idea["id"] for idea in api.ideas.proposed("")["ideas"]]
        again = api.ideas.ticket(club["id"])
        assert (again["ticket"], again["created"]) == (made["ticket"], made["created"])
        assert len(board.query("tickets")) == tickets_before, "turned again, written once"
        assert api.ideas.undo(project)["idea"]["id"] == mine["id"], "a scope's own last choice"
        try:
            api.ideas.undo(project)
        except LookupError:
            pass
        else:
            raise AssertionError("nothing left to take back in this project")


@case
def an_idea_is_kept_thrown_reopened_and_nothing_is_ever_deleted(state_home):
    """Keeping writes nothing on the board; throwing away keeps the idea; every
    status is counted, and a ticket must be made new again before it is thrown."""
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        fake_run, _ = _proposing(
            [[_idea("Un mode sombre"), _idea("Un export CSV"), _idea("Un tutoriel")]]
        )
        original, session.run = session.run, fake_run
        try:
            dark, export, tutorial = api.ideas.generate(project)["ideas"]
        finally:
            session.run = original
        tickets_before = len(board.query("tickets"))
        kept = api.ideas.keep(dark["id"])
        assert kept["status"] == "kept" and not kept["ticket"]
        assert len(board.query("tickets")) == tickets_before, "kept is not yet a ticket"
        thrown = api.ideas.discard(export["id"])
        assert thrown["status"] == "discarded" and thrown["decided_at"]
        made = api.ideas.ticket(tutorial["id"])
        try:
            api.ideas.discard(tutorial["id"])
        except ValueError:
            pass
        else:
            raise AssertionError("a ticket is made new again before it is thrown away")

        every = api.ideas.every(project)
        assert every["counts"] == {"proposed": 0, "kept": 1, "discarded": 1, "ticket": 1}
        assert {idea["id"] for idea in every["ideas"]} == {dark["id"], export["id"], tutorial["id"]}

        # The Ideas page asks for every scope at once, the workspace's included.
        api.ideas.write("", "ticket", "Une idée de l'espace")
        everywhere = api.ideas.every(None)
        assert everywhere["scope"] == "all" and len(everywhere["ideas"]) == 4
        assert {idea["project"] for idea in everywhere["ideas"]} == {"", ideas.bare(project)}
        assert everywhere["counts"]["proposed"] == 1

        back = api.ideas.reopen(tutorial["id"])
        assert back["status"] == "proposed" and back["ticket"] == made["ticket"]
        assert back["changed_at"] >= made["changed_at"] and back["decided_at"] is None
        assert api.ideas.discard(tutorial["id"])["status"] == "discarded"
        assert api.ideas.every(project)["counts"]["discarded"] == 2
        assert [idea.title for idea in ideas.listed(project, ("discarded",))] == [
            "Un export CSV",
            "Un tutoriel",
        ]


@case
def an_idea_written_by_hand_is_signed_and_never_proposed_again(state_home):
    """Origin manual, its author's name and picture; reworded, the editor and the
    moment; Ponos's own say Ponos. And the next batch is told about it."""
    with _board() as board:
        project = board.create_row("projects", "Usine", {})
        api = _ideas_api(board)
        api.ideas._person = ("Salva", "https://example.com/salva.png")
        written = api.ideas.create(
            {
                "project": project,
                "title": "  Une carte  des usines ",
                "description": "Pour voir.\n\nOù.",
            }
        )
        assert written["origin"] == "manual" and written["status"] == "proposed"
        assert written["title"] == "Une carte des usines"
        assert written["description"] == "Pour voir.\n\nOù.", (
            "a hand-written paragraph keeps its lines"
        )
        assert written["author"] == {
            "kind": "human",
            "name": "Salva",
            "avatar": "https://example.com/salva.png",
        }
        assert written["edited"] is None and written["kind"] == "ticket"
        assert written["project"] == project.replace("-", "")
        for wrong in ({"project": project, "title": "  "}, {"project": "f" * 32, "title": "Rien"}):
            try:
                api.ideas.create(wrong)
            except (ValueError, LookupError):
                pass
            else:
                raise AssertionError(f"refused: {wrong}")
        workspace = api.ideas.create({"title": "Un site", "kind": "project", "category": "feature"})
        assert workspace["scope"] == "global" and workspace["kind"] == "project"
        assert workspace["category"] == "feature" and written["category"] == ""

        fake_run, asked = _proposing([[_idea("Une carte des usines !"), _idea("Un mode sombre")]])
        original, session.run = session.run, fake_run
        try:
            found = api.ideas.generate(project)
        finally:
            session.run = original
        assert "Une carte des usines" in asked[0]["prompt"], (
            "a hand-written idea is named to the model"
        )
        assert found["dropped"] == ["Une carte des usines !"]
        ponos = found["ideas"][0]
        assert ponos["origin"] == "ponos" and ponos["author"]["kind"] == "ponos"

        api.ideas._person = ("Quelqu'un", "")
        edited = api.ideas.edit(
            ponos["id"],
            {"title": "Un mode sombre, partout", "description": "Oui.", "category": "ux"},
        )
        assert edited["title"] == "Un mode sombre, partout" and edited["author"]["kind"] == "ponos"
        assert edited["category"] == "ux"
        assert edited["edited"]["name"] == "Quelqu'un" and edited["edited"]["at"]

        db.close()
        assert ideas.get(written["id"]).author == "Salva", "it survives a restart"
        assert len(api.ideas.every(project)["ideas"]) == 2


@case
def the_ideas_kept_before_their_author_was_known_became_tickets(state_home):
    """Migration 13 on a file of migration 12: a kept idea had become a ticket,
    and every idea is Ponos's, dated by its last decision."""
    location = db.path()
    raw = db.open_at(location, db.MIGRATIONS[:12])
    raw.execute(
        "INSERT INTO ideas (scope, project, kind, title, status, ticket, created_at, decided_at)"
        " VALUES ('project', 'p', 'ticket', 'Gardée', 'kept', 't1', '2026-10-01', '2026-10-02'),"
        " ('project', 'p', 'ticket', 'Jetée', 'discarded', '', '2026-10-01', '2026-10-03'),"
        " ('project', 'p', 'ticket', 'Neuve', 'proposed', '', '2026-10-01', NULL)"
    )
    raw.close()
    db.close()
    found = {idea.title: idea for idea in ideas.every("p")}
    assert found["Gardée"].status == "ticket" and found["Gardée"].ticket == "t1"
    assert found["Jetée"].status == "discarded" and found["Jetée"].changed_at == "2026-10-03"
    assert found["Neuve"].changed_at == "2026-10-01"
    assert all(idea.origin == "ponos" for idea in found.values())


@case
def the_console_writes_a_schedule_without_touching_what_a_pass_writes_back():
    """`Next`, `Last` and `Last ticket` are the runner's, not the form's.

    Letting the console edit them would let somebody make an occurrence happen
    twice, or never — which is the one thing the calendar must not allow.
    """
    with _board() as board:
        api = _markdown_api(board)
        created = api.create_schedule(
            "Revue des dépendances",
            {"cadence": "Weekly", "at": "09:00", "day": "Monday", "active": True},
        )
        row = schedules.read(board.page(created["id"]), board.settings())
        assert row.name == "Revue des dépendances"
        assert (row.cadence, row.at, row.day) == ("Weekly", "09:00", "Monday")
        assert row.active is False, "a new schedule is created unticked, whatever was asked"
        assert not row.problem

        api.save_schedule(created["id"], {"active": True, "at": "07:30", "priority": 80})
        again = schedules.read(board.page(created["id"]), board.settings())
        assert again.active is True and again.at == "07:30" and again.priority == 80
        assert again.next is None and again.last is None

        # The type and the sub-type its tickets are born with, said by their
        # keys and written in the board's words; empty lets them be guessed.
        api.save_schedule(created["id"], {"type": "code", "subtype": "bug"})
        typed = schedules.read(board.page(created["id"]), board.settings())
        assert (typed.kind, typed.subtype) == ("Code", "Bug"), (typed.kind, typed.subtype)
        listed = api.schedules()
        assert (
            listed["schedules"][0]["type"] == "code" and listed["schedules"][0]["subtype"] == "bug"
        )
        assert [choice["value"] for choice in listed["choices"]["type"]] == list(kinds.KINDS)
        api.save_schedule(created["id"], {"type": ""})
        assert schedules.read(board.page(created["id"]), board.settings()).kind == ""
        try:
            api.save_schedule(created["id"], {"type": "poem"})
        except ValueError:
            pass
        else:
            raise AssertionError("a type that is none of the four is refused")

        # What a pass writes back is not the form's to set — so a payload made
        # only of those is refused, rather than quietly doing nothing.
        try:
            api.save_schedule(created["id"], {"next": "2030-01-01", "last": "2030-01-01"})
        except ValueError:
            pass
        else:
            raise AssertionError("a change with nothing to change must say so")
        untouched = schedules.read(board.page(created["id"]), board.settings())
        assert untouched.next is None and untouched.last is None


@case
def the_console_reads_and_rewrites_the_brief_a_schedule_is_born_with():
    """A schedule's page body is copied under every ticket it makes.

    The list leaves it out — twenty rows would be twenty pages read — so one
    schedule opened is the row plus its body, and saving the body alone is a
    change, not a payload with nothing in it.
    """
    with _board() as board:
        api = _markdown_api(board)
        created = api.create_schedule(
            "Revue des dépendances", {"cadence": "Weekly", "body": "Première version."}
        )
        opened = api.schedule(created["id"])
        assert opened["name"] == "Revue des dépendances"
        assert opened["body"] == "Première version."

        api.save_schedule(created["id"], {"body": "## Deuxième\n\n- une liste"})
        assert api.schedule(created["id"])["body"] == "## Deuxième\n\n- une liste"
        api.save_schedule(created["id"], {"body": "## Deuxième\n\n- une liste"})
        assert board.blocks_text(created["id"]) == "## Deuxième\n\n- une liste", (
            "a second save must not stack"
        )
        try:
            api.schedule("f" * 32)
        except LookupError:
            pass
        else:
            raise AssertionError("a schedule that is not there must say so")


@case
def the_console_says_which_board_it_is_looking_at():
    """The panes read it: a Notion link is worth drawing on one and not the other."""
    with _board() as board, _state_home():
        said = _markdown_api(board).state()
    assert said["storage"] == "markdown"
    assert said["board_path"] == str(board.root)


@case
def a_block_reads_back_whichever_end_of_the_wire_it_came_from():
    """`plain` serves two callers, and they hand it two shapes.

    Notion returns a piece of rich text with `plain_text` on it; a block this
    code has just built carries `text.content`. Reading only the first left the
    live report writing a file full of empty bullets.
    """
    built = markdown.to_blocks("- une puce")[0]
    assert "plain_text" not in json.dumps(built), "premise: a built block has no plain_text"
    assert markdown.plain(built) == "- une puce"
    returned = {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"plain_text": "une puce"}]},
    }
    assert markdown.plain(returned) == "- une puce"


@case
def an_image_in_a_brief_is_named_for_the_session_and_drawn_by_the_console():
    """A capture in a Notion brief: no dead link anywhere, a fresh one on demand.

    The line used to carry the file's address cut off its signature, which S3
    answers with 403 from the first second — shown as is on the console, in
    English, crochets and all. It now names the file and the block holding it:
    the session is still told there is a picture, and the console asks the
    board where that block's file is at the moment it draws it.
    """
    signed = "https://prod-files-secure.s3.us-west-2.amazonaws.com/w/f/opoil-bug-prix-negatif.png?X-Amz-Signature=abc"
    block_id = "3ec45168-0af4-8106-be46-dbf34ca5cc95"
    image = {
        "id": block_id,
        "type": "image",
        "image": {
            "type": "file",
            "file": {"url": signed, "expiry_time": "2026-10-01T10:00:00.000Z"},
            "caption": [{"plain_text": "Prix négatif affiché au client"}],
        },
    }
    line = markdown.plain(image)
    assert "amazonaws" not in line and "?" not in line, line
    assert (
        line
        == f"[image attached to the ticket: Prix négatif affiché au client (Notion block {block_id.replace('-', '')})]"
    )
    read = markdown.ATTACHED.match(line)
    assert read and read["kind"] == "image" and read["block"] == block_id.replace("-", "")
    assert read["label"] == "Prix négatif affiché au client"
    # Without a caption, the file's own name says what it is.
    image["image"]["caption"] = []
    assert markdown.ATTACHED.match(markdown.plain(image))["label"] == "opoil-bug-prix-negatif.png"
    pdf = {"id": "b" * 32, "type": "pdf", "pdf": {"type": "external", "external": {"url": ""}}}
    assert markdown.ATTACHED.match(markdown.plain(pdf))["label"] is None

    client = notion.Client("ntn_x")
    asked: list[str] = []

    def request(method, path, body=None, **_):
        asked.append(path)
        if path == f"/blocks/{'c' * 32}":
            return {"id": "c" * 32, "type": "paragraph", "paragraph": {"rich_text": []}}
        return image

    client._request = request  # type: ignore[method-assign]
    assert client.attachment(block_id.replace("-", "")) == signed
    try:
        client.attachment("c" * 32)
        raise AssertionError("a paragraph holds no file")
    except LookupError:
        pass

    from ponos.web import app as web_app

    api = _bare_api(client)
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:

        def get(path: str) -> tuple[int, str]:
            connection = http.client.HTTPConnection(
                "127.0.0.1", console.server_address[1], timeout=5
            )
            connection.request("GET", path, headers={"Authorization": "Bearer tok"})
            response = connection.getresponse()
            response.read()
            connection.close()
            return response.status, response.getheader("Location") or ""

        # Signed at the moment it is opened, and the browser is sent there.
        assert get(f"/api/files/{block_id}") == (302, signed)
        assert asked[-1] == f"/blocks/{block_id.replace('-', '')}"
        assert get(f"/api/files/{'c' * 32}")[0] == 404
    finally:
        console.shutdown()
        console.server_close()

    # A board of files has no blocks: a line copied from Notion is only a name.
    try:
        files.Board(Path(tempfile.mkdtemp())).attachment(block_id)
        raise AssertionError("a board of files holds no Notion file")
    except LookupError:
        pass


@case
def the_live_report_writes_its_steps_into_the_file():
    """A text file has no fold to hide a session's story in, so it keeps it.

    The toggle's title is the one thing lost — there is no line to rewrite in
    place — and `update_block` says so by doing nothing. What must not happen is
    the report disabling itself: the board's live column comes off the same
    flush, and a Markdown installation would silently stop having one.
    """
    with _board() as board:
        page_id = board.create_row("tickets", "Un ticket", {"Status": "Ready"})
        live = progress.Live(
            board,
            page_id,
            database="tickets",
            property_name="Progress",
            interval=0,
            words=voice.Voice(""),
        )
        live.add(progress.Step("Read", "src/x.py"))
        live.flush()
        assert store.read(board.page(page_id), "Progress") == "Read · src/x.py"
        live.add(progress.Step("J'ai lu le fichier.", said=True))
        live.flush()
        live.close("Fini.", ok=True)

        assert not live.disabled
        written = board.blocks_text(page_id)
        assert "src/x.py" not in written, written
        assert "J'ai lu le fichier." in written
        # Cleared on the way out, exactly as on a Notion board.
        assert store.read(board.page(page_id), "Progress") == ""


def _to_score() -> ideas.Idea:
    return ideas.Idea(
        id=1,
        batch=None,
        scope="global",
        project="",
        kind="ticket",
        title="Un cache",
        description="",
    )


@case
def the_goals_of_the_moment_are_read_by_both_prompts_or_left_out():
    """Material to read, never a criterion: without any, the prompt is what it was."""
    caps = [
        goals.Goal("Lancer la v1", criterion="Dix clients payants", due="2026-12-31"),
        goals.Goal("Réduire la dette"),
    ]
    for asked in (
        ideas.prompt(project="Usine", objectives=caps),
        ideas.score_prompt([_to_score()], project="Usine", objectives=caps),
    ):
        assert "# Les caps du moment" in asked
        assert "- Lancer la v1 (criterion: Dix clients payants; due: 2026-12-31)" in asked
        assert "- Réduire la dette\n" in asked
    assert "Les caps du moment" not in ideas.prompt(project="Usine", objectives=[])
    assert ideas.prompt(project="Usine", objectives=[]) == ideas.prompt(project="Usine")
    one = [_to_score()]
    assert ideas.score_prompt(one, objectives=None) == ideas.score_prompt(one)
    assert "Les caps du moment" not in ideas.score_prompt(one)


@case
def the_goals_of_the_moment_stop_at_their_limit():
    many = [goals.Goal(f"Cap {number} " + "x" * 80) for number in range(100)]
    asked = ideas.prompt(objectives=many)
    section = asked.split("# Les caps du moment\n\n", 1)[1]
    assert len(section.split("\n\n", 1)[0].strip()) <= ideas.OBJECTIVES_LIMIT
    scoring = ideas.score_prompt([_to_score()], objectives=many)
    assert "- Cap 0 " in scoring and "- Cap 99 " not in scoring
    assert ideas.SCORE_OBJECTIVES_LIMIT < ideas.OBJECTIVES_LIMIT
