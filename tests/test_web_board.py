"""`web/board.py`: the console and Notion, kept in step."""

from __future__ import annotations

import shutil
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import (
    _bare_api,
    _board_runner,
    _ColumnsClient,
    _mirror,
    _Nudged,
    _reviewed,
    _settings,
    _state_home,
    case,
)

from ponos import notion, store, sync
from ponos import ticket as ticket_module
from ponos.web import board as web_board

# -- the console and Notion, kept in step ------------------------------------


class _Minutes:
    """A tickets database whose clock, like Notion's, is kept to the minute.

    Queries answer the `last_edited_time` filter the console builds; `update`
    and `page` are what a move from the console reads and writes. `stale` is a
    query index that has not caught up with the last write yet — measured on the
    real board, one to four seconds after the `PATCH` answered.
    """

    def __init__(self, count: int = 3) -> None:
        self.now = datetime(2026, 9, 30, 9, 32, 6, tzinfo=UTC)
        self.pages: dict[str, store.Page] = {}
        self.queried: list[dict | None] = []
        self.patched: list[tuple[str, dict]] = []
        self.stale: dict[str, store.Page] = {}
        for index in range(count):
            self.add(f"{index + 1:032x}", f"ticket {index + 1}", "done")

    def minute(self) -> str:
        return self.now.replace(second=0, microsecond=0).isoformat().replace("+00:00", ".000Z")

    def add(self, page_id: str, title: str, status: str) -> None:
        self.pages[page_id] = store.Page(
            id=page_id,
            url="",
            title=title,
            properties={"Status": store.written("select", status)},
            raw={"last_edited_time": self.minute()},
        )

    def move(self, page_id: str, status: str) -> None:
        """Somebody drags a card in Notion."""
        page = self.pages[page_id]
        self.pages[page_id] = store.Page(
            id=page.id,
            url="",
            title=page.title,
            properties={**page.properties, "Status": store.written("select", status)},
            raw={"last_edited_time": self.minute()},
        )

    def query(self, database_id, filter_=None):
        self.queried.append(filter_)
        pages = [self.stale.get(key, page) for key, page in self.pages.items()]
        since = ((filter_ or {}).get("last_edited_time") or {}).get("on_or_after")
        if since:
            floor = datetime.fromisoformat(since)
            pages = [
                page
                for page in pages
                if datetime.fromisoformat(page.raw["last_edited_time"].replace("Z", "+00:00"))
                >= floor
            ]
        return pages

    def page(self, page_id):
        return self.pages[page_id.replace("-", "")]

    def update(self, database_id, page_id, values):
        self.patched.append((page_id, values))
        self.move(page_id, values["Status"])


def _reader(fake: _Minutes, said: list) -> web_board.Reader:
    return web_board.Reader(
        clock=lambda: fake.now.timestamp(), journal=lambda report: said.extend(report.entries)
    )


def _statuses(pages) -> dict[str, str]:
    return {page.title: store.read(page, "Status") for page in pages}


@case
def three_moves_in_one_notion_minute_all_reach_the_console():
    """Notion keeps `last_edited_time` to the minute; the console must not care.

    Measured on the real board: four statuses written at :06, :22, :39 and :52
    all came back as `09:32:00.000Z`. A read of "edited since my last read"
    starts inside that minute and would skip all but the first. The window
    reaches two minutes back instead, and every change is seen — and written in
    the journal with when it was made and when it was seen.
    """
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "done"
    assert fake.queried[-1] is None, "the first read is the whole board"

    for second, status in ((22, "blocked"), (39, "review"), (52, "done")):
        fake.now = fake.now.replace(second=second)
        fake.move("1".zfill(32), status)
        assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == status
        window = fake.queried[-1]["last_edited_time"]["on_or_after"]
        assert datetime.fromisoformat(window) < fake.now.replace(second=0), (
            "the window starts before the minute Notion rounds to"
        )
    seen = [entry.detail.split(" · ")[0] for entry in said if entry.what == "seen"]
    assert seen == ["done → blocked", "blocked → review", "review → done"], seen
    assert all("seen 09:32:" in entry.detail for entry in said if entry.what == "seen")

    # The overlap brings the same pages back; the same page is not news.
    fake.now = fake.now.replace(second=58)
    reader.read(fake, "db", "Status")
    assert len([entry for entry in said if entry.what == "seen"]) == 3


