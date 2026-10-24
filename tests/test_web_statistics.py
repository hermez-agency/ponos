"""`web/statistics.py`: the statistics tab."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from support import (
    FRONTEND,
    ROOT,
    _bare_api,
    _bare_runner,
    _board,
    _ColumnsClient,
    _environment,
    _ideas_api,
    _markdown_api,
    _recurring,
    _saved,
    _schedule_page,
    _TalkClient,
    case,
)

from ponos import (
    channels,
    conversation,
    legacy,
    log,
    notion,
    redaction,
    schedules,
    state,
    store,
    vault,
    voice,
)
from ponos import config as C
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import live as web_live
from ponos.web import settings as web_settings
from ponos.web import statistics as web_statistics
from ponos.web import tickets as web_tickets

# -- statistics --------------------------------------------------------------


def _card(key: str, column: str, created: str, edited: str = "", project: str = "") -> dict:
    return {"id": key, "column": column, "created": created, "edited": edited, "project": project}


@case
def a_closing_is_dated_by_the_runner_before_the_last_edit():
    """The history says the minute the runner closed a ticket; an edit since does not move it.

    And a session that opened a pull request reports "done" without closing
    anything: that line is no closing.
    """

    history = [
        {"at": "2026-09-02T10:00:00+00:00", "id": "a", "status": "done", "pull_request": "u"},
        {"at": "2026-09-05T10:00:00+00:00", "id": "a", "status": "done", "merged": "u"},
        {"at": "2026-09-06T10:00:00+00:00", "id": "b", "status": "done", "kind": "document"},
        {"at": "2026-09-07T10:00:00+00:00", "id": "c", "status": "done", "pull_request": "u"},
    ]
    tickets = [
        _card("a", "done", "2026-09-01T09:00:00.000Z", edited="2026-09-20T09:00:00.000Z"),
        _card("b", "done", "2026-09-01T09:00:00.000Z", edited="2026-09-06T10:01:00.000Z"),
        # Merged by hand, closed by `close_merged`: no history line, its edit says when.
        _card("c", "done", "2026-09-01T09:00:00.000Z", edited="2026-09-08T09:00:00.000Z"),
    ]
    figures = web_statistics.figures(tickets, history, date(2026, 9, 1), date(2026, 9, 10), UTC)
    closed = {item["day"]: item["closed"] for item in figures["days"] if item["closed"]}
    assert closed == {"2026-09-05": 1, "2026-09-06": 1, "2026-09-08": 1}, closed
    assert figures["dated"] == {"history": 2, "edited": 1}


@case
def the_open_curve_starts_from_the_board_as_it_stood_and_ends_on_it():
    """What is open on the last day is what the board shows as not done.

    A ticket from before the period counts from the first point, not from its
    creation; one created and closed the same day is never open overnight;
    blocked and failed are still open.
    """

    tickets = [
        _card("old", "blocked", "2026-07-01T09:00:00.000Z", project="Opoil"),
        _card("gone", "done", "2026-07-01T09:00:00.000Z", edited="2026-09-03T09:00:00.000Z"),
        _card("quick", "done", "2026-09-02T09:00:00.000Z", edited="2026-09-02T18:00:00.000Z"),
        _card("new", "ready", "2026-09-04T09:00:00.000Z", project="Opoil"),
        _card("failed", "failed", "2026-09-04T12:00:00.000Z", project="ponos"),
    ]
    history = [
        {"at": "2026-09-02T12:00:00+00:00", "id": "quick", "status": "done", "cost_usd": 1.5},
        {"at": "2026-09-04T12:00:00+00:00", "id": "new", "status": "blocked", "cost_usd": 0.25},
        {"at": "2026-08-01T12:00:00+00:00", "id": "old", "status": "blocked", "cost_usd": 9},
    ]
    figures = web_statistics.figures(tickets, history, date(2026, 9, 1), date(2026, 9, 5), UTC)
    opened = [item["open"] for item in figures["days"]]
    assert opened == [2, 2, 1, 3, 3], opened
    assert figures["totals"] == {"open": 3, "closed": 2, "created": 3, "cost": 1.75}, figures[
        "totals"
    ]
    assert [item["cost"] for item in figures["days"]] == [0, 1.5, 1.5, 1.75, 1.75]
    assert {item["name"]: item["count"] for item in figures["projects"]} == {
        "": 1,
        "Opoil": 1,
        "ponos": 1,
    }
    assert {item["key"]: item["count"] for item in figures["statuses"]} == {
        "done": 1,
        "ready": 1,
        "failed": 1,
    }


@case
def a_cancelled_ticket_is_neither_closed_nor_open_and_keeps_its_cost():
    """Given up on is not done, and not somebody's to deal with any more.

    It leaves the open curve on its last edit without being counted closed,
    and what its sessions spent stays in the spending: the money is gone.
    """

    tickets = [
        _card("kept", "ready", "2026-09-01T09:00:00.000Z"),
        _card(
            "dropped", "cancelled", "2026-09-01T09:00:00.000Z", edited="2026-09-03T09:00:00.000Z"
        ),
    ]
    history = [
        {"at": "2026-09-02T12:00:00+00:00", "id": "dropped", "status": "blocked", "cost_usd": 2.0},
    ]
    figures = web_statistics.figures(tickets, history, date(2026, 9, 1), date(2026, 9, 4), UTC)
    assert [item["open"] for item in figures["days"]] == [2, 2, 1, 1]
    assert figures["totals"] == {"open": 1, "closed": 0, "created": 2, "cost": 2.0}, figures[
        "totals"
    ]
    assert figures["average"] is None, "no ticket closed, none averaged"
    assert {item["key"]: item["count"] for item in figures["statuses"]} == {
        "ready": 1,
        "cancelled": 1,
    }


@case
def the_open_tickets_of_the_last_day_are_the_boards_not_closed_ones():
    """Open on the evening of today is every card but done, validated and cancelled.

    Validated is approved and left to the runner to merge: nothing is left for
    anybody, so it leaves the open ones — dated by the edit that moved it,
    which is all the board says until the runner's history dates the merge.
    """

    columns = ("draft", "ready", "running", "blocked", "review", "validated", "done", "cancelled")
    tickets = [
        _card(column, column, "2026-09-01T09:00:00.000Z", edited="2026-09-03T09:00:00.000Z")
        for column in columns
    ]
    figures = web_statistics.figures(tickets, [], date(2026, 9, 1), date(2026, 9, 4), UTC)
    board = sum(
        1 for ticket in tickets if ticket["column"] not in ("done", "validated", "cancelled")
    )
    assert [item["open"] for item in figures["days"]] == [8, 8, board, board], figures["days"]
    assert figures["totals"]["open"] == board == 5
    assert [item["closed"] for item in figures["days"]] == [0, 0, 2, 0]


@case
def the_tickets_created_are_handed_by_type_sub_type_and_project():
    """Cells the console filters on the spot, day by day up to a month, and the period before.

    A code ticket with no sub-type, or one the table does not know, is a cell
    with none — unclassified, still counted — and the period before is the
    one of the same length that ends the day before.
    """

    def card(key: str, created: str, kind: str, subtype: str = "", project: str = "") -> dict:
        return {**_card(key, "ready", created, project=project), "type": kind, "subtype": subtype}

    tickets = [
        card("a", "2026-09-08T09:00:00.000Z", "Code", "bug", "Opoil"),
        card("b", "2026-09-08T10:00:00.000Z", "Code", "bug", "Opoil"),
        card("c", "2026-09-09T09:00:00.000Z", "Code", "feature", "ponos"),
        card("d", "2026-09-09T09:00:00.000Z", "Code", "", "ponos"),
        card("e", "2026-09-10T09:00:00.000Z", "Rédaction", "", "ponos"),
        card("f", "2026-09-10T09:00:00.000Z", "Code", "made-up", "ponos"),
        # The week before: compared with, not drawn.
        card("g", "2026-09-02T09:00:00.000Z", "Code", "feature", "Opoil"),
        # Before that: neither.
        card("h", "2026-08-20T09:00:00.000Z", "Code", "bug", "Opoil"),
    ]
    kinds = {"code": "code", "rédaction": "writing"}
    figures = web_statistics.figures(
        tickets,
        [],
        date(2026, 9, 7),
        date(2026, 9, 13),
        UTC,
        kind_of=lambda option: kinds.get(option.casefold(), ""),
    )
    made = figures["made"]
    assert made["unit"] == "day"
    assert made["buckets"][0] == "2026-09-07" and len(made["buckets"]) == 7
    assert made["cells"] == [
        {"bucket": "2026-09-08", "kind": "code", "subtype": "bug", "project": "Opoil", "count": 2},
        {"bucket": "2026-09-09", "kind": "code", "subtype": "", "project": "ponos", "count": 1},
        {
            "bucket": "2026-09-09",
            "kind": "code",
            "subtype": "feature",
            "project": "ponos",
            "count": 1,
        },
        {"bucket": "2026-09-10", "kind": "code", "subtype": "", "project": "ponos", "count": 1},
        {"bucket": "2026-09-10", "kind": "writing", "subtype": "", "project": "ponos", "count": 1},
    ], made["cells"]
    assert made["before"] == [
        {"kind": "code", "subtype": "feature", "project": "Opoil", "count": 1}
    ]

    # Past a month, a bucket is a week, named by its Monday.
    longer = web_statistics.figures(tickets, [], date(2026, 8, 1), date(2026, 9, 13), UTC)
    assert longer["made"]["unit"] == "week"
    assert longer["made"]["buckets"][:2] == ["2026-07-27", "2026-08-03"]
    assert {cell["bucket"] for cell in longer["made"]["cells"]} == {
        "2026-08-17",
        "2026-08-31",
        "2026-09-07",
    }
    # No type said: none of the four.
    assert {cell["kind"] for cell in longer["made"]["cells"]} == {""}


@case
def the_projects_figures_add_up_to_the_boards():
    """Created and spent, project by project, are the board's — less the tickets with no project.

    A project's figures are the board's over its tickets alone, and its
    sessions are the history lines of those tickets. A line about a ticket the
    board no longer has belongs to nobody, so it is in the global spend only.
    """

    tickets = [
        _card(
            "a",
            "done",
            "2026-09-02T09:00:00.000Z",
            edited="2026-09-04T09:00:00.000Z",
            project="Opoil",
        ),
        _card("b", "ready", "2026-09-03T09:00:00.000Z", project="Opoil"),
        _card("c", "review", "2026-09-03T10:00:00.000Z", project="ponos"),
        _card("d", "ready", "2026-09-04T10:00:00.000Z"),
    ]
    history = [
        {
            "at": "2026-09-02T12:00:00+00:00",
            "id": "a",
            "status": "done",
            "kind": "document",
            "cost_usd": 1.0,
        },
        {"at": "2026-09-03T12:00:00+00:00", "id": "b", "status": "blocked", "cost_usd": 0.5},
        {"at": "2026-09-03T13:00:00+00:00", "id": "c", "status": "done", "cost_usd": 2.0},
        {"at": "2026-09-04T13:00:00+00:00", "id": "d", "status": "blocked", "cost_usd": 4.0},
        {"at": "2026-09-04T14:00:00+00:00", "id": "gone", "status": "done", "cost_usd": 8.0},
    ]
    first, last = date(2026, 9, 1), date(2026, 9, 10)
    whole = web_statistics.figures(tickets, history, first, last, UTC)
    by_project = {
        name: web_statistics.figures(tickets, history, first, last, UTC, project=name)
        for name in ("Opoil", "ponos", "")
    }
    assert whole["totals"]["created"] == sum(f["totals"]["created"] for f in by_project.values())
    assert whole["totals"]["closed"] == sum(f["totals"]["closed"] for f in by_project.values())
    # 8.0 is a session of a ticket that left the board: in the whole only.
    assert whole["totals"]["cost"] == 15.5
    assert sum(f["totals"]["cost"] for f in by_project.values()) == 7.5
    assert by_project["Opoil"]["totals"] == {"open": 1, "closed": 1, "created": 2, "cost": 1.5}
    assert by_project[""]["totals"]["cost"] == 4.0
    # One closed ticket, 1.0 spent on it.
    assert by_project["Opoil"]["average"] == 1.0
    assert by_project["ponos"]["average"] is None
    assert [item["name"] for item in by_project["Opoil"]["projects"]] == ["Opoil"]


@case
def a_day_is_this_machines_day():
    """23:30 in Paris is that evening, not the next UTC morning's."""

    paris = timezone(timedelta(hours=2))
    assert web_statistics.day_of("2026-09-02T22:30:00.000Z", paris) == date(2026, 9, 3)
    assert web_statistics.day_of("2026-09-02T22:30:00.000Z", UTC) == date(2026, 9, 2)
    assert web_statistics.day_of("2026-09-02", paris) == date(2026, 9, 2)
    assert web_statistics.day_of("", paris) is None
    assert web_statistics.day_of("hier", paris) is None


