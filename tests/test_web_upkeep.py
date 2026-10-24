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
from ponos.web import upkeep

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


@case
def the_health_is_checked_once_for_two_pages_and_again_when_asked_afresh(state_home):
    """`gh auth status` asks GitHub, and the band asks on every tickets page.

    Ten seconds of checks on a busy day: two pages in a row are one check, and
    "Recheck", a fix, a saved setting or the time running out are the next one.
    """
    directory = Path(tempfile.mkdtemp())
    path, calls = _counting_gh()
    console = web_api.Api.__new__(web_api.Api)
    console._config = _config(f'[storage]\nmode = "markdown"\npath = "{directory}/board"\n')
    console._stamp = web_base._stamp(console._config.path)
    console._runner = None
    console._projects = {}
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

        console._health = (time.time() - upkeep.HEALTH_TTL - 1, console._health[1])
        console.health()
        assert _asked(calls) == 4, "and so does the time running out"
