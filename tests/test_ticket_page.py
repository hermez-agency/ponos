"""`ticket_page.py`: a ticket's page in two parts, the mission and what was done."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from support import _board, case

from ponos import config as C
from ponos import db, journal, question, ticket_page, voice
from ponos import prompt as prompt_module
from ponos import ticket as ticket_module
from ponos.runner import Runner


@case
def a_page_reads_as_its_mission_and_what_was_done() -> None:
    page = ticket_page.split(
        "## Mission\n\nCorriger l'entête.\n\n## Ce qui a été fait\n\n"
        "**Résultat** : ✅ corrigé\n\n### Historique\n\n- une\n- deux"
    )
    assert page.mission == "Corriger l'entête."
    assert page.report == "**Résultat** : ✅ corrigé"
    assert page.history == ["une", "deux"]


@case
def a_page_written_before_the_format_is_all_mission() -> None:
    """No heading, no second part: what somebody wrote is the mission whole."""
    text = "## À faire\n\nRelire la page.\n\n### Mission secondaire\n\nGarder le logo."
    assert ticket_page.split(text).mission == text
    assert ticket_page.split(text).done == ""


@case
def the_second_part_is_found_however_its_heading_was_written() -> None:
    """In either language, at any level, numbered or not — a heading is found by its words."""
    for heading in (
        "## What was done",
        "# Ce qui a été fait",
        "### 2. Ce qui a été fait :",
        "## ce qui a été fait",
    ):
        page = ticket_page.split(f"La mission.\n{heading}\nLe compte rendu.")
        assert (page.mission, page.done) == ("La mission.", "Le compte rendu."), heading
    assert ticket_page.split("Ce qui a été fait hier, en une ligne.").done == ""


@case
def a_new_ticket_is_written_with_both_headings() -> None:
    said = voice.Voice("fr")
    page = ticket_page.template(said, "Écrire l'édito.")
    assert page.startswith("## Mission\n\nÉcrire l'édito.\n\n## Ce qui a été fait\n\n")
    assert ticket_page.mission(page) == "Écrire l'édito."
    # A ticket that is all title still says where each part goes.
    assert ticket_page.template(said).startswith("## Mission\n\n## Ce qui a été fait")
    assert ticket_page.mission(ticket_page.template(said)) == ""


@case
def a_report_says_the_result_the_pull_request_the_report_and_what_is_left_to_check() -> None:
    said = voice.Voice("fr")
    answer = (
        "**Ce qui a changé** : l'entête.\n\n**Vérifié** : `npm test`, vert.\n\n"
        "CAVEAT: le rendu mobile\nRESULT: ok — entête corrigé"
    )
    report = ticket_page.report(
        said,
        status="done",
        summary="entête corrigé",
        pull_request="https://github.com/x/y/pull/3",
        answer=answer,
        caveats=question.caveats(answer),
    )
    assert report.splitlines()[0] == "**Résultat** : ✅ entête corrigé"
    assert "**Pull request** : https://github.com/x/y/pull/3" in report
    assert "**Vérifié** : `npm test`, vert." in report
    assert "RESULT" not in report and "CAVEAT" not in report, report
    assert report.endswith("**Reste à vérifier**\n\n- le rendu mobile"), report


@case
def the_lines_written_for_the_runner_are_not_the_report() -> None:
    answer = (
        "J'ai fait ceci.\n\nQUESTION: on garde ?\nMODE: yes-no\nLESSON: x\n**RESULT: blocked — ?**"
    )
    assert question.prose(answer) == "J'ai fait ceci."
    assert question.prose("RESULT: ok — rien") == ""


@case
def a_line_of_history_is_its_date_duration_cost_result_and_session() -> None:
    line = ticket_page.history_line(
        voice.Voice("fr"),
        {
            "ticket": "a" * 32,
            "started_at": "2026-11-06T09:00:00+00:00",
            "ended_at": "2026-11-06T09:12:00+00:00",
            "status": "done",
            "reason": "entête corrigé",
            "cost_usd": 1.5,
        },
        "https://ponos.example/",
    )
    parts = line.split(" · ")
    assert parts[1:] == [
        "12 minutes",
        "1,50 $",
        "✅ entête corrigé",
        f"[session](https://ponos.example/?view=console/tickets/read/{'a' * 32}&tab=live)",
    ], line


# -- the page, rewritten -------------------------------------------------------


@case
def the_ledger_rewrites_the_second_part_and_never_the_mission() -> None:
    with _board("fr") as board:
        page_id = board.create_row("tickets", "Corriger l'entête", {"statut": "ready"})
        board.append_markdown(page_id, "Relire la page.")
        said = voice.Voice("fr")
        for report in ("Un.", "Deux."):
            board.replace_section(page_id, ticket_page.DONE, ticket_page.section(said, report, []))
        body = board.blocks_text(page_id)
        assert body == "## Mission\n\nRelire la page.\n\n## Ce qui a été fait\n\nDeux.", body


# -- three sessions on one ticket -------------------------------------------------


def _runner(board: Any) -> Runner:
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner._comments = {}
    runner.client = board
    runner.dry_run = False
    runner.config = C.Config(
        runner=C.Runner(language="fr"),
        projects={},
        path=Path("/nowhere"),
    )
    runner.config.web.url = "https://ponos.example"
    runner.quiet = True
    return runner


@case
def a_ticket_run_three_times_has_one_part_and_three_lines_of_history(state_home: Path) -> None:
    """The acceptance of the format: replaced at every session, never stacked."""
    try:
        with _board("fr") as board:
            page_id = board.create_row("tickets", "Corriger l'entête", {"statut": "ready"})
            board.replace_markdown(
                page_id, ticket_page.template(voice.Voice("fr"), "Le titre est faux.")
            )
            runner = _runner(board)
            ticket = ticket_module.Ticket(board.page(page_id))
            for attempt in (1, 2, 3):
                run = runner._journals[ticket.id] = journal.Run.start(ticket=ticket.id)
                run.answer = (
                    f"**Ce qui a changé** : essai {attempt}.\n\nRESULT: ok — essai {attempt}"
                )
                run.summary = f"essai {attempt}"
                runner._journal_end(ticket, {"status": "done"})

            body = board.blocks_text(page_id)
            page = ticket_page.split(body)
            assert body.count("Ce qui a été fait") == 1, body
            assert page.mission == "Le titre est faux."
            assert "essai 3" in page.report and "essai 1" not in page.report, page.report
            assert len(page.history) == 3, page.history
            assert all(
                "https://ponos.example/?view=console/tickets/read/" in line for line in page.history
            )

            # What the next session is told of its page: the mission, once,
            # and no earlier report at all.
            brief = runner._body(ticket)
            assert brief == "Le titre est faux."
            prompt = prompt_module.build(
                prompt_module.DEFAULT,
                project="Site",
                title=ticket.title,
                body=brief,
                repo="/repo",
                branch="ticket/x",
                base="main",
                url="",
            )
            assert prompt.count("Le titre est faux.") == 1
            assert "essai" not in prompt and "Ce qui a été fait" not in prompt, prompt
    finally:
        db.close()


@case
def a_session_that_did_no_work_keeps_the_last_report(state_home: Path) -> None:
    """Out of credit, or put back in the queue: a line of history, and the report stays."""
    try:
        with _board("fr") as board:
            page_id = board.create_row("tickets", "Corriger l'entête", {"statut": "ready"})
            runner = _runner(board)
            ticket = ticket_module.Ticket(board.page(page_id))
            run = runner._journals[ticket.id] = journal.Run.start(ticket=ticket.id)
            run.summary = "entête corrigé"
            runner._journal_end(ticket, {"status": "done"})
            runner._journals[ticket.id] = journal.Run.start(ticket=ticket.id)
            runner._journal_end(ticket, {"status": "waiting", "reason": "crédits épuisés"})

            page = ticket_page.split(board.blocks_text(page_id))
            assert "entête corrigé" in page.report and "crédits" not in page.report, page.report
            assert len(page.history) == 2 and "⏸️" in page.history[1], page.history
    finally:
        db.close()
