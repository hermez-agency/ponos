"""`ticket_page.py`: a ticket's page in two parts, the mission and what was done."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from support import _board, _run_on, case

from ponos import config as C
from ponos import db, journal, markdown, notion, progress, question, state, ticket_page, voice
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
    """In either language, at any level, numbered or not — Notion flattens it to one line."""
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


class _Page:
    """A Notion page as a list of blocks, reached through the client's own requests."""

    def __init__(self) -> None:
        self.children: dict[str, list[dict[str, Any]]] = {"page": []}
        self.deleted: list[str] = []

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        made = []
        for block in blocks:
            kind = block["type"]
            rich = [
                {**part, "plain_text": part["text"]["content"]}
                for part in block[kind].get("rich_text", [])
            ]
            made.append(
                {"id": uuid.uuid4().hex, "has_children": False, **block, kind: {"rich_text": rich}}
            )
        self.children.setdefault(block_id, []).extend(made)
        for held in self.children.values():
            for child in held:
                child["has_children"] = bool(self.children.get(child["id"]))
        return [block["id"] for block in made]

    def request(self, method: str, path: str, body: Any = None, **_: Any) -> dict[str, Any]:
        parent = path.split("?")[0].split("/")[2]
        if method == "DELETE":
            self.deleted.append(parent)
            for held in self.children.values():
                held[:] = [block for block in held if block["id"] != parent]
            return {}
        if method == "PATCH":
            return {
                "results": [{"id": made} for made in self.append_blocks(parent, body["children"])]
            }
        return {"results": list(self.children.get(parent, [])), "has_more": False}


def _client(page: _Page) -> notion.Client:
    client = notion.Client("ntn_x")
    client._request = page.request  # type: ignore[method-assign]
    return client


@case
def notion_rewrites_the_second_part_and_never_the_mission() -> None:
    """Block by block: the mission's blocks keep their identity, the old part and
    the toggles an older live report left are the only ones deleted."""
    page = _Page()
    page.append_blocks("page", markdown.to_blocks("Corriger l'entête.\n\n- garder le logo"))
    mission = [block["id"] for block in page.children["page"]]
    _run_on(page, "fr", "Je lis la configuration.")  # type: ignore[arg-type]  # a fake: a page as a tree of blocks
    client = _client(page)
    said = voice.Voice("fr")

    for report in ("Premier compte rendu.", "Second compte rendu."):
        client.replace_section("page", ticket_page.DONE, ticket_page.section(said, report, []))

    assert [block["id"] for block in page.children["page"][:2]] == mission
    assert not [block for block in page.children["page"] if progress.is_live(block)]
    text = client.blocks_text("page")
    assert text.count("Ce qui a été fait") == 1, text
    assert "Second compte rendu." in text and "Premier compte rendu." not in text, text
    assert ticket_page.mission(text) == "Corriger l'entête.\n- garder le logo"


@case
def the_ledger_rewrites_the_second_part_and_drops_its_live_reports() -> None:
    with _board("fr") as board:
        page_id = board.create_row("tickets", "Corriger l'entête", {"statut": "ready"})
        board.append_markdown(page_id, "Relire la page.")
        _run_on(board, "fr", "Je lis la configuration.", page_id=page_id)
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
        notion=C.Notion(),
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
            assert state.shaped([ticket.id]) == {ticket.id}

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


@case
def an_open_ticket_written_before_the_format_is_put_in_two_parts_once(state_home: Path) -> None:
    """The mission is the page as it stood; the last report comes from the comments."""
    try:
        with _board("fr") as board:
            runner = _runner(board)
            page_id = board.create_row("tickets", "Corriger l'entête", {"statut": "ready"})
            board.append_markdown(page_id, "Le titre est faux.")
            _run_on(board, "fr", "Je lis la configuration.", page_id=page_id)
            board.comment(page_id, "✅ À relire\nEntête corrigé.\nhttps://github.com/x/y/pull/3")
            finished = board.create_row("tickets", "Fini", {"statut": "done"})
            board.append_markdown(finished, "Rien à toucher.")
            runner._workspace = type("W", (), {"tickets": "tickets"})()

            assert runner.reshape() == 1
            page = ticket_page.split(board.blocks_text(page_id))
            assert page.mission == "Le titre est faux.", page
            assert "Entête corrigé." in page.report, page.report
            assert "Je lis la configuration." not in board.blocks_text(page_id)
            assert ticket_page.split(board.blocks_text(finished)).mission == "Rien à toucher."
            assert not ticket_page.split(board.blocks_text(finished)).report, (
                "a done ticket is not touched"
            )

            # Once: the board is not read for it again.
            board.append_markdown(page_id, "Ajouté depuis.")
            assert runner.reshape() == 0
            assert "Ajouté depuis." in board.blocks_text(page_id)
    finally:
        db.close()