@case
def a_period_is_thirty_days_unless_it_says_otherwise():

    today = date(2026, 9, 29)
    assert web_statistics.period("", "", today) == (date(2026, 8, 31), today)
    assert web_statistics.period("2026-09-01", "2026-09-07", today) == (
        date(2026, 9, 1),
        date(2026, 9, 7),
    )
    for start, end in (("2026-09-07", "2026-09-01"), ("2020-01-01", "2026-01-01"), ("hier", "")):
        try:
            web_statistics.period(start, end, today)
        except ValueError:
            continue
        raise AssertionError(f"{start}..{end} should have been refused")


@case
def changing_the_period_does_not_read_the_board_again(state_home):
    """Two periods asked one after the other: one board read, the watcher's."""
    from ponos.web import live as web_live

    api = _bare_api(_TalkClient([]))
    reads = []

    def board() -> dict:
        reads.append(1)
        return {"tickets": [_card("a", "done", "2026-09-01T09:00:00+00:00")]}

    api.watch = web_live.Watch(api.hub, board)
    state.record(
        {"at": "2026-09-03T10:00:00+00:00", "id": "a", "status": "done", "kind": "delivery"}
    )
    month = api.statistics("2026-09-01", "2026-09-30")
    week = api.statistics("2026-09-01", "2026-09-07")
    assert len(reads) == 1, reads
    assert month["totals"]["closed"] == 1 and week["totals"]["created"] == 1


@case
def a_message_typed_at_a_ticket_is_a_comment_in_your_own_voice():
    """The console writes with the runner's token; the words are still yours.

    Without the relayed opening, the next run would read its own voice under its
    own question — and a conversation with oneself is the one failure mode here
    that never ends on its own.
    """
    report = notion.Comment(
        f"{legacy.OLD}@laptop — blocked.\nWhich header?",
        discussion_id="d-report",
        created_by="runner-id",
    )
    client = _TalkClient([notion.Comment("une note à moi", discussion_id="d-mine"), report])
    api = _bare_api(client)
    api.tell("p-ticket", "  Celui du dashboard.  ")

    page, text, discussion = client.written[0]
    assert page == "p-ticket"
    assert conversation.is_relayed(text), text
    assert conversation.said(text) == "Celui du dashboard."
    assert discussion == "d-report", (
        "an answer goes under the question, not at the foot of the page"
    )

    try:
        api.tell("p-ticket", "   ")
    except ValueError:
        pass
    else:
        raise AssertionError("an empty message should not become a comment")


