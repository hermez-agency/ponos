"""`recurrence.py`: the tickets that come back on their own."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from support import (
    _Board,
    _FakeClient,
    _recurring,
    _schedule_page,
    _ScheduleClient,
    _settings,
    case,
)

from ponos import notion, projects, provision, schedules, state, workspace
from ponos import ticket as ticket_module
from ponos.runner import Runner

# -- what comes back on its own ----------------------------------------------


def _after(text: str) -> datetime:
    """A naive local moment to compute the next occurrence from."""
    return datetime.fromisoformat(text)


@case
def each_cadence_lands_on_the_first_moment_after_now() -> None:
    """The four cadences, read against a Wednesday afternoon."""
    now = _after("2026-09-09T14:20:00")  # a Wednesday

    hourly = schedules.next_occurrence("Hourly", "09:35", after=now)
    assert hourly == _after("2026-09-09T14:35:00")
    # An empty hour means the top of the hour, not nine in the morning.
    assert schedules.next_occurrence("Hourly", "", after=now) == _after("2026-09-09T15:00:00")

    daily = schedules.next_occurrence("Daily", "09:00", after=now)
    assert daily == _after("2026-09-10T09:00:00"), "the hour is behind us: tomorrow"
    assert schedules.next_occurrence("Daily", "18:30", after=now) == _after("2026-09-09T18:30:00")

    weekly = schedules.next_occurrence("Weekly", "09:00", "Monday", after=now)
    assert weekly == _after("2026-09-14T09:00:00")
    # No day named: the weekday the schedule is read on, a week from now since
    # this Wednesday's nine o'clock has already gone.
    assert schedules.next_occurrence("Weekly", "09:00", after=now) == _after("2026-09-16T09:00:00")

    monthly = schedules.next_occurrence("Monthly", "08:00", "1", after=now)
    assert monthly == _after("2026-10-01T08:00:00")


@case
def a_monthly_schedule_on_the_31st_lands_on_the_last_day_february_has() -> None:
    """Seven months have a 31st. A schedule set on it does not skip the others."""
    from_january = schedules.next_occurrence(
        "Monthly", "07:00", "31", after=_after("2026-01-31T09:00:00")
    )
    assert from_january == _after("2026-02-28T07:00:00")
    leap = schedules.next_occurrence("Monthly", "07:00", "31", after=_after("2028-01-31T09:00:00"))
    assert leap == _after("2028-02-29T07:00:00")


@case
def an_occurrence_is_always_strictly_after_the_moment_it_is_computed_from() -> None:
    """Landing *on* `after` would have a pass fire the same occurrence twice."""
    exactly = _after("2026-09-09T09:00:00")
    assert schedules.next_occurrence("Daily", "09:00", after=exactly) == _after(
        "2026-09-10T09:00:00"
    )
    assert schedules.next_occurrence("Hourly", "00", after=exactly) == _after("2026-09-09T10:00:00")


@case
def a_schedule_nobody_can_read_is_none_rather_than_an_exception() -> None:
    now = _after("2026-09-09T14:20:00")
    assert schedules.next_occurrence("Fortnightly", "09:00", after=now) is None
    assert schedules.next_occurrence("", "09:00", after=now) is None
    assert schedules.next_occurrence("Daily", "bientôt", after=now) is None
    assert schedules.next_occurrence("Daily", "31:00", after=now) is None
    assert schedules.next_occurrence("Weekly", "09:00", "Lunedì", after=now) is None
    assert schedules.next_occurrence("Monthly", "09:00", "quarante", after=now) is None
    # And an aware moment comes back aware, in this machine's timezone: the same
    # reading `scheduled_for` gives a date written on a ticket.
    aware = schedules.next_occurrence("Daily", "09:00", after=now.astimezone())
    assert aware is not None and aware.tzinfo is not None


def _ticket_page(page_id: str, status: str) -> notion.Page:
    return notion.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"Status": {"type": "status", "status": {"name": status}}},
    )


def _schedules(runner: Runner) -> _ScheduleClient:
    """The fake `_recurring` gave the runner, to read what was written on it."""
    return cast(_ScheduleClient, runner.client)


def _written(runner: Runner, name: str) -> object:
    """The last value written into one column of the schedule, or None."""
    for _, values in reversed(_schedules(runner).written):
        if name in values:
            return values[name]
    return None


@case
def a_machine_that_was_off_for_three_days_produces_one_ticket_and_not_twelve() -> None:
    """Anacron, not cron: waking up must not set off an avalanche of sessions."""
    stale = (datetime.now().astimezone() - timedelta(days=3)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    born = runner.recur()

    assert len(born) == 1 and born[0]["status"] == "scheduled"
    assert born[0]["from"] == "Revue des dépendances"
    assert len(_schedules(runner).created) == 1, "one ticket, not one per day missed"
    title_, values = _schedules(runner).created[0]
    assert title_.startswith("Revue des dépendances — ")
    assert values["Status"] == "Ready"
    assert values["Project"] == "p-northwind" and values["Priority"] == 40

    # The next moment is computed from now, never by stacking up what was lost.
    ahead = schedules.scheduled_for(_written(runner, "Next"))
    assert ahead is not None and ahead > datetime.now().astimezone()
    # A daily schedule is a wall-clock hour: across a change of clocks, tomorrow's
    # 09:00 is 23 or 25 hours away, so the day is measured on the wall, not in UTC.
    now = datetime.now().astimezone()
    assert ahead.astimezone().replace(tzinfo=None) - now.replace(tzinfo=None) < timedelta(days=1), (
        "the next one, not the fourth"
    )


@case
def a_code_schedule_makes_a_code_ticket_that_nobody_classifies() -> None:
    """A long, well-written brief read as « Rédaction » by the classifier sent
    four Whisper Desk tickets to done with their pull requests lost: the
    schedule says what its tickets are, and the ticket is born with it."""
    stale = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    runner = _recurring(
        [_schedule_page("s-1", next=stale, type="Code", subtype="Feature", model="opus")]
    )
    assert len(runner.recur()) == 1
    _, values = _schedules(runner).created[0]
    assert values["Type"] == "Code" and values["Sous-type"] == "Feature"
    assert values["Model"] == "opus" and values["Priority"] == 40

    # Born typed, it is never handed to the classifier.
    born = notion.Page(
        id="t-1",
        url="",
        title="Revue — 2026-10-16",
        properties={
            "Type": {"type": "select", "select": {"name": values["Type"]}},
            "Sous-type": {"type": "select", "select": {"name": values["Sous-type"]}},
        },
    )
    runner.client.schema = lambda database_id: {  # type: ignore[method-assign]  # a double: a typed board
        "Status": "status",
        "Type": "select",
        "Sous-type": "select",
    }

    def classified(*_: Any) -> Any:
        raise AssertionError("a typed ticket is not classified")

    runner._classify = classified  # type: ignore[method-assign, assignment]  # a double: never to be called
    runner._ask_subtype = classified  # type: ignore[method-assign, assignment]  # the same
    assert runner._kind(ticket_module.Ticket(born), "", projects.Project(name="", path=None)) == (
        "code",
        "",
    )
    assert runner._subtype(ticket_module.Ticket(born), "") == ("feature", "")


@case
def a_schedule_without_a_type_leaves_its_ticket_to_be_classified() -> None:
    stale = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    runner.recur()
    _, values = _schedules(runner).created[0]
    assert "Type" not in values and "Sous-type" not in values


@case
def a_schedules_database_without_a_type_column_makes_its_repository_tickets_code() -> None:
    """“Whisper Desk — rattraper Wispr Flow” was born « Rédaction » twice: its
    schedules database had no Type to say Code, and the classifier read its brief.
    Until the column is there, a project with a repository is enough to say it."""
    stale = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    project = notion.Page(
        id="p-northwind",
        url="",
        title="Northwind",
        properties={
            "Repository": {
                "type": "url",
                "url": "https://github.com/hermez-agency/northwind",
            }
        },
    )
    runner = _recurring([_schedule_page("s-1", next=stale)], tickets={"p-northwind": project})
    runner.recur()
    _, values = _schedules(runner).created[0]
    assert values["Type"] == "Code", values
    assert "Sous-type" not in values, "the sub-type is still the ticket's own to find"

    # A project without one is a document: left to the classifier, as before.
    paper = notion.Page(id="p-northwind", url="", title="Northwind", properties={})
    runner = _recurring([_schedule_page("s-1", next=stale)], tickets={"p-northwind": paper})
    runner.recur()
    assert "Type" not in _schedules(runner).created[0][1]

    # And a database that has the column says what it says, even nothing.
    runner = _recurring(
        [_schedule_page("s-1", next=stale)],
        tickets={"p-northwind": project},
        columns={"Type": "select", "Sous-type": "select"},
    )
    runner.recur()
    assert "Type" not in _schedules(runner).created[0][1], "an empty Type is a choice: guessed"


@case
def launching_a_schedule_by_hand_makes_the_ticket_and_leaves_its_next_moment_alone() -> None:
    """Even paused: that is how one is tried. `Last` moves, `Next` does not."""
    later = (datetime.now().astimezone() + timedelta(days=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=later, active=False)])
    recorded: list[dict[str, Any]] = []
    original = state.record
    state.record = recorded.append  # type: ignore[assignment]  # a double: what was recorded is kept
    try:
        entry = runner.launch("s-1")
    finally:
        state.record = original

    assert len(_schedules(runner).created) == 1 and entry["id"] == "t1"
    assert _schedules(runner).created[0][1]["Status"] == "Ready"
    assert _written(runner, "Last") is not None
    assert _written(runner, "Next") is None, "the planned occurrence is untouched"
    assert _written(runner, "Active") is None, "a paused schedule stays paused"
    assert recorded and recorded[0]["status"] == "scheduled"


@case
def a_launch_that_fails_is_raised_and_leaves_last_alone() -> None:
    runner = _recurring([_schedule_page("s-1")], refuses="400 body failed validation")
    try:
        runner.launch("s-1")
    except notion.NotionError:
        pass
    else:
        raise AssertionError("the failure has to reach whoever asked")
    assert _written(runner, "Last") is None


@case
def the_body_of_the_schedule_is_copied_into_the_ticket_it_makes() -> None:
    """The ticket has to read on its own, and say where it came from."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    runner.recur()

    page_id, body = _schedules(runner).appended[0]
    assert page_id == "t-1"
    assert "Revue des dépendances" in body and "https://notion.so/s-1" in body
    assert "Lister les dépendances en retard" in body
    # And the schedule is told what it produced, which is how the next pass
    # knows whether this occurrence is over.
    assert _written(runner, "Last ticket") == "t-1"


