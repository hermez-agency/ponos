"""`question.py`: the question a blocked ticket asks."""

from __future__ import annotations

from pathlib import Path

from support import (
    TICKET,
    _answering,
    _board_runner,
    _closing,
    _config,
    _reviewed,
    _runner_reading,
    case,
)

from ponos import channels, conversation, notion, prompt, question, voice
from ponos import config as C
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import settings as web_settings

# -- the question a blocked ticket asks ---------------------------------------


# What the session of the 02/10 ticket would hand over: PR #58 verified and
# ready, the merge forbidden in its session. The comment it got was one block —
# what was done, the technical detail and the footer — and no question at all.
PR_58 = (
    "J'ai vérifié la PR : build vert, vidéo de 56 s, QR code lisible.\n\n"
    "DONE: [PR #58](https://github.com/salva/site/pull/58) prête (build ok)\n"
    "WHY: Je n'ai pas le droit de fusionner sur main.\n"
    "QUESTION: Qui fusionne la PR #58 ?\n"
    "MODE: choice\n"
    "OPTION: Tu fusionnes toi-même\n"
    "OPTION: Tu m'autorises à fusionner\n"
    "OPTION: On attend\n\n"
    "RESULT: blocked — PR #58 prête, la fusion sur main est interdite dans cette session"
)


def _asking(question: object, language: str = "fr") -> tuple[Runner, str, list[str]]:
    """A ticket blocked on `question`: the comment written, and what reached the phone."""
    runner = _board_runner([_reviewed("p-stuck", "In progress", None)], {"blocked": "Blocked"})
    runner.config.runner.language = language
    runner.config.notify = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    ).notify
    sent: list[str] = []
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
    try:
        runner._fail(
            ticket_module.Ticket(runner.client._pages[0]),
            runner.voice.say("asked-something"),
            "la session a résumé ça autrement",
            code="session.question",
            blocked=True,
            question=question,
            note=runner.voice.say("trace-in-page"),
        )
    finally:
        channels.announce = original
    return runner, runner.client.comments_written[0], sent


@case
def a_yes_no_question_says_the_two_words_that_answer_it():

    asked = question.Question(
        ask="Je fusionne et je déploie ?",
        mode="yes-no",
        done="PR #58 prête (build ok)",
        why="Je n'ai pas le droit de fusionner sur main.",
    )
    _, comment, sent = _asking(asked)
    assert comment.split("\n") == [
        "🙋 Bloqué — PR #58 prête (build ok)",
        "Je n'ai pas le droit de fusionner sur main.",
        "Je fusionne et je déploie ? → oui / non",
    ], comment
    assert "Une réponse ici" not in comment and "bloc replié" not in comment, "no footer"
    assert "la session a résumé" not in comment, "the session's own question says it all"
    assert sent[0].split("\n")[1:4] == [
        "PR #58 prête (build ok)",
        "Je n'ai pas le droit de fusionner sur main.",
        "Je fusionne et je déploie ? → oui / non",
    ], "the phone gets the same lines"
    _, english, _ = _asking(asked, "en")
    assert english.endswith("Je fusionne et je déploie ? → yes / no"), english


@case
def a_choice_is_numbered_on_one_line_so_that_a_number_answers_it():

    _, comment, _ = _asking(
        question.Question(
            ask="Qui fusionne ?",
            mode="choice",
            options=["Tu fusionnes toi-même", "Tu m'autorises à fusionner", "On attend"],
            why="Je n'ai pas le droit de fusionner sur main.",
        )
    )
    assert comment.split("\n") == [
        "🙋 Bloqué",
        "Je n'ai pas le droit de fusionner sur main.",
        "Qui fusionne ?",
        "1. Tu fusionnes toi-même · 2. Tu m'autorises à fusionner · 3. On attend",
    ], comment
    # A choice of one is no choice, and five is a menu.
    assert question.Question(ask="?", mode="choice", options=["seule"]).mode == "free"
    assert len(question.Question(ask="?", mode="choice", options=list("abcde")).options) == 4


