"""`board.py`: what a pass reads of the board, and the tidyings it does first."""

from __future__ import annotations

import os
import time
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from support import _board_runner, _BoardClient, _in_progress, _ready, _reviewed, case

from ponos import conversation, db, journal, priority, projects, state, store, voice
from ponos.board import InHand
from ponos.config import state_dir
from ponos.runner import Runner
from ponos.ticket import Ticket

STATUS = {"ready": "ready", "running": "progress", "review": "review", "done": "done"}


def _page(page_id: str, status: str = "ready", **properties: dict[str, Any]) -> store.Page:
    return store.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"statut": {"type": "status", "status": {"name": status}}, **properties},
        raw={"created_time": f"2026-01-01T00:00:{page_id[-1]}0.000Z"},
    )


def _date(moment: datetime) -> dict[str, Any]:
    return {"type": "date", "date": {"start": moment.isoformat()}}


def _number(value: int) -> dict[str, Any]:
    return {"type": "number", "number": value}


def _select(name: str) -> dict[str, Any]:
    return {"type": "select", "select": {"name": name}}


def _text(value: str) -> dict[str, Any]:
    return {"type": "rich_text", "rich_text": [{"plain_text": value}]}


def _client(runner: Runner) -> _BoardClient:
    """The fake board `_board_runner` gave the runner, to read what was written on it."""
    return cast(_BoardClient, runner.client)


class _Refusing(_BoardClient):
    """A board that will not hand over its schema, options and identity."""

    def schema(self, database_id: str) -> dict[str, str]:
        raise store.StoreError("GET /databases/db: 403 restricted")

    def options(self, database_id: str, name: str) -> list[str]:
        raise store.StoreError("GET /databases/db: 403 restricted")

    def me(self) -> str:
        raise store.StoreError("GET /users/me: 403 missing capability")

    def my_name(self) -> str:
        raise store.StoreError("GET /users/me: 403 missing capability")


# -- the tickets in hand -------------------------------------------------------


@case
def a_ticket_left_by_the_pass_is_held_out_only_while_the_board_settles() -> None:
    hand = InHand(settle=60)
    hand.take("t1", "northwind")
    hand.take("t2", "northwind")
    hand.take("t3")
    assert "t1" in hand and hand.holding("northwind") == 2 and hand.holding("") == 1

    hand.leave("t1")
    assert "t1" in hand, "the status it had may still be served for a few seconds"
    assert hand.holding("northwind") == 1, "but its place in the project is free at once"

    settled = InHand(settle=0)
    settled.take("t1")
    settled.leave("t1")
    assert "t1" not in settled, "once settled, a ticket made ready again is run again"
    assert "never-taken" not in settled


@case
def a_ticket_taken_again_after_leaving_is_held_for_as_long_as_it_works() -> None:
    hand = InHand(settle=0)
    hand.take("t1")
    hand.leave("t1")
    hand.take("t1")
    time.sleep(0.01)
    assert "t1" in hand, "a second session on it holds it, whatever the first one left"


@case
def a_session_that_lands_lets_go_of_its_ticket_and_no_other() -> None:
    hand = InHand(settle=0)
    ours: Future[Any] = Future()
    stranger: Future[Any] = Future()
    hand.take("t1", "northwind")
    hand.take("t2", "northwind")
    assert hand.carry(ours, "t1") is ours
    hand.land({ours, stranger})
    assert "t1" not in hand and "t2" in hand
    assert hand.holding("northwind") == 1
    hand.land({ours})  # landed twice: nothing more to let go of
    assert "t2" in hand


# -- the queue -----------------------------------------------------------------


@case
def a_dated_ticket_waits_and_the_rest_go_by_priority_then_date_then_age() -> None:
    now = datetime.now().astimezone()
    tomorrow, last_week, yesterday = (
        now + timedelta(days=1),
        now - timedelta(days=7),
        now - timedelta(days=1),
    )
    pages = [
        _page("a1", Priorité=_number(50)),
        _page("a2", Priorité=_number(90)),
        _page("a3", Priorité=_number(50), Scheduled=_date(yesterday)),
        _page("a4", Priorité=_number(50), Scheduled=_date(last_week)),
        _page("a5", Priorité=_number(99), Scheduled=_date(tomorrow)),
        _page("a6", Priorité=_number(50)),
    ]
    runner = _board_runner(pages, STATUS)
    eligible, waiting = runner.queue()
    assert [ticket.id for ticket in eligible] == ["a2", "a4", "a3", "a1", "a6"]
    assert [(ticket.id, moment) for ticket, moment in waiting] == [("a5", tomorrow)]
    assert [ticket.id for ticket in runner.ready()] == ["a2", "a4", "a3", "a1", "a6"]


