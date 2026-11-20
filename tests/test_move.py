"""`ponos move` and `ponos comment`: what an « On » session uses instead of the console's login."""

from __future__ import annotations

import argparse
import contextlib
import io
from collections.abc import Iterator
from pathlib import Path

from support import _config, case

from ponos import __main__ as cli
from ponos import tickets


@contextlib.contextmanager
def _installed() -> Iterator[None]:
    """The CLI reading a configuration of the case's own, on the case's ponos.db."""
    config = _config()
    was = cli.load_config
    cli.load_config = lambda: config
    try:
        yield
    finally:
        cli.load_config = was


def _run(function: object, **values: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = function(argparse.Namespace(**values))  # type: ignore[operator]
    return code, out.getvalue(), err.getvalue()


def _status(ticket: str) -> str:
    return next(record.status for record in tickets.listing() if record.id == ticket)


@case
def ponos_move_changes_the_status_of_a_ticket_by_its_short_id(state_home: Path) -> None:
    made = tickets.create("Suivant", status="draft")
    with _installed():
        code, out, err = _run(cli.command_move, ticket=made.id[-8:], status="ready", source=None)
    assert (code, err) == (0, ""), (code, out, err)
    assert "Suivant" in out and "ready" in out
    assert _status(made.id) == "ready"


@case
def ponos_move_with_from_refuses_when_the_ticket_is_no_longer_there(state_home: Path) -> None:
    made = tickets.create("Suivant", status="paused")
    with _installed():
        code, _, err = _run(cli.command_move, ticket=made.id, status="ready", source="draft")
        assert code == 1 and "refused" in err and "not “draft”" in err
        assert _status(made.id) == "paused"
        code, _, _ = _run(cli.command_move, ticket=made.id, status="ready", source="paused")
    assert code == 0 and _status(made.id) == "ready"


@case
def ponos_move_refuses_an_unknown_status_and_an_unknown_ticket(state_home: Path) -> None:
    made = tickets.create("Suivant", status="draft")
    with _installed():
        code, _, err = _run(cli.command_move, ticket=made.id, status="enfer", source=None)
        assert code == 2 and "unknown status “enfer”" in err and "ready" in err
        code, _, err = _run(cli.command_move, ticket="ffffffff", status="ready", source=None)
        assert code == 1 and "No ticket for ffffffff" in err
    assert _status(made.id) == "draft"


@case
def ponos_move_takes_the_word_the_board_writes_and_any_case(state_home: Path) -> None:
    made = tickets.create("Suivant", status="ready")
    with _installed():
        code, _, err = _run(cli.command_move, ticket=made.id, status="Paused", source="READY")
    assert (code, err) == (0, "") and _status(made.id) == "paused"


@case
def ponos_comment_writes_on_the_ticket_like_a_reply_from_the_console(state_home: Path) -> None:

    made = tickets.create("Suivant", status="ready")
    with _installed():
        code, out, err = _run(cli.command_comment, ticket=made.id[-8:], text=["Vu,", "merci"])
        assert (code, err) == (0, ""), (code, out, err)
        code, _, err = _run(cli.command_comment, ticket=made.id, text=["  "])
    assert code == 1 and "nothing to say" in err
    from ponos.runner import Runner

    said = [comment.text for comment in Runner(_config(), quiet=True).client.comments(made.id)]
    assert any("Vu, merci" in text for text in said), said


@case
def the_on_prompt_names_ponos_move_and_forbids_the_internals() -> None:
    from ponos import prompt

    text = prompt.ON_STATUS
    assert "ponos move <ticket> <status> [--from <status>]" in text
    assert 'ponos comment <ticket> "text"' in text
    assert "Never import Ponos's own code" in text and "ponos.db" in text


@case
def ponos_schedule_dates_a_ticket_and_now_takes_the_date_away(state_home: Path) -> None:
    made = tickets.create("Plus tard", status="draft")
    with _installed():
        code, out, err = _run(cli.command_schedule, ticket=made.id[-8:], when=["+2d"])
        assert (code, err) == (0, ""), (code, out, err)
        assert "scheduled for" in out
        record = tickets.get(made.id)
        assert record is not None and record.scheduled and record.status == "draft"
        code, _, err = _run(cli.command_schedule, ticket=made.id, when=["2020-01-01", "09:00"])
        assert code == 1 and "already passed" in err
        code, out, _ = _run(cli.command_schedule, ticket=made.id, when=["now"])
    assert code == 0 and "no date" in out
    record = tickets.get(made.id)
    assert record is not None and not record.scheduled


@case
def ponos_move_at_makes_a_ticket_ready_for_later(state_home: Path) -> None:
    made = tickets.create("Demain matin", status="draft")
    with _installed():
        code, out, err = _run(
            cli.command_move, ticket=made.id, status="ready", source=None, at="demain 9h"
        )
        assert (code, err) == (0, ""), (code, out, err)
        assert "scheduled for" in out
        record = tickets.get(made.id)
        assert record is not None and record.status == "ready" and "T09:00" in record.scheduled
        code, _, err = _run(
            cli.command_move, ticket=made.id, status="paused", source=None, at="hier"
        )
    assert code == 1 and "unreadable" in err
    assert _status(made.id) == "ready", "a date refused moves nothing"
