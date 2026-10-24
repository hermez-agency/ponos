"""`prompt.py`: the order the prompt reads its frames in."""

from __future__ import annotations

import os

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


_COMMON = dict(
    project="Northwind", title="t", body="b", repo="/r", branch="br", base="main", url="u"
)


# -- what a session may do alone ----------------------------------------------


@case
def the_permissions_are_said_even_when_nobody_allowed_anything():
    bare = prompt.permissions()
    assert "You do these without asking:" not in bare, "no empty list under a heading"
    assert "You always ask the user" not in bare
    assert "A ticket aimed at the wrong repository." in bare, "that rule never depends on a list"
    assert "this project's GitHub owner" in bare


@case
def blank_rules_and_owners_are_left_out_and_owners_are_sorted_once():
    text = prompt.permissions(
        allowed=["relancer une CI", "  ", ""],
        ask=["toute dépense"],
        owners=["zeta", "Alpha", "zeta", " ", ""],
    )
    assert "- relancer une CI\n" in text and "- \n" not in text, "a blank rule is no rule"
    assert "- toute dépense" in text
    assert "this project's GitHub owner or `Alpha` or `zeta`" in text, (
        "each owner once, in alphabetical order whatever the case"
    )


@case
def a_prompt_file_without_permissions_still_hands_them_over_at_its_end():
    text = prompt.build("Fais {title}.", **_COMMON, allowed=["relancer une CI"])
    assert text.startswith("Fais t.")
    assert text.rstrip().endswith(prompt.permissions(["relancer une CI"]).rstrip())


# -- the secrets --------------------------------------------------------------


@case
def the_secrets_are_named_and_never_valued():
    assert prompt.held_secrets([]) == "", "no key, no section"
    said = prompt.held_secrets(["STRIPE_KEY", "DOKPLOY_TOKEN"])
    assert said.startswith("# Secrets")
    assert "`STRIPE_KEY`, `DOKPLOY_TOKEN`" in said


@case
def the_secrets_come_last_whatever_the_template():
    for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.RESOLVE, "{title}"):
        text = prompt.build(template, **_COMMON, secrets=["STRIPE_KEY"])
        assert text.rstrip().endswith(prompt.held_secrets(["STRIPE_KEY"]).rstrip()), template[:40]


# -- the type of a ticket -----------------------------------------------------


@case
def only_an_external_action_and_a_publication_add_a_section():
    assert prompt.kind("external") == prompt.EXTERNAL
    assert prompt.kind("publication") == prompt.PREPARE
    assert prompt.kind("writing") == "" and prompt.kind("code") == "" and prompt.kind("") == ""


@case
def a_text_about_a_codebase_may_read_it_and_change_nothing():
    said = prompt.kind("writing", "/home/x/northwind")
    assert said.startswith("- The project's repository is at /home/x/northwind")
    assert "change nothing in it" in said
    both = prompt.kind("external", "/home/x/northwind")
    assert both.index("change nothing") < both.index("# This ticket is an external action")


@case
def a_prompt_file_older_than_the_types_gets_the_section_at_its_end():
    section = prompt.kind("external")
    text = prompt.build("Fais {title}.", **_COMMON, kind=section)
    assert text.rstrip().endswith(section.rstrip()), "the rule that stops at a doubt is not lost"
    placed = prompt.build(prompt.DOCUMENT, **_COMMON, kind=section)
    assert placed.count("# This ticket is an external action") == 1, "never twice"


# -- the ticket itself --------------------------------------------------------


@case
def a_ticket_without_a_description_says_everything_is_in_its_title():
    text = prompt.build(prompt.DEFAULT, **{**_COMMON, "body": "  \n "})
    assert "(the ticket has no description: everything is in the title)" in text


@case
def braces_in_a_ticket_are_handed_over_as_written():
    body = 'Le gabarit `{title}` et un objet JSON {"a": 1} doivent rester tels quels.'
    text = prompt.build(prompt.DEFAULT, **{**_COMMON, "title": "Les {accolades}", "body": body})
    assert body in text and "Les {accolades}" in text


@case
def a_ticket_with_no_project_reads_as_one():
    text = prompt.build(prompt.DOCUMENT, **{**_COMMON, "project": ""})
    assert "a Notion ticket that belongs to no project" in text
    assert "# About" not in text, "no brief heading without a project brief"


@case
def the_language_is_a_paragraph_of_its_own_or_exactly_nothing():
    assert prompt._language("") == "" and prompt._language("  \n") == ""
    assert prompt._language("  Write in French.  ") == "\nWrite in French.\n"
    said = prompt.build(prompt.DEFAULT, **_COMMON, language="Write in French.")
    assert "\nWrite in French.\n" in said
    assert prompt.build(prompt.DEFAULT, **_COMMON) == prompt.build(
        prompt.DEFAULT, **_COMMON, language="   "
    ), "blank is not a language"