@case
def a_date_the_runner_cannot_read_holds_nothing_back() -> None:
    page = _page("a1", Scheduled={"type": "rich_text", "rich_text": [{"plain_text": "demain"}]})
    runner = _board_runner([page], STATUS)
    assert runner._moment(Ticket(page)) is None
    assert [ticket.id for ticket in runner.ready()] == ["a1"]


@case
def a_ticket_the_credit_stopped_goes_before_a_higher_priority_one() -> None:
    pages = [
        _page("a1", Priorité=_number(99)),
        _page(
            "a2",
            Priorité=_number(10),
            **{
                "Waiting for credit": {  # type: ignore[arg-type]  # a column, never `status`
                    "type": "checkbox",
                    "checkbox": True,
                }
            },
        ),
    ]
    runner = _board_runner(pages, STATUS, waiting=True)
    runner.under_reserve = lambda: 0.0  # type: ignore[method-assign]  # a double: credit to spare
    assert runner.parked([Ticket(page) for page in pages]) == {"a2"}
    assert [ticket.id for ticket in runner.ready()] == ["a2", "a1"]


@case
def a_status_kept_in_a_select_is_filtered_as_a_select() -> None:
    runner = _board_runner([], STATUS)
    _client(runner).columns["statut"] = "select"
    assert runner._ready_filter() == {"property": "statut", "select": {"equals": "ready"}}
    assert all("select" in condition for condition in runner._woken_filter()["and"])


# -- the optional columns ------------------------------------------------------


@case
def optional_columns_are_absent_on_a_board_that_will_not_show_its_schema() -> None:
    runner = _board_runner([], STATUS)
    runner.client = _Refusing([])  # type: ignore[assignment]  # a fake: a board that refuses
    assert runner.waiting_flag() == ""
    assert runner.type_column() == ""
    assert runner.subtype_column() == ""
    assert runner.backfill_subtypes() == [], "no column, nothing to fill"
    assert runner.priority_cell(75) == 75, "a number, when the column's kind is unknown"


@case
def a_waiting_column_of_the_wrong_type_is_not_the_credit_flag() -> None:
    runner = _board_runner([], STATUS)
    _client(runner).columns["Waiting for credit"] = "rich_text"
    assert runner.waiting_flag() == "", "writing True there would read as the word True"
    assert runner.parked([Ticket(_page("a1"))]) == set()


@case
def a_priority_goes_into_a_select_column_as_its_word() -> None:
    runner = _board_runner([], STATUS)
    _client(runner).columns["Priorité"] = "select"
    assert runner.priority_cell(75) == priority.word(75)
    assert isinstance(runner.priority_cell(75), str)
    _client(runner).columns["Priorité"] = "number"
    assert runner.priority_cell(75) == 75


@case
def cancelled_and_paused_exist_only_as_options_of_their_own() -> None:
    runner = _board_runner([], {**STATUS, "cancelled": "cancelled", "paused": "paused"})
    _client(runner)._options = ["ready", "done"]
    assert not runner.cancelled_column() and not runner.paused_column(), "not offered"

    _client(runner)._options = ["ready", "done", "cancelled", "paused"]
    assert runner.cancelled_column() and runner.paused_column()

    shared = _board_runner([], {**STATUS, "cancelled": "done", "paused": "ready"})
    _client(shared)._options = ["ready", "done"]
    assert not shared.cancelled_column(), "a cancelled ticket that is done is a done one"
    assert not shared.paused_column(), "a paused ticket that is ready would be run"


# -- types ---------------------------------------------------------------------


