"""`progress.py`: the live line a session keeps on the board, and the steps it reads."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from support import _Clock, _run_on, case

from ponos import markdown, notion, progress, session

# -- the live report ---------------------------------------------------------


def _assistant(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool(name: str, **payload: Any) -> dict[str, Any]:
    return {"type": "tool_use", "name": name, "input": payload}


@case
def an_event_becomes_the_line_a_human_would_write() -> None:
    steps = progress.describe(
        _assistant(
            {"type": "text", "text": "I will read the config.\n\nThen the tests."},
            _tool("Bash", command="npm test -- --watch=false"),
            _tool("Read", file_path="src/app/config.ts"),
        )
    )
    assert [step.line for step in steps] == [
        # What was said keeps its own shape; what was done is a line.
        "I will read the config.\nThen the tests.",
        "Bash · npm test -- --watch=false",
        "Read · src/app/config.ts",
    ]
    assert [step.said for step in steps] == [True, False, False]


@case
def what_the_agent_said_is_written_whole_and_not_cut_to_a_bullet() -> None:
    """A paragraph of reasoning is the part a human reads; it goes down entire."""
    said = "Le ticket parle de la documentation. " * 20  # far past a bullet's 200
    steps = progress.describe(_assistant({"type": "text", "text": said}))
    assert steps[0].label == said.strip() and "…" not in steps[0].label and steps[0].said

    live, client, clock = _reporting()
    live.add(steps[0])
    clock.now += 11
    live.flush()
    # The board column shows a line, whatever the journal keeps.
    assert len(client.properties[-1]) <= progress.LINE


@case
def the_column_counts_each_command_and_shows_the_last() -> None:
    """The calls are counted and shown, one at a time, in the board's column.

    A failed one too: it is the last thing that happened.
    """
    live, client, clock = _reporting()
    for step in progress.describe(
        _assistant(
            {"type": "text", "text": "Le port 5199 est pris ; je prends un autre port."},
            _tool("Bash", command="npx vite --port 5200"),
            _tool("Read", file_path="/tmp/portrait.png"),
            _tool("Edit", file_path="src/style.css"),
        )
    ) + progress.describe(
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "is_error": True, "content": "exit 1"}]
            },
        }
    ):
        live.add(step)
    clock.now += 11
    live.flush()
    assert live.written == 5
    assert client.properties[-1] == "Error · exit 1"


@case
def a_turn_too_long_for_a_step_is_the_only_one_cut() -> None:
    steps = progress.describe(_assistant({"type": "text", "text": "x" * (progress.SAID + 500)}))
    assert len(steps[0].label) == progress.SAID and steps[0].label.endswith("…")


@case
def a_tool_nobody_named_still_says_what_it_touched() -> None:
    """An MCP tool, a new built-in: unknown is not a reason to say nothing."""
    steps = progress.describe(_assistant(_tool("mcp__github__create_pull_request", url="x/y#3")))
    assert steps[0].line == "create_pull_request · x/y#3"


@case
def only_a_failing_tool_result_is_worth_a_line() -> None:
    quiet = progress.describe(
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
    )
    loud = progress.describe(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "is_error": True, "content": [{"text": "exit 1"}]}
                ]
            },
        }
    )
    assert quiet == []
    assert loud[0].line == "Error · exit 1"
    # The payload is the log's business, never the ticket's.
    assert progress.describe({"type": "result", "num_turns": 4}) == []


class _Live:
    """A board that counts what a live report would have written to it."""

    def __init__(self, refuse: bool = False) -> None:
        self.refuse = refuse
        self.properties: list[str] = []  # every value written to the board column
        self.page: list[str] = []  # every write aimed at the page itself

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        self.page.append(block_id)
        return ["block"] * len(blocks)

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None:
        self.page.append(block_id)

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.properties.append(values["Progress"])


def _reporting(refuse: bool = False, interval: float = 10.0) -> tuple[progress.Live, _Live, _Clock]:
    clock, client = _Clock(), _Live(refuse)
    live = progress.Live(
        client,  # type: ignore[arg-type]  # a fake: only what a live report writes
        "page",
        database="db",
        property_name="Progress",
        interval=interval,
        clock=clock,
        say=lambda message: None,
    )
    return live, client, clock


@case
def the_steps_are_written_on_the_cadence_and_not_before() -> None:
    """Six events a second must not become six writes a second."""
    live, client, clock = _reporting()
    for index in range(5):
        clock.now += 1
        live.add(progress.Step("Read", f"file-{index}.py"))
    assert client.properties == [], "nothing written before the cadence came round"

    clock.now += 6
    live.add(progress.Step("Bash", "pytest"))
    assert client.properties == ["Bash · pytest"], "one write, the last step"
    assert live.written == 6, "counting all that waited"


@case
def the_page_is_never_written_while_the_session_runs() -> None:
    """The page is the mission and what was done (ticket_page.py), not a log.

    A run used to append a toggle per session holding everything the agent
    said: three runs, three toggles, and nobody could tell what stood done. The
    steps are the run journal's now; the board only gets its one live line.
    """
    live, client, clock = _reporting()
    live.add(progress.Step("Je lis la configuration.", said=True))
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 120
    live.close()
    assert client.page == [], client.page
    assert client.properties == ["Bash · npm test", ""]


class _Stuck(_Live):
    """A board that holds every write until it is let go — a 429, waited out."""

    def __init__(self) -> None:
        super().__init__()
        self.free = threading.Event()
        self.held = threading.Event()

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        self.held.set()
        assert self.free.wait(10), "never let go"
        super().update(database_id, page_id, values)


@case
def a_notion_that_takes_minutes_does_not_hold_up_reading_the_session() -> None:
    """The report used to be written from the loop that reads the CLI's output.

    A write waiting out a 429 stopped that loop, the pipe filled, and the CLI
    stopped on its next write while its timeout kept running. The writing has
    its own thread now: the stream is read through as if nobody listened, and
    what waited goes down in one write when Notion answers.
    """
    clock, client = _Clock(), _Stuck()
    live = progress.Live(
        client,  # type: ignore[arg-type]  # a fake: only what a live report writes
        "page",
        database="db",
        property_name="Progress",
        interval=10.0,
        clock=clock,
        background=True,
    )
    said = [
        json.dumps(_assistant({"type": "text", "text": f"Étape {index}."})) + "\n"
        for index in range(200)
    ]

    def ticking(event: dict[str, Any]) -> None:
        clock.now += 1  # a write comes due every ten lines
        live.event(event)

    # A session that has ended, its log and its code on disk: what `follow` reads.
    directory = Path(tempfile.mkdtemp())
    log = directory / "session.jsonl"
    log.write_text("".join(said), encoding="utf-8")
    (directory / "session.jsonl.code").write_text("0", encoding="utf-8")
    handle = session.Handle(
        session_id="s-1",
        pid=2**22 + 1,  # past pid_max: nobody's
        log=log,
        stderr=directory / "session.err",
        code=directory / "session.jsonl.code",
        cwd=directory,
        started=time.time(),
    )
    started = time.monotonic()
    final, texts, *_ = session.follow(handle, on_event=ticking)
    elapsed = time.monotonic() - started

    assert client.held.wait(5), "the writer had started its first write"
    assert len(texts) == 200 and client.properties == [], "read to the end, Notion still stuck"
    assert elapsed < 2, f"reading took {elapsed:.1f}s behind a stuck Notion"

    client.free.set()
    live.close()
    assert live.written == 200, "every step counted"
    assert client.properties[-1] == "", "and the column cleared on the way out"


@case
def what_is_still_waiting_is_written_when_the_session_ends() -> None:
    live, client, clock = _reporting()
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close()

    assert client.properties[0] == "Edit · src/x.py"
    # A finished ticket no longer claims to be doing anything.
    assert client.properties[-1] == ""


class _Page:
    """A Notion page as a tree of blocks: written by a live report, read by the client."""

    def __init__(self) -> None:
        self.children: dict[str, list[dict[str, Any]]] = {"page": []}
        self.asked: list[str] = []

    def add(self, parent: str, block: dict[str, Any]) -> str:
        identifier = uuid.uuid4().hex
        kind = block["type"]
        rich = [
            {**part, "plain_text": part["text"]["content"]} for part in block[kind]["rich_text"]
        ]
        self.children[parent].append(
            {"id": identifier, "has_children": False, **block, kind: {"rich_text": rich}}
        )
        self.children[identifier] = []
        for held in self.children.values():
            for child in held:
                child["has_children"] = bool(self.children.get(child["id"]))
        return identifier

    def append_blocks(self, block_id: str, blocks: list[dict[str, Any]]) -> list[str]:
        return [self.add(block_id, block) for block in blocks]

    def update_block(self, block_id: str, payload: dict[str, Any]) -> None:
        for held in self.children.values():
            for child in held:
                if child["id"] == block_id:
                    child["toggle"]["rich_text"] = [
                        {**part, "plain_text": part["text"]["content"]}
                        for part in payload["toggle"]["rich_text"]
                    ]

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        pass

    def request(self, method: str, path: str, body: Any = None, **_: Any) -> dict[str, Any]:
        parent = path.split("/")[2]
        self.asked.append(parent)
        return {"results": self.children[parent], "has_more": False}


@case
def a_brief_is_read_without_the_story_of_earlier_runs() -> None:
    """A ticket sent back to Ready is briefed on what you wrote, not on its past runs.

    Every run leaves its toggle on the page; read as a brief, the page skips
    them — and does not even ask Notion for what they hold. The report a run
    ends on, and a toggle somebody wrote by hand, are still read.
    """
    page = _Page()
    page.add("page", markdown.to_blocks("## À faire\n\nCorriger l'entête.")[0])
    page.add("page", markdown.to_blocks("Corriger l'entête.")[0])
    _run_on(page, "fr", "Je lis la configuration.", ok=False)  # type: ignore[arg-type]  # a fake: a page as a tree of blocks
    page.add("page", markdown.to_blocks("Pull request ouverte : x/y#3")[0])
    _run_on(page, "en", "Reading the header again.")  # type: ignore[arg-type]  # a fake: a page as a tree of blocks
    by_hand = page.add(
        "page",
        {
            "object": "block",
            "type": "toggle",
            "toggle": {"rich_text": [{"type": "text", "text": {"content": "Notes"}}]},
        },
    )
    page.add(by_hand, markdown.to_blocks("Garder le logo.")[0])
    titles = [
        "".join(part["plain_text"] for part in block["toggle"]["rich_text"])
        for block in page.children["page"]
        if block["type"] == "toggle"
    ]
    assert titles[0].startswith("⚠️ Trace — 2 étapes") and titles[1].startswith("✓ 2 steps"), titles
    runs = [block["id"] for block in page.children["page"] if progress.is_live(block)]
    assert len(runs) == 2

    client = notion.Client("ntn_x")
    client._request = page.request  # type: ignore[method-assign]
    brief = client.blocks_text("page", live=False)
    assert brief == (
        "## À faire\nCorriger l'entête.\nPull request ouverte : x/y#3\nNotes\n  Garder le logo."
    ), brief
    assert not set(runs) & set(page.asked), "a run's toggle is not even opened"
    whole = client.blocks_text("page")
    assert "Je lis la configuration." in whole and "Reading the header again." in whole
    assert "Trace" in whole


@case
def a_toggle_that_only_looks_like_a_run_is_kept() -> None:
    def toggle(title: str, bold: bool = True) -> dict[str, Any]:
        part = {"type": "text", "text": {"content": title}, "annotations": {"bold": bold}}
        return {"type": "toggle", "toggle": {"rich_text": [part]}}

    assert progress.is_live(toggle("⏳ Live"))
    assert progress.is_live(toggle("⏳ En cours — 4 étapes · moins d'une minute"))
    assert progress.is_live(toggle("✓ 16 step(s) · 3 min"))
    assert progress.is_live(toggle("⚠️ Trace — 3 steps · 2 minutes · interrupted"))
    assert not progress.is_live(toggle("✓ Done items"))
    assert not progress.is_live(toggle("⏳ Live", bold=False))
    assert not progress.is_live(toggle("Notes"))
    assert not progress.is_live({"type": "paragraph", "paragraph": toggle("⏳ Live")["toggle"]})


@case
def a_session_that_did_nothing_writes_nothing() -> None:
    live, client, _ = _reporting()
    live.close()
    assert client.properties == [] and client.page == []


@case
def the_same_step_twice_in_a_row_is_said_once() -> None:
    live, client, clock = _reporting()
    live.add(progress.Step("Je lis la config.", said=True))
    live.add(progress.Step("Je lis la config.", said=True))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/y.py"))
    clock.now += 11
    live.flush()
    assert live.written == 3
    assert client.properties[-1] == "Read · src/y.py"


@case
def a_notion_that_refuses_costs_the_report_and_not_the_ticket() -> None:
    """Reporting is commentary: it never becomes a reason to fail a ticket."""
    live, client, clock = _reporting(refuse=True)
    for index in range(10):
        clock.now += 11
        live.add(progress.Step("Read", f"file-{index}.py"))
    live.close()
    assert live.disabled and client.properties == []


# -- the plan ----------------------------------------------------------------


def _todos(*tasks: tuple[str, str]) -> dict[str, Any]:
    return _tool(
        "TodoWrite",
        todos=[
            {"content": f"Do {name}", "activeForm": f"Doing {name}", "status": status}
            for name, status in tasks
        ],
    )


@case
def a_todo_list_becomes_a_plan_step_and_the_board_says_how_far_it_is() -> None:
    """3/5, and the task under way — never a share of tool calls."""
    live, client, clock = _reporting()
    plan = progress.describe(
        _assistant(
            _todos(
                ("a", "completed"),
                ("b", "completed"),
                ("c", "completed"),
                ("d", "in_progress"),
                ("e", "pending"),
            )
        )
    )
    assert [step.label for step in plan] == ["Plan"]
    assert [task["status"] for task in progress.read_plan(plan[0].detail)][:4] == [
        "completed",
        "completed",
        "completed",
        "in_progress",
    ]
    live.add(plan[0])
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 11
    live.flush()
    assert client.properties[-1] == "3/5 — Doing d"


@case
def a_session_without_a_plan_publishes_its_last_step_and_no_figure() -> None:
    live, client, clock = _reporting()
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 11
    live.flush()
    assert client.properties[-1] == "Bash · npm test"
    assert progress.summary([]) == "" and progress.read_plan("not json") == []
    assert progress.summary(progress.plan_of([{"content": "x", "status": "completed"}])) == "1/1"
    assert progress.describe(_assistant(_tool("TodoWrite", todos=[]))) == []
