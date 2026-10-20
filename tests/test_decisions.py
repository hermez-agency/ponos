"""`decisions.py`: deciding on a card that waits on you."""

from __future__ import annotations

from support import _board, _ideas_api, case

from ponos import config as C
from ponos import conversation, prompt, question, store, voice

# -- deciding on a card that waits on you -------------------------------------


@case
def a_blocked_session_names_what_it_stopped_on_and_a_finished_one_what_to_check():
    """CATEGORY and CAVEAT, read like the other fields: from the end, before RESULT."""

    asked = question.parse(
        "I tried.\nDONE: nothing\nWHY: no Cloudflare token\nCATEGORY: Access\n"
        "QUESTION: Which token?\nMODE: free\nRESULT: blocked — no token"
    )
    assert asked.category == "access" and asked.why == "no Cloudflare token"
    unknown = question.parse("WHY: x\nCATEGORY: weather\nQUESTION: Now?\nRESULT: blocked — x")
    assert unknown.category == "", "a category nobody offered is no category"
    assert question.caveats(
        "CAVEAT: quoted earlier\nDone.\nCAVEAT: not tried on Safari\n- CAVEAT: **no screenshot**\n"
        "RESULT: ok — the header"
    ) == ["not tried on Safari", "no screenshot"]
    assert question.caveats("Done.\nRESULT: ok — the header") == []
    assert "CATEGORY: <one word" in prompt.ASKING and "CAVEAT: <" in prompt.ASKING
    assert all(
        "{asking}" in template for template in (prompt.DEFAULT, prompt.DOCUMENT, prompt.RESOLVE)
    )


@case
def a_blocked_report_says_its_category_and_the_console_reads_it_back():
    """Written in front of why, in the runner's language, and read back in either."""
    from ponos import decisions

    for language, named in (("fr", "Accès manquant : "), ("en", "Missing access: ")):
        said = voice.Voice(language)
        asked = question.Question(
            ask="Which token?",
            mode="choice",
            options=["Production", "A new one"],
            done="branch ready",
            why="no Cloudflare token",
            category="access",
        )
        report = said.paragraphs(
            said.report(said.verdict("blocked", asked.done), *said.question(asked)),
            "Worktree kept.",
        )
        assert named + "no Cloudflare token" in report
        assert question.found(report).options == ["Production", "A new one"], (
            "the layout still reads"
        )
        found = decisions.blockage(["an answer", report, "a reply of yours"])
        assert found.category == "access" and found.declared and found.reported
        assert found.reason == "no Cloudflare token" and found.done == "branch ready"
        assert found.detail == "Worktree kept." and found.question.ask == "Which token?"
        keys = [solution.key for solution in decisions.unblocking(found)]
        assert keys == ["option", "option", "done-retry", "instruct", "abandon", "other"], keys


@case
def a_ticket_blocked_before_the_categories_still_reads_as_a_reason_and_offers_defaults():
    """No name in front: the words give the kind away, and the defaults follow."""
    from ponos import decisions

    said = voice.Voice("fr")
    old = decisions.blockage(["🙋 Question\nWhich header, the dashboard's or the site's?"])
    assert old.category == "question" and not old.declared and old.reported
    assert old.reason == "Which header, the dashboard's or the site's?"
    offered = decisions.unblocking(old)
    assert [solution.key for solution in offered] == ["answer", "instruct", "abandon", "other"]
    assert len(offered) - 1 >= 2, "at least two solutions beside the free one"
    for key, category in (
        ("conflict-open", "conflict"),
        ("checks-red", "ci"),
        ("rebased-too-often", "conflict"),
    ):
        reason = said.sentence(said.say(key, base="main", branch="b", limit="5 $"))
        found = decisions.blockage([said.report(said.verdict("blocked"), reason)])
        assert found.category == category, (key, found)
        assert found.reason == reason
    budget = said.say("over-ticket-budget", limit="5,00 $")
    assert decisions.classify(budget) == "credits"
    assert decisions.classify("I need the SSH password of the server") == "access"
    assert decisions.classify("Il faut que tu installes Tailscale sur ta machine") == "manual"
    assert decisions.classify("too big for one ticket, split it") == "split"
    assert decisions.classify("Nothing to say") == "other"
    aside = decisions.blockage(["✅ To review — PR #3\nDone."])
    assert aside.category == "other" and not aside.reported, "set aside by hand: nothing said"
    assert [solution.key for solution in decisions.unblocking(aside, models=False)] == [
        "retry",
        "instruct",
        "abandon",
        "other",
    ]
    for category in decisions.DEFAULTS:
        offered = decisions.unblocking(decisions.Blockage(category=category))
        assert offered[-1].key == "other" and len(offered) >= 3, category


