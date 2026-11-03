"""`unblocking.py`: the pass that reads the blocked column again.

`test_conversation.py` already holds what one examination decides. What is
here is the way in — the gates that keep the pass from spending a session it
should not, and the choice of the tickets it spends them on — because a bug
there costs money or lets go of a ticket, and nothing else would show it.
"""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from support import _bare_runner, _config, _no_session, _Unblocking, case

from ponos import credits, notion, projects, session, store, unblocking
from ponos import ticket as ticket_module
from ponos.ticket import short_id

KEEP = "DECISION: keep\nREASON: B n'est pas fini."


def _page(ident: str, title: str, status: str = "Blocked", **values: Any) -> notion.Page:
    """A row of the board, last edited `age` ago (two hours unless told otherwise)."""
    age: timedelta = values.pop("age", timedelta(hours=2))
    edited = values.pop("edited", (datetime.now(UTC) - age).isoformat())
    properties: dict[str, Any] = {"Status": {"type": "status", "status": {"name": status}}}
    for name, checked in values.items():
        properties[name.replace("_", " ")] = {"type": "checkbox", "checkbox": checked}
    return notion.Page(
        id=ident,
        url=f"https://notion.so/{ident}",
        title=title,
        properties=properties,
        raw={"last_edited_time": edited},
    )


class _Board:
    """A tickets database: the blocked rows when filtered, the whole board when not."""

    def __init__(self, pages: list[notion.Page], refuses: str = "") -> None:
        self.pages, self.refuses = pages, refuses
        self.asked: list[dict[str, Any] | None] = []

    def schema(self, database_id: str) -> dict[str, str]:
        if self.refuses:
            raise notion.NotionError(self.refuses)
        return {"Status": "status"}

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[notion.Page]:
        self.asked.append(filter_)
        if filter_ is None:
            return self.pages
        wanted = filter_["status"]["equals"]
        return [page for page in self.pages if store.read(page, "Status") == wanted]


class _Pass(_Unblocking):
    """`_Unblocking`, with the gates of a whole pass under the test's hand."""

    reserves: list[float]
    flag: str
    answered: set[str]
    broken: set[str]
    broke: bool
    said: list[str]
    project: projects.Project
    board: _Board  # the client, as its own type

    def under_reserve(self) -> float:
        # One entry per question, the last one standing: a reserve can be
        # reached in the middle of a pass.
        return self.reserves.pop(0) if len(self.reserves) > 1 else self.reserves[0]

    def waiting_flag(self) -> str:
        return self.flag

    def _answered(self, ticket: ticket_module.Ticket) -> bool:
        return ticket.id in self.answered

    def _project_of(self, ticket: ticket_module.Ticket) -> projects.Project:
        return self.project

    def _out_of_credit(self, outcome: session.Outcome) -> bool:
        return self.broke

    def _examine(self, ticket: ticket_module.Ticket, board: str) -> dict[str, Any] | None:
        if ticket.id in self.broken:
            raise store.StoreError(f"{ticket.title}: object not found")
        return super()._examine(ticket, board)

    def say(self, message: str) -> None:
        self.said.append(message)


def _pass(board: _Board, *, unblock: bool = True, dry_run: bool = False) -> _Pass:
    runner = _bare_runner(board)
    runner.__class__ = _Pass
    assert isinstance(runner, _Pass)
    runner.board = board
    runner.config = _config("[runner]\nunblock = true\n" if unblock else "")
    runner.dry_run, runner._claimed = dry_run, set()
    runner.moved, runner.comments_written, runner.said = [], [], []
    runner.reserves, runner.flag, runner.answered, runner.broken = [0.0], "", set(), set()
    runner.broke, runner.project = False, projects.Project(name="", path=None)
    return runner


def _examined(calls: list[dict[str, Any]]) -> list[str]:
    """The tickets a session was started on, by the URL its prompt carries."""
    return [
        url
        for call in calls
        for url in ("https://notion.so/" + name for name in ("a", "b", "c", "d", "e"))
        if url in call["prompt"]
    ]


# -- the gates ----------------------------------------------------------------


@case
def a_dry_run_or_a_pass_that_was_not_asked_for_reads_nothing(state_home: Path) -> None:
    for runner in (
        _pass(_Board([_page("a", "A")]), dry_run=True),
        _pass(_Board([_page("a", "A")]), unblock=False),
    ):
        with _no_session(KEEP) as calls:
            assert runner.unblock() == []
        assert calls == [] and runner.board.asked == [], "not even the board is read"
        assert not credits.held(what="unblock"), "and nothing is held for a pass that never ran"


