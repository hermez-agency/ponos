"""`prompt.py`: the order the prompt reads its frames in."""

from __future__ import annotations

from support import case

from ponos import prompt

# -- the prompt --------------------------------------------------------------


@case
def the_prompt_reads_from_the_widest_frame_to_the_narrowest():
    text = prompt.build(
        prompt.DEFAULT,
        project="Northwind",
        title="Retirer l'entête",
        body="Le header prend trop de place.",
        repo="/home/x/northwind",
        branch="ticket/x",
        base="main",
        url="https://notion.so/x",
        brief="Ton: direct, pas d'emoji.",
        context="Je suis Camille Martin, développeur web.",
    )
    assert text.index("Camille Martin") < text.index("Ton: direct"), "the global frame comes first"
    assert text.index("Ton: direct") < text.index("# Context"), (
        "then the project, then the mechanics"
    )
    assert "Le header prend trop de place." in text


@case
def a_workspace_without_a_context_page_changes_nothing():
    common = dict(
        project="Northwind", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    bare = prompt.build(prompt.DEFAULT, **common)
    assert "# Who you are working for" not in bare
    assert prompt.build(prompt.DOCUMENT, **common, context="   ") == prompt.build(
        prompt.DOCUMENT, **common
    ), "whitespace is not a context"


@case
def a_goal_frames_the_task_between_the_project_and_the_role():
    common = dict(
        project="Animalink",
        title="t",
        body="b",
        repo="/r",
        branch="br",
        base="main",
        url="u",
        brief="Les conventions du projet.",
        agent_name="Dev front",
        agent_brief="Le CSS avant le JS.",
    )
    aimed = prompt.build(
        prompt.DEFAULT,
        **common,
        goal_name="Lancer la v1",
        goal_brief="La version que l'on montre.",
        goal_criterion="Dix clients payants",
        goal_due="2026-12-31",
    )
    assert "# L'objectif — Lancer la v1" in aimed
    assert "- Critère : Dix clients payants" in aimed and "- Échéance : 2026-12-31" in aimed
    assert (
        aimed.index("# About Animalink")
        < aimed.index("# L'objectif")
        < aimed.index("# Your role — Dev front")
    ), "the intent after the project, the role's rules last"

    # No goal is the prompt as it was before goals existed, to the character.
    for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.RESOLVE):
        before = template.replace("{goal}", "")
        assert prompt.build(template, **common) == prompt.build(before, **common)
        assert prompt.build(template, **common, goal_name="  ") == prompt.build(before, **common)

    # A prompt file written before `{goal}` still hands the session its goal.
    older = prompt.build(prompt.DEFAULT.replace("{goal}", ""), **common, goal_name="Lancer la v1")
    assert "# L'objectif — Lancer la v1" in older
