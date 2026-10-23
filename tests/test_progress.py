"""`progress.py`: the live report written on a ticket."""

from __future__ import annotations

import io
import json
import threading
import time
import uuid

from support import _Clock, _run_on, case

from ponos import markdown, notion, progress, session, voice

# -- the live report ---------------------------------------------------------


def _assistant(*blocks) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool(name: str, **payload) -> dict:
    return {"type": "tool_use", "name": name, "input": payload}


@case
def an_event_becomes_the_line_a_human_would_write():
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
def what_the_agent_said_is_written_whole_and_not_cut_to_a_bullet():
    """A paragraph of reasoning is the part a human reads; it goes down entire."""
    said = "Le ticket parle de la documentation. " * 20  # far past a bullet's 200
    steps = progress.describe(_assistant({"type": "text", "text": said}))
    assert steps[0].label == said.strip() and "…" not in steps[0].label

    live, client, clock = _reporting()
    live.add(steps[0])
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 11
    live.flush()
    # Prose is a paragraph; a tool call never reaches the page.
    assert client.kinds == ["paragraph"]
    assert client.blocks[0] == said.strip()

    live.add(steps[0])
    clock.now += 11
    live.flush()
    # One paragraph after the other, no rule between them.
    assert client.kinds == ["paragraph", "paragraph"]
    # The board column shows a line, whatever the page shows.
    assert len(client.properties[-1]) <= progress.LINE