@case
def under_the_reserve_the_pass_starts_nothing(state_home: Path) -> None:
    runner = _pass(_Board([_page("a", "A")]))
    runner.reserves = [time.time() + 3600]
    with _no_session(KEEP) as calls:
        assert runner.unblock() == []
    assert calls == [] and runner.board.asked == []
    assert not credits.held(what="unblock"), "the next pass may look as soon as there is room"


@case
def a_pass_already_held_waits_for_its_turn(state_home: Path) -> None:
    credits.hold(time.time() + 60, what="unblock")
    runner = _pass(_Board([_page("a", "A")]))
    with _no_session(KEEP) as calls:
        assert runner.unblock() == []
    assert calls == [] and runner.board.asked == []


@case
def a_pass_that_ran_holds_the_column_for_the_next_few_minutes(state_home: Path) -> None:
    runner = _pass(_Board([_page("a", "A")]))
    with _no_session(KEEP) as calls:
        first = runner.unblock()
        second = runner.unblock()
    assert [result["status"] for result in first] == ["kept-blocked"], first
    assert second == [] and len(calls) == 1, "the second pass, a minute later, reads nothing"
    held = credits.held(what="unblock")
    assert time.time() < held <= time.time() + unblocking.PASS
    ticket = credits.held(what="unblock:a")
    assert ticket > time.time() + runner.config.runner.unblock_interval_seconds - 60, (
        "the ticket itself is not looked at again before its own clock"
    )


@case
def a_board_that_cannot_be_read_is_said_once_and_spends_nothing(state_home: Path) -> None:
    runner = _pass(_Board([_page("a", "A")], refuses="Notion is down"))
    with _no_session(KEEP) as calls:
        assert runner.unblock() == []
    assert calls == []
    assert [line for line in runner.said if "not examined" in line] == [
        "  ! blocked tickets not examined: Notion is down"
    ], runner.said


# -- which tickets are looked at ----------------------------------------------


@case
def only_the_blocked_tickets_nobody_is_on_are_looked_at(state_home: Path) -> None:
    board = _Board(
        [
            _page("a", "Bloqué depuis longtemps"),
            _page("b", "Bloqué il y a dix minutes", age=timedelta(minutes=10)),
            _page("c", "Déjà répondu"),
            _page("d", "Attend des crédits", Waiting_for_credit=True),
            _page("e", "Pris par cette passe"),
            _page("f", "Prêt", status="Ready"),
        ]
    )
    runner = _pass(board)
    runner.flag, runner.answered, runner._claimed = "Waiting for credit", {"c"}, {"e"}
    with _no_session(KEEP) as calls:
        results = runner.unblock()
    assert _examined(calls) == ["https://notion.so/a"], _examined(calls)
    assert [result["id"] for result in results] == ["a"]
    assert board.asked[0] == {"property": "Status", "status": {"equals": "Blocked"}}, (
        "the blocked column, by the status the board is written in"
    )


@case
def a_ticket_examined_lately_waits_for_its_own_clock(state_home: Path) -> None:
    credits.hold(time.time() + 3600, what="unblock:a")
    runner = _pass(_Board([_page("a", "A"), _page("b", "B")]))
    with _no_session(KEEP) as calls:
        results = runner.unblock()
    assert _examined(calls) == ["https://notion.so/b"], "a was seen, b was not yet"
    assert [result["id"] for result in results] == ["b"]


@case
def a_date_the_runner_cannot_read_does_not_hide_a_ticket(state_home: Path) -> None:
    runner = _pass(_Board([_page("a", "A", edited="")]))
    with _no_session(KEEP) as calls:
        runner.unblock()
    assert _examined(calls) == ["https://notion.so/a"]


@case
def nothing_due_reads_neither_the_board_nor_a_session(state_home: Path) -> None:
    board = _Board([_page("a", "A", age=timedelta(minutes=1)), _page("f", "F", status="Done")])
    runner = _pass(board)
    with _no_session(KEEP) as calls:
        assert runner.unblock() == []
    assert calls == [] and board.asked == [board.asked[0]] and board.asked[0] is not None, (
        "the whole board is only read for a ticket about to be examined"
    )