@case
def the_whole_board_is_read_again_and_what_the_window_missed_is_counted():
    """Every five minutes, the full read — and an écart is shown, not hidden."""
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    reader.read(fake, "db", "Status")
    # A page whose edit time the window cannot see: as if Notion's clock lied.
    fake.move("1".zfill(32), "blocked")
    fake.pages["1".zfill(32)].raw["last_edited_time"] = "2026-09-30T08:00:00.000Z"
    fake.now = fake.now + timedelta(seconds=30)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "done", "premise"

    fake.now = fake.now + timedelta(seconds=web_board.RECONCILE)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "blocked"
    assert fake.queried[-1] is None, "the reconciliation reads everything"
    assert reader.drift == [
        {"id": "1".zfill(32), "title": "ticket 1", "held": "done", "truth": "blocked"}
    ], reader.drift
    assert any(entry.what == "drift" for entry in said)
    assert web_board.describe(reader, [])["drift"] == 1

    # "Resynchronise now" makes the very next read a full one.
    reader.reconcile_next()
    fake.now = fake.now + timedelta(seconds=5)
    reader.read(fake, "db", "Status")
    assert fake.queried[-1] is None and reader.drift == []


@case
def a_board_of_more_than_a_hundred_tickets_is_read_to_its_last_page():
    """Notion hands out a hundred at a time; the real board is 366 tickets."""
    client = notion.Client("ntn_x")
    asked: list[dict] = []

    def answer(method, path, body=None):
        asked.append(dict(body or {}))
        start = int((body or {}).get("start_cursor") or 0)
        results = [
            {"object": "page", "id": f"{index:032x}", "properties": {}}
            for index in range(start, min(start + 100, 250))
        ]
        more = start + 100 < 250
        return {
            "results": results,
            "has_more": more,
            "next_cursor": str(start + 100) if more else None,
        }

    client._request = answer  # type: ignore[method-assign]
    pages = client.query("db")
    assert len(pages) == 250 and len({page.id for page in pages}) == 250
    assert [one.get("start_cursor") for one in asked] == [None, "100", "200"]
    assert all(one["page_size"] == 100 for one in asked)


@case
def a_move_the_network_lost_is_sent_again_until_notion_has_it():
    """Never lost in silence: pending on the card, then there, or said failed."""
    fake, said = _Minutes(), []
    now = [fake.now.timestamp()]
    outbox = web_board.Outbox(
        clock=lambda: now[0], journal=lambda report: said.extend(report.entries)
    )
    failures = [store.StoreError("PATCH /pages/x: <urlopen error timed out>")] * 2

    def send(write):
        if failures:
            raise failures.pop()
        return web_board.send(fake, "db", "Status", write)

    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    changed: list[int] = []
    outbox.flush(send, lambda: changed.append(1))
    mark = outbox.marks()["1".zfill(32)]
    assert mark.state == "pending" and "timed out" in mark.error and mark.attempts == 1
    card = web_board.overlay({"status": "done", "column": "done"}, mark, lambda status: status)
    assert card["column"] == "blocked" and card["sync"] == "pending", "drawn where it is going"
    assert fake.patched == []

    outbox.flush(send, lambda: changed.append(1))
    assert outbox.marks()["1".zfill(32)].attempts == 1, "not before its wait is over"
    now[0] += web_board.BACKOFF[0]
    outbox.flush(send, lambda: changed.append(1))
    now[0] += web_board.BACKOFF[1]
    outbox.flush(send, lambda: changed.append(1))
    assert outbox.marks() == {}, "confirmed, and let go of"
    assert store.read(fake.page("1".zfill(32)), "Status") == "blocked"
    assert [entry.what for entry in said] == ["console→notion"]
    assert "3 attempt(s)" in said[0].detail


@case
def a_move_notion_refuses_for_good_is_said_on_the_card_and_tried_again_on_demand():
    fake, said = _Minutes(), []
    outbox = web_board.Outbox(
        clock=lambda: fake.now.timestamp(), journal=lambda r: said.extend(r.entries)
    )

    def refused(write):
        raise store.StoreError("PATCH /pages/x: 400 blocked is not an option of Status")

    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    outbox.flush(refused, lambda: None)
    mark = outbox.marks()["1".zfill(32)]
    assert mark.state == "failed", "a 400 is not retried: the request itself is wrong"
    card = web_board.overlay({"status": "done", "column": "done"}, mark, lambda status: status)
    assert card["column"] == "done" and card["sync"] == "failed" and "400" in card["sync_error"]
    assert [entry.what for entry in said] == ["write-failed"]

    outbox.retry()
    assert outbox.marks()["1".zfill(32)].state == "pending"
    outbox.flush(lambda write: web_board.send(fake, "db", "Status", write), lambda: None)
    assert outbox.marks() == {}