@case
def a_free_question_stands_alone_and_says_what_to_give():

    _, comment, _ = _asking(question.Question(ask="Quelle URL pour le site de Wizaplace ?"))
    assert comment == "🙋 Bloqué\nQuelle URL pour le site de Wizaplace ?", comment
    # A question the runner asks on its own behalf is a free one, and its
    # detail still goes under it — after a blank line, out of the question.
    _, plain, _ = _asking("Quel en-tête ?")
    assert plain == "🙋 Bloqué\nQuel en-tête ?\n\nla session a résumé ça autrement", plain


@case
def a_blocked_comment_reaches_notion_with_real_line_breaks_and_a_link():

    _, comment, _ = _asking(question.parse(PR_58))
    pieces = notion._comment_text(comment)
    drawn = "".join(piece["text"]["content"] for piece in pieces)
    assert drawn.count("\n") == 3, "four lines, three breaks, none of them flattened"
    assert "\\n" not in drawn, "a break, not its escape"
    linked = [piece for piece in pieces if piece["text"].get("link")]
    assert linked == [
        {
            "type": "text",
            "text": {"content": "PR #58", "link": {"url": "https://github.com/salva/site/pull/58"}},
        }
    ], linked
    # And read back as it was written, so the console and the next run see the link.
    read = "".join(
        notion._written({"plain_text": piece["text"]["content"], **piece}) for piece in pieces
    )
    assert read == comment
    assert notion._comment_text("[x](javascript:alert(1))")[0]["text"].get("link") is None


@case
def the_pull_request_58_comes_back_as_a_clear_choice_in_four_lines():
    """The 02/10 comment, played again: a choice, and nothing else."""

    asked = question.parse(PR_58)
    assert asked and asked.mode == "choice", asked
    _, comment, _ = _asking(asked)
    assert comment.split("\n") == [
        "🙋 Bloqué — [PR #58](https://github.com/salva/site/pull/58) prête (build ok)",
        "Je n'ai pas le droit de fusionner sur main.",
        "Qui fusionne la PR #58 ?",
        "1. Tu fusionnes toi-même · 2. Tu m'autorises à fusionner · 3. On attend",
    ], comment
    assert "56 s" not in comment and "QR" not in comment, "the detail stays in the folded block"
    # What was written is what is read back when the answer arrives.
    again = question.found(comment)
    assert (again.mode, again.ask, again.options) == ("choice", asked.ask, asked.options)


@case
def a_session_that_wrote_no_question_blocks_the_way_it_always_did():

    assert question.parse("RESULT: blocked — quel en-tête ?") is None
    found = question.parse("**QUESTION:** On publie ?\n- MODE: yes/no\nRESULT: blocked — x")
    assert found and (found.ask, found.mode) == ("On publie ?", "yes-no"), found
    assert question.found("🙋 Bloqué — Quel en-tête ?") is None, (
        "an older report: no question to read"
    )
    assert question.found("✅ À relire — PR #1\nFait.") is None


@case
def an_answer_is_read_as_the_option_it_names_whatever_its_shape():

    choice = question.Question(
        ask="Qui fusionne ?",
        mode="choice",
        options=["Tu fusionnes toi-même", "Tu m'autorises à fusionner", "On attend"],
    )
    for text, option in (
        ("2", 2),
        ("la 2", 2),
        ("2.", 2),
        ("#3", 3),
        ("option 1", 1),
        ("la deuxième", 2),
        ("2, mais sans déployer", 2),
        ("on attend", 3),
        ("Option 2 : Tu m'autorises à fusionner.", 2),
    ):
        reading = question.read(text, choice)
        assert (reading.kind, reading.option) == ("option", option), (text, reading)
    assert question.read("2", choice).label == "Tu m'autorises à fusionner"
    assert question.read("5", choice).kind == "free", "an option nobody offered"
    assert question.read("un détail : attends lundi", choice).kind == "free"
    yes_no = question.Question(ask="Je fusionne ?", mode="yes-no")
    for text, kind in (("oui", "yes"), ("ok", "yes"), ("Non", "no"), ("2", "free")):
        assert question.read(text, yes_no).kind == kind, text
    free = question.read("https://wizaplace.example", question.Question(ask="Quelle URL ?"))
    assert (free.kind, free.text) == ("free", "https://wizaplace.example")


