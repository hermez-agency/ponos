"""`later.py`: a moment as somebody types it, and the dates a ticket may not carry."""

from __future__ import annotations

from datetime import datetime, timedelta

from support import case

from ponos import later

# A Friday, at ten past four in the afternoon, here.
NOW = datetime(2026, 11, 20, 16, 10).astimezone()


def _at(text: str) -> datetime | None:
    return later.parse(text, NOW)


@case
def an_iso_moment_is_read_as_written_and_a_bare_one_as_an_hour_of_this_machine() -> None:
    with_offset = _at("2026-11-21T09:00+01:00")
    assert with_offset is not None and with_offset.isoformat() == "2026-11-21T09:00:00+01:00"
    typed = _at("2026-11-21 09:00")
    assert typed == datetime(2026, 11, 21, 9, 0).astimezone()


@case
def an_offset_counts_from_now() -> None:
    assert _at("+2h") == NOW + timedelta(hours=2)
    assert _at("+30m") == NOW + timedelta(minutes=30)
    assert _at("+2d") == NOW + timedelta(days=2)
    assert _at("+3j") == NOW + timedelta(days=3), "in French too"
    assert _at("+1w") == NOW + timedelta(weeks=1)


@case
def a_day_said_in_words_is_that_day_in_the_morning_or_at_the_hour_given() -> None:
    assert _at("demain") == datetime(2026, 11, 21, 9, 0).astimezone()
    assert _at("demain 14h30") == datetime(2026, 11, 21, 14, 30).astimezone()
    assert _at("Tomorrow at 7:05") == datetime(2026, 11, 21, 7, 5).astimezone()
    assert _at("après-demain 18h") == datetime(2026, 11, 22, 18, 0).astimezone()
    # The next one, never today: a Friday's "vendredi" is a week away.
    assert _at("lundi 9h") == datetime(2026, 11, 23, 9, 0).astimezone()
    assert _at("next monday") == datetime(2026, 11, 23, 9, 0).astimezone()
    assert _at("vendredi") == datetime(2026, 11, 27, 9, 0).astimezone()


@case
def an_hour_alone_is_today_until_it_has_passed() -> None:
    assert _at("18h") == datetime(2026, 11, 20, 18, 0).astimezone()
    assert _at("9h") == datetime(2026, 11, 21, 9, 0).astimezone(), "9 this morning has passed"


@case
def what_names_no_moment_is_none() -> None:
    for said in ("", "bientôt", "demain soir tard", "25h", "+2y", "lundi 9h99"):
        assert _at(said) is None, said


@case
def a_ticket_carries_a_moment_to_come_and_nothing_else() -> None:
    assert later.written("", NOW) == "", "empty removes the date"
    assert later.written("+2h", NOW) == (NOW + timedelta(hours=2)).isoformat(timespec="minutes")
    for wrong, said in (("bientôt", "unreadable"), ("2026-11-20 09:00", "already passed")):
        try:
            later.written(wrong, NOW)
        except ValueError as error:
            assert said in str(error), error
        else:
            raise AssertionError(f"{wrong!r} must be refused")
