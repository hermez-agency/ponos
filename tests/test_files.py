"""`files.py`: a board made of Markdown files."""

from __future__ import annotations

import tempfile
from pathlib import Path

from support import _board, _no_session, _run_on, case

from ponos import config as C
from ponos import files, notion, schedules, store, voice
from ponos.runner import Runner

# -- a board made of files ----------------------------------------------------


@case
def a_frontmatter_survives_the_round_trip():
    """What `render` writes, `parse` has to read back — every shape of it.

    The file is the board: a value that comes back as something else is a
    status nobody can filter on, or a day of the month that is no longer one.
    """
    front = {
        "id": "a" * 32,
        "title": "Corriger l'entête « à faire »",
        "created": "2026-09-14T09:00:00+00:00",
        "Status": "In review",
        "Active": False,
        "Cost": 1.25,
        "Day": "1",
        "Project": ["p1", "p2"],
        "Empty": "",
    }
    back, body = files.parse(files.render(front, "# Titre\n\nUn corps."))
    assert back == front, back
    assert body == "# Titre\n\nUn corps."
    # Twice through, byte for byte: a pass that rewrote the same file would
    # otherwise look like a change to the sync, for ever.
    once = files.render(front, "x")
    assert files.render(*files.parse(once)) == once


@case
def a_file_with_no_frontmatter_is_all_body():
    front, body = files.parse("Je suis Camille Martin.\n")
    assert front == {} and body == "Je suis Camille Martin."


@case
def tickets_are_written_and_read_back_as_markdown():
    with _board() as board:
        page_id = board.create_row(
            "tickets", "Corriger l'entête", {"Status": "Ready", "Priority": "High"}
        )
        board.append_markdown(page_id, "## À faire\n\nRelire la page.")
        page = board.page(page_id)
        assert page.title == "Corriger l'entête"
        assert store.read(page, "Status") == "Ready"
        assert store.read(page, "Priority") == "High"
        assert "Relire la page." in board.blocks_text(page_id)
        # The file is where somebody would look for it, named after the ticket.
        written = list((board.root / "tickets").glob("*.md"))
        assert len(written) == 1 and written[0].name.startswith("corriger-l-entete-")

        board.update("tickets", page_id, {"Status": "In progress", "Runner": "ponos@here"})
        assert store.read(board.page(page_id), "Status") == "In progress"
        assert store.read(board.page(page_id), "Runner") == "ponos@here"
        # And the body is untouched by a property write.
        assert "Relire la page." in board.blocks_text(page_id)


@case
def a_markdown_ticket_reads_its_brief_without_its_live_reports():
    """A file has no toggle: the story of a run is fenced, and the brief leaves it out."""
    with _board() as board:
        page_id = board.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})
        board.append_markdown(page_id, "## À faire\n\nRelire la page.")
        _run_on(board, "fr", "Je lis la configuration.", ok=False, page_id=page_id)
        board.append_markdown(page_id, "---\nPull request ouverte : x/y#3")
        _run_on(board, "en", "Reading the header again.", page_id=page_id)
        brief = board.blocks_text(page_id, live=False)
        assert brief == "## À faire\n\nRelire la page.\n\n---\nPull request ouverte : x/y#3", brief
        whole = board.blocks_text(page_id)
        assert "Je lis la configuration." in whole and "Reading the header again." in whole
        # One stretch per run, opened by its toggle and holding all its steps.
        assert whole.count(files.LIVE_OPEN) == 2 == whole.count(files.LIVE_CLOSE), whole
        assert whole.index("Je lis la configuration.") < whole.index(files.LIVE_CLOSE)


@case
def a_markdown_board_answers_the_filters_the_runner_builds():
    with _board() as board:
        ready = board.create_row("tickets", "À faire", {"Status": "Ready"})
        board.create_row("tickets", "Finie", {"Status": "Done"})
        found = board.query("tickets", {"property": "Status", "select": {"equals": "Ready"}})
        assert [page.id for page in found] == [ready]
        # The woken filter: everything but the statuses that speak for a ticket.
        awake = board.query(
            "tickets",
            {
                "and": [
                    {"property": "Status", "select": {"does_not_equal": "Ready"}},
                    {"property": "Status", "select": {"does_not_equal": "Done"}},
                ]
            },
        )
        assert awake == []
        # A filter this cannot read must not silently empty the board.
        assert len(board.query("tickets", {"timestamp": "created_time"})) == 2