@case
def the_ticket_gets_what_the_agent_said_and_not_each_command():
    """“Bash · npx vite --port 5199” teaches nothing to whoever reads a ticket.

    The calls stay counted in the title and shown in the board's column; their
    detail is the log's and the console's. A failed one stays off as well: what
    the agent says next is what it made of it.
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
    assert client.blocks == ["Le port 5199 est pris ; je prends un autre port."]
    assert client.titles[-1].startswith("⏳ Live — 5 steps")
    assert client.properties[-1] == "Error · exit 1"


@case
def a_turn_too_long_for_a_ticket_page_is_the_only_one_cut():
    steps = progress.describe(_assistant({"type": "text", "text": "x" * (progress.SAID + 500)}))
    assert len(steps[0].label) == progress.SAID and steps[0].label.endswith("…")

    live, client, clock = _reporting()
    live.add(steps[0])
    clock.now += 11
    live.flush()
    # Notion caps a piece of rich text, not a block: the paragraph is in pieces.
    assert client.pieces[-1] > 1 and client.blocks[-1] == steps[0].label


@case
def the_markdown_an_agent_writes_reaches_the_page_as_markup():
    live, client, clock = _reporting()
    live.add(progress.Step("**Interprétation** : lire `README.md`.", said=True))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Interprétation : lire README.md."], "no stray asterisks"
    marked = [name for mark in client.marks for name, on in mark.items() if on]
    assert marked == ["bold", "code"]


@case
def a_tool_nobody_named_still_says_what_it_touched():
    """An MCP tool, a new built-in: unknown is not a reason to say nothing."""
    steps = progress.describe(_assistant(_tool("mcp__github__create_pull_request", url="x/y#3")))
    assert steps[0].line == "create_pull_request · x/y#3"


@case
def only_a_failing_tool_result_is_worth_a_line():
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
    """A Notion that counts what a live report would have written to it."""

    def __init__(self, refuse=False):
        self.refuse = refuse
        self.blocks = []  # the text of every child appended under the toggle
        self.kinds = []  # and its block type
        self.pieces = []  # and how many pieces of rich text it took
        self.marks = []  # every annotation any of those pieces carried
        self.titles = []  # every title the toggle has carried
        self.properties = []  # every value written to the board column

    def append_blocks(self, block_id, blocks):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        if block_id == "page":
            return ["toggle"]
        for block in blocks:
            kind = block["type"]
            parts = block[kind].get("rich_text", [])
            self.kinds.append(kind)
            self.pieces.append(len(parts))
            self.blocks.append("".join(part["text"]["content"] for part in parts))
            self.marks += [part["annotations"] for part in parts if part.get("annotations")]
        return ["block"] * len(blocks)

    def update_block(self, block_id, payload):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.titles.append(payload["toggle"]["rich_text"][0]["text"]["content"])

    def update(self, database_id, page_id, values):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.properties.append(values["Progress"])


def _reporting(refuse=False, interval=10.0):
    clock, client = _Clock(), _Live(refuse)
    live = progress.Live(
        client,
        "page",
        database="db",
        property_name="Progress",
        interval=interval,
        clock=clock,
        say=lambda message: None,
    )
    return live, client, clock


@case
def the_steps_are_written_on_the_cadence_and_not_before():
    """Six events a second must not become six writes a second."""
    live, client, clock = _reporting()
    for index in range(5):
        clock.now += 1
        live.add(progress.Step("Read", f"file-{index}.py"))
    assert client.blocks == [], "nothing written before the cadence came round"

    assert client.titles == [], "nothing written before the cadence came round"

    clock.now += 6
    live.add(progress.Step("Bash", "pytest"))
    assert client.titles[-1].startswith("⏳ Live — 6 steps"), "one write, counting all that waited"
    assert client.properties[-1] == "Bash · pytest", "the board column shows the last step"


class _Stuck(_Live):
    """A Notion that holds every write until it is let go — a 429, waited out."""

    def __init__(self):
        super().__init__()
        self.free = threading.Event()
        self.held = threading.Event()

    def append_blocks(self, block_id, blocks):
        self.held.set()
        assert self.free.wait(10), "never let go"
        return super().append_blocks(block_id, blocks)


class _Session:
    """What `session._read` reads: a process, reduced to its output."""

    def __init__(self, lines):
        self.stdout = iter(lines)


@case
def a_notion_that_takes_minutes_does_not_hold_up_reading_the_session():
    """The report used to be written from the loop that reads the CLI's output.

    A write waiting out a 429 stopped that loop, the pipe filled, and the CLI
    stopped on its next write while its timeout kept running. The writing has
    its own thread now: the stream is read through as if nobody listened, and
    what waited goes down in one write when Notion answers.
    """
    clock, client = _Clock(), _Stuck()
    live = progress.Live(client, "page", interval=10.0, clock=clock, background=True)
    said = [
        json.dumps(_assistant({"type": "text", "text": f"Étape {index}."})) + "\n"
        for index in range(200)
    ]

    def ticking():
        for line in said:
            clock.now += 1  # a write comes due every ten lines
            yield line

    started = time.monotonic()
    final, texts = session._read(_Session(ticking()), io.StringIO(), live.event)
    elapsed = time.monotonic() - started

    assert client.held.wait(5), "the writer had started its first write"
    assert len(texts) == 200 and client.blocks == [], "read to the end, Notion still stuck"
    assert elapsed < 2, f"reading took {elapsed:.1f}s behind a stuck Notion"

    client.free.set()
    live.close("done")
    assert client.titles[-1].startswith("✓ 200 steps"), "every step counted"
    assert client.blocks == [f"Étape {index}." for index in range(200)], "none lost, in order"


@case
def what_is_still_waiting_is_written_when_the_session_ends():
    live, client, clock = _reporting()
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close("removed the header")

    assert client.blocks == []
    assert client.titles[-1] == "✓ 1 step · 2 minutes · removed the header"
    # A finished ticket no longer claims to be doing anything.
    assert client.properties[-1] == ""


@case
def a_run_that_went_wrong_calls_its_block_a_trace_and_keeps_it_there():
    """The report is two lines and says where the rest is; the rest is here.

    Which is the whole move: what every comment used to end on — the command
    that resumes the session, the log, the worktree that was kept — is worth
    exactly one click on the day a run failed, and nothing at all on every
    other day.
    """
    live, client, clock = _reporting()
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close("it asked a question", ok=False)
    assert client.titles[-1] == "⚠️ Trace — 1 step · 2 minutes · it asked a question"

    assert live.detail("To pick the session back up: `claude --resume s-1`.")
    assert client.blocks[-1].startswith("To pick the session back up")
    assert not live.detail("  "), "nothing to file is not something to file"


@case
def a_ticket_with_no_block_to_file_a_trace_in_keeps_it_in_the_report():
    """A trace nobody can find is a trace nobody has."""
    live, client, _ = _reporting()
    assert not live.detail("`claude --resume s-1`"), "no step, no toggle, nowhere to put it"
    assert client.blocks == []


@case
def the_block_a_run_leaves_speaks_the_language_the_report_does():
    """“⏳ Live — 16 step(s)” under a French verdict is one glance, two languages."""
    clock, client = _Clock(), _Live()
    live = progress.Live(client, "page", words=voice.Voice("fr"), clock=clock)
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close()
    assert client.titles[0].startswith("⏳ En cours")
    assert client.titles[-1] == "✓ 1 étape · 2 minutes"


class _Page:
    """A Notion page as a tree of blocks: written by a live report, read by the client."""

    def __init__(self):
        self.children: dict[str, list[dict]] = {"page": []}
        self.asked: list[str] = []

    def add(self, parent: str, block: dict) -> str:
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

    def append_blocks(self, block_id, blocks):
        return [self.add(block_id, block) for block in blocks]

    def update_block(self, block_id, payload):
        for held in self.children.values():
            for child in held:
                if child["id"] == block_id:
                    child["toggle"]["rich_text"] = [
                        {**part, "plain_text": part["text"]["content"]}
                        for part in payload["toggle"]["rich_text"]
                    ]

    def update(self, database_id, page_id, values):
        pass

    def request(self, method, path, body=None, **_):
        parent = path.split("/")[2]
        self.asked.append(parent)
        return {"results": self.children[parent], "has_more": False}


@case
def a_brief_is_read_without_the_story_of_earlier_runs():
    """A ticket sent back to Ready is briefed on what you wrote, not on its past runs.

    Every run leaves its toggle on the page; read as a brief, the page skips
    them — and does not even ask Notion for what they hold. The report a run
    ends on, and a toggle somebody wrote by hand, are still read.
    """
    page = _Page()
    page.add("page", markdown.to_blocks("## À faire\n\nCorriger l'entête.")[0])
    page.add("page", markdown.to_blocks("Corriger l'entête.")[0])
    _run_on(page, "fr", "Je lis la configuration.", ok=False)
    page.add("page", markdown.to_blocks("Pull request ouverte : x/y#3")[0])
    _run_on(page, "en", "Reading the header again.")
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
def a_toggle_that_only_looks_like_a_run_is_kept():
    def toggle(title, bold=True):
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
def a_session_that_did_nothing_leaves_no_toggle_behind():
    live, client, _ = _reporting()
    live.close("nothing to do")
    assert client.blocks == [] and client.titles == []


@case
def the_same_step_twice_in_a_row_is_said_once():
    live, client, clock = _reporting()
    live.add(progress.Step("Je lis la config.", said=True))
    live.add(progress.Step("Je lis la config.", said=True))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/y.py"))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Je lis la config."]
    assert client.titles[-1].startswith("⏳ Live — 3 steps")


@case
def a_notion_that_refuses_costs_the_report_and_not_the_ticket():
    """Reporting is commentary: it never becomes a reason to fail a ticket."""
    live, client, clock = _reporting(refuse=True)
    for index in range(10):
        clock.now += 11
        live.add(progress.Step("Read", f"file-{index}.py"))
    live.close("done anyway")
    assert live.disabled and client.blocks == []


@case
def a_reporter_never_writes_more_than_a_page_can_hold():
    live, client, clock = _reporting()
    for index in range(progress.MAX_STEPS + 50):
        live.add(progress.Step(f"Paragraphe {index}.", said=True))
    clock.now += 11
    live.flush()
    assert len(client.blocks) == progress.MAX_STEPS + 1, "the prose, then one line saying enough"
    assert client.blocks[-1].startswith("…")

    # Capped is not disabled: the page stops, the title still counts and ends.
    live.add(progress.Step("Encore un.", said=True))
    clock.now += 11
    live.close("done")
    assert len(client.blocks) == progress.MAX_STEPS + 1
    assert client.titles[-1].startswith(f"✓ {progress.MAX_STEPS + 51} steps")
    assert client.titles[-1].endswith("· done")


@case
def tool_calls_by_the_hundred_do_not_cost_the_prose_its_place():
    live, client, clock = _reporting()
    for index in range(progress.MAX_STEPS + 50):
        live.add(progress.Step("Read", f"file-{index}.py"))
    live.add(progress.Step("Tout est lu ; je lance les tests.", said=True))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Tout est lu ; je lance les tests."]


# -- the plan ----------------------------------------------------------------


def _todos(*tasks) -> dict:
    return _tool(
        "TodoWrite",
        todos=[
            {"content": f"Do {name}", "activeForm": f"Doing {name}", "status": status}
            for name, status in tasks
        ],
    )


@case
def a_todo_list_becomes_a_plan_step_and_the_board_says_how_far_it_is():
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
def a_session_without_a_plan_publishes_its_last_step_and_no_figure():
    live, client, clock = _reporting()
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 11
    live.flush()
    assert client.properties[-1] == "Bash · npm test"
    assert progress.summary([]) == "" and progress.read_plan("not json") == []
    assert progress.summary(progress.plan_of([{"content": "x", "status": "completed"}])) == "1/1"
    assert progress.describe(_assistant(_tool("TodoWrite", todos=[]))) == []
