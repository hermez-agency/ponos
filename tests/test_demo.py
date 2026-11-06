"""`scripts/demo.py`: the console of made-up data, for working on the interface."""

from __future__ import annotations

import importlib.util
import json
import random
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path
from types import ModuleType

from support import ROOT, _state_home, case

_STAMP = re.compile(r"\d{4}-\d\d-\d\dT[\d:.+-]+")


def _demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_script", ROOT / "scripts" / "demo.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _written() -> dict[str, str]:
    """The board of one start, by table, with every date taken out: those are what may differ."""
    from ponos import db

    demo = _demo()
    with _state_home():
        rng = random.Random(demo.SEED)
        demo.board(demo.workbench.Seed(), rng, demo.tickets_of(rng))
        found: dict[str, str] = {}
        with db.transaction(immediate=False) as connection:
            for table in ("tickets", "ticket_after", "ticket_comments", "board_pages"):
                rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()  # noqa: S608
                found[table] = _STAMP.sub("<date>", "\n".join(repr(tuple(row)) for row in rows))
        db.close()
    return found


@case
def the_demo_board_is_the_same_at_every_start() -> None:
    one, two = _written(), _written()
    assert one == two
    assert len(one["tickets"].splitlines()) > 60, len(one["tickets"].splitlines())
    assert one["board_pages"] and one["ticket_comments"]


@case
def the_demo_board_has_every_column_and_every_family_of_stop() -> None:
    from ponos import blocks

    demo = _demo()
    tickets = demo.tickets_of(random.Random(demo.SEED))
    statuses = Counter(ticket.status for ticket in tickets)
    for status in (
        "draft",
        "ready",
        "progress",
        "review",
        "validated",
        "done",
        "blocked",
        "cancelled",
    ):
        assert statuses[status], status
    assert len(tickets) >= 60
    families = {blocks.cause(t.flag).family for t in tickets if t.status == "blocked"}
    assert families == set(blocks.FAMILIES), families
    assert len({t.id for t in tickets}) == len(tickets)
    assert {t.kind for t in tickets} == {"Code", "Rédaction", "Action externe", "Publication"}
    assert len({t.subtype for t in tickets if t.subtype}) == 8


@case
def the_demo_goals_are_served_by_tickets_of_the_board() -> None:
    demo = _demo()
    titles = {ticket.title for ticket in demo.tickets_of(random.Random(demo.SEED))}
    statuses = {goal[2] for goal in demo.GOALS}
    assert {"actif", "en pause", "atteint"} <= statuses, statuses
    assert any(goal[3] is None for goal in demo.GOALS), "one goal has no due date"
    assert any(goal[2] == "actif" and (goal[3] or 0) < 0 for goal in demo.GOALS), "one is late"
    served = [title for goal in demo.GOALS for title in goal[8]]
    assert set(served) <= titles, set(served) - titles
    assert len(served) == len(set(served)), "a ticket serves one goal"


@case
def the_demo_serves_its_board_and_removes_what_it_wrote() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    before = set(Path(tempfile.gettempdir()).glob("ponos-demo-*"))
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "demo.py"), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/board", headers={"Cookie": "ponos_token=demo"}
        )
        deadline = time.time() + 60
        board = None
        while board is None and time.time() < deadline:
            try:
                board = json.load(urllib.request.urlopen(request, timeout=5))
            except OSError:
                time.sleep(0.5)
        assert board is not None, "the demo never answered"
        assert len(board["tickets"]) >= 60, len(board["tickets"])
        statistics = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/statistics", headers=request.headers
                ),
                timeout=5,
            )
        )
        assert statistics["totals"]["closed"] > 0 and statistics["totals"]["cost"] > 0
        goals = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/goals", headers=request.headers
                ),
                timeout=5,
            )
        )["goals"]
        assert len(goals) >= 3, goals
        assert all(goal["tickets"].get("done") for goal in goals), goals
    finally:
        process.send_signal(signal.SIGINT)
        output, _ = process.communicate(timeout=30)
    assert "npm run dev:demo" in output and "?token=demo" in output, output
    assert set(Path(tempfile.gettempdir()).glob("ponos-demo-*")) <= before, (
        "the demo left its temporary directory behind"
    )