@case
def projects_the_context_and_the_schedules_live_in_files_too():
    """The three things the ticket's UI has to be able to show without Notion."""
    with _board() as board:
        project = board.create_row("projects", "ponos", {"Repository": "user/repo"})
        assert store.read(board.page(project), "Repository") == "user/repo"

        board.set_context("Je suis Camille Martin, développeur web.")
        assert board.context() == "Je suis Camille Martin, développeur web."
        assert board.blocks_text(files.CONTEXT_PAGE) == board.context()

        schedule = board.create_row(
            "schedules",
            "Revue des dépendances",
            {"Cadence": "Weekly", "At": "09:00", "Day": "Monday", "Active": True},
        )
        row = schedules.read(board.page(schedule), board.settings())
        assert row.cadence == "Weekly" and row.at == "09:00" and row.day == "Monday"
        assert row.active is True and not row.problem
        # And a schedule turned off from the console comes back off.
        board.update("schedules", schedule, {"Active": False})
        assert schedules.read(board.page(schedule), board.settings()).active is False


@case
def a_markdown_board_keeps_a_discussion_per_page():
    with _board() as board:
        page_id = board.create_row("tickets", "Une question", {})
        board.comment(page_id, "La question ?")
        board.comment(page_id, "Et la suite,\n\navec un blanc au milieu.", discussion_id="d-1")
        said = board.comments(page_id)
        assert [comment.text for comment in said] == [
            "La question ?",
            "Et la suite,\n\navec un blanc au milieu.",
        ]
        assert said[1].discussion_id == "d-1"
        assert all(comment.created_by == board.me() for comment in said)


@case
def the_whole_runner_runs_against_files_with_no_notion_at_all(state_home):
    """A full pass in `storage.mode = "markdown"`, network unplugged.

    The one test that answers the question the mode exists for: does the runner
    — the queue, the claim, the session, the report — work when there is no
    integration, no token and no workspace to resolve? Notion's own client is
    replaced by something that raises if it is so much as constructed, so a
    single call that reached for it would fail here rather than in production.
    """
    with _board() as board:
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text(
            f'[storage]\nmode = "markdown"\npath = "{board.root}"\n'
            "[runner]\ndry_run = false\nprogress = false\nreply = false\n"
            "auto_update = false\nnotify = false\nattach_sessions = false\n",
            encoding="utf-8",
        )
        configuration = C.load(path)

        # Nothing here may be reached for. A configuration with no token would
        # only have produced a 401; this produces a traceback naming the caller.
        def refuse(*_args, **_kwargs):
            raise AssertionError("markdown mode must never construct a Notion client")

        # Typed by hand: a ticket with no type would first be classified, and
        # that is a question of its own — see the cases on kinds.py.
        page_id = board.create_row(
            "tickets", "Écrire l'annonce", {"Status": "Ready", "Type": "Writing"}
        )
        board.append_markdown(page_id, "Rédige une annonce courte.")
        board.set_context("Je suis Camille Martin.")

        real_client = notion.Client
        notion.Client = refuse
        try:
            configuration.require_usable()  # no token, and that is not a fault
            run = Runner(configuration, quiet=True)
            assert isinstance(run.client, files.Board)
            assert run.database == "tickets"
            assert run.workspace.context == "Je suis Camille Martin."
            ready = run.ready()
            assert [ticket.title for ticket in ready] == ["Écrire l'annonce"]

            with _no_session(answer="C'est écrit.", writes={"ANSWER.md": "# Annonce\n\nVoilà."}):
                results = run.tick()
        finally:
            notion.Client = real_client

        assert [result["status"] for result in results] == ["done"], results
        done = board.page(page_id)
        assert store.read(done, "Status") == "Done"
        assert "Voilà." in board.blocks_text(page_id), board.blocks_text(page_id)
        # The report went into the ticket's discussion, as it does on Notion.
        assert any(voice.is_report(comment.text) for comment in board.comments(page_id))


@case
def two_processes_writing_one_ticket_lose_nothing():
    """The runner and the console are two processes, and both write tickets.

    The console moves a status while the runner appends its report: each one
    reads the file, changes it and writes it back. Without a lock between them
    the last writer wins and the other's change is gone; written in place, a
    reader caught in the middle reads a frontmatter that is not there yet.
    """
    import os

    rounds = 60
    with _board() as board:
        page_id = board.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})

        def writer(which: str) -> None:
            for index in range(rounds):
                if which == "console":
                    board.update("tickets", page_id, {"Status": f"S{index}"})
                board.append_markdown(page_id, f"{which}-{index}.")

        def reader() -> None:
            for _ in range(rounds * 4):
                assert files.parse(files._text(board._find(page_id)[1]))[0].get("id")

        children = []
        for job in (lambda: writer("runner"), lambda: writer("console"), reader):
            child = os.fork()
            if child == 0:
                code = 1
                try:
                    job()
                    code = 0
                finally:
                    os._exit(code)
            children.append(child)
        codes = [os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) for child in children]
        assert codes == [0, 0, 0], codes
        body = board.blocks_text(page_id)
        lost = [
            f"{which}-{index}."
            for which in ("runner", "console")
            for index in range(rounds)
            if f"{which}-{index}." not in body
        ]
        assert not lost, f"{len(lost)} writes lost: {lost[:5]}"
        assert store.read(board.page(page_id), "Status") == f"S{rounds - 1}"