@case
def a_ticket_the_runner_has_never_spoken_on_gets_a_thread_of_its_own():
    """No question to answer, and none invented: the message opens a discussion."""
    client = _TalkClient(
        [notion.Comment("une remarque", discussion_id="d-mine", created_by="salva")]
    )
    _bare_api(client).tell("p-ticket", "on reprend ça demain")
    assert client.written[0][2] == ""
    # Same when Notion will not say who we are: without an identity there is no
    # telling our own thread from yours, and guessing is how it goes wrong.
    other = _TalkClient(
        [notion.Comment("un rapport", discussion_id="d-report", created_by="runner-id")]
    )
    _bare_api(other, me="").tell("p-ticket", "et celui-ci ?")
    assert other.written[0][2] == ""


@case
def the_discussion_of_a_ticket_reads_as_a_conversation():
    """The ticket's terminal is the page's comments, said by who said them."""
    client = _TalkClient(
        [
            notion.Comment(
                f"{legacy.OLD}@laptop — blocked.\nWhich header?",
                created_time="2026-08-30T10:00:00.000Z",
                discussion_id="d-report",
                created_by="runner-id",
            ),
            notion.Comment(
                f"{conversation.RELAYED[0]}Telegram by Salva.\nCelui du dashboard.",
                discussion_id="d-report",
                created_by="runner-id",
            ),
            notion.Comment("Merci.", discussion_id="d-report", created_by="salva"),
        ]
    )
    payload = _bare_api(client).talk("p-ticket")
    assert [message["role"] for message in payload["messages"]] == ["runner", "you", "you"]
    said = payload["messages"][1]["text"]
    assert said == "Celui du dashboard.", f"the device it came through is not the message: {said}"
    assert payload["mention"] == conversation.MENTION, (
        "the hint has to name what the runner answers to"
    )

    # An integration that will not say who we are still leaves the discussion
    # readable: a report opens with the name the runner signs it with.
    blind = _bare_api(client, me="").talk("p-ticket")
    assert [message["role"] for message in blind["messages"]] == ["runner", "you", "you"]


@case
def a_question_left_unanswered_is_a_ticket_waiting_on_you():
    """The page opens on the discussion when the last word is a run's question."""
    question = notion.Comment(
        f"{voice.MARKS['blocked']} Question\nWhich header?",
        discussion_id="d-report",
        created_by="runner-id",
    )
    assert _bare_api(_TalkClient([question])).talk("p-ticket")["waiting"] is True
    answered = _TalkClient(
        [
            question,
            notion.Comment("Celui du dashboard.", discussion_id="d-report", created_by="salva"),
        ]
    )
    assert _bare_api(answered).talk("p-ticket")["waiting"] is False, (
        "an answered question waits on nobody"
    )
    report = notion.Comment(f"{voice.MARKS['review']} To review — PR #38", created_by="runner-id")
    assert _bare_api(_TalkClient([report])).talk("p-ticket")["waiting"] is False, (
        "a report is not a question"
    )
    assert _bare_api(_TalkClient([])).talk("p-ticket")["waiting"] is False


@case
def a_message_written_to_a_ticket_reaches_every_open_console():
    """A click posts and says nothing: what appears is what came back on the stream."""
    api = _bare_api(_TalkClient([]))
    channel = api.hub.subscribe(after=0)
    api.tell("p-ticket", "on garde le bandeau")
    event = channel.get_nowait()
    assert event.kind == "talk"
    assert event.payload["ticket"] == "p-ticket"
    assert event.payload["role"] == "you"
    assert event.payload["text"] == "on garde le bandeau"


@case
def a_password_is_masked_and_what_only_talks_of_one_is_left_alone():
    """The sentences `frontend/src/lib/secrets.test.ts` reads, read here too.

    Masked, the label stays and the value goes: the next session still knows
    a password was given, and has to ask for it some other way.
    """
    shown = {
        "mot de passe : hunter2": (["password"], "mot de passe : ••••••"),
        "password=S3cr3t!": (["password"], "password=••••••"),
        "Le mot de passe npm de l'agence est Hz!2026kpl": (
            ["password"],
            "Le mot de passe npm de l'agence est ••••••",
        ),
        'mdp: "azerty123" merci': (["password"], 'mdp: "••••••" merci'),
        "la clé API : abcd1234": (["password"], "la clé API : ••••••"),
        "voici ghp_abcdefghijklmnopqrstuvwxyz0123456789": (["token"], "voici ••••••"),
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz": (["token"], "••••••"),
        "npm_abcdefghijklmnopqrstuvwxyz0123456789": (["token"], "••••••"),
        "git clone https://salva:p4ss@github.com/x/y.git": (
            ["address"],
            "git clone https://salva:••••••@github.com/x/y.git",
        ),
        "token : ghp_abcdefghijklmnopqrstuvwxyz0123456789": (
            ["token", "password"],
            "token : ••••••",
        ),
    }
    for text, (flagged, masked) in shown.items():
        assert redaction.found(text) == flagged, (text, redaction.found(text))
        assert redaction.masked(text) == masked, (text, redaction.masked(text))
    for text in (
        "le token est expiré, refais-le",
        "le secret est dans le coffre",
        "Oui, vas-y avec le mot de passe que tu as.",
        "commit 8df7c20a1b2c3d4e5f60718293a4b5c6d7e8f901, session 3fe451680af4819c8f1bdb25215b6ff7",
        "https://github.com/SalvadorCardona/ticket-runner/pull/284",
    ):
        assert redaction.found(text) == [], text
        assert redaction.masked(text) == text, text


@case
def the_page_and_the_runner_know_the_same_tokens():
    """`secrets.ts` warns about what `redaction` masks: the same list, twice."""
    source = (Path(__file__).resolve().parents[1] / "frontend/src/lib/secrets.ts").read_text()
    listed = re.search(r"export const TOKENS[^\[]*\[(.*?)\n\]", source, re.S)
    assert listed, "secrets.ts lost its TOKENS"
    written = re.findall(r"String\.raw`(.*?)`,", listed.group(1))
    assert written == list(redaction.TOKENS), written


@case
def a_password_typed_at_a_ticket_never_reaches_the_page():
    """Masked before the comment, the stream and the answer all see it."""
    client = _TalkClient([])
    api = _bare_api(client)
    channel = api.hub.subscribe(after=0)
    message = api.tell("p-ticket", "Le mot de passe npm est Hz!2026kpl, publie la 1.2.0")
    written = client.written[0][1]
    assert "Hz!2026kpl" not in written, written
    assert conversation.said(written) == "Le mot de passe npm est ••••••, publie la 1.2.0"
    assert "Hz!2026kpl" not in channel.get_nowait().payload["text"]
    assert "Hz!2026kpl" not in message["text"]

    # A reply from a phone goes the same way.
    relayed = channels.answer(
        channels.Reply(channel="telegram", text="token: npm_abcdefghijklmnopqrstuvwxyz0123456789")
    )
    assert "npm_" not in relayed and relayed.endswith("token: ••••••"), relayed


@case
def a_password_given_with_a_decision_never_reaches_the_page(state_home):
    """The instruction typed under a blocked ticket is an answer like any other."""
    settings = C.Notion()
    with _board() as board:
        project = board.create_row("projects", "Usine", {"Repository": "user/usine"})
        api = _ideas_api(board)
        said = api.runner.voice
        page = board.create_row("tickets", "Publish", {"Status": settings.state("blocked")})
        board.update("tickets", page, {"Project": [project]})
        board.comment(page, said.report(said.verdict("blocked", "nothing"), "No npm login."))
        api.decide(page, "other", text="Le mot de passe : Hz!2026kpl")
        comment = board.comments(page)[-1].text
        assert "Hz!2026kpl" not in comment and comment.endswith("Le mot de passe : ••••••"), comment


