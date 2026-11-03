"""`web/upkeep.py`: the health the dashboard shows, and how long it is held."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from support import _config, _environment, case
from test_web_server import _console, _talk_to

from ponos.web import api as web_api
from ponos.web import base as web_base
from ponos.web import live, upkeep

AUTH = {"Authorization": "Bearer tok"}


def _counting_gh() -> tuple[str, Path]:
    """A `gh` first on the PATH that notes each call, and the file it notes them in."""
    folder = Path(tempfile.mkdtemp())
    calls = folder / "calls"
    gh = folder / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\necho "Logged in to github.com"\n')
    gh.chmod(0o755)
    return f"{folder}{os.pathsep}{os.environ.get('PATH', '')}", calls


def _asked(calls: Path) -> int:
    lines = calls.read_text().splitlines() if calls.exists() else []
    return sum(line == "auth status" for line in lines)


def _bare_console() -> web_api.Api:
    directory = Path(tempfile.mkdtemp())
    console = web_api.Api.__new__(web_api.Api)
    console._config = _config(f'[storage]\nmode = "markdown"\npath = "{directory}/board"\n')
    console._stamp = web_base._stamp(console._config.path)
    console._runner = None
    console._projects = {}
    console._projects_written = 0
    console.hub = live.Hub()
    return console


@case
def the_health_is_checked_once_for_two_pages_and_again_when_asked_afresh(state_home):
    """`gh auth status` asks GitHub, and the band asks on every tickets page.

    Ten seconds of checks on a busy day: two pages in a row are one check, and
    "Recheck", a fix or a saved setting are the next one.
    """
    path, calls = _counting_gh()
    console = _bare_console()
    with _environment(PATH=path), _console(console) as served:
        status, _, first = _talk_to(served, "GET", "/api/health", **AUTH)
        assert status == 200, first
        assert _asked(calls) == 1, calls.read_text()
        started = time.monotonic()
        status, _, second = _talk_to(served, "GET", "/api/health", **AUTH)
        assert time.monotonic() - started < 0.3, "a held answer is not checked again"
        assert second == first and _asked(calls) == 1, "two pages, one check"

        status, _, fresh = _talk_to(served, "GET", "/api/health?fresh=true", **AUTH)
        assert _asked(calls) == 2, "Recheck asks again"
        assert fresh["checked_at"] > first["checked_at"]

        console.forget()
        console.health()
        assert _asked(calls) == 3, "a saved setting drops what was held"


@case
def an_answer_past_its_time_is_given_at_once_and_checked_again_behind_it(state_home):
    """Eighteen seconds for whoever opened the dashboard after five minutes.

    The answer held is the one given, however old; one check starts behind it,
    however many pages ask meanwhile, and what it finds goes out on the stream.
    """
    folder = Path(tempfile.mkdtemp())
    gate = folder / "gate"
    calls = folder / "calls"
    gh = folder / "gh"
    # Held at the door until the case opens it: the check is still running
    # while the answers below are timed.
    gh.write_text(
        f'#!/bin/sh\necho "$@" >> "{calls}"\n'
        f'while [ ! -e "{gate}" ]; do sleep 0.05; done\necho "Logged in to github.com"\n'
    )
    gh.chmod(0o755)
    gate.touch()
    console = _bare_console()
    channel = console.hub.subscribe()
    with _environment(PATH=f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"):
        first = console.health()
        assert _asked(calls) == 1 and channel.empty(), "nothing held: checked there and then"
        gate.unlink()
        console._health = (time.time() - upkeep.HEALTH_TTL - 1, first)

        started = time.monotonic()
        for _ in range(3):
            assert console.health() == first, "the answer held, however old"
        assert time.monotonic() - started < 0.2, "and given at once"

        deadline = time.monotonic() + 10
        while _asked(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert channel.empty(), "the check is still running"
        gate.touch()
        event = channel.get(timeout=10)
        assert event.kind == "health", event
        assert event.payload["checked_at"] > first["checked_at"]
        assert console.health() == event.payload, "and is what the next page is given"
        assert _asked(calls) == 2, "three pages, one check behind them"