@case
def a_move_over_a_status_changed_in_notion_meanwhile_is_not_written():
    """The console showed done; somebody moved it to review in Notion since."""
    fake, said = _Minutes(), []
    outbox = web_board.Outbox(
        clock=lambda: fake.now.timestamp(), journal=lambda r: said.extend(r.entries)
    )
    fake.move("1".zfill(32), "review")
    outbox.put(
        web_board.Write(
            page="1".zfill(32), column="blocked", status="blocked", seen="done", title="ticket 1"
        )
    )
    outbox.flush(lambda write: web_board.send(fake, "db", "Status", write), lambda: None)
    assert fake.patched == [], "Notion's review was not written over"
    mark = outbox.marks()["1".zfill(32)]
    assert mark.state == "conflict" and "review" in mark.error
    assert [entry.what for entry in said] == ["conflict"] and "review" in said[0].detail
    card = web_board.overlay({"status": "review", "column": "review"}, mark, lambda status: status)
    assert card["column"] == "review" and card["sync"] == "conflict"

    # Seen, and let go of: a resynchronisation drops it rather than forcing it.
    outbox.retry()
    assert outbox.marks() == {} and fake.patched == []


@case
def a_write_is_confirmed_by_reading_the_page_back():
    fake = _Minutes()
    fake.update = lambda database, page_id, values: fake.patched.append((page_id, values))  # type: ignore[method-assign]
    try:
        web_board.send(
            fake,
            "db",
            "Status",
            web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"),
        )
    except store.StoreError as error:
        assert "still says done" in str(error)
    else:
        raise AssertionError("a PATCH Notion did not keep is not a move")


@case
def a_confirmed_move_is_not_undone_by_a_query_that_has_not_caught_up():
    """The query index lags a write by seconds: the page read back outranks it."""
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    reader.read(fake, "db", "Status")
    stale = fake.pages["1".zfill(32)]
    confirmed = web_board.send(
        fake,
        "db",
        "Status",
        web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"),
    )
    reader.hold(confirmed)
    fake.stale["1".zfill(32)] = stale
    fake.now = fake.now + timedelta(seconds=3)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "blocked"
    # Once the hold is over, Notion's word is the word again.
    fake.now = fake.now + timedelta(seconds=web_board.HOLD + 1)
    assert _statuses(reader.read(fake, "db", "Status"))["ticket 1"] == "done"


@case
def reading_the_board_never_writes_to_it():
    """No loop: a move is written once, however many reads and flushes follow."""
    fake, said = _Minutes(), []
    reader = _reader(fake, said)
    outbox = web_board.Outbox(
        clock=lambda: fake.now.timestamp(), journal=lambda r: said.extend(r.entries)
    )
    outbox.put(web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done"))
    for _ in range(5):
        outbox.flush(
            lambda write: reader.hold(web_board.send(fake, "db", "Status", write)), lambda: None
        )
        reader.read(fake, "db", "Status")
        fake.now = fake.now + timedelta(seconds=20)
    fake.now = fake.now + timedelta(seconds=web_board.RECONCILE)
    reader.read(fake, "db", "Status")
    assert len(fake.patched) == 1, fake.patched

    # A move to where the page already is goes out as no write at all.
    outbox.put(
        web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="blocked")
    )
    outbox.flush(lambda write: web_board.send(fake, "db", "Status", write), lambda: None)
    assert len(fake.patched) == 1 and outbox.marks() == {}


@case
def a_move_waiting_to_be_sent_survives_a_console_restart():
    directory = Path(tempfile.mkdtemp())
    try:
        first = web_board.Outbox(directory / "outbox.json")
        first.put(
            web_board.Write(page="1".zfill(32), column="blocked", status="blocked", seen="done")
        )
        again = web_board.Outbox(directory / "outbox.json")
        assert again.marks()["1".zfill(32)].status == "blocked"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@case