@case
def the_console_draws_what_comes_back_on_its_own():
    """A schedule the runner reads is one the console shows, problem included.

    And the switch travels with the rows, because a browser is the one place
    `runner.schedule = false` cannot be seen otherwise: a page of ticked
    schedules that never fire would read as a calendar that works.
    """
    import time as clock

    ahead = (datetime.now().astimezone() + timedelta(days=5)).replace(second=0, microsecond=0)
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring(
        [
            _schedule_page(
                "s-1",
                next=ahead.isoformat(),
                last_ticket="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            ),
            _schedule_page("s-2", name="Le rapport", cadence="Fortnightly", active=False),
        ],
        schedule=False,
    )
    api._config = api._runner.config
    api._projects = {"p-northwind": {"id": "pnorthwind", "name": "Northwind", "kind": "code"}}
    api._projects_at = clock.time()

    payload = api.schedules()
    assert payload["database"], "the workspace has one; the pane must not offer to build it"
    assert payload["page"] == "Schedules"
    assert payload["enabled"] is False, "the one switch that turns the whole calendar off"

    first, second = payload["schedules"]
    assert first["name"] == "Revue des dépendances"
    assert (first["cadence"], first["at"], first["active"]) == ("Daily", "09:00", True)
    assert schedules.scheduled_for(first["next"]) == ahead
    assert first["project"] == "Northwind", "the relation is resolved, as it is on a card"
    assert first["project_id"] == "pnorthwind", "and the page, for a name not known yet"
    assert first["ticket"] == "aaaaaaaabbbbccccddddeeeeeeeeeeee", "addressed as the board does"
    assert not first["problem"]

    # A cadence nobody knows is stepped over by the pass rather than raised, and
    # says so here rather than showing a date it does not have.
    assert second["problem"], "a schedule the runner cannot read has to say why"
    assert second["next"] == "" and second["active"] is False

    # A projects cache gone cold is not a query the rows wait for: the name is
    # left to the console, which has the page to find it by.
    api._projects = {}
    api.projects = lambda: (_ for _ in ()).throw(AssertionError("the projects were read"))
    first = api.schedules()["schedules"][0]
    assert first["project"] == "" and first["project_id"] == "pnorthwind"


@case
def a_second_launch_of_the_same_schedule_is_refused_while_the_first_runs():
    """The double click: one ticket, and the second request told why."""
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring([_schedule_page("s-1")])
    api._config = api._runner.config
    api._launching, api._launch_guard = set(), __import__("threading").Lock()
    seen: list[str] = []

    def slow(page_id):
        # The double click lands while the first launch is still writing.
        try:
            api.launch_schedule("s-1")
        except RuntimeError as error:
            seen.append(str(error))
        return {"id": "t1", "ticket": "Revue"}

    api._runner.launch = slow
    assert api.launch_schedule("s-1") == {"ticket": "t1", "title": "Revue"}
    assert seen and "already being launched" in seen[0]
    # And the guard is let go of, so that the next launch is not refused for ever.
    assert api.launch_schedule("s-1")["ticket"] == "t1"


@case
def a_schedule_deleted_from_the_console_goes_to_the_trash_and_is_no_longer_read():
    """Deleting is the board's trash, not a tick: the row leaves every query.

    Its tickets are not touched — only the schedule goes — and the page is not
    destroyed, since the trash keeps it restorable.
    """
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring([_schedule_page("s-1", name="Test email"), _schedule_page("s-2")])
    api._config = api._runner.config
    api._projects = {}
    api.projects = lambda: {"projects": []}
    client = api._runner.client

    answer = api.delete_schedule("s-1")
    assert answer == {"id": "s1", "name": "Test email"}
    assert client.trashed == ["s-1"]
    assert client.written == [], "nothing else on the board is written"
    assert [row["id"] for row in api.schedules()["schedules"]] == ["s2"]
    # What the pass reads is what the console reads: it no longer fires.
    assert [row.name for row in api._runner.schedules()] == ["Revue des dépendances"]

    try:
        api.delete_schedule("s-1")
    except LookupError:
        pass
    else:
        raise AssertionError("a schedule already gone has nothing to delete")


@case
def the_console_never_shows_a_next_occurrence_already_behind_us():
    """`Next` is the pass's bookmark; the list says when a ticket is born.

    Turned off three weeks ago, a schedule keeps the date it had then — and
    nothing will be born from it. Turned on and due, it fires on the very next
    pass, which is now and not a moment in the past.
    """
    stale = "2026-09-09T21:00:00+02:00"
    api = _bare_api(_TalkClient([]))
    api._runner = _recurring(
        [
            _schedule_page("s-1", name="Test email", cadence="Hourly", next=stale, active=False),
            _schedule_page("s-2", cadence="Hourly", next=stale),
        ]
    )
    api._config = api._runner.config
    api._projects = {}
    api.projects = lambda: {"projects": []}

    before = datetime.now().astimezone().replace(second=0, microsecond=0)
    paused, due = api.schedules()["schedules"]
    assert paused["active"] is False and paused["next"] == "", "a paused schedule has no next"
    assert paused["cadence"] == "Hourly", "the word the board holds, translated by the page"
    assert schedules.scheduled_for(due["next"]) >= before, (
        f"an occurrence in the past: {due['next']}"
    )


class _PageClient(_TalkClient):
    """A ticket page: its row, and the blocks written under it."""

    def __init__(self, content: str, status: str = "Ready") -> None:
        super().__init__([])
        self._content = content
        self._status = status

    def page(self, page_id: str) -> notion.Page:
        return notion.Page(
            id="1a2b3c4d-0000-0000-0000-000000000000",
            url="https://notion.so/p",
            title="Retirer le bandeau",
            properties={"Status": {"type": "status", "status": {"name": self._status}}},
            raw={"created_time": "2026-09-01T09:00:00.000Z"},
        )

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._content


@case
def a_ticket_read_on_its_own_is_the_card_and_the_page_under_it():
    """The board hands out rows; the ticket's page hands out what was written on it.

    Same shape as the card — the console draws one component for both — plus
    the page's blocks flattened the way the runner reads them before a run: the
    brief you wrote, and the report a run appended under it.
    """
    api = _bare_api(_PageClient("# Brief\nRetirer le bandeau du dashboard.\n\n- [x] fait"))
    api._runner._workspace = type("W", (), {"goals": "", "projects": ""})()
    payload = api.ticket("1a2b3c4d000000000000000000000000")
    assert payload["id"] == "1a2b3c4d000000000000000000000000", "the id is the one the board uses"
    assert payload["short"] == "00000000", "the short id is the tail, where the entropy is"
    assert payload["title"] == "Retirer le bandeau"
    assert payload["column"] == "ready", "the column is named the way the board names it"
    assert payload["content"].startswith("# Brief"), "the page's blocks come with the row"
    assert "- [x] fait" in payload["content"]

    elsewhere = _bare_api(_PageClient("", status="Parked"))
    elsewhere._runner._workspace = type("W", (), {"goals": "", "projects": ""})()
    assert elsewhere.ticket("1a2b3c4d000000000000000000000000")["column"] == "draft"


class _EditedPageClient(_PageClient):
    """A ticket page that says when it was last edited, and counts its block reads."""

    def __init__(self, content: str, edited: str) -> None:
        super().__init__(content)
        self.edited = edited
        self.reads = 0

    def page(self, page_id: str) -> notion.Page:
        page = super().page(page_id)
        page.raw["last_edited_time"] = self.edited
        return page

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        self.reads += 1
        return self._content


@case
def a_ticket_page_is_read_again_only_when_notion_says_it_changed():
    """Opening a ticket read every block of its page, one to three seconds a time.

    The row is still read each time — it is what says the page moved — and the
    blocks only when its `last_edited_time` did. A read made in the very minute
    of the edit is not kept: Notion counts in minutes, and a second edit in that
    minute would not move the time. A Markdown board is never kept.
    """
    client = _EditedPageClient("first brief", "2026-09-01T09:00:00.000Z")
    api = _bare_api(client)
    api._runner._workspace = type("W", (), {"goals": "", "projects": ""})()
    ticket = "1a2b3c4d000000000000000000000000"
    assert api.ticket(ticket)["content"] == "first brief"
    assert api.ticket(ticket)["content"] == "first brief"
    assert client.reads == 1, "an unchanged page is not read twice"

    client._content, client.edited = "second brief", "2026-09-01T09:30:00.000Z"
    assert api.ticket(ticket)["content"] == "second brief", "an edit is read at the next opening"
    assert client.reads == 2

    # Edited just now: the minute is not over, so nothing is kept.
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    client.edited = now.isoformat().replace("+00:00", ".000Z")
    api.ticket(ticket)
    client._content = "third brief"
    assert api.ticket(ticket)["content"] == "third brief", (
        "an edit in the same minute is still read"
    )

    files = _EditedPageClient("on disk", "2026-09-01T09:00:00.000Z")
    board = _bare_api(files)
    board._runner._workspace = type("W", (), {"goals": "", "projects": ""})()
    board._config.storage = C.Storage(mode="markdown")
    board.ticket(ticket)
    board.ticket(ticket)
    assert files.reads == 2, "a file changed by hand says nothing in its edited time"


@case
def a_relation_is_written_as_notion_spells_it():
    """A ticket created from the console names its project, or it is not one."""
    page = "3ca451680af480ae9443de0b65d9abf8"
    assert notion._encode("relation", page) == {"relation": [{"id": page}]}
    assert notion._encode("relation", [page]) == {"relation": [{"id": page}]}
    assert notion._encode("relation", []) == {"relation": []}


@case
def a_ticket_under_no_known_status_is_a_draft_and_no_column_is_added_for_it():
    """The board used to draw a "No status" column of its own, after Done.

    A ticket written without a status is a draft, and so is one under a status
    nobody configured: it is never claimed, but dropping it from the board
    would hide exactly the card that needs a look. Both sit in the one column
    the drafts have, on the left — no column is added for them.
    """
    api = _bare_api(_ColumnsClient(["Ready", "", "Parked"]))
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    board = api.board()
    keys = [column["key"] for column in board["columns"]]
    assert keys[0] == "draft" and "other" not in keys, keys
    assert board["columns"][0] == {"key": "draft", "name": ""}, (
        "the console names the drafts, not the board"
    )
    assert [item["column"] for item in board["tickets"]] == ["draft", "draft", "ready"]


class _CancelClient(_ColumnsClient):
    """The same database, offering — or not — a cancelled option."""

    def __init__(self, statuses: list[str], offered: bool) -> None:
        super().__init__(statuses)
        self.offered = offered

    def options(self, database: str, prop: str) -> list[str]:
        return [*super().options(database, prop), *(["Cancelled"] if self.offered else [])]


@case
def a_cancelled_ticket_has_its_column_where_the_board_offers_one():
    """Cancelled closes the row, beside Done — on a board that can say it.

    A Notion board without the option is told rather than written into: no
    gesture is offered, and a move asked anyway is refused in words rather than
    sent to an API that would reject it.
    """
    quiet = type("W", (), {"nudge": lambda self: None})()

    api = _bare_api(_CancelClient(["Ready", "Cancelled", "Done"], offered=True))
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api.watch = quiet
    board = api.board()
    keys = [column["key"] for column in board["columns"]]
    assert keys[-2:] == ["done", "cancelled"], keys
    assert board["cancel"] is True
    assert [item["column"] for item in board["tickets"]] == ["ready", "done", "cancelled"]
    assert api.set_status("1" * 32, "cancelled")["status"] == "Cancelled"

    bare = _bare_api(_CancelClient(["Ready", "Done"], offered=False))
    bare._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    bare._schema_at = time.time()
    bare.watch = quiet
    assert bare.board()["cancel"] is False
    try:
        bare.set_status("1" * 32, "cancelled")
    except ValueError as error:
        assert "no “Cancelled” option" in str(error), error
    else:
        raise AssertionError("a status the board does not offer is refused before it is sent")

    # A board that points cancelled at a status the runner moves tickets
    # through has no cancelled column of its own: a cancelled `ready` is run.
    api._config.notion.status = api._runner.config.notion.status = {"cancelled": "Done"}
    assert api.board()["cancel"] is False


@case
def a_markdown_board_reads_and_writes_the_cancelled_status():
    """A board of files declares every default column, cancelled with them."""
    with _board() as board:
        assert "Cancelled" in board.options("tickets", "Status")
        page = board.create_row("tickets", "Plus besoin", {"Status": "Ready"})
        api = _markdown_api(board)
        api.watch = type("W", (), {"nudge": lambda self: None})()
        api._schema_at = time.time()
        shown = api.board()
        assert shown["cancel"] is True
        assert "cancelled" in [column["key"] for column in shown["columns"]]
        board.update("tickets", page, {"Status": "Cancelled"})
        card = next(item for item in api.board()["tickets"] if item["id"] == page.replace("-", ""))
        assert card["column"] == "cancelled" and card["status"] == "Cancelled"
        assert store.read(board.page(page), "Status") == "Cancelled"


@case
def the_runner_never_runs_a_cancelled_ticket_even_when_named():
    """Not from the ready column, not woken by a comment, not by `run --ticket`."""
    with _board() as board:
        page = board.create_row("tickets", "Abandonné", {"Status": "Cancelled"})
        runner = Runner.__new__(Runner)
        runner._journals = {}
        runner.config = C.Config(
            notion=C.Notion(),
            runner=C.Runner(),
            projects={},
            path=Path("/nowhere/config.toml"),
            web=C.Web(),
            storage=C.Storage(mode="markdown", path=board.root),
        )
        runner.client = board
        runner._workspace = board.workspace(runner.config.notion)
        said: list[str] = []
        runner.say = said.append
        assert runner.cancelled_column()
        assert runner.requested(page) == []
        assert said == ["Requested ticket is cancelled — not run: Abandonné"]
        assert page.replace("-", "") not in {
            ticket_module.Ticket(found).id
            for found in board.query(runner.database, runner._ready_filter())
        }
        assert page.replace("-", "") not in {
            ticket_module.Ticket(found).id
            for found in board.query(runner.database, runner._woken_filter())
        }
        board.update("tickets", page, {"Status": "Blocked"})
        assert [ticket.title for ticket in runner.requested(page)] == ["Abandonné"]


class _DraftClient(_ColumnsClient):
    """The same database, offering a draft option, and keeping what is created."""

    def __init__(self, statuses: list[str]) -> None:
        super().__init__(statuses)
        self.created: list[tuple[str, dict]] = []

    def options(self, database: str, prop: str) -> list[str]:
        return ["draft", *super().options(database, prop)]

    def create_row(self, database_id, title, values=None):
        self.created.append((title, dict(values or {})))
        return "f" * 32


@case
def a_ticket_with_no_status_is_a_draft_whether_or_not_the_board_names_them():
    """Master Tickets has a `draft` option; the console put those under "No status".

    The drafts are always the first column, and a ticket with no status is one.
    Named in `[notion.status]`, the column is also the option, and "New ticket"
    with its "Draft" button writes it. Left unnamed, a move to the drafts
    clears the status and a new draft is written with none — and one named the
    same as `ready` is the runner's, so never called a draft.
    """
    quiet = type("W", (), {"nudge": lambda self: None})()

    api = _bare_api(_DraftClient(["draft", "Ready", ""]))
    api._config.notion.status = {"draft": "draft"}
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api.watch = quiet
    board = api.board()
    keys = [column["key"] for column in board["columns"]]
    assert keys[0] == "draft" and "other" not in keys, keys
    assert board["columns"][0]["name"] == "draft", "the status a move writes, as Notion spells it"
    assert [item["column"] for item in board["tickets"]] == ["draft", "draft", "ready"]
    api.create_ticket("Écrire l'audit", ready=False)
    api.create_ticket("Lancer l'audit", ready=True)
    assert [values.get("Status") for _, values in api._runner.client.created] == ["draft", "Ready"]
    assert api.set_status("1" * 32, "draft")["status"] == "draft"

    plain = _bare_api(_DraftClient(["draft", "Ready", ""]))
    plain._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    plain._schema_at = time.time()
    plain.watch = quiet
    board = plain.board()
    assert board["columns"][0] == {"key": "draft", "name": ""}
    assert [item["column"] for item in board["tickets"]] == ["draft", "draft", "ready"]
    plain.create_ticket("Écrire l'audit", ready=False)
    assert plain._runner.client.created == [("Écrire l'audit", {})], "no key, no status, as before"
    assert plain.set_status("1" * 32, "draft")["status"] == "", (
        "a move to the drafts clears the status"
    )

    assert C.Notion().state("draft") == "", "nothing is defaulted"
    assert C.Notion(status={"draft": "Ready"}).state("draft") == "Ready"
    assert web_tickets._draft(C.Notion(status={"draft": "Ready"})) == "", (
        "a draft that is the runner's ready is no draft"
    )


class _UntitledClient(_ColumnsClient):
    """The same database, where nobody wrote a title on any row."""

    def query(self, database: str, *args, **kwargs) -> list[notion.Page]:
        return [
            notion.Page(
                id=page.id, url=page.url, title="", properties=page.properties, raw=page.raw
            )
            for page in super().query(database, *args, **kwargs)
        ]


@case
def a_ticket_without_a_title_is_named_by_the_console_in_its_language():
    """ "(untitled ticket)" used to come from the server, in English on a French console.

    The server sends the title Notion has — none — and the console says what
    to call it, through the dictionary like every other word it says.
    """
    api = _bare_api(_UntitledClient(["Ready"]))
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    assert [item["title"] for item in api.board()["tickets"]] == [""]
    store_ = (FRONTEND / "src/lib/board-store.ts").read_text(encoding="utf-8")
    assert 't("(untitled ticket)")' in store_, (
        "the console no longer names a ticket without a title"
    )
    french = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    assert '"(untitled ticket)": "(ticket sans titre)"' in french


@case
def the_pages_of_a_list_are_said_in_the_console_s_language():
    """react-resource-view writes "Showing 1 to 30 sur 475 results" whatever the language.

    Every list brings the console's own pagination, whose words go through the
    dictionary, with one ellipsis between the pages rather than four dots.
    """
    pagination = (FRONTEND / "src/components/console/pagination.tsx").read_text(encoding="utf-8")
    assert 't("Showing {{from}} to {{to}} of {{total}} results"' in pagination
    assert "…" in pagination and "...." not in pagination
    french = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    assert '"Affichage de {{from}} à {{to}} sur {{total}} résultats"' in french
    # Given once, under every resource, rather than list by list.
    views = (FRONTEND / "src/lib/resource-view.ts").read_text(encoding="utf-8")
    assert "defaults: { components: { pagination: Pagination } }" in views, (
        "the lists say their pages in English"
    )
    for resource in ("tickets", "projects", "schedules", "pairs"):
        source = (FRONTEND / f"src/resources/{resource}.tsx").read_text(encoding="utf-8")
        assert "pagination: null" not in source, f"the {resource} list says its pages in English"


def _session_line(kind: str = "assistant") -> str:
    if kind == "result":
        return json.dumps({"type": "result", "result": "done", "session_id": "s"}) + "\n"
    return (
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "reading"}]}}
        )
        + "\n"
    )


