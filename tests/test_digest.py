"""`digest.py`: the period's figures, sent once, without a session."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from support import _config, case

from ponos import channels, digest, notion, state
from ponos.config import Notify
from ponos.projects import Project
from ponos.runner import Runner
from ponos.ticket import Ticket
from ponos.voice import Voice

WEEKLY = '[notify]\ndigest = "weekly"\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'


def _local(day: int, hour: int = 9, minute: int = 0) -> datetime:
    """A moment of late October or early November 2026, on this machine's clock.

    The 26th is a Monday, and so is 2 November.
    """
    return datetime(2026, 10 if day > 20 else 11, day, hour, minute).astimezone()


def _line(moment: datetime, **values: Any) -> dict[str, Any]:
    entry = {"at": moment.astimezone(UTC).isoformat(timespec="seconds"), **values}
    state.record(entry)
    return entry


def _period(settings: Notify, now: datetime) -> tuple[datetime, datetime]:
    """`digest.period`, for a moment that has one."""
    period = digest.period(settings, now)
    assert period is not None
    return period


def _history() -> None:
    """A week of Ponos and Leadz, 26 October to 2 November."""
    _line(
        _local(27),
        id="a1",
        status="done",
        project="Ponos",
        pull_request="https://github.com/o/r/pull/1",
        merged="https://github.com/o/r/pull/1",
        cost_usd=2.5,
    )
    _line(_local(28), id="b2", status="done", project="Ponos", pull_request="u2", cost_usd=1.5)
    _line(_local(29), id="c3", status="done", project="Leadz", pull_request="u3", cost_usd=4.0)
    _line(_local(30), id="d4", status="blocked", project="Leadz", code="access.credentials")
    # Before the week, and after it: not counted.
    _line(_local(25), id="e5", status="done", project="Ponos", pull_request="u5", cost_usd=9.0)
    _line(_local(2, 10), id="f6", status="done", project="Ponos", pull_request="u6", cost_usd=7.0)


@case
def the_digest_is_off_unless_asked(state_home: Path) -> None:
    assert digest.period(_config("").notify, _local(2, 12)) is None
    assert _config('[notify]\ndigest = "monthly"\n').notify.digest == "off", "a typo asks nothing"
    settings = _config(
        '[notify]\ndigest = "weekly"\ndigest_day = "friday"\ndigest_hour = 18\n'
    ).notify
    assert (settings.digest, settings.digest_day, settings.digest_hour) == ("weekly", "friday", 18)


@case
def a_weekly_period_ends_on_the_last_monday_at_nine(state_home: Path) -> None:
    settings = _config(WEEKLY).notify
    start, end = _period(settings, _local(2, 9, 30))
    assert end == _local(2) and start == _local(26) and (end - start).days == 7
    # Before the hour, the period is the one before.
    _, earlier = _period(settings, _local(2, 8))
    assert earlier == end - timedelta(days=7)
    # Midweek, still Monday's.
    assert _period(settings, _local(4, 15))[1] == end
    # Daily: yesterday's hour to today's.
    daily = _config('[notify]\ndigest = "daily"\n').notify
    start, end = _period(daily, _local(4, 10))
    assert end == _local(4) and start == _local(3)


@case
def a_period_is_sent_late_but_not_stale(state_home: Path) -> None:
    settings = _config(WEEKLY).notify
    assert digest.due(settings, _local(2, 9, 40)), "a laptop woken at 9:40 still sends"
    assert digest.due(settings, _local(2, 20)), "and so does the evening"
    assert digest.due(settings, _local(4, 10)) is None, "a digest enabled on Wednesday waits"


@case
def the_figures_of_a_week_are_counted_by_ticket(state_home: Path) -> None:
    _history()
    start, end = _local(26), _local(2)
    figures = digest.count(state.between(start, end))
    assert dict(figures.delivered) == {"Ponos": 2, "Leadz": 1}
    assert figures.cost["Ponos"] == 4.0 and figures.cost["Leadz"] == 4.0
    assert (figures.merged, figures.opened) == (1, 3)
    assert dict(figures.stops) == {"access.credentials": 1}


@case
def the_message_names_the_numbers_and_the_tickets_waiting(state_home: Path) -> None:
    _history()
    start, end = _local(26), _local(2)
    text = digest.compose(
        Voice("en"),
        digest.count(state.between(start, end)),
        [("Ponos", "Le header", "https://notion.so/h")],
        start,
        end,
        True,
    )
    assert "Weekly digest" in text and "26/10 – 2/11" in text
    assert "Delivered: 3" in text and "Ponos 2" in text and "Leadz 1" in text
    assert "Cost: $8.00" in text and "Ponos $4.00" in text
    assert "Merge rate: 33% (1/3 pull requests)" in text
    assert "Stops: 1" in text
    assert "Waiting for a decision (1):" in text
    assert "Ponos — Le header" in text and "https://notion.so/h" in text
    french = digest.compose(Voice("fr"), digest.Figures(), [], start, end, True)
    assert "Bilan de la semaine" in french and "Rien n'a tourné" in french


class _Telegram(channels.Channel):
    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str, *, ticket: str = "", title: str = "", ask: bool = False) -> bool:
        self.sent.append(text)
        return True


class _Board:
    """The two columns that wait for a person, and nothing else."""

    def schema(self, database: str) -> dict[str, str]:
        return {"statut": "status"}

    def query(self, database: str, filter_: dict[str, Any] | None = None) -> list[notion.Page]:
        assert filter_ is not None
        column = filter_["status"]["equals"]
        if column != "review":
            return []
        return [notion.Page(id="p1", url="https://notion.so/p1", title="Le header")]


class _Runner(Runner):
    database = "db"

    def _project_of(self, ticket: Ticket) -> Project:
        return Project(name="Ponos", path=None)


@contextmanager
def _open(live: list[channels.Channel]) -> Iterator[None]:
    original = channels.open
    channels.open = lambda settings: live
    try:
        yield
    finally:
        channels.open = original


def _runner(body: str = WEEKLY) -> _Runner:
    runner = _Runner.__new__(_Runner)
    runner.config = _config(body)
    runner.client = _Board()  # type: ignore[assignment]  # a fake: the waiting columns only
    runner.dry_run = False
    runner.quiet = True
    return runner


@case
def a_period_is_sent_once_however_many_passes_meet_it(state_home: Path) -> None:
    _history()
    stub = _Telegram()
    with _open([stub]):
        runner = _runner()
        assert runner.digest(at=_local(2, 9, 5)) is True
        assert runner.digest(at=_local(2, 9, 15)) is False, "the second pass finds it taken"
        assert _runner().digest(at=_local(2, 9, 20)) is False, "and so does another process"
        assert len(stub.sent) == 1
        assert "Weekly digest" in stub.sent[0] and "Le header" in stub.sent[0]
        assert runner.digest(at=_local(9, 9, 5)) is True, "the next Monday is another period"
        # Asked for by hand, it goes whatever was sent.
        assert runner.digest(now=True) is True and len(stub.sent) == 3


@case
def a_period_no_channel_took_is_tried_again(state_home: Path) -> None:
    refusing = _Telegram()
    refusing.send = lambda text, **_: False  # type: ignore[method-assign]  # a channel that takes nothing
    with _open([refusing]):
        assert _runner().digest(at=_local(2, 9, 5)) is False
    stub = _Telegram()
    with _open([stub]):
        assert _runner().digest(at=_local(2, 9, 10)) is True
        assert len(stub.sent) == 1


@case
def without_a_channel_or_with_the_digest_off_nothing_is_sent(state_home: Path) -> None:
    stub = _Telegram()
    with _open([stub]):
        assert (
            _runner('[notify.telegram]\ntoken = "1:a"\nchat = "4"\n').digest(at=_local(2, 9, 5))
            is False
        )
        assert _runner('[notify]\ndigest = "weekly"\n').digest(at=_local(2, 9, 5)) is False
    assert stub.sent == []