@case
def a_ticket_too_big_offers_its_sub_tickets_as_a_split():
    from ponos import decisions

    found = decisions.Blockage(
        category="split",
        question=question.Question(ask="Split?", mode="choice", options=["The API", "The page"]),
    )
    offered = decisions.unblocking(found)
    assert [solution.key for solution in offered] == ["split", "instruct", "abandon", "other"]
    assert offered[0].text == "The API\nThe page" and offered[0].column == "done"


@case
def a_question_that_proposes_to_close_the_ticket_offers_to_close_it_at_once():
    """A duplicate, nothing to do: "yes, close it" files it as done, no session to say so."""
    from ponos import decisions

    said = voice.Voice("fr")
    for ask in ("C'est un doublon de #12 : je le clos ?", "Nothing to do here — close it?"):
        found = decisions.Blockage(
            category="question", question=question.Question(ask=ask, mode="yes-no")
        )
        offered = decisions.unblocking(found)
        assert [solution.key for solution in offered][:3] == ["yes", "close", "answer"], ask
        assert offered[1].column == "done" and offered[1].needs == ""
    told = decisions.told(said, decisions.Solution("close", "done"))
    assert told == ["Décision : oui, clos-le — passé en terminé.", said.say("told-close")]
    work = decisions.Blockage(
        question=question.Question(ask="Which header?", mode="choice", options=["A", "B"])
    )
    assert "close" not in [solution.key for solution in decisions.unblocking(work)]
    free = decisions.Blockage(question=question.Question(ask="Close which one?", mode="free"))
    assert "close" not in [solution.key for solution in decisions.unblocking(free)], (
        "a free answer is words"
    )


@case
def a_review_report_carries_what_to_check_and_the_panel_offers_to_send_it_back():
    from ponos import decisions

    said = voice.Voice("fr")
    report = said.report(
        said.verdict("review", "PR #3", "2 commits"),
        "Ajoute un bouton.",
        "https://github.com/a/b/pull/3",
        *said.caveats(
            ["Pas de test e2e", "Les captures restent à faire", "Le wording est à relire"]
        ),
    )
    assert "À vérifier : Pas de test e2e" in report
    found = decisions.delivered([report])
    assert found.summary == "Ajoute un bouton." and found.pull_request.endswith("/pull/3")
    assert found.caveats == [
        "Pas de test e2e",
        "Les captures restent à faire",
        "Le wording est à relire",
    ]
    assert found.facts == "PR #3 · 2 commits"
    offered = decisions.deciding(found, said, checks="failed")
    assert [solution.key for solution in offered] == [
        "validate",
        "rework",
        "fix-ci",
        "add-tests",
        "screenshots",
        "caveat",
        "reject",
    ]
    assert offered[0].column == "validated" and offered[-1].column == "done"
    assert "Le wording est à relire" in offered[5].text and offered[5].number == 3
    green = decisions.deciding(found, said, checks="passed", validate=False)
    assert green[0].column == "done" and "fix-ci" not in [solution.key for solution in green]
    assert decisions.checks_state([{"bucket": "pass"}, {"bucket": "fail"}]) == "failed"
    assert decisions.checks_state([{"bucket": "pass"}, {"bucket": "pending"}]) == "pending"
    assert decisions.checks_state([{"bucket": "pass"}, {"bucket": "skipping"}]) == "passed"
    assert decisions.checks_state([]) == "none"


