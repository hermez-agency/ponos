"""`blocks.py`: why a ticket stopped."""

from __future__ import annotations

import ast
import re
from datetime import UTC, date
from pathlib import Path
from typing import Any

from support import FRONTEND, ROOT, _board_runner, _BoardClient, _reviewed, case

from ponos import config as C
from ponos import files, journal, provision, session, state, store, voice
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
def every_fail_carries_a_code_the_catalogue_knows() -> None:
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
    asked: list[str] = []
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
    for cause in asked:
        assert cause in blocks.CAUSES, f"{cause!r} is not in blocks.py"
    # And at run time: a code the catalogue does not hold is refused, not written.
    runner = _board_runner([_reviewed("p-1", "progress", None)], {"blocked": "blocked"})
    client = runner.client
    assert isinstance(client, _BoardClient)
    try:
        runner._fail(ticket_module.Ticket(client._pages[0]), "x", code="merge.nope")
    except ValueError as error:
        assert "merge.nope" in str(error)
    else:
        raise AssertionError("an unknown code was accepted")
    assert client.written == []


@case
def every_cause_is_described_whole_in_both_languages() -> None:
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
        "ci.billing",
    ):
        assert given in blocks.CAUSES, f"the ticket's {given} is missing"
    for code, cause in blocks.CAUSES.items():
        assert code == blocks.UNKNOWN or re.fullmatch(r"[a-z]+\.[a-z-]+", code), code
        assert cause.family in blocks.FAMILIES, code
        assert cause.who in blocks.WHO, code
        assert cause.action in blocks.ACTIONS, code
        assert re.fullmatch(r"retry:\d|wait-base|wait-billing|ask", cause.policy), code
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
def every_sentence_said_for_a_cause_is_read_back_to_it() -> None:
    """What the migration counts on: today's sentences, and those the history holds."""
    from ponos import blocks

    values = {
        "account": "acme",
        "base": "main",
        "branch": "ticket/x",
        "limit": "$5",
        "origin": "validated",
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
def a_stop_writes_its_cause_on_the_board_and_in_its_result_and_leaving_clears_it() -> None:
    runner = _board_runner(
        [_reviewed("p-stop", "progress", None)], {"blocked": "blocked", "failed": "blocked"}
    )
    client = runner.client
    assert isinstance(client, _BoardClient)
    ticket = ticket_module.Ticket(client._pages[0])
    blocked = runner._fail(
        ticket,
        runner.voice.say("merge-refused"),
        code="merge.refused",
        blocked=True,
        question="?",
    )
    assert blocked["status"] == "blocked" and blocked["code"] == "merge.refused", blocked
    assert client.written == [("p-stop", {"statut": "blocked", "Blocage": "merge.refused"})]
    failed = runner._fail(ticket, runner.voice.say("crashed"), "boom", code="runner.crashed")
    assert failed["code"] == "runner.crashed", failed
    assert client.written[-1] == (
        "p-stop",
        {"statut": "blocked", "Blocage": "runner.crashed"},
    )

    # The page now says why it stopped; the next status that is not a stop empties it.
    page = client._pages[0]
    page.properties["Blocage"] = {"type": "select", "select": {"name": "runner.crashed"}}
    page.properties["statut"] = {"type": "status", "status": {"name": "blocked"}}
    client.written.clear()
    runner._set(ticket, statut="progress", Agent="ponos@laptop")
    assert client.written == [
        ("p-stop", {"Blocage": "", "statut": "progress", "Agent": "ponos@laptop"})
    ], client.written
    # A card with nothing in the column is not written to for nothing.
    del page.properties["Blocage"]
    client.written.clear()
    runner._set(ticket, statut="done")
    assert client.written == [("p-stop", {"statut": "done"})], client.written


@case
def a_session_that_did_not_finish_is_told_by_its_cause() -> None:
    runner = _board_runner([_reviewed("p-1", "progress", None)], {"blocked": "blocked"})
    client = runner.client
    assert isinstance(client, _BoardClient)
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
def the_board_offers_the_column_and_doctor_names_it_when_it_is_missing() -> None:
    from ponos import blocks

    settings = C.Notion()
    column = provision.tickets_schema(settings)["Blocage"]
    options = [option["name"] for option in column["select"]["options"]]
    assert options == list(blocks.CODES), options
    assert "block" in store.COLUMNS and store.COLUMNS["block"][0] == ("select",)
    assert files.schemas(settings)["tickets"]["Blocage"] == "select"
    from test_health import _columns

    columns = _columns(settings, {"statut": "status"})
    assert "“Blocage”" in columns.params["missing"], columns.params


@case
def a_stop_is_kept_with_its_code_in_the_history_and_the_run(state_home: Path) -> None:
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
def a_stopped_card_carries_its_cause_from_the_board_or_else_from_the_history(
    state_home: Path,
) -> None:
    from ponos import blocks

    state.record({"id": "c2", "status": "blocked", "reason": "x", "code": "merge.refused"})
    state.record({"id": "c4", "status": "blocked", "reason": "x", "code": "merge.refused"})
    cards: list[dict[str, Any]] = [
        {"id": "c1", "column": "blocked", "block": blocks.describe("session.question")},
        {"id": "c2", "column": "blocked", "block": None},
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
def the_statistics_count_the_stops_by_cause_and_by_week() -> None:

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
