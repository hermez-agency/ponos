"""`web/live.py`: the stream a browser follows, and what it is given again."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from support import _bare_api, _TalkClient, case

from ponos import notion, session, state
from ponos.web import live as web_live

# -- what a message to the workspace carries ----------------------------------


@case
def a_browser_that_reconnects_is_given_only_what_it_missed():
    """The backlog is replayed by event id, or a suspend would double the chat."""
    hub = web_live.Hub()
    hub.publish("chat", stage="sent", text="one")
    hub.publish("chat", stage="answer", text="two")
    hub.publish("board", tickets=[])

    fresh = hub.subscribe()  # a first connection: the board, and no transcript
    kinds = [fresh.get_nowait().kind for _ in range(fresh.qsize())]
    assert kinds == ["board"], kinds

    back = hub.subscribe(after=1)  # a reconnection, having seen event 1
    seen = [back.get_nowait() for _ in range(back.qsize())]
    assert [event.kind for event in seen] == ["chat", "board"]
    assert seen[0].payload["text"] == "two"


@case
def an_event_carries_its_id_so_the_browser_can_ask_again():
    hub = web_live.Hub()
    hub.publish("step", label="Read", detail="src/x.py")
    channel = hub.subscribe(after=0)
    hub.publish("step", label="Bash", detail="npm test")
    event = channel.get_nowait()
    assert event.encode().startswith("id: 2\nevent: step\ndata: {")
    assert '"label": "Bash"' in event.encode()


@case
def a_log_line_becomes_the_step_the_board_would_have_shown():
    """The live panel and the Notion toggle read the same events, one way."""
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]
            },
        }
    )
    steps = web_live.steps(line)
    assert [step.line for step in steps] == ["Bash · npm test"]
    assert web_live.steps("not json at all") == []


@case
def a_ticket_finds_its_own_session_and_tells_what_the_agent_said_from_what_it_did(state_home):
    """The ticket page reads its journal by the ticket, not by a session id.

    What the agent said and what it ran are drawn differently there — the one
    read, the other folded — so each step says which it is, on the stream and
    in the log read back alike.
    """
    said = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Je lis le code."}]}}
    )
    ran = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]
            },
        }
    )
    logs = state.logs_dir()
    (logs / "20260830-120000-1a2b3c4d.jsonl").write_text(said + "\n" + ran + "\n", encoding="utf-8")
    (logs / "20260830-130000-99999999.jsonl").write_text(ran + "\n", encoding="utf-8")
    api = _bare_api(_TalkClient([]))
    found = api.logs("1a2b3c4d")["logs"]
    assert [entry["name"] for entry in found] == ["20260830-120000-1a2b3c4d.jsonl"], found
    assert len(api.logs()["logs"]) == 2
    read = api.log(found[0]["name"])
    assert read["count"] == 2
    assert [(step["label"], step["said"]) for step in read["steps"]] == [
        ("Je lis le code.", True),
        ("Bash", False),
    ]

    hub = web_live.Hub()
    published = []
    hub.publish = lambda kind, **payload: published.append((kind, payload))  # type: ignore[method-assign]
    web_live.Tail(hub, logs).pass_once()
    told = [
        payload for kind, payload in published if kind == "step" and payload["source"] == "1a2b3c4d"
    ]
    assert [payload["said"] for payload in told] == [True, False], told


@case
def a_session_log_is_tailed_forward_and_never_twice():
    hub = web_live.Hub()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        log = folder / "20260830-120000-1a2b3c4d.jsonl"
        event = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "reading"}]}}
        )
        log.write_text(event + "\n", encoding="utf-8")
        tail = web_live.Tail(hub, folder)
        assert tail.pass_once() == 1
        assert tail.pass_once() == 0, "a pass that adds nothing must publish nothing"

        # A half-written line is left for the next pass rather than dropped.
        with log.open("a", encoding="utf-8") as handle:
            handle.write(event[:20])
        assert tail.pass_once() == 0
        with log.open("a", encoding="utf-8") as handle:
            handle.write(event[20:] + "\n")
        assert tail.pass_once() == 1


@case
def the_board_is_published_only_when_it_has_moved():
    """A poll that redrew an unchanged board would lose your scroll for nothing."""
    hub = web_live.Hub()
    boards = [
        {"tickets": [{"id": "a", "title": "one"}]},
        {"tickets": [{"id": "a", "title": "one"}]},
        {"tickets": [{"id": "a", "title": "two"}]},
    ]
    watch = web_live.Watch(hub, lambda: boards.pop(0), interval=5)
    channel = hub.subscribe()
    watch.refresh()
    watch.refresh()
    watch.refresh()
    published = [channel.get_nowait() for _ in range(channel.qsize())]
    assert [event.kind for event in published] == ["board", "changes"], published
    assert published[1].payload == {
        "changed": [{"after": "", "ticket": {"id": "a", "title": "two"}}],
        "removed": [],
        "base": 1,
        "version": 2,
    }, published[1].payload


def _tickets(*cards: tuple[str, str, str]) -> dict:
    """A board as `Api.board` sorts it: by column, then by title."""
    order = ["ready", "running", "review"]
    tickets = [{"id": i, "column": c, "title": t, "steps": 0} for i, c, t in cards]
    tickets.sort(key=lambda item: (order.index(item["column"]), item["title"]))
    return {
        "tickets": tickets,
        "validate": False,
        "columns": [{"key": k, "name": k} for k in order],
    }


def _apply(board: dict, changes: dict) -> list[dict]:
    """What `applyChanges` in `board-store.ts` does with them, line for line."""
    gone = set(changes["removed"]) | {entry["ticket"]["id"] for entry in changes["changed"]}
    tickets = [ticket for ticket in board["tickets"] if ticket["id"] not in gone]
    for entry in changes["changed"]:
        at = (
            next(i for i, t in enumerate(tickets) if t["id"] == entry["after"]) + 1
            if entry["after"]
            else 0
        )
        tickets.insert(at, entry["ticket"])
    return tickets


@case
def a_board_that_moved_is_sent_as_what_moved_and_gives_back_the_same_board():
    """A card moved, one added, one gone: the page rebuilds exactly the board, in its order."""
    before = _tickets(
        ("a", "ready", "Alpha"),
        ("b", "ready", "Beta"),
        ("c", "running", "Gamma"),
        ("d", "review", "Delta"),
    )
    after = _tickets(
        ("a", "running", "Alpha"),
        ("b", "ready", "Beta"),
        ("c", "running", "Gamma"),
        ("e", "ready", "Epsilon"),
    )
    changes = web_live.difference(before, after)
    assert changes is not None
    assert [entry["ticket"]["id"] for entry in changes["changed"]] == ["e", "a"], changes
    assert changes["removed"] == ["d"]
    assert _apply(before, changes) == after["tickets"]

    # The same board again says nothing has changed; new columns need the whole board.
    assert web_live.difference(after, after) == {"changed": [], "removed": []}
    renamed = {**after, "columns": [{"key": "ready", "name": "Prêt"}]}
    assert web_live.difference(after, renamed) is None
    assert web_live.difference(None, after) is None


@case
def a_ticket_in_flight_costs_the_stream_its_own_card_not_the_board():
    """475 tickets, one step further on one of them: under 10 KB, where the board is ~360."""
    filler = "x" * 600
    cards = [
        {"id": f"{n:032x}", "column": "backlog", "title": f"Ticket {n:03d}", "brief": filler}
        for n in range(475)
    ]
    board = {"tickets": cards, "validate": True, "columns": [{"key": "backlog", "name": "Backlog"}]}
    moved = {**board, "tickets": [dict(card) for card in cards]}
    moved["tickets"][200]["steps"] = 42
    hub = web_live.Hub()
    watch = web_live.Watch(hub, iter([board, moved]).__next__)
    channel = hub.subscribe()
    watch.refresh()
    watch.refresh()
    whole, step = (channel.get_nowait() for _ in range(2))
    assert step.kind == "changes"
    assert len(whole.encode().encode()) > 300_000
    assert len(step.encode().encode()) < 10_000, len(step.encode().encode())


@case
def a_browser_is_given_the_whole_board_again_only_when_it_missed_a_version():
    hub = web_live.Hub()
    watch = web_live.Watch(
        hub,
        iter(
            [
                _tickets(("a", "ready", "Alpha")),
                _tickets(("a", "running", "Alpha")),
            ]
        ).__next__,
    )
    watch.refresh()  # event 1: the whole board
    hub.publish("step", label="Read")  # event 2
    watch.refresh()  # event 3: what changed

    fresh = hub.subscribe()
    first = fresh.get_nowait()
    assert (first.kind, first.payload["version"]) == ("board", 2), (
        "a new tab gets it whole, as it is now"
    )
    assert first.payload["tickets"][0]["column"] == "running"

    up_to_date = hub.subscribe(after=3)
    assert up_to_date.qsize() == 0, "a tab that saw the last changes is not sent the board again"

    behind = hub.subscribe(after=2)
    kinds = [behind.get_nowait().kind for _ in range(behind.qsize())]
    assert kinds == ["board"], "missed changes are replaced by the whole board, never replayed"

    lost = hub.subscribe(after=3, board=True)
    assert [lost.get_nowait().kind for _ in range(lost.qsize())] == ["board"]


@case
def a_write_from_the_console_that_changed_nothing_sends_the_board_whole():
    """The page drew the card ahead; a board that did not move puts it back."""
    board = _tickets(("a", "ready", "Alpha"))
    hub = web_live.Hub()
    watch = web_live.Watch(hub, lambda: board)
    channel = hub.subscribe()
    watch.refresh()
    watch.refresh(force=True)
    watch.refresh()
    assert [channel.get_nowait().kind for _ in range(channel.qsize())] == ["board", "board"]


@case
def a_board_read_lets_the_bell_go_of_a_ticket_that_moved_on(state_home):
    """The console holds the board: it is the one that settles the bell against it."""
    from datetime import UTC, datetime, timedelta

    from ponos import db, notifications

    notifications.add("review", "a", "Alpha")
    notifications.add("review", "b", "Beta")
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        connection.execute("UPDATE notifications SET at = ?", (old,))
    hub = web_live.Hub()
    watch = web_live.Watch(hub, lambda: _tickets(("a", "ready", "Alpha"), ("b", "review", "Beta")))
    channel = hub.subscribe()
    watch.refresh()
    watch.ring()
    bells = [
        event
        for event in (channel.get_nowait() for _ in range(channel.qsize()))
        if event.kind == "notifications"
    ]
    assert bells and bells[-1].payload["unread"] == 1
    assert [i["ticket"] for i in bells[-1].payload["items"] if not i["read"]] == ["b"]


@case
def a_notion_that_will_not_answer_reaches_the_console_as_a_notice():
    """Named `notice`: EventSource already fires an `error` of its own."""
    hub = web_live.Hub()
    said = []
    hub.publish = lambda kind, **payload: said.append((kind, payload))  # type: ignore[method-assign]

    def broken() -> dict:
        raise notion.NotionError("object not found\nsecond line nobody needs")

    web_live.Watch(hub, broken).refresh()
    assert said == [("notice", {"where": "board", "message": "object not found"})]


@case
def a_session_identifier_is_read_from_either_shape_of_the_column():
    """A URL column holds a link, a text column holds the bare ID. Same session."""
    from ponos.web.tickets import _session_id

    identifier = "6f1c2b70-1c39-4f0a-9a52-1f3c1a2b3c4d"
    assert _session_id(identifier) == identifier
    assert _session_id(session.deep_link(identifier, cwd="/home/me/work")) == identifier
    assert _session_id(session.deep_link(identifier, host="server")) == identifier
    assert _session_id("") == ""
