"""`transitions.py`: the « On » prompt a status change runs."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from support import _config, _Unblocking, case

from ponos import notion, session, voice

# -- the « On » prompt -------------------------------------------------------


def _page(identifier: str, status: str, prompt: str = "", title: str = "") -> notion.Page:
    def text(kind: str, value: str) -> dict:
        return {"type": kind, kind: [{"plain_text": value}]}

    return notion.Page(
        id=identifier,
        url=f"https://notion.test/{identifier}",
        title=title or identifier,
        properties={
            "Status": {"type": "status", "status": {"name": status}},
            "On": text("rich_text", prompt),
        },
    )


class _OnBoard:
    """Pages by id, the way a board answers: the whole database, or one page."""

    def __init__(self, *pages: notion.Page) -> None:
        self.pages = {page.id: page for page in pages}

    def query(self, database, filter_=None):
        return list(self.pages.values())

    def page(self, page_id):
        return self.pages[page_id]

    def schema(self, database):
        return {"Status": "status", "On": "rich_text"}

    def set(self, identifier: str, status: str) -> None:
        self.pages[identifier] = _page(
            identifier,
            status,
            notion.read(self.pages[identifier], "On") if identifier in self.pages else "",
        )


class _OnRunner(_Unblocking):
    """A runner that has only what the « On » chapter asks of one."""

    def say(self, message):
        pass

    def under_reserve(self):
        return 0.0

    def _out_of_credit(self, outcome):
        return outcome.exhausted

    @property
    def voice(self):
        return voice.Voice("en")

    @property
    def environment(self):
        return {}


def _on_runner(board: _OnBoard, **runner_settings) -> _OnRunner:
    runner = _OnRunner.__new__(_OnRunner)
    runner.client = board
    runner.config = _config("")
    # Read at every call: the throttle has a test of its own.
    runner.config.runner.on_interval_seconds = 0
    for key, value in runner_settings.items():
        setattr(runner.config.runner, key, value)
    runner.dry_run, runner.moved, runner.comments_written = False, [], []
    runner._on_read = float("-inf")
    runner._comments = {}
    runner._claimed = set()
    return runner


def _a_session_that(effect=None, **outcome):
    """`session.run`, replaced by one that does `effect` while it runs."""
    seen: list[dict] = []

    def fake(prompt_text, **kwargs):
        seen.append({"prompt": prompt_text, **kwargs})
        if effect:
            effect()
        return session.Outcome(
            **{
                "ok": True,
                "blocked": False,
                "session_id": "s-on",
                "summary": "fait",
                "log": Path("/tmp/none.jsonl"),
                "answer": "RESULT: ok — fait",
                "cost_usd": 0.12,
                "seconds": 3.0,
                **outcome,
            }
        )

    return seen, fake


@contextmanager
def _replacing(module, name: str, value):
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


@case
def a_status_is_a_change_only_from_the_second_time_it_is_seen_and_only_once(state_home):
    from ponos import transitions

    assert transitions.observe("t1", "Ready", title="A", depth_limit=3) == (0, ""), "a first sight"
    assert transitions.observe("t1", "Ready", title="A", depth_limit=3) == (0, ""), "nothing moved"
    found, old = transitions.observe("t1", "Done", title="A", depth_limit=3)
    assert found and old == "Ready"
    assert transitions.observe("t1", "Done", title="A", depth_limit=3) == (0, ""), (
        "the same change is not met twice: it is already the starting point"
    )
    assert [(row["old"], row["new"]) for row in transitions.pending(10)] == [("Ready", "Done")]
    # A ticket that loses its prompt is forgotten: the day it gets one again
    # is a first sight, not a change from a status it had months ago.
    transitions.forget(set())
    assert transitions.observe("t1", "Blocked", title="A", depth_limit=3) == (0, "")


@case
def the_on_prompt_of_a_ticket_runs_with_the_transition_and_is_closed_with_what_it_cost(state_home):
    from ponos import transitions

    board = _OnBoard(_page("t1", "Ready", "Si Done, crée le déploiement.", "Site"))
    runner = _on_runner(board)
    runner.transitions()  # the starting point
    board.set("t1", "Done")
    seen, fake = _a_session_that()
    with _replacing(session, "run", fake):
        results = runner.transitions()
    assert [entry["status"] for entry in results] == ["on-ok"], results
    prompt = seen[0]["prompt"]
    assert "Old status: Ready" in prompt and "New status: Done" in prompt, prompt
    assert "Si Done, crée le déploiement." in prompt
    assert seen[0]["max_budget_usd"] == 1.0, "a ceiling by default"
    assert seen[0]["timeout_minutes"] == 10
    (row,) = transitions.history("t1")
    assert (row["state"], row["cost_usd"], row["result"]) == ("ok", 0.12, "fait"), row


@case
def what_an_execution_moves_or_creates_never_wakes_a_prompt_and_its_children_are_one_generation_down(
    state_home,
):
    from ponos import transitions

    board = _OnBoard(_page("t1", "Ready", "Crée un ticket de suivi puis passe-moi en Done."))
    runner = _on_runner(board)
    runner.transitions()
    board.set("t1", "In progress")

    def effect():
        # What the prompt does: moves its own ticket, makes another, with a prompt too.
        board.set("t1", "Done")
        board.pages["t2"] = _page("t2", "Ready", "Moi aussi.")

    seen, fake = _a_session_that(effect)
    with _replacing(session, "run", fake):
        runner._on_read = float("-inf")
        runner.transitions()
        assert len(seen) == 1
        # The next reading: neither the move of t1 nor the birth of t2 is a change.
        runner._on_read = float("-inf")
        assert runner.transitions() == [] and len(seen) == 1, "no loop"
        # But t2 is a ticket like another from now on, one generation down.
        board.set("t2", "Done")
        runner._on_read = float("-inf")
        assert [e["status"] for e in runner.transitions()] == ["on-ok"]
        (row,) = transitions.history("t2")
        assert row["depth"] == 1, row


@case
def a_chain_of_tickets_made_by_prompts_stops_at_the_depth_the_file_allows(state_home):
    from ponos import transitions

    board = _OnBoard(_page("t1", "Ready", "Fais un ticket."))
    runner = _on_runner(board, on_max_depth=1)
    runner.transitions()
    generation = {"n": 0}

    def effect():
        # Every execution makes the next ticket of the chain, with the same prompt.
        generation["n"] += 1
        name = f"c{generation['n']}"
        board.pages[name] = _page(name, "Ready", "Fais un ticket.")

    seen, fake = _a_session_that(effect)
    with _replacing(session, "run", fake):
        board.set("t1", "Done")
        for _ in range(4):
            runner._on_read = float("-inf")
            runner.transitions()
            # What the chain does by itself: each new ticket is done by somebody.
            for name in [n for n in board.pages if n.startswith("c")]:
                if notion.read(board.pages[name], "Status") != "Done":
                    board.set(name, "Done")
    # t1 (depth 0) and c1 (depth 1) ran; c2 would be depth 2 > the limit of 1.
    assert generation["n"] == 2, generation
    skipped = [row for row in transitions.history("c2") if row["state"] == "skipped"]
    assert skipped and "deeper" in skipped[0]["result"], transitions.history("c2")


@case
def an_execution_that_fails_or_overspends_is_commented_and_never_touches_a_status(state_home):
    from ponos import transitions

    board = _OnBoard(_page("t1", "Ready", "Fais-le."))
    runner = _on_runner(board)
    runner.transitions()
    board.set("t1", "Blocked")
    _, fake = _a_session_that(ok=False, blocked=True, over_budget=True, answer="", summary="")
    with _replacing(session, "run", fake):
        results = runner.transitions()
    assert [entry["status"] for entry in results] == ["on-failed"], results
    assert runner.moved == [], "the status is the board's"
    assert len(runner.comments_written) == 1
    assert "Ready → Blocked" in runner.comments_written[0] and "1.00" in runner.comments_written[0]
    assert transitions.history("t1")[0]["state"] == "failed"
    runner._on_read = float("-inf")
    assert runner.transitions() == [], "a failure is not tried again by itself"


@case
def an_execution_that_never_started_for_want_of_credit_is_still_to_run(state_home):
    from ponos import transitions

    board = _OnBoard(_page("t1", "Ready", "Fais-le."))
    runner = _on_runner(board)
    runner.transitions()
    board.set("t1", "Done")
    _, broke = _a_session_that(ok=False, exhausted=True, answer="")
    with _replacing(session, "run", broke):
        assert runner.transitions() == []
    assert [row["state"] for row in transitions.history("t1")] == ["pending"]
    seen, fake = _a_session_that()
    with _replacing(session, "run", fake):
        runner._on_read = float("-inf")
        assert len(runner.transitions()) == 1 and len(seen) == 1


@case
def the_board_is_read_for_moved_statuses_no_more_often_than_the_file_says(state_home):
    board = _OnBoard(_page("t1", "Ready", "Fais-le."))
    runner = _on_runner(board, on_interval_seconds=30)
    reads = []
    original = board.query
    board.query = lambda *a, **k: (reads.append(1), original(*a, **k))[1]
    runner.transitions()
    runner.transitions()
    runner.transitions()
    assert len(reads) == 1, "three passes within the interval, one reading"
    runner.config.runner.on = False
    runner._on_read = float("-inf")
    runner.transitions()
    assert len(reads) == 1, "runner.on = false reads nothing"


@case
def an_execution_a_dead_run_left_open_is_closed_and_never_run_again(state_home):
    from ponos import transitions

    transitions.observe("t1", "Ready", title="A", depth_limit=3)
    found, _ = transitions.observe("t1", "Done", title="A", depth_limit=3)
    assert transitions.start(found) and not transitions.start(found), "taken once"
    assert transitions.abandon(-5) == 1, "older than the future: any execution left open"
    (row,) = transitions.history("t1")
    assert row["state"] == "failed" and "interrupted" in row["result"], row
    assert transitions.pending(10) == []