@case
def an_answer_from_a_phone_is_written_as_the_option_it_chose():

    _, comment, _ = _asking(question.parse(PR_58))
    said = voice.Voice("fr")
    asked = question.waiting([comment])
    reply = channels.Reply(channel="telegram", text="2", who="Salva", ticket=TICKET)
    assert channels.answer(reply, said, asked) == (
        "Répondu depuis Telegram par Salva.\nOption 2 : Tu m'autorises à fusionner."
    )
    reply.text = "la 2, mais sans déployer"
    assert channels.answer(reply, said, asked).splitlines()[1:] == [
        "Option 2 : Tu m'autorises à fusionner.",
        "la 2, mais sans déployer",
    ]
    reply.text = "oui"
    assert channels.answer(reply, said, asked).splitlines()[1:] == ["oui"], (
        "a yes to a list of roads takes none of them"
    )
    # The question a page waits on is its last report's, and only if that one asked.
    assert question.waiting([comment, "2", "✅ À relire — PR #58\nFait."]) is None
    # Through the runner: the question is read off the ticket's own comments.
    runner, _ = _answering(
        [channels.Reply(channel="telegram", text="3", ticket=TICKET, title="Le site")],
        asked=[comment],
    )
    assert runner.client.written[0][1].endswith("Option 3: On attend."), runner.client.written


@case
def the_next_run_is_told_the_question_and_what_the_answer_chose():

    _, comment, _ = _asking(question.parse(PR_58))
    _, lines = _runner_reading([comment, "la 2"])
    assert lines == [
        "a previous run: 🙋 Bloqué — [PR #58](https://github.com/salva/site/pull/58) prête "
        "(build ok) Je n'ai pas le droit de fusionner sur main. — asked: Qui fusionne la PR #58 ? "
        "(options: 1. Tu fusionnes toi-même; 2. Tu m'autorises à fusionner; 3. On attend)",
        "the ticket's author: la 2 (read as: option 2, “Tu m'autorises à fusionner”)",
    ], lines
    _, plain = _runner_reading(["🙋 Stuck\nWhich header? → yes / no", "yes"])
    assert plain[-1] == "the ticket's author: yes (read as: yes)", plain


@case
def every_session_that_can_block_is_told_how_to_ask():
    common = dict(project="p", title="t", body="b", repo="/r", branch="br", base="main", url="u")
    for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.DELIVERY, prompt.RESOLVE):
        text = prompt.build(template, **common)
        assert "QUESTION: <" in text and "MODE: <yes-no, choice or free>" in text, template[:40]
    assert "{asking}" not in prompt.build("{title}", **common), "a prompt of your own is left alone"


@case
def an_answer_is_understood_in_either_language_and_relayed_in_the_runners():
    """« oui » on a board told to speak English, `yes` on one told French: the
    word is read whatever it was typed in, and spelled out in the runner's."""
    for text, verdict in (("oui", "yes"), ("yes", "yes"), ("non", "no"), ("no", "no")):
        assert channels.decide(text) == verdict, text
    reply = channels.Reply(channel="telegram", text="yes", who="Salva", ticket=TICKET)
    relayed = channels.answer(reply, voice.Voice("fr"))
    assert relayed == "Répondu depuis Telegram par Salva.\nOui — vas-y avec ce que tu as proposé."
    assert conversation.is_relayed(relayed), "and it still wakes the ticket"
    assert (
        channels.answer(reply)
        == "Answered from Telegram by Salva.\nYes — go ahead with what you proposed."
    )
    assert conversation.is_relayed("Answered from Slack.\nok"), "a board keeps the old ones"
    assert conversation.said(relayed) == "Oui — vas-y avec ce que tu as proposé."