@case
def a_session_is_running_until_its_log_says_its_last_word():
    """A step says a session is alive; only the `result` line says it is over.

    Counted from the logs rather than from the steps a browser happened to see:
    a console reloaded mid-run counted nothing, and one left open counted every
    session it had ever seen as still writing.
    """
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        working = folder / "20260830-120000-1a2b3c4d.jsonl"
        working.write_text(_session_line(), encoding="utf-8")
        finished = folder / "20260830-110000-9f8e7d6c.jsonl"
        finished.write_text(_session_line() + _session_line("result"), encoding="utf-8")

        running = web_live.active(folder, held=lambda: "4242 now")
        assert running == [{"source": "1a2b3c4d", "log": working.name}], running
        assert web_live.active(folder, held=lambda: "") == [], (
            "no run holds the lock: a log that still looks fresh is a run that died"
        )

        # An answer longer than what is read of the end is still recognised.
        huge = folder / "20260830-130000-00aa11bb.jsonl"
        huge.write_text(
            _session_line()
            + json.dumps({"type": "result", "result": "x" * (web_live.ENDING_BYTES + 10)})
            + "\n",
            encoding="utf-8",
        )
        assert web_live.answered(huge)


@case
def how_long_a_session_took_is_read_from_its_log_where_the_board_has_no_column():
    """The `result` line carries the duration; a run still writing does not count."""
    finished = json.dumps({"type": "result", "result": "done", "duration_ms": 540_000}) + "\n"
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        assert web_live.lasted("1a2b3c4d", folder) is None, "no log, no duration"
        (folder / "20260830-110000-1a2b3c4d.jsonl").write_text(
            _session_line() + finished, encoding="utf-8"
        )
        (folder / "20260830-120000-1a2b3c4d.jsonl").write_text(_session_line(), encoding="utf-8")
        (folder / "20260830-130000-1a2b3c4d-talk.jsonl").write_text(
            _session_line() + json.dumps({"type": "result", "duration_ms": 60_000}) + "\n",
            encoding="utf-8",
        )
        assert web_live.lasted("1a2b3c4d", folder) == 9.0, (
            "the newest finished session of the ticket — not a run in progress, not a reply"
        )
        assert web_live.lasted("9f8e7d6c", folder) is None