@case
def a_type_is_read_in_french_and_an_unknown_option_is_no_type() -> None:
    runner = _board_runner([], STATUS)
    assert runner.kind(Ticket(_page("a1", Type=_select("Rédaction")))) == "writing"
    assert runner.kind(Ticket(_page("a2", Type=_select("action externe")))) == "external"
    assert runner.kind(Ticket(_page("a3", Type=_select("Bug")))) == ""
    assert runner.kind(Ticket(_page("a4"))) == ""


@case
def a_type_is_written_the_way_the_board_already_spells_it() -> None:
    runner = _board_runner([], STATUS)
    _client(runner)._options = ["Code", "Rédaction"]
    assert runner.kind_name("writing") == "Rédaction"
    assert runner.kind_name("code") == "Code"
    _client(runner)._options = []
    assert runner.kind_name("writing") == "Rédaction", "the board's name on a bare board"
    _client(runner)._options = ["Writing"]
    assert runner.kind_name("writing") == "Writing", "an older spelling the board still has"

    refused = _board_runner([], STATUS)
    refused.client = _Refusing([])  # type: ignore[assignment]  # a fake: a board that refuses
    assert refused.kind_name("external") == "Action externe"


# -- who has the last word -----------------------------------------------------


class _Discussed(_BoardClient):
    def __init__(
        self,
        pages: list[store.Page],
        said: list[store.Comment] | None = None,
        broken: bool = False,
    ) -> None:
        super().__init__(pages)
        self.said, self.broken, self.asked = said or [], broken, 0

    def comments(self, page_id: str) -> list[store.Comment]:
        self.asked += 1
        if self.broken:
            raise store.StoreError("GET /comments: 403 missing capability")
        return list(self.said)

    def my_name(self) -> str:
        return "Ponos bot"


def _answered(
    said: list[store.Comment],
    *,
    agent: str = "ponos@laptop",
    broken: bool = False,
    me: str = "",
) -> tuple[bool, _Discussed]:
    page = _page("a1", "blocked", Agent=_text(agent)) if agent else _page("a1", "blocked")
    runner = _board_runner([page], STATUS)
    client = _Discussed([page], said, broken)
    runner.client = client  # type: ignore[assignment]  # a fake: a discussion
    runner._me, runner._spellings = me, None
    return runner._answered(Ticket(page)), client


REPORT = store.Comment(f"{voice.MARKS['blocked']} Bloqué — quelle base ?", created_by="u-bot")


@case
def a_human_word_under_a_report_wakes_the_ticket() -> None:
    woke, _ = _answered([REPORT, store.Comment("La base staging.", created_by="u-human")])
    assert woke


@case
def what_is_not_an_answer_under_a_report_wakes_nothing() -> None:
    asleep, _ = _answered([REPORT])
    assert not asleep, "nobody spoke since"
    asleep, _ = _answered([store.Comment("Une remarque.", created_by="u-human")])
    assert not asleep, "no report to answer"
    named, _ = _answered([REPORT, store.Comment("@ponos pourquoi ?", created_by="u-human")])
    assert not named, "naming it asks it to speak, not to work"
    integration, _ = _answered([REPORT, store.Comment("ponos bot, tu relis ?", created_by="h")])
    assert not integration, "the integration's own name names it too"
    ours, _ = _answered([REPORT, store.Comment("Je regarde.", created_by="u-bot")], me="u-bot")
    assert not ours, "what the runner said since is not an answer to it"


@case
def a_ticket_of_another_host_or_of_nobody_is_not_asked_about() -> None:
    other, client = _answered([REPORT, store.Comment("Oui.")], agent="ponos@desktop")
    assert not other and client.asked == 0, "another host's ticket costs no request"
    unknown, client = _answered([REPORT, store.Comment("Oui.")], agent="")
    assert not unknown and client.asked == 0, "an unclaimed ticket the ledger never spoke on"


@case
def comments_the_integration_cannot_read_never_wake_a_ticket() -> None:
    woke, client = _answered([], broken=True)
    assert not woke and client.asked == 1


@case
def a_board_that_will_not_say_who_the_runner_is_fails_nothing() -> None:
    runner = _board_runner([], STATUS)
    runner.client = _Refusing([])  # type: ignore[assignment]  # a fake: a board that refuses
    runner._me, runner._spellings = None, None
    assert runner.myself() == ""
    assert "403" in runner._identity_error
    assert runner.spellings() == conversation.names("", "")
    runner.client = _BoardClient([])  # type: ignore[assignment]  # a fake: a board that answers
    assert runner.myself() == "", "asked once per run, not again"


