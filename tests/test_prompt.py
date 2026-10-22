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