@case
def the_sessions_running_are_announced_when_they_change_and_kept_for_the_next_tab():
    hub = web_live.Hub()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        log = folder / "20260830-120000-1a2b3c4d.jsonl"
        log.write_text(_session_line(), encoding="utf-8")
        tail = web_live.Tail(hub, folder, held=lambda: "4242")
        said = []
        publish = hub.publish

        def listening(kind: str, **payload: object) -> None:
            said.append((kind, payload))
            publish(kind, **payload)

        hub.publish = listening  # type: ignore[method-assign]
        tail.pass_once()
        tail.pass_once()
        announced = [payload for kind, payload in said if kind == "sessions"]
        assert announced == [{"sessions": [{"source": "1a2b3c4d", "log": log.name}]}], (
            "said once, and not again while nothing changed"
        )

        # A tab opened now is told what is running before anything else moves.
        fresh = hub.subscribe()
        kinds = [fresh.get_nowait().kind for _ in range(fresh.qsize())]
        assert kinds == ["sessions"], kinds

        with log.open("a", encoding="utf-8") as handle:
            handle.write(_session_line("result"))
        tail.pass_once()
        announced = [payload for kind, payload in said if kind == "sessions"]
        assert announced[-1] == {"sessions": []}, "the end of a session is news too"


@case
def the_pages_before_the_console_speak_the_browsers_language():
    """The sign-in and the gate, as the console would say them.

    Same rule as the console: the browser's own list decides. And every field
    has a label that names it, rather than a greyed example that vanishes the
    moment somebody starts typing.
    """
    from ponos.web import server as web_server

    assert web_server.language_of("fr-FR,fr;q=0.9,en;q=0.8") == "fr"
    assert web_server.language_of("de-DE,en-GB;q=0.7") == "en"
    assert web_server.language_of("") == "en"

    for build in (web_server.sign_in_page, web_server.gate_page):
        french = build("fr")
        assert '<html lang="fr"' in french
        assert "Ouvrir la console" in french
        assert web_server.GUARD_HEADER in french or build is web_server.gate_page
        for field in re.findall(r'<(?:input|textarea)[^>]*\bid="([^"]+)"', french):
            assert f'<label for="{field}"' in french, f"{field} has no label"
        assert "#3b82f6" not in french, (
            "the door is drawn in the console's own blue, not a stock one"
        )
    assert '<html lang="en"' in web_server.SIGN_IN


