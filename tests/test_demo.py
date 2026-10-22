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

from support import ROOT, case

_STAMP = re.compile(r"\d{4}-\d\d-\d\dT[\d:.+-]+")


def _demo():
    spec = importlib.util.spec_from_file_location("demo_script", ROOT / "scripts" / "demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _written(demo, directory: Path) -> dict[str, str]:
    """The board of one start, by file, with every date taken out: those are what may differ."""
    rng = random.Random(demo.SEED)
    demo.board(directory, rng, demo.tickets_of(rng))
    return {
        str(path.relative_to(directory)): _STAMP.sub("<date>", path.read_text(encoding="utf-8"))
        for path in sorted(directory.rglob("*.md"))
    }


@case
def the_demo_board_is_the_same_at_every_start():
    demo = _demo()
    with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
        one = _written(demo, Path(first) / "board")
        two = _written(demo, Path(second) / "board")
    assert one == two
    assert len(one) > 100, len(one)


@case
def the_demo_board_has_every_column_and_every_family_of_stop():
    from ponos import blocks

    demo = _demo()
    tickets = demo.tickets_of(random.Random(demo.SEED))
    statuses = Counter(ticket.status for ticket in tickets)
    for status in (
        "Backlog",
        "Ready",
        "In progress",
        "In review",
        "Validated",
        "Done",
        "Failed",
        "Blocked",
        "Cancelled",
    ):
        assert statuses[status], status
    assert len(tickets) >= 60
    families = {blocks.cause(t.flag).family for t in tickets if t.status in ("Blocked", "Failed")}
    assert families == set(blocks.FAMILIES), families
    assert len({t.id for t in tickets}) == len(tickets)
    assert {t.kind for t in tickets} == {"Code", "Writing", "External action", "Publication"}
    assert len({t.subtype for t in tickets if t.subtype}) == 8


@case
def the_demo_serves_its_board_and_removes_what_it_wrote():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
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
        directory = Path(board["tickets"][0]["url"].removeprefix("file://")).parents[2]
        assert directory.is_dir()
    finally:
        process.send_signal(signal.SIGINT)
        output, _ = process.communicate(timeout=30)
    assert "npm run dev:demo" in output and "?token=demo" in output, output
    assert not directory.exists(), "the demo left its temporary directory behind"