@case
def a_pass_starts_a_few_sessions_and_leaves_the_rest_for_later(state_home: Path) -> None:
    runner = _pass(_Board([_page(name, name.upper()) for name in "abcde"]))
    with _no_session(KEEP) as calls:
        results = runner.unblock()
    assert len(calls) == unblocking.BATCH == len(results)
    assert not credits.held(what="unblock:e"), "the ones left over are not held"


@case
def a_reserve_reached_mid_pass_stops_it_there(state_home: Path) -> None:
    runner = _pass(_Board([_page(name, name.upper()) for name in "abc"]))
    # Free for the pass, free for `a`, spent by the time `b` comes.
    runner.reserves = [0.0, 0.0, time.time() + 3600]
    with _no_session(KEEP) as calls:
        results = runner.unblock()
    assert _examined(calls) == ["https://notion.so/a"] and len(results) == 1
    assert not credits.held(what="unblock:b")


@case
def a_ticket_that_cannot_be_examined_does_not_stop_the_others(state_home: Path) -> None:
    runner = _pass(_Board([_page("a", "A"), _page("b", "B")]))
    runner.broken = {"a"}
    with _no_session(KEEP) as calls:
        results = runner.unblock()
    assert [result["id"] for result in results] == ["b"]
    assert _examined(calls) == ["https://notion.so/b"]
    assert "    ! A not examined: A: object not found" in runner.said, runner.said


@case
def out_of_credit_the_ticket_is_looked_at_again_at_the_next_pass(state_home: Path) -> None:
    runner = _pass(_Board([_page("a", "A")]))
    runner.broke = True
    with _no_session(KEEP) as calls:
        assert runner.unblock() == []
    assert len(calls) == 1 and runner.moved == [] and runner.comments_written == []
    assert not credits.held(what="unblock:a"), "its clock is given back"
    assert "    ⏸ out of credit — this one is looked at later" in runner.said


# -- what the session is shown ------------------------------------------------


@case
def the_session_reads_the_whole_board_a_line_per_ticket(state_home: Path) -> None:
    others = [_page(f"x{n:03d}", f"Autre {n}", status="Done") for n in range(unblocking.OVERVIEW)]
    nameless = notion.Page(id="z", url="", title="Sans statut")
    runner = _pass(_Board([_page("a", "Ticket A"), *others, nameless]))
    with _no_session(KEEP) as calls:
        runner.unblock()
    prompt = calls[0]["prompt"]
    assert f"- [Blocked] Ticket A ({short_id('a')})" in prompt
    assert f"- [Done] Autre 0 ({short_id('x000')})" in prompt
    assert "(and 2 more)" in prompt, "a board past OVERVIEW is cut, and says by how much"
    assert "Autre 199" not in prompt and "Sans statut" not in prompt


@case
def a_short_board_is_shown_whole_with_a_mark_for_a_missing_status() -> None:
    runner = _pass(_Board([_page("a", "Ticket A"), notion.Page(id="z", url="", title="Nu")]))
    assert runner._overview() == (
        f"- [Blocked] Ticket A ({short_id('a')})\n- [?] Nu ({short_id('z')})"
    )


# -- the corners of one examination -------------------------------------------


@case
def a_code_ticket_is_examined_in_its_repository(state_home: Path) -> None:
    repository = Path(tempfile.mkdtemp())
    runner = _pass(_Board([]))
    runner.project = projects.Project(name="northwind", path=repository)
    with _no_session(KEEP) as calls:
        result = runner._examine(ticket_module.Ticket(_page("a", "A")), "")
    assert calls[0]["cwd"] == repository
    assert f"Repository: {repository}" in calls[0]["prompt"]
    assert result is not None and result["project"] == "northwind"


@case
def a_note_the_page_cannot_be_read_back_is_written_rather_than_lost(state_home: Path) -> None:
    class _Unreadable(_Pass):
        def comments(self, page_id: str) -> list[notion.Comment]:
            raise store.StoreError("comments: object not found")

    runner = _pass(_Board([]))
    runner.__class__ = _Unreadable
    with _no_session(KEEP):
        runner._examine(ticket_module.Ticket(_page("a", "A")), "")
        runner._examine(ticket_module.Ticket(_page("a", "A")), "")
    assert len(runner.comments_written) == 2, "unsure it was said, it is said again"