@case
def the_gate_says_where_this_machines_token_actually_is():
    """`~/.local/state/…` printed as a constant was wrong wherever XDG_STATE_HOME is set."""
    from ponos.web import server as web_server

    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = "/srv/elsewhere"
    try:
        page = web_server.gate_page("en")
    finally:
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous
    assert "/srv/elsewhere/ponos/web/token" in page
    assert "~/.local/state" not in page


@case
def the_gate_says_a_chosen_token_lives_in_secrets_env_and_why_a_cookie_was_refused():
    """The token left `config.toml` for `secrets.env`; the gate said otherwise.

    And a cookie is scoped by host, not by port: a test console beside 8787
    overwrites 8787's, and the gate came back with nothing to say why.
    """
    import urllib.error
    import urllib.request

    from ponos.web import app as web_app
    from ponos.web import server as web_server

    api = _bare_api(_TalkClient([]))
    api._config.web.token = "tok"
    folder = Path(tempfile.mkdtemp())
    api._config.path = folder / "config.toml"
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def gate(path: str, cookie: str = "") -> str:
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        request.add_header("Accept-Language", "fr")
        if cookie:
            request.add_header("Cookie", f"{web_server.COOKIE}={cookie}")
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 401
            return error.read().decode()
        raise AssertionError("the door opened")

    previous = os.environ.pop(C.SECRETS_PATH_ENV, None)
    try:
        page = gate("/")
        assert "variable d'environnement <code>PONOS_WEB_TOKEN</code>" in page, page
        assert "web.token" not in page
        assert "n'est pas celui de cette console" not in page, "nothing was offered"

        (folder / "secrets.env").write_text("PONOS_WEB_TOKEN=tok\n")
        page = gate("/", cookie="another-consoles")
        assert f"<code>{folder / 'secrets.env'}</code>" in page, page
        assert "n'est pas celui de cette console" in page
        assert "jeton incorrect" in gate("/?token=nope")
    finally:
        if previous is not None:
            os.environ[C.SECRETS_PATH_ENV] = previous
        console.shutdown()
        console.server_close()


@case
def the_door_is_drawn_in_the_consoles_palette_in_both_themes():
    """Hermez's stone and orange, dark unless the console was switched to light."""
    from ponos.web import server as web_server

    tokens = (ROOT / "frontend" / "src" / "tokens.css").read_text()
    light, dark = tokens.split("\n.dark {", 1)
    for name in ("background", "card", "primary", "field", "foreground"):
        ours = re.findall(rf"--{name}:([^;]+);", web_server._STYLE)
        assert ours[0] in light.replace("#ffffff", "#fff"), name
        assert ours[1] in dark, name
    assert '<html lang="en" class="dark">' in web_server.GATE
    assert "ponos-theme" in web_server.GATE, "the choice made in the console is the door's too"


@case
def a_write_refused_before_its_body_is_read_closes_the_connection():
    """A POST turned away unread must not leave its body on a reused connection.

    The browser reuses a keep-alive connection: the `{}` of a refused
    `/api/refresh` was read as the start of the next request, and a signed-out
    page that reloaded itself got "501 Unsupported method ('{}GET')" instead of
    the sign-in.
    """
    import socket as sockets

    from ponos.web import app as web_app

    api = _bare_api(_TalkClient([]))
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    thread = threading.Thread(target=console.serve_forever, daemon=True)
    thread.start()
    try:
        port = console.server_address[1]
        with sockets.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(
                b"POST /api/refresh HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Ponos: 1\r\n"
                b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"
                b"GET /api/state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
            )
            answer = b""
            while chunk := connection.recv(65536):
                answer += chunk
    finally:
        console.shutdown()
        console.server_close()
    said = answer.decode("utf-8", "replace")
    assert said.startswith("HTTP/1.1 401"), said[:80]
    assert "connection: close" in said.lower()
    assert "501" not in said, "the body was read as the next request"