@case
def an_occurrence_still_open_never_produces_a_second_one() -> None:
    """A schedule stuck on a question must not fill the board with copies."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    for status in ("Ready", "In progress", "In review", "Blocked"):
        runner = _recurring(
            [_schedule_page("s-1", next=stale, last_ticket="t-old")],
            tickets={"t-old": _ticket_page("t-old", status)},
        )
        assert runner.recur() == [], status
        assert _schedules(runner).created == [], status
        # Next moves on regardless, or the schedule would keep re-firing.
        ahead = schedules.scheduled_for(_written(runner, "Next"))
        assert ahead is not None and ahead > datetime.now().astimezone(), status

    for status in ("Done", "Failed"):
        runner = _recurring(
            [_schedule_page("s-1", next=stale, last_ticket="t-old")],
            tickets={"t-old": _ticket_page("t-old", status)},
        )
        assert len(runner.recur()) == 1, status


@case
def a_last_ticket_that_no_longer_exists_never_wedges_its_schedule() -> None:
    """A page somebody deleted would otherwise stop it being born for good."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale, last_ticket="t-gone")])
    assert len(runner.recur()) == 1


@case
def a_schedule_written_this_minute_does_not_fire_this_minute() -> None:
    """“Weekly / Monday” written on a Tuesday must not produce a ticket now."""
    runner = _recurring([_schedule_page("s-1", cadence="Weekly", day="Monday", next="")])
    assert runner.recur() == []
    assert _schedules(runner).created == []
    ahead = schedules.scheduled_for(_written(runner, "Next"))
    assert ahead is not None and ahead > datetime.now().astimezone()
    assert _written(runner, "Last") is None, "nothing happened, so nothing was the last"


