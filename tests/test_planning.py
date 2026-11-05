"""`planning.py`: « Plan d'abord » — the plan proposed, the answer read back, the project's rule."""

from __future__ import annotations

from pathlib import Path

from support import case

from ponos import planning, project_settings, store, voice

ME = "runner"


def _comment(text: str, by: str = "person") -> store.Comment:
    return store.Comment(text, created_by=by)


def _report(plan: str = "1. Écrire FAKE.md\n\n2. Le tester", language: str = "fr") -> str:
    said = voice.Voice(language)
    return said.paragraphs(
        said.report(said.verdict("blocked", said.say("plan-done")), f"{said.say('plan-ask')} → x"),
        f"{said.say('plan-heading')}\n\n{plan}",
    )


@case
def the_plan_is_read_between_its_tags_and_back_from_under_its_heading() -> None:
    answer = "Je lis.\n<plan>\n1. Écrire\n\n2. Tester\n</plan>\nRESULT: blocked — écrire"
    assert planning.written(answer) == "1. Écrire\n\n2. Tester"
    assert planning.written("RESULT: blocked — pas clair") == ""
    # The plan is the rest of the report, blank lines included, in either language.
    assert planning.proposed(_report()) == "1. Écrire FAKE.md\n\n2. Le tester"
    assert planning.proposed(_report("Étape", "en")) == "Étape"
    assert planning.proposed("🙋 Bloqué — rien\nUne question ?") == ""


@case
def a_yes_under_the_plan_approves_it_whatever_road_it_came_by() -> None:
    def pending(*answers: str) -> planning.Pending | None:
        return planning.pending(
            [_comment(_report(), by=ME), *(_comment(text) for text in answers)], ME
        )

    for yes in ("oui", "OK, mais sans la migration", "yes"):
        found = pending(yes)
        assert found is not None and found.approved, yes
    # Relayed from a phone, and clicked in the console: the yes under the first line.
    relayed = "Répondu depuis Telegram par Ada.\nOui — vas-y avec ce que tu as proposé."
    clicked = (
        "Répondu depuis la console.\nDécision : oui, vas-y.\nOui — vas-y avec ce que tu as proposé."
    )
    assert pending(relayed).approved  # type: ignore[union-attr]
    assert pending(clicked).approved  # type: ignore[union-attr]
    for other in ("non", "Ajoute une étape de migration", ""):
        found = pending(*([other] if other else []))
        assert found is not None and not found.approved, other
        assert found.plan.startswith("1. Écrire FAKE.md")


@case
def only_the_last_report_can_be_waiting_on_a_plan() -> None:
    later = _comment("🙋 Bloqué — autre chose\nUne autre question ?", by=ME)
    assert planning.pending([_comment(_report(), by=ME), _comment("oui"), later], ME) is None
    assert planning.pending([], ME) is None
    assert not planning.reported([_comment("une remarque")])
    assert planning.reported([_comment(_report(), by=ME)])


@case
def a_project_rule_plans_from_a_priority_or_a_sub_type_and_keeps_nothing_unknown() -> None:
    rule = planning.rule({"priority": 75, "subtypes": ["refactor", "nonsense", "refactor"]})
    assert rule.priority == 75 and rule.subtypes == ["refactor"]
    assert rule.applies(80, "") and rule.applies(10, "refactor")
    assert not rule.applies(50, "bug")
    assert not planning.rule({"priority": 140}) and not planning.rule(None)
    assert not planning.rule({"priority": True})
    assert planning.rule(rule.as_dict()) == rule


@case
def a_project_keeps_its_rule_in_the_database_and_an_empty_one_drops_it(state_home: Path) -> None:
    project = "1234-abcd"
    assert not project_settings.plan(project)
    project_settings.set_plan(project, "Site", planning.Rule(60, ["perf"]))
    assert project_settings.plan(project) == planning.Rule(60, ["perf"])
    project_settings.set_plan(project, "Site", planning.Rule())
    assert not project_settings.plan(project)


@case
def a_long_plan_is_cut_at_a_line() -> None:
    plan = "\n".join(f"- étape {index}" for index in range(5000))
    clipped = planning.clipped(plan)
    assert len(clipped) <= planning.LONGEST + 2 and clipped.endswith("\n…")
    assert planning.clipped("court") == "court"


@case
def a_planning_session_amends_the_plan_it_was_answered_on_and_the_next_carries_it() -> None:
    first = planning.propose_prompt()
    assert "<plan>" in first and "Propose the plan again" not in first
    again = planning.propose_prompt("1. Écrire FAKE.md")
    assert "Propose the plan again" in again and "1. Écrire FAKE.md" in again
    carried = planning.approved_prompt("1. Écrire FAKE.md", "oui,\n  sans la migration")
    assert "1. Écrire FAKE.md" in carried and "“oui, sans la migration”" in carried