@case
def a_client_that_hangs_up_mid_answer_leaves_no_trace():
    """A tab closed while its board was on the way is not an error.

    The journal of `ponos-web.service` held 38 tracebacks by 1 October
    2026, two per closed tab: the `BrokenPipeError` of the write, then the 500
    the route's `except Exception` tried to send on the same dead socket.
    """
    import socket as sockets

    from ponos.web import app as web_app

    asked = threading.Event()
    journal: list[str] = []

    class Kept(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            journal.append(self.format(record))

    kept = Kept(logging.WARNING)
    api = _bare_api(_TalkClient([]))
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]
    request = b"GET /api/board HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer tok\r\n\r\n"
    stderr, sys.stderr = sys.stderr, io.StringIO()
    logging.getLogger("uvicorn.error").addHandler(kept)
    try:

        def large():
            asked.set()
            # Far more than the socket buffers hold, so the write meets the hang-up.
            return {"tickets": ["x" * 1024] * 8192}

        api.board = large
        with sockets.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(request)
            connection.recv(100)
        assert asked.wait(5), "the request never arrived"
        time.sleep(0.5)
        journal.append(sys.stderr.getvalue())

        def broken():
            raise RuntimeError("the board is upside down\nand more")

        api.board = broken
        with sockets.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(request.replace(b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n"))
            answer = b""
            while chunk := connection.recv(65536):
                answer += chunk
    finally:
        logging.getLogger("uvicorn.error").removeHandler(kept)
        sys.stderr = stderr
        console.shutdown()
        console.server_close()
    assert "".join(journal) == "", journal
    said = answer.decode("utf-8", "replace")
    assert said.startswith("HTTP/1.1 500"), said[:80]
    assert said.endswith('{"error": "the board is upside down"}'), said[-80:]


@case
def a_500_leaves_its_trace_in_the_journal_masked(state_home):
    """A route that raised answered a 500 and kept the reason to itself.

    The request log was switched off and the `except Exception` turned the error
    into one line of JSON: the console's journal said nothing of it. It now
    holds the whole trace — and the request that came back 500 — with the
    secrets the trace printed masked, a vault's value and a token's shape alike.
    """
    import socket as sockets

    from ponos.web import app as web_app

    secret = "vault-value-" + "q" * 24
    token = "ghp_" + "Z" * 36
    target = log.setup(state_home / "logs" / "ponos.log")
    assert target is not None
    vault.remember(secret)
    api = _bare_api(_TalkClient([]))

    def broken():
        raise RuntimeError(f"the board refused {secret} and {token}")

    api.board = broken
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:
        request = (
            b"GET /api/board?token=tok HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Authorization: Bearer tok\r\nConnection: close\r\n\r\n"
        )
        with sockets.create_connection(("127.0.0.1", console.server_address[1]), 5) as link:
            link.sendall(request)
            answer = b""
            while chunk := link.recv(65536):
                answer += chunk
    finally:
        console.shutdown()
        console.server_close()
        vault.forget()
        written = target.read_text(encoding="utf-8")
        served = api.service_log(50)["lines"]
    assert answer.startswith(b"HTTP/1.1 500"), answer[:80]
    assert "ERROR ponos.web.routes: console: GET /api/board failed" in written, written
    assert "Traceback (most recent call last)" in written and "in broken" in written, written
    assert "console: GET /api/board → 500" in written, written
    assert secret not in written and token not in written, written
    assert "the board refused *** and ••••••" in written, written
    assert "token=tok" not in written, "a request is logged by its path, never its query"
    assert served == written.splitlines()


@case
def say_writes_what_it_always_printed_and_the_journal_keeps_it_dated(state_home):
    """`say` went through `print`: the standard output reads the same line, and
    ponos.log has it too, with a date, a level and the module — and the trace of
    an error already said goes to the file alone."""

    target = log.setup(state_home / "logs" / "ponos.log")
    assert target is not None
    runner = _bare_runner(_TalkClient([]))
    runner.quiet = False
    stdout, sys.stdout = sys.stdout, io.StringIO()
    try:
        runner.say("  ✓ a line, 100% as it was")
        try:
            raise ValueError("inside")
        except ValueError:
            logging.getLogger("ponos.test").exception("said already", extra=log.FILE_ONLY)
        printed = sys.stdout.getvalue()
    finally:
        sys.stdout = stdout
    written = target.read_text(encoding="utf-8")
    assert printed == "  ✓ a line, 100% as it was\n", printed
    assert " INFO ponos.base:   ✓ a line, 100% as it was\n" in written, written
    assert "ERROR ponos.test: said already" in written and "ValueError: inside" in written


@case
def the_journal_tail_is_its_last_lines_and_nothing_when_it_was_never_written():
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "ponos.log"
        assert log.tail(10, target) == []
        target.write_text("".join(f"line {number}\n" for number in range(100_000)))
        tail = log.tail(3, target)
        assert tail == ["line 99997", "line 99998", "line 99999"], tail
        assert all(line.startswith("line ") for line in log.tail(0, target))


@case
def a_path_field_picks_from_the_folder_it_points_at():
    """Names, folders first; a file typed half-way lists its folder."""
    root = Path(tempfile.mkdtemp())
    (root / "prompts").mkdir()
    (root / "ticket.md").write_text("x", encoding="utf-8")
    (root / ".hidden").write_text("x", encoding="utf-8")
    listed = web_settings.folder(str(root))
    assert listed["folder"] == str(root) and listed["parent"] == str(root.parent)
    assert listed["entries"] == [
        {"name": "prompts", "folder": True},
        {"name": "ticket.md", "folder": False},
    ], "hidden ones stay hidden"
    assert web_settings.folder(str(root / "tic"))["folder"] == str(root)
    assert any(
        item["name"] == ".hidden" for item in web_settings.folder(str(root / ".h"))["entries"]
    )


@case
def an_example_token_is_not_a_token_the_settings_call_set():
    """The `ntn_xxxx…` the example file ships with is where a token goes, not one."""
    assert web_settings._preview(C.PLACEHOLDER) == ""
    assert web_settings._preview("ntn_xxxxxxxx") == ""
    assert web_settings._preview("ntn_real_secret_abcd") == "…abcd"


@case
def the_settings_are_six_pages_and_every_key_is_on_one_of_them_once():
    """Grouped by the question somebody asks, not by the table the loader reads.

    Twenty-two sections at one rank put the Notion token beside the twenty-one
    names of its properties. Six pages now, the names folded at the end of the
    one about where tickets come from — and every model the runner can be told
    to use on the page about models, rather than wherever its table was.
    """
    groups = [group.key for group in web_settings.GROUPS]
    assert len(groups) == 6 and len(set(groups)) == 6, groups
    for section in web_settings.SECTIONS:
        assert section.group in groups, f"{section.key} is on no page"
        assert not section.fold or section.fold in web_settings.FOLDS, section.key
    assert {section.group for section in web_settings.SECTIONS} == set(groups), "an empty page"

    names = [field.name for section in web_settings.SECTIONS for field in section.fields]
    twice = sorted({name for name in names if names.count(name) > 1})
    assert not twice, f"drawn on two cards: {twice}"
    keys = [section.key for section in web_settings.SECTIONS]
    assert len(keys) == len(set(keys)), "two cards under one key"

    where = {field.name: section for section in web_settings.SECTIONS for field in section.fields}
    for name in where:
        if not name.startswith("notion.") and "model" in name.rpartition(".")[2]:
            assert where[name].group == "models", f"{name} is not with the models"
    for table in ("status", "properties", "pages", "types"):
        for key in C.defaults(table):
            assert where[f"notion.{table}.{key}"].fold == "mapping", f"notion.{table}.{key}"
    notion = [name for name in where if name.startswith("notion.") and not where[name].fold]
    assert sorted(notion) == [
        "notion.mention",
        "notion.tickets_database",
        "notion.token",
        "notion.workspace",
    ], notion
    assert where["notion.mention"].key == "replies", "the word that asks is about answers"
    source = [section.key for section in web_settings.SECTIONS if section.group == "source"]
    assert source.index("storage") < source.index("notion"), "a board need not be in Notion"

    path, config = _saved()
    drawn = web_settings.describe(config)
    assert [group["key"] for group in drawn["groups"]] == groups
    assert drawn["folds"][0]["key"] == "mapping"
    assert {section["group"] for section in drawn["sections"]} == set(groups)


@case
def the_old_desktop_switch_is_one_field_and_moves_when_touched():
    """`runner.notify` and `notify.desktop` said the same thing in two places.

    The page draws the second only, which already falls back on the first; a
    save of it takes the old line away, so the file ends up saying it once —
    and a file nobody touches keeps working as it did.
    """
    assert "runner.notify" not in web_settings.FIELDS
    assert web_settings.LEGACY["runner.notify"] in web_settings.FIELDS
    path, config = _saved("\n[runner]\nnotify = false\n")
    drawn = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert drawn["notify.desktop"]["fallback"] is False, "the old key still answers"
    web_settings.save(config, {"settings": {"notify.desktop": True}})
    text = path.read_text()
    assert "notify = false" not in text and "desktop = true" in text, text
    assert C.load(path).notify.desktop is True


@case
def a_value_the_environment_gives_is_said_to_come_from_it():
    """Retyping a token the environment overrides changes nothing — the page says so."""
    path, config = _saved()
    with _environment(
        PONOS_SLACK_TOKEN="xoxb-from-the-environment", PONOS_WEB_EMAIL="me@example.com"
    ):
        drawn = {
            field["name"]: field
            for section in web_settings.describe(config)["sections"]
            for field in section["fields"]
        }
    assert drawn["notify.slack.token"]["environment"] == "PONOS_SLACK_TOKEN"
    assert drawn["web.email"]["environment"] == "PONOS_WEB_EMAIL"
    assert drawn["notion.token"]["environment"] == "", "secrets.env holds this one"


@case
def a_container_is_given_its_language_by_the_environment():
    """`PONOS_LANGUAGE` when the file names none; the file when it does."""
    path, _ = _saved()
    with _environment(PONOS_LANGUAGE="fr"):
        assert C.load(path).runner.language == "fr"
        assert C.load(path).runner.interface_language() == "fr", "the console follows it too"
    with _environment(PONOS_LANGUAGE=None):
        assert C.load(path).runner.language == "", "nothing said is still nothing said"
    path, _ = _saved('\n[runner]\nlanguage = "en"\n')
    with _environment(PONOS_LANGUAGE="fr"):
        assert C.load(path).runner.language == "en", "a language picked in Settings wins"