@case
def a_schedule_in_the_future_and_one_that_is_off_both_cost_nothing() -> None:
    later = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()

    ahead = _recurring([_schedule_page("s-1", next=later)])
    assert ahead.recur() == [] and _schedules(ahead).written == []

    unticked = _recurring([_schedule_page("s-1", next=stale, active=False)])
    assert unticked.recur() == [] and _schedules(unticked).written == []

    # One line turns every schedule off, without unticking a single row — and
    # without the database being read at all.
    off = _recurring([_schedule_page("s-1", next=stale)], schedule=False)
    assert off.recur() == [] and _schedules(off).written == []

    # A schedule nobody can read holds nobody up.
    broken = _recurring(
        [
            _schedule_page("s-broken", cadence="Fortnightly", next=stale),
            _schedule_page("s-fine", next=stale),
        ]
    )
    assert len(broken.recur()) == 1
    assert _schedules(broken).created[0][0].startswith("Revue")


@case
def a_dry_run_says_what_would_be_born_and_writes_nowhere() -> None:
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], dry_run=True)
    born = runner.recur()
    assert len(born) == 1 and born[0]["status"] == "dry-run"
    assert _schedules(runner).created == [] and _schedules(runner).written == []


@case
def the_occurrence_is_taken_before_it_is_made() -> None:
    """A crash between the two loses one occurrence; the other order makes two.

    So a ticket Notion refuses still leaves `Next` moved on: one lost report
    beats two identical tickets and the session each of them costs.
    """
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], refuses="400 body failed validation")
    assert runner.recur() == []
    ahead = schedules.scheduled_for(_written(runner, "Next"))
    assert ahead is not None and ahead > datetime.now().astimezone()
    assert _written(runner, "Last ticket") is None, "nothing was made to point at"


