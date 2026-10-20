"""`worktime.py`: the time a ticket really worked."""

from __future__ import annotations

from datetime import datetime

from support import case

from ponos import journal, worktime

# -- why a ticket stopped -----------------------------------------------------


def _span(
    start: str, end: str | None, status: str | None = "done", code: str = "", last: str = ""
) -> dict:
    day = "2026-10-14T"
    return {
        "start": day + start + "+00:00",
        "end": day + end + "+00:00" if end else None,
        "status": status,
        "code": code,
        "last": day + (last or end or start) + "+00:00",
    }


def _at(clock: str) -> datetime:
    return datetime.fromisoformat("2026-10-14T" + clock + "+00:00")


@case
def a_ticket_that_works_waits_for_an_answer_and_works_again_counts_only_the_work():
    """10 min, 30 min waiting on a question, 5 min more: the clock reads 15."""
    spans = [
        _span("10:00:00", "10:10:00", "blocked", "session.question"),
        _span("10:40:00", "10:45:00", "done"),
    ]
    one = worktime.measure(spans, "review", _at("12:00:00"))
    assert one == {"work": 900, "paused": 1800, "sessions": 2, "running": False, "pause": ""}, one


@case
def the_clock_runs_on_a_live_run_and_stops_on_a_blocked_one():
    live = [_span("10:00:00", None, None, last="10:04:30")]
    going = worktime.measure(live, "progress", _at("10:05:00"))
    assert going and going["running"] and going["work"] == 300 and going["pause"] == "", going
    # The same run, once the ticket is blocked on a question: the clock stops where it ended.
    stopped = [_span("10:00:00", "10:05:00", "blocked", "session.question")]
    waiting = worktime.measure(stopped, "blocked", _at("10:35:00"))
    assert waiting and not waiting["running"] and waiting["work"] == 300, waiting
    assert waiting["pause"] == "question" and waiting["paused"] == 1800, waiting
    assert worktime.measure(stopped, "blocked", _at("10:36:00"))["work"] == 300  # type: ignore[index]


@case
def review_and_the_wait_in_ready_are_nobodys_pause_and_credit_is_one():
    reviewed = worktime.measure([_span("10:00:00", "10:20:00", "done")], "review", _at("18:00:00"))
    assert (
        reviewed
        and reviewed["work"] == 1200
        and reviewed["paused"] == 0
        and reviewed["pause"] == ""
    ), reviewed
    # A correction after review: the days in review are not counted either.
    again = worktime.measure(
        [_span("10:00:00", "10:20:00", "done"), _span("15:00:00", "15:10:00", "done")],
        "review",
        _at("18:00:00"),
    )
    assert again and again["work"] == 1800 and again["paused"] == 0, again
    credit = worktime.measure([_span("10:00:00", "10:20:00", "waiting")], "ready", _at("11:20:00"))
    assert credit and credit["pause"] == "credit" and credit["paused"] == 3600, credit
    failed = worktime.measure(
        [_span("10:00:00", "10:20:00", "failed", "runner.crashed")], "failed", _at("10:30:00")
    )
    assert failed and failed["pause"] == "blocked", failed


@case
def a_run_the_runner_never_closed_stops_at_its_last_step_and_an_overlap_counts_once():
    killed = worktime.measure(
        [_span("10:00:00", None, None, last="10:07:00")], "ready", _at("20:00:00")
    )
    assert killed and killed["work"] == 420 and not killed["running"], killed
    # Still "progress" but silent for hours: the runner is gone, the clock is not running.
    silent = worktime.measure(
        [_span("10:00:00", None, None, last="10:07:00")], "progress", _at("20:00:00")
    )
    assert silent and silent["work"] == 420 and not silent["running"], silent
    overlap = worktime.measure(
        [_span("10:00:00", "10:10:00"), _span("10:05:00", "10:20:00")], "review", _at("11:00:00")
    )
    assert overlap and overlap["work"] == 1200, overlap
    assert worktime.measure([], "review", _at("11:00:00")) is None


@case
def the_time_of_a_ticket_survives_a_restart_because_it_is_read_from_the_journal(state_home):
    ticket = "a" * 32
    first = journal.Run.start(ticket=ticket)
    first.end("blocked", "", "session.question")
    second = journal.Run.start(ticket=ticket)
    second.end("done")
    found = journal.spans(ticket)[ticket]
    assert [span["status"] for span in found] == ["blocked", "done"], found
    assert journal.spans("b" * 32) == {}
    one = worktime.measure(found, "review")
    assert one and one["sessions"] == 2, one
