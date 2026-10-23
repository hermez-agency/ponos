"""`blocks.py`: why a ticket stopped."""

from __future__ import annotations

import ast
import json
import re
import tempfile
from datetime import UTC, date
from pathlib import Path

from support import FRONTEND, ROOT, _board_runner, _reviewed, case

from ponos import config as C
from ponos import db, files, journal, provision, session, state, store, voice
from ponos import ticket as ticket_module
from ponos.web import statistics as web_statistics
from ponos.web import tickets as web_tickets

# -- why a ticket stopped -----------------------------------------------------


def _fail_calls() -> list[tuple[str, int, ast.Call]]:
    """Every `self._fail(...)` of the run's chapters, where it is written.

    The run's modules are the ones at the top of the package: `web/` and
    `channels/` have a `_fail` of their own, which answers an HTTP request.
    """
    found = []
    for path in sorted((ROOT / "src/ponos").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_fail"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                found.append((path.name, node.lineno, node))
    return found


@case
def every_fail_carries_a_code_the_catalogue_knows():
    """The guarantee the catalogue is for: no stop said without its cause.

    A literal code is checked against the catalogue as it is written; the one
    a session's ending decides (`_why_stopped`) is a variable at the call, and
    its literals are checked where they are written instead.
    """
    from ponos import blocks

    calls = _fail_calls()
    assert len(calls) >= 25, f"{len(calls)} calls to _fail — the scan missed the run's modules"
    for name, line, call in calls:
        given = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "code" in given, f"{name}:{line} — a _fail without code="
        code = given["code"]
        if isinstance(code, ast.Constant):
            assert code.value in blocks.CAUSES, (
                f"{name}:{line} — {code.value!r} is not in blocks.py"
            )
        else:
            assert isinstance(code, ast.Name), f"{name}:{line} — code= is neither a code nor a name"
    asked = []
    for path in sorted((ROOT / "src/ponos").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in (
                "_why_stopped",
                "_blocked_by",
            ):
                asked += [
                    constant.value
                    for argument in node.args
                    for constant in ast.walk(argument)
                    if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
                ]
    assert len(asked) >= 4, asked
    for code in asked:
        assert code in blocks.CAUSES, f"{code!r} is not in blocks.py"
    # And at run time: a code the catalogue does not hold is refused, not written.
    runner = _board_runner([_reviewed("p-1", "In progress", None)], {"blocked": "Blocked"})
    try:
        runner._fail(ticket_module.Ticket(runner.client._pages[0]), "x", code="merge.nope")
    except ValueError as error:
        assert "merge.nope" in str(error)
    else:
        raise AssertionError("an unknown code was accepted")
    assert runner.client.written == []


@case
def every_cause_is_described_whole_in_both_languages():
    from ponos import blocks

    assert blocks.UNKNOWN in blocks.CAUSES
    for given in (
        "worktree.residue",
        "worktree.interrupted",
        "session.killed",
        "session.not-started",
        "session.no-answer",
        "session.no-commit",
        "session.question",
        "merge.base-red",
        "merge.checks-failed",
        "merge.base-moving",
        "merge.refused",
        "merge.conflict-decision",
        "merge.push-refused",
        "merge.no-pr",
        "publish.failed",
        "notion.write-failed",
        "access.sudo",
        "access.credentials",
        "project.no-repo",
    ):
        assert given in blocks.CAUSES, f"the ticket's {given} is missing"
    for code, cause in blocks.CAUSES.items():
        assert code == blocks.UNKNOWN or re.fullmatch(r"[a-z]+\.[a-z-]+", code), code
        assert cause.family in blocks.FAMILIES, code
        assert cause.who in blocks.WHO, code
        assert cause.action in blocks.ACTIONS, code
        assert re.fullmatch(r"retry:\d|wait-base|ask", cause.policy), code
        for language in voice.LANGUAGES:
            assert cause.label[language].strip() and cause.help[language].strip(), code
            assert len(cause.label[language]) <= 32, f"{code}: a badge, not a sentence"
        for key in cause.said:
            assert key in voice._SAID, f"{code} names the voice key {key!r}, which does not exist"
    # The families are drawn by the console, one icon each: the same five.
    console = (FRONTEND / "src/components/console/ticket-bits.tsx").read_text(encoding="utf-8")
    for family in blocks.FAMILIES:
        assert f"{family}:" in console or f'"{family}":' in console, family


@case
def every_sentence_said_for_a_cause_is_read_back_to_it():
    """What the migration counts on: today's sentences, and those the history holds."""
    from ponos import blocks

    values = {
        "base": "main",
        "branch": "ticket/x",
        "limit": "$5",
        "origin": "Validated",
        "problem": "x",
        "url": "https://github.com/o/r/pull/1",
    }
    for code, cause in blocks.CAUSES.items():
        for key in cause.said:
            if code == "worktree.interrupted":
                continue  # asked as a question, never kept as a sentence
            for language in voice.LANGUAGES:
                sentence = voice.Voice(language).say(key, **values)
                assert blocks.classify(sentence) == code, (code, language, sentence)
    heard = {
        "its conflicts were resolved, but its checks fail": "merge.checks-failed",
        "ses conflits ont été résolus, mais ses vérifications échouent": "merge.checks-failed",
        "`dev` keeps moving faster than its pull request can be replayed onto it": "merge.base-moving",
        "`main` avance plus vite que sa pull request ne peut être rejouée dessus": "merge.base-moving",
        "the pull request could not be merged": "merge.refused",
        "la pull request n'a pas voulu fusionner": "merge.refused",
        "sa pull request est en conflit avec `main`, et le conflit demande une décision": "merge.conflict-decision",
        "it was validated, but there is no pull request to merge": "merge.no-pr",
        "commits made but the push was refused": "merge.push-refused",
        "worktree could not be created": "worktree.residue",
        "je n'ai pas pu créer le worktree pour travailler": "worktree.residue",
        "the session stopped to ask you something": "session.question",
        "la session s’est arrêtée pour poser une question": "session.question",
        "the agent stopped without deciding": "session.question",
        "the agent stopped without answering": "session.no-answer",
        "la session s'est arrêtée sans écrire de réponse": "session.no-answer",
        "the session declared itself done without a single commit": "session.no-commit",
        "the session failed": "session.killed",
        "la session n'est pas allée au bout": "session.killed",
        "Claude session could not be started": "session.not-started",
        "the Claude session would not start": "session.not-started",
        "something nobody ever wrote": "unknown",
        "": "unknown",
    }
    for sentence, code in heard.items():
        assert blocks.classify(sentence) == code, (sentence, blocks.classify(sentence), code)


@case
def a_stop_writes_its_cause_on_the_board_and_in_its_result_and_leaving_clears_it():
    runner = _board_runner(
        [_reviewed("p-stop", "In progress", None)], {"blocked": "Blocked", "failed": "Failed"}
    )
    ticket = ticket_module.Ticket(runner.client._pages[0])
    blocked = runner._fail(
        ticket,
        runner.voice.say("merge-refused"),
        code="merge.refused",
        blocked=True,
        question="?",
    )
    assert blocked["status"] == "blocked" and blocked["code"] == "merge.refused", blocked
    assert runner.client.written == [("p-stop", {"Status": "Blocked", "Blocage": "merge.refused"})]
    failed = runner._fail(ticket, runner.voice.say("crashed"), "boom", code="runner.crashed")
    assert failed["code"] == "runner.crashed", failed
    assert runner.client.written[-1] == (
        "p-stop",
        {"Status": "Failed", "Blocage": "runner.crashed"},
    )

    # The page now says why it stopped; the next status that is not a stop empties it.
    page = runner.client._pages[0]
    page.properties["Blocage"] = {"type": "select", "select": {"name": "runner.crashed"}}
    page.properties["Status"] = {"type": "status", "status": {"name": "Failed"}}
    runner.client.written.clear()
    runner._set(ticket, Status="In progress", Runner="ponos@laptop")
    assert runner.client.written == [
        ("p-stop", {"Blocage": "", "Status": "In progress", "Runner": "ponos@laptop"})
    ], runner.client.written
    # A card with nothing in the column is not written to for nothing.
    del page.properties["Blocage"]
    runner.client.written.clear()
    runner._set(ticket, Status="Done")
    assert runner.client.written == [("p-stop", {"Status": "Done"})], runner.client.written


@case
def a_session_that_did_not_finish_is_told_by_its_cause():
    runner = _board_runner([_reviewed("p-1", "In progress", None)], {"blocked": "Blocked"})
    ended = session.Outcome(
        ok=False, blocked=True, session_id="s", summary="Which one?", log=Path("/tmp/x")
    )
    code, sentence, detail = runner._why_stopped(ended, "session.question")
    assert (code, detail) == ("session.question", "Which one?")
    assert sentence == runner.voice.say("asked-something")
    ended.over_budget = True
    code, sentence, _ = runner._why_stopped(ended, "session.question")
    assert code == "session.over-budget" and "$" in sentence, (code, sentence)


@case
def the_board_offers_the_column_and_doctor_names_it_when_it_is_missing():
    from ponos import blocks

    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    column = provision.tickets_schema(settings)["Blocage"]
    options = [option["name"] for option in column["select"]["options"]]
    assert options == list(blocks.CODES), options
    assert "block" in store.COLUMNS and store.COLUMNS["block"][0] == ("select",)
    assert files.schemas(settings)["tickets"]["Blocage"] == "select"
    from test_health import _columns

    columns = _columns(settings, {"Status": "status"})
    assert "“Blocage”" in columns.params["missing"], columns.params


@case
def the_history_written_before_the_codes_is_reclassed_by_its_sentence():
    """Migration 17, on a file migrated as far as 16: every stop gets its code."""
    with tempfile.TemporaryDirectory() as directory:
        location = Path(directory) / "ponos.db"
        before = db.open_at(location, db.MIGRATIONS[:16])
        lines = [
            {"id": "a", "status": "blocked", "reason": "the session stopped to ask you something"},
            {
                "id": "b",
                "status": "failed",
                "reason": "je n'ai pas pu créer le worktree pour travailler",
            },
            {
                "id": "c",
                "status": "blocked",
                "reason": "ses conflits ont été résolus, mais ses vérifications échouent",
            },
            {"id": "d", "status": "failed", "reason": "a sentence from nowhere"},
            {"id": "e", "status": "done", "reason": ""},
        ]
        for line in lines:
            before.execute(
                "INSERT INTO history (ticket, status, entry) VALUES (?, ?, ?)",
                (line["id"], line["status"], json.dumps(line)),
            )
        before.execute(
            "INSERT INTO runs (ticket, started_at, status, reason)"
            " VALUES ('a', '2026-10-01', 'blocked', 'the session called itself done without committing anything')"
        )
        before.commit()
        before.close()
        after = db.open_at(location)
        try:
            rows = after.execute("SELECT ticket, code, entry FROM history ORDER BY id").fetchall()
            assert [(ticket, code) for ticket, code, _ in rows] == [
                ("a", "session.question"),
                ("b", "worktree.residue"),
                ("c", "merge.checks-failed"),
                ("d", "unknown"),
                ("e", ""),
            ], rows
            assert json.loads(rows[1][2])["code"] == "worktree.residue"
            assert "code" not in json.loads(rows[4][2])
            assert after.execute("SELECT code FROM runs").fetchone() == ("session.no-commit",)
        finally:
            after.close()


@case
def a_stop_is_kept_with_its_code_in_the_history_and_the_run(state_home):
    state.record({"id": "t-1", "status": "blocked", "reason": "x", "code": "merge.refused"})
    state.record({"id": "t-2", "status": "done"})
    state.record({"id": "t-1", "status": "failed", "reason": "y", "code": "runner.crashed"})
    assert state.history(1)[0]["code"] == "runner.crashed"
    # Keyed as a card is: the page id without its dashes.
    assert state.causes() == {"t1": "runner.crashed"}
    run = journal.Run.start(ticket="3f745168" * 4, title="A ticket")
    run.end("blocked", "z", "session.question")
    assert journal.runs("3f745168" * 4)[0]["code"] == "session.question"


@case
def a_stopped_card_carries_its_cause_from_the_board_or_else_from_the_history(state_home):
    from ponos import blocks

    state.record({"id": "c2", "status": "failed", "reason": "x", "code": "merge.refused"})
    state.record({"id": "c4", "status": "blocked", "reason": "x", "code": "merge.refused"})
    cards = [
        {"id": "c1", "column": "blocked", "block": blocks.describe("session.question")},
        {"id": "c2", "column": "failed", "block": None},
        {"id": "c3", "column": "blocked", "block": None},
        # Left the stopped columns: whatever the column still said, it is not drawn.
        {"id": "c4", "column": "ready", "block": blocks.describe("merge.refused")},
    ]
    web_tickets._causes(cards)
    assert [(card["block"] or {}).get("code") for card in cards] == [
        "session.question",
        "merge.refused",
        None,
        None,
    ], cards
    said = cards[0]["block"]
    assert said["family"] == "question" and said["action"] == "answer"
    assert said["label"]["fr"] and said["help"]["en"]


@case
def the_statistics_count_the_stops_by_cause_and_by_week():

    history = [
        {"at": "2026-10-05T09:00:00+00:00", "status": "blocked", "code": "session.question"},
        {"at": "2026-10-06T09:00:00+00:00", "status": "failed", "code": "merge.checks-failed"},
        {"at": "2026-10-07T09:00:00+00:00", "status": "blocked", "code": "session.question"},
        # Written before the codes and never migrated: read back from its sentence.
        {
            "at": "2026-10-13T09:00:00+00:00",
            "status": "blocked",
            "reason": "the pull request would not merge",
        },
        {"at": "2026-10-13T09:00:00+00:00", "status": "done"},
        {"at": "2026-09-01T09:00:00+00:00", "status": "blocked", "code": "session.question"},
    ]
    found = web_statistics.figures([], history, date(2026, 10, 1), date(2026, 10, 20), UTC)[
        "blocks"
    ]
    assert found["total"] == 4, found
    assert [week["week"] for week in found["weeks"]] == [
        "2026-09-28",
        "2026-10-05",
        "2026-10-12",
        "2026-10-19",
    ], found["weeks"]
    assert found["weeks"][0]["counts"] == {}
    assert found["weeks"][1]["counts"] == {"session.question": 2, "merge.checks-failed": 1}
    assert found["weeks"][2]["counts"] == {"merge.refused": 1}
    assert [(cause["code"], cause["count"]) for cause in found["causes"]] == [
        ("session.question", 2),
        ("merge.checks-failed", 1),
        ("merge.refused", 1),
    ]
    assert found["causes"][0]["family"] == "question" and found["causes"][0]["label"]["fr"]