@case
def each_choice_moves_the_ticket_and_leaves_the_instruction_for_the_next_session(state_home):
    """The panel's gestures, on a board of files: the comment, then the move.

    A choice that sends the ticket back to work writes the instruction first —
    as an answer relayed from the console, which the next session reads as the
    author's — and queues the move; one that files it away moves it at once,
    then says so, so that the runner never reads that comment as an answer.
    """
    settings = C.Notion()
    with _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        api = _ideas_api(board)
        said = api.runner.voice
        assert said.language == "en"
        asked = said.report(
            said.verdict("blocked", "nothing"),
            *said.question(
                type(
                    "Q",
                    (),
                    {
                        "ask": "Which host?",
                        "mode": "choice",
                        "why": "",
                        "options": ["Dokploy", "Vercel"],
                        "category": "",
                    },
                )()
            ),
        )

        def blocked(title: str, report: str = asked) -> str:
            page = board.create_row("tickets", title, {"Status": settings.state("blocked")})
            board.update("tickets", page, {"Project": [project]})
            board.comment(page, report)
            return page

        first = blocked("Choose the host")
        shown = api.decision(first)
        assert shown["column"] == "blocked" and shown["category"] == "question"
        assert [solution["key"] for solution in shown["solutions"]][:2] == ["option", "option"]
        assert shown["solutions"][1]["label"] == "option 2, “Vercel”"
        assert shown["solutions"][-1]["key"] == "other"

        done = api.decide(first, "option", number=2)
        assert done["column"] == "ready" and api.outbox.marks()[first].column == "ready"
        comment = board.comments(first)[-1].text
        assert comment.splitlines() == [
            "Answered from the console.",
            "Decision: option 2, “Vercel”.",
            "Option 2: Vercel.",
        ]
        assert conversation.is_relayed(comment), "read by the next session as the author's word"

        second = blocked("Install Tailscale")
        try:
            api.decide(second, "other")
        except ValueError:
            pass
        else:
            raise AssertionError("an instruction of your own needs its words")
        api.decide(second, "other", text="Use the auth key in 1Password.\nThen carry on.")
        assert board.comments(second)[-1].text.endswith(
            "Use the auth key in 1Password.\nThen carry on."
        )

        third = blocked("Give up")
        api.decide(third, "abandon", text="Not needed any more.")
        # Given up on, not done: the board offers a cancelled column.
        assert store.read(board.page(third), "Status") == settings.state("cancelled"), (
            "moved at once"
        )
        assert third not in api.outbox.marks()
        assert board.comments(third)[-1].text.splitlines()[1:] == [
            "Decision: abandoned, moved to cancelled.",
            "Not needed any more.",
        ]

        fourth = blocked(
            "Too big",
            said.report(
                said.verdict("blocked"),
                *said.question(
                    type(
                        "Q",
                        (),
                        {
                            "ask": "Split it?",
                            "mode": "choice",
                            "why": "two things",
                            "options": ["The API", "The page"],
                            "category": "split",
                        },
                    )()
                ),
            ),
        )
        assert api.decision(fourth)["solutions"][0] == {
            "key": "split",
            "column": "done",
            "needs": "titles",
            "text": "The API\nThe page",
            "number": 0,
            "label": "split into sub-tickets",
        }
        api.decide(fourth, "split", titles=["The API", " ", "The page"])
        assert store.read(board.page(fourth), "Status") == settings.state("done")
        made = [
            page for page in board.query("tickets", {}) if page.title in ("The API", "The page")
        ]
        assert len(made) == 2 and all(store.read(page, "Project") == [project] for page in made)
        assert all(not store.read(page, "Status") for page in made), "drafts, never a paid session"
        assert "split into 2 tickets: The API · The page" in board.comments(fourth)[-1].text

        fifth = blocked(
            "Crashed twice", said.report(said.verdict("blocked"), "It went round in circles.")
        )
        assert "model" in [solution["key"] for solution in api.decision(fifth)["solutions"]]
        api.decide(fifth, "model", model="opus")
        assert store.read(board.page(fifth), settings.prop("model")) == "opus"
        assert api.outbox.marks()[fifth].column == "ready"
        assert "Decision: run it again on opus." in board.comments(fifth)[-1].text

        reviewed = board.create_row("tickets", "A button", {"Status": settings.state("review")})
        board.comment(
            reviewed,
            said.report(
                said.verdict("review", "PR #3"),
                "Adds a button.",
                "https://github.com/a/b/pull/3",
                *said.caveats(["no screenshot taken"]),
            ),
        )
        panel = api.decision(reviewed)
        assert panel["summary"] == "Adds a button." and panel["caveats"] == ["no screenshot taken"]
        assert panel["pull_request"] == "https://github.com/a/b/pull/3"
        assert [solution["key"] for solution in panel["solutions"]][-1] == "reject"
        api.decide(reviewed, "screenshots", text="Take them on mobile too.")
        assert api.outbox.marks()[reviewed].column == "ready"
        assert board.comments(reviewed)[-1].text.splitlines()[1:] == [
            "Decision: back to work: take the screenshots.",
            "Take them on mobile too.",
        ]

        ready = board.create_row("tickets", "Elsewhere", {"Status": settings.state("ready")})
        try:
            api.decision(ready)
        except ValueError:
            pass
        else:
            raise AssertionError("a ready ticket waits on nobody")