# -- one ticket, by name -------------------------------------------------------


@case
def a_requested_ticket_is_found_from_its_console_link() -> None:
    page = _page("abc123")
    runner = _board_runner([page], STATUS)
    found = runner.requested("https://board.invalid/team/Retirer-le-shader-abc123?pvs=4 ")
    assert [ticket.id for ticket in found] == ["abc123"]
    assert [ticket.id for ticket in runner.requested("abc-123")] == ["abc123"]


@case
def a_requested_ticket_is_run_from_cancelled_only_on_a_board_without_that_option() -> None:
    page = _page("abc123", "cancelled")
    runner = _board_runner([page], {**STATUS, "cancelled": "cancelled"})
    _client(runner)._options = ["ready", "cancelled"]
    assert runner.requested("abc123") == [], "given up on, not undone by a shell history"
    _client(runner)._options = ["ready"]
    assert [ticket.id for ticket in runner.requested("abc123")] == ["abc123"]


# -- the tidyings at the top of a pass -----------------------------------------


@case
def a_board_that_refuses_the_in_progress_query_sweeps_nothing(state_home: Path) -> None:
    runner = _board_runner([_in_progress("t1", "ponos@laptop")], STATUS)
    runner.client = _Refusing([])  # type: ignore[assignment]  # a fake: a board that refuses
    assert runner.sweep() == 0

    class _Gone(_Refusing):
        def schema(self, database_id: str) -> dict[str, str]:
            raise store.Unreachable("the board: network unreachable")

    runner.client = _Gone([])  # type: ignore[assignment]  # a fake: a board out of reach
    try:
        runner.sweep()
    except store.Unreachable:
        pass
    else:
        raise AssertionError("an unreachable board stops the pass, it is not a refusal")


@case
def a_ticket_claimed_by_this_pass_or_just_edited_is_not_swept(state_home: Path) -> None:
    fresh = _in_progress("t2", "ponos@laptop")
    fresh.raw["last_edited_time"] = datetime.now().astimezone().isoformat()
    undated = _in_progress("t3", "ponos@laptop")
    undated.raw["last_edited_time"] = "hier"
    runner = _board_runner([_in_progress("t1", "ponos@laptop"), fresh, undated], STATUS)
    _client(runner).columns["Agent"] = "rich_text"
    runner._claimed = {"t1"}
    assert runner.sweep() == 1, "only the one whose edit cannot be read: a day old"
    assert [page_id for page_id, _ in _client(runner).written] == ["t3"]


@case
def a_run_a_dead_runner_left_open_is_closed_and_a_live_one_kept(state_home: Path) -> None:
    try:
        dead = journal.Run.start(ticket="a" * 32)
        dead.event({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}})
        journal.Run.start(ticket="b" * 32)
        stops = state_dir() / "stops"
        stops.mkdir(parents=True, exist_ok=True)
        (stops / f"{'b' * 32}.live").write_text(str(os.getpid()))
        journal.Run.start(ticket="c" * 32)
        (stops / f"{'c' * 32}.live").write_text("999999999")  # its pid is gone
        runner = _board_runner([], STATUS)
        runner.sweep()

        (closed,) = journal.runs("a" * 32)
        assert closed["status"] == "failed" and closed["code"] == "worktree.interrupted"
        (last,) = journal.steps(closed["id"])["steps"]
        assert closed["ended_at"] == last["at"], "ended on its last step"
        (kept,) = journal.runs("b" * 32)
        assert kept["status"] is None and kept["ended_at"] is None, "its session is alive"
        (stepless,) = journal.runs("c" * 32)
        assert stepless["status"] == "failed" and stepless["ended_at"] == stepless["started_at"]
    finally:
        db.close()


@case
def a_board_that_refuses_the_review_query_closes_nothing() -> None:
    runner = _board_runner([_reviewed("r1", "review", "https://github.com/o/r/pull/1")], STATUS)
    runner.client = _Refusing([])  # type: ignore[assignment]  # a fake: a board that refuses
    assert runner.close_merged() == 0

    same = _board_runner([], {**STATUS, "review": "done"})
    same.client = _Refusing([])  # type: ignore[assignment]  # a fake: a board that refuses
    assert same.close_merged() == 0, "nowhere to wait: nothing is even asked"