@case
def an_occurrence_that_could_not_be_taken_makes_no_ticket() -> None:
    """`Next` left in the past by a refused write would fire on every pass.

    Notion answering 500 to the write on the schedule's row, the ticket would
    still be made, and the next pass would read the same `Next` and make it
    again: two passes, two tickets for one occurrence.
    """
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], marks="500 internal server error")
    assert runner.recur() == [] and runner.recur() == []
    assert _schedules(runner).created == [], "not taken, not made"


@case
def a_next_column_nobody_can_write_takes_no_occurrence() -> None:
    """A formula is read, never written: Notion would drop the value silently."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], columns={"Next": "formula"})
    assert runner.recur() == [] and runner.recur() == []
    assert _schedules(runner).created == [] and _schedules(runner).written == []


@case
def a_workspace_with_nothing_that_repeats_is_a_workspace_that_runs() -> None:
    """The whole feature is optional: no row, no warning, no difference."""
    client = _FakeClient(
        {"Tickets": "p-tickets", "Context": "p-context", "Objectifs": "p-goals"}, text="x"
    )
    space = workspace.from_notion(client, _settings())  # type: ignore[arg-type]  # a fake: a workspace in memory
    assert space.schedules == ""
    assert not space.warnings

    present = _FakeClient(
        {"Tickets": "p-tickets", "Context": "p-context", "Schedules": "p-schedules"}, text="x"
    )
    assert workspace.from_notion(present, _settings()).schedules  # type: ignore[arg-type]  # the same == "db-of-p-schedules"

    # And a Runner reading a workspace without one asks Notion nothing at all.
    runner = _recurring([])
    runner._workspace = workspace.Workspace(tickets="db-tickets")
    assert runner.recur() == [] and runner.schedules() == []


@case
def the_schedules_database_is_built_after_the_tickets_it_points_at() -> None:
    """A relation cannot name a database that does not exist yet."""
    board = _Board()
    provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake: a board in memory

    schema = board._schemas["db-schedules"]
    for expected in (
        "Cadence",
        "At",
        "Day",
        "Active",
        "Next",
        "Last",
        "Last ticket",
        "Type",
        "Sous-type",
    ):
        assert expected in schema, expected
    # The same options as the tickets', so a value copied across is one they offer.
    tickets = board._schemas["db-tickets"]
    for column in ("Type", "Sous-type"):
        assert schema[column] == tickets[column], column
    assert schema["Last ticket"]["relation"]["database_id"] == "db-tickets"
    assert schema["Project"]["relation"]["database_id"] == "db-projects"
    assert board.created.index("db-tickets") < board.created.index("db-schedules")

    cadences = [option["name"] for option in schema["Cadence"]["select"]["options"]]
    assert cadences == list(schedules.CADENCES)

    # The example schedule is left unticked: an init must start nothing.
    example = board._rows["db-schedules"]
    assert len(example) == 1
    row = provision.schedules_schema(_settings(), "db-tickets", "db-projects")
    assert len(row) == 13, "twelve columns beside the title"


@case
def init_run_again_on_a_board_that_already_schedules_touches_nothing() -> None:
    board = _Board()
    provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake: a board in memory
    before = dict(board._schemas["db-schedules"])
    board.created.clear()

    second = provision.provision(board, _settings(), "root")  # type: ignore[arg-type]  # a fake: a board in memory
    assert board.created == [], "no second schedules database, no second example"
    assert board._schemas["db-schedules"] == before
    assert any("Schedules" in what for verb, what in second.steps if verb == "kept")
    assert all(verb == "kept" for verb, _ in second.steps), second.steps


@case
def every_occurrence_is_kept_with_the_ticket_it_made_or_why_it_made_none(state_home: Path) -> None:
    """The schedule's row keeps only its last ticket: `ponos.db` keeps them all,
    and the passes that made none, for the schedule's page in the console."""
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)])
    runner.recur()
    runner.launch("s-1")
    kept = state.occurrences("s-1")
    assert [row["outcome"] for row in kept] == ["launched", "born"], "the latest first"
    assert all(row["ticket"] and row["title"].startswith("Revue") for row in kept)

    busy = _recurring(
        [_schedule_page("s-2", next=stale, last_ticket="t-old")],
        tickets={"t-old": _ticket_page("t-old", "In review")},
    )
    busy.recur()
    (skipped,) = state.occurrences("s-2")
    assert skipped["outcome"] == "skipped" and skipped["ticket"] == ""
    assert "told" in skipped["reason"], "the ticket still open, by its id"

    refused = _recurring([_schedule_page("s-3", next=stale)], refuses="400 body failed validation")
    refused.recur()
    (failed,) = state.occurrences("s-3")
    assert failed["outcome"] == "failed" and "400" in failed["reason"]


@case
def a_dry_run_keeps_no_occurrence(state_home: Path) -> None:
    stale = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
    runner = _recurring([_schedule_page("s-1", next=stale)], dry_run=True)
    runner.recur()
    assert state.occurrences("s-1") == []