@case
def what_the_runner_writes_on_github_and_on_a_schedules_ticket_follows_the_language():
    said = voice.Voice("fr")
    body = said.pull_request_body("Le header est parti.", "https://notion.so/t", "abc", 3)
    assert body == (
        "Le header est parti.\n\n---\nTicket Notion : https://notion.so/t\n"
        "Session Claude Code : `abc`\nOuverte par ponos (3 commits)."
    ), body
    assert (
        voice.Voice().pull_request_body("s", "u", "abc", 1).endswith("Opened by ponos (1 commit).")
    ), "and English says what it always said"
    assert said.say("born-of-schedule", name="Veille", stamp="2026-10-02", url="u") == (
        "*Né de la récurrence « Veille », 2026-10-02* — u"
    )
    assert "Ponos" in said.say("out-of-credit") and said.say("out-of-credit") != voice.Voice().say(
        "out-of-credit"
    )


@case
def the_console_opens_in_the_language_the_file_names_and_follows_the_reports_by_default():
    """One line — `language = "fr"` — is enough to have everything in French;
    `app_language` is for whoever wants the two apart."""
    from ponos.web import server as web_server

    settings = C.Runner()
    assert settings.interface_language() == "", "nothing said: the browser decides"
    settings.language = "fr"
    assert settings.interface_language() == "fr", "the console follows the reports"
    settings.app_language = "en"
    assert settings.interface_language() == "en", "unless it is told otherwise"
    loaded = _config('[runner]\nlanguage = "fr"\napp_language = "en"\n').runner
    assert (loaded.language, loaded.app_language) == ("fr", "en")

    page = b'<!doctype html>\n<html lang="en" class="dark">\n<body></body></html>'
    assert web_server.configured(page, "") == page, "nothing said, nothing written"
    marked = web_server.configured(page, "fr")
    assert marked.startswith(b'<!doctype html>\n<html data-language="fr" lang="en" class="dark">')
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    assert b"\napp_language = " in example.read_bytes(), "documented where every key is"
    fields = {
        (field.table, field.key) for section in web_settings.SECTIONS for field in section.fields
    }
    assert ("runner", "app_language") in fields, "and the Settings screen offers it"


@case
def a_ticket_is_never_closed_on_an_answer_github_did_not_give():
    """No pull request, or no `gh` to ask: the ticket stays where it is."""
    client, closed = _closing(
        [
            _reviewed("p-nothing", "In review", None),
            _reviewed("p-empty", "In review", ""),
            _reviewed("p-unreachable", "In review", "https://github.com/x/y/pull/3"),
        ],
        {},  # as when gh is missing or not authenticated
        {"review": "In review", "done": "Done"},
    )
    assert closed == 0 and client.written == []


@case
def the_columns_are_read_in_one_order_with_blocked_right_after_running():
    """The console, its filters and the MCP tools share one order, cancelled last."""
    from ponos.web import api, mcp

    order = api.COLUMNS
    assert order.index("blocked") == order.index("running") + 1, order
    assert order[-2:] == ("done", "cancelled"), order
    assert [key for key in order if key not in ("blocked",)] == [
        "ready",
        "running",
        "review",
        "validated",
        "failed",
        "done",
        "cancelled",
    ], order
    assert ("draft", *order) == mcp.STATUSES, mcp.STATUSES


@case
def a_board_without_a_review_column_is_never_even_queried():
    """`review` following `done` means there is nowhere for a ticket to wait."""
    client, closed = _closing(
        [_reviewed("p-done", "Done", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {"done": "Done"},
    )
    assert closed == 0 and client.written == []