def a_card_moved_from_the_console_is_drawn_waiting_until_notion_has_it():
    """The board the stream carries says it, so every tab says the same thing."""
    api = _bare_api(_ColumnsClient(["Ready", "Done"]))
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    api._outbox = web_board.Outbox(journal=lambda report: None)
    api.watch = _Nudged()
    api.board()
    answer = api.set_status("00000001-0000-0000-0000-000000000000", "review")
    assert answer["sync"] == "pending" and api.watch.count == 1
    write = api._outbox.marks()["00000001000000000000000000000000"]
    assert write.seen == "Done", "what the console showed is what must still be there"
    card = [item for item in api.board()["tickets"] if item["title"] == "ticket 1"][0]
    assert card["column"] == "review" and card["sync"] == "pending", card
    assert api.synchronised()["pending"] == 1 and api.synchronised()["synced_at"]


@case
def a_run_does_not_write_its_verdict_over_a_status_moved_by_hand():
    """Half an hour of session, and you moved the ticket to done meanwhile.

    The run's verdict is not written over yours: the status is left alone, said
    in the journal (where the console finds it and marks the card), and the
    rest of what the run writes — its cost, its session — still goes in.
    """
    status = {"ready": "Ready", "running": "In progress", "review": "In review", "done": "Done"}
    page = _reviewed("a" * 32, "In progress", None)
    with _state_home():
        runner = _board_runner([page], status)
        ticket = ticket_module.Ticket(page)
        moved = _reviewed("a" * 32, "Done", None)
        runner.client.page = lambda page_id: moved  # type: ignore[method-assign]
        runner._set(
            ticket, **{"Status": "In review", "Pull Request": "https://github.com/o/r/pull/1"}
        )
        assert runner.client.written == [
            ("a" * 32, {"Pull Request": "https://github.com/o/r/pull/1"})
        ]
        entries = sync.journal()
        assert [entry["what"] for entry in entries] == ["conflict"], entries
        assert "Done" in entries[0]["detail"] and "In review" in entries[0]["detail"]

        # The card wears it until somebody edits the page again, in a later minute.
        card = {"id": "a" * 32, "edited": entries[0]["at"]}
        assert web_board.settled(card, web_board.conflicts(entries)["a" * 32])["sync"] == "conflict"
        later = {"id": "a" * 32, "edited": "2099-01-01T00:00:00.000Z"}
        assert "sync" not in web_board.settled(later, web_board.conflicts(entries)["a" * 32])

        # What the run now holds is the page as it is: its next write is judged
        # against Done, and a status written where the page already is is fine.
        runner._set(ticket, **{"Status": "Done"})
        assert runner.client.written[-1] == ("a" * 32, {"Status": "Done"})

    # And a run whose ticket nobody touched writes its verdict as it always did.
    with _state_home():
        page = _reviewed("b" * 32, "In progress", None)
        runner = _board_runner([page], status)
        runner._set(ticket_module.Ticket(page), **{"Status": "In review"})
        assert runner.client.written == [("b" * 32, {"Status": "In review"})]
        assert sync.journal() == []


@case
def a_notion_page_edited_twice_in_one_minute_reaches_the_files_both_times(state_home):
    """The Markdown mirror trusted the minute, and lost the second edit of it."""
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)
        minute = (datetime.now(UTC) + timedelta(days=1)).replace(second=0, microsecond=0)
        at = minute.isoformat().replace("+00:00", ".000Z")
        here.update("tickets", page_id, {"Status": "Blocked"}, at=at)
        assert [entry.what for entry in both.synchronise(_settings(), stamps=marks).carried] == [
            "notion→markdown"
        ]
        here.update("tickets", page_id, {"Status": "Done"}, at=at)
        again = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in again.carried] == ["notion→markdown"], again.entries
        assert store.read(there.page(page_id), "Status") == "Done"
        assert not both.synchronise(_settings(), stamps=marks).carried, "and then nothing"


@case
def a_blocked_ticket_on_a_board_where_failed_is_blocked_too_is_drawn_in_blocked():
    """The 30/09 board: Notion showed three blocked tickets, the console none.

    `failed = blocked = "blocked"` draws one column, the first — and the tickets
    went to the second, which was never drawn.
    """
    api = _bare_api(_ColumnsClient(["blocked", "blocked", "Done"]))
    api._config.notion.status = {
        **api._config.notion.status,
        "blocked": "blocked",
        "failed": "blocked",
    }
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    board = api.board()
    drawn = [column["key"] for column in board["columns"]]
    assert "blocked" in drawn and "failed" not in drawn, drawn
    assert [item["column"] for item in board["tickets"]][:2] == ["blocked", "blocked"]
    assert all(item["column"] in drawn for item in board["tickets"]), "no card off the board"