@case
def what_was_said_on_the_ticket_sits_with_the_ticket_oldest_first():
    text = prompt.build(
        prompt.DEFAULT, **_COMMON, comments=["Salva: c'est pour quand ?", "you: demain"]
    )
    assert "# What has already been said on this ticket" in text
    assert text.index("- Salva: c'est pour quand ?") < text.index("- you: demain")
    assert "# What has already been said" not in prompt.build(
        prompt.DEFAULT, **_COMMON, comments=[]
    )


@case
def a_goal_with_only_a_name_has_no_empty_lines_under_it():
    aim = prompt.build("{goal}", **_COMMON, goal_name="  Lancer la v1  ")
    assert aim.startswith("# L'objectif — Lancer la v1\n\n")
    assert "Critère" not in aim and "Échéance" not in aim


# -- a conversation -----------------------------------------------------------


@case
def a_conversation_puts_the_thread_nearest_the_message():
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="Northwind",
        title="Le header",
        body="",
        where="/home/x/northwind",
        url="https://notion.so/x",
        message="  Et pour le mobile ?  ",
        thread=["Camille: trop haut", "you: je regarde"],
        comments=["Camille: ouvert lundi"],
        language="Write in French.",
    )
    assert text.index("# What has already been said") < text.index("# This thread so far")
    assert text.index("# This thread so far") < text.index("# The message to answer")
    assert "Et pour le mobile ?\n" in text and "  Et pour le mobile ?" not in text, "stripped"
    assert "(the ticket has no description: everything is in the title)" in text
    assert "\nWrite in French.\n" in text


@case
def a_conversation_without_a_thread_has_no_thread_heading():
    text = prompt.conversation(
        prompt.CONVERSATION, project="", title="t", body="b", where="w", url="u", message="m"
    )
    assert "# This thread so far" not in text
    assert "that belongs to no project" in text


@case
def the_message_of_a_built_conversation_is_what_a_resumed_session_is_sent():
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="Northwind",
        title="t",
        body="b",
        where="w",
        url="u",
        message="Et pour le mobile ?\n\nAvec une capture.",
    )
    assert prompt.message_of(text) == "Et pour le mobile ?\n\nAvec une capture."
    assert prompt.message_of("  Une ligne seule.  \n") == "Une ligne seule.", (
        "a prompt with no message section is the message"
    )


@case
def a_follow_up_keeps_the_language_of_the_thread():
    said = prompt.follow_up("Et sur Safari ?", "Write in French.")
    assert "Et sur Safari ?" in said and "\nWrite in French.\n" in said
    assert "Write in" not in prompt.follow_up("Et sur Safari ?")


# -- the reminders ------------------------------------------------------------


@case
def carrying_on_after_the_credit_says_to_look_before_writing():
    said = prompt.carry_on()
    assert "carry on from where you stopped" in said and "`git status`" in said
    assert prompt.carry_on("Write in French.").rstrip().endswith("Write in French.")


@case
def a_write_up_asks_for_answer_md_on_a_document_and_an_answer_on_code():
    document = prompt.write_up("/tmp/scratch/x")
    assert "write `ANSWER.md` in /tmp/scratch/x" in document
    code = prompt.write_up()
    assert "write your report as your answer" in code and "ANSWER.md" not in code
    assert "Do no more work on it" in code and "Do no more work on it" in document


@case
def a_red_local_ci_hands_back_its_command_attempt_and_output():
    said = prompt.local_ci("make ci", "\n  FAILED tests/test_x.py::a  \n", 2, 3, "Write in French.")
    assert "`make ci`" in said and "(attempt 2 of 3)" in said
    assert "```\nFAILED tests/test_x.py::a\n```" in said, "the output, stripped, fenced"
    assert "\nWrite in French.\n" in said
    assert "```\n(no output)\n```" in prompt.local_ci("make ci", "   ", 1, 1)


# -- a prompt file of your own ------------------------------------------------


@case
def no_prompt_file_is_the_fallback(state_home):
    assert prompt.template("") == prompt.DEFAULT
    assert prompt.template("", prompt.DOCUMENT) == prompt.DOCUMENT


@case
def a_prompt_file_that_is_not_there_is_said_rather_than_replaced(state_home):
    missing = state_home / "nowhere" / "prompt.md"
    try:
        prompt.template(str(missing))
    except FileNotFoundError as error:
        assert str(missing) in str(error)
    else:
        raise AssertionError("a missing prompt file is an error, not the default prompt")


@case
def a_prompt_file_is_read_as_written_and_its_home_expanded(state_home):
    written = state_home / "prompt.md"
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text("Fais {title}, en français.\n", encoding="utf-8")
    assert prompt.template(str(written)) == "Fais {title}, en français.\n"
    home = os.environ.get("HOME", "")
    os.environ["HOME"] = str(state_home)
    try:
        assert prompt.template("~/prompt.md") == "Fais {title}, en français.\n"
    finally:
        os.environ["HOME"] = home