# -- choosing the next ticket ---------------------------------------------------


def _picked(runner: Runner, queued: list[Ticket], hand: InHand) -> str | None:
    """The id of the ticket `pick` takes, or None when it takes none."""
    ticket = runner.pick(queued, hand)
    return ticket.id if ticket is not None else None


@case
def a_project_at_its_number_lets_the_next_project_go_first() -> None:
    runner = _board_runner([], STATUS)
    runner.config.runner.max_concurrent_per_project = 1
    where = {"a1": "northwind", "a2": "northwind", "a3": "", "a4": "animalink"}
    runner.in_repository = lambda ticket: where[ticket.id]  # type: ignore[method-assign]  # a double: the projects above
    queued = [Ticket(_page(page_id)) for page_id in ("a0", "a1", "a2", "a3", "a4")]
    hand = InHand(settle=60)
    hand.take("a0")

    assert _picked(runner, queued, hand) == "a1"
    assert "a0" not in [ticket.id for ticket in queued], "a ticket in hand leaves the queue"
    assert _picked(runner, queued, hand) == "a3", "a2 waits behind its project's place"
    assert runner._holding["a2"][1] == "project"
    assert _picked(runner, queued, hand) == "a4"
    assert runner.pick(queued, hand) is None and [ticket.id for ticket in queued] == ["a2"]

    hand.leave("a1")
    assert _picked(runner, queued, hand) == "a2"
    assert "a2" not in runner._holding, "taken, it no longer waits for its project"


@case
def a_ticket_works_in_a_repository_only_for_code_in_a_project_that_has_one() -> None:
    runner = _board_runner([], STATUS)
    bare = Ticket(_page("a1"))
    assert runner.in_repository(bare) == "", "no project at all"

    class _Resolver:
        def __init__(self, project: projects.Project | None = None) -> None:
            self.project = project

        def resolve(self, client: Any, page_id: str, *, clone: bool = False) -> projects.Project:
            if self.project is None:
                raise LookupError("moved")
            return self.project

    linked = Ticket(_page("a2", Project={"type": "relation", "relation": [{"id": "p1"}]}))
    runner.resolver = _Resolver()  # type: ignore[assignment]  # a fake: a project moved away
    assert runner._project_of(linked) == projects.Project(name="", path=None)
    assert runner.in_repository(linked) == ""

    runner.resolver = _Resolver(projects.Project(name="northwind", path=Path("/r/northwind")))  # type: ignore[assignment]  # a fake: one project
    assert runner.in_repository(linked) == "northwind"
    written = Ticket(
        _page(
            "a3",
            Project={"type": "relation", "relation": [{"id": "p1"}]},
            Type=_select("Rédaction"),
        )
    )
    assert runner.in_repository(written) == "", "a text touches no file of the repository"


@case
def why_a_ready_ticket_waits_is_written_once_until_it_changes(state_home: Path) -> None:
    runner = _board_runner([], STATUS)
    said: list[str] = []
    runner.say = said.append  # type: ignore[method-assign, assignment]  # a double: what it says is kept
    first, second = Ticket(_page("a1")), Ticket(_page("a2"))

    runner.explain([first], 2)
    assert said == ["  … a1 — waiting: all 2 place(s) taken — it starts at the next free one"]
    assert state.held() == {"a1": ("places", "2")}

    runner.explain([first], 2)
    assert len(said) == 1, "the same reason is not written at every look"

    runner.explain([first, second], 2, limited=True)
    assert said[1:] == [
        "  … a1 — waiting: --limit reached for this run",
        "  … a2 — waiting: --limit reached for this run",
    ]
    assert state.held() == {"a1": ("limit", ""), "a2": ("limit", "")}

    runner.explain([], 2, done=True)
    assert state.held() == {}, "the pass ending holds nothing any more"


@case
def a_dry_run_explains_without_writing_down_the_reasons(state_home: Path) -> None:
    runner = _board_runner([], STATUS)
    runner.dry_run = True
    runner.explain([Ticket(_ready("a1"))], 1)
    assert state.held() == {}
    assert runner._explained == {"a1": "places"}
