"""`runner.py`: the pass, and the places it fills."""

from __future__ import annotations

import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from support import _board_runner, _github, _in_progress, _ready, _reviewed, case

from ponos import config as C
from ponos import credits, notion, projects, state, store, workspace
from ponos import git as git_module
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import board as web_board

# -- runner ------------------------------------------------------------------


@case
def a_template_only_body_counts_as_blank():
    """A Notion template fills a new page with empty headings.

    They are not blank text, so without this they would travel into the prompt
    as noise and stop the "everything is in the title" fallback from firing.
    """
    from ponos.ticket import is_blank

    assert is_blank("## Ce qu'il faut faire\n## Où\n## Comment on saura\n")
    assert is_blank("")
    assert is_blank("   \n\n---\n")
    assert not is_blank("## Ce qu'il faut faire\nRetirer le header.")
    assert not is_blank("Une seule ligne de texte")


# -- the queue that refills itself --------------------------------------------


@case
def a_place_freed_mid_pass_is_filled_without_waiting_for_the_long_session(state_home):
    """The whole point of `max_concurrent`, and what a batch used to lose.

    A pass used to prepare the tickets that were ready at its first second and
    wait for every one of them. Measured on a real board: a pass started at
    14:04 with two tickets, one done in minutes and one still running at 14:23,
    while four tickets reached the ready column and not one agent was started —
    three free places and nothing in them.

    Here: two places, a long ticket and a short one, and a third ticket made
    ready while they run. It must start when the *short* one ends — which is
    what the long session witnesses on its way out.
    """
    third_started = threading.Event()
    started: list[str] = []
    witnessed: list[str] = []
    guard = threading.Lock()
    flight = peak = 0

    runner = _board_runner([_ready("p-long"), _ready("p-short")], {})
    runner.config.runner.max_concurrent = 2

    def prepare(ticket):
        return ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

    def execute(job):
        nonlocal flight, peak
        name = job.ticket.page.id  # `Ticket.id` drops the dashes
        with guard:
            started.append(name)
            flight += 1
            peak = max(peak, flight)
        if name == "p-long":
            # Held until the third one has begun: what it sees when it
            # wakes is the whole point of the test.
            third_started.wait(10)
            with guard:
                witnessed.extend(started)
        elif name == "p-short":
            # The board moves on while the long one is still in flight.
            runner.client._pages.append(_ready("p-third"))
        else:
            third_started.set()
        with guard:
            flight -= 1
        return {"ticket": name, "id": name, "status": "done"}

    runner.prepare, runner.execute = prepare, execute
    results = runner._work(runner.queue()[0], None, refill=True)

    assert "p-third" in witnessed, "the freed place was filled while the long one ran"
    assert len(witnessed) == 3, witnessed
    assert peak == 2, "never more than max_concurrent sessions at once"
    assert len(started) == 3, "and the pass ended only once the column was empty"
    assert results[0]["id"] == "p-short", "recorded as it ended, not as it was queued"
    assert sorted(result["id"] for result in results) == ["p-long", "p-short", "p-third"]


@case
def a_project_never_holds_more_places_than_max_concurrent_per_project(state_home):
    """Four tickets, three places: two of one project, then another's goes first.

    The third ticket of project A waits for a place of its own project although
    one is free, and the ticket behind it — project B's — is taken instead. It
    starts once a ticket of A has ended, and all four run.
    """
    guard = threading.Lock()
    inside: dict[str, int] = {}
    peak: dict[str, int] = {}
    order: list[str] = []
    projects_of = {"p-a1": "A", "p-a2": "A", "p-a3": "A", "p-b1": "B"}

    runner = _board_runner([_ready(name) for name in projects_of], {})
    runner.config.runner.max_concurrent = 3
    runner.config.runner.max_concurrent_per_project = 2
    runner.in_repository = lambda ticket: projects_of[ticket.page.id]

    def prepare(ticket):
        return ticket_module.Job(
            ticket,
            projects.Project(name="", path=None),
            branch="",
            base="",
            workdir=Path(tempfile.mkdtemp()) / "doc",
        )

    def execute(job):
        name = job.ticket.page.id
        project = projects_of[name]
        with guard:
            order.append(name)
            inside[project] = inside.get(project, 0) + 1
            peak[project] = max(peak.get(project, 0), inside[project])
        time.sleep(0.3)
        with guard:
            inside[project] -= 1
        return {"ticket": name, "id": name, "status": "done"}

    runner.prepare, runner.execute = prepare, execute
    results = runner._work(runner.queue()[0], None, refill=True)

    assert peak == {"A": 2, "B": 1}, peak
    assert sorted(result["id"] for result in results) == sorted(projects_of), results
    assert order.index("p-b1") < order.index("p-a3"), order


@case
def generated_files_are_declared_in_a_toml_file_and_read_as_globs():
    """`**` crosses folders, `*` does not, and a file that says nothing usable says nothing."""
    from ponos import generated

    rules = generated.parse(
        'generated = ["src/ponos/web/static/**", "*.lock", "docs/**/*.html"]\n'
        'build = " cd frontend && npm run build "\n'
    )
    assert rules.build == "cd frontend && npm run build"
    assert rules.covers("src/ponos/web/static/assets/console-1.js")
    assert rules.covers("src/ponos/web/static/index.html")
    assert rules.covers("uv.lock") and not rules.covers("sub/uv.lock")
    assert rules.covers("docs/a/b/c.html") and rules.covers("docs/c.html")
    assert not rules.covers("src/ponos/web/console.py")
    for broken in ("", "generated = [", 'generated = "dist/**"\nbuild = 3\n'):
        assert generated.parse(broken) == generated.Rules(), broken


@case
def max_concurrent_per_project_defaults_to_two_and_is_never_below_one():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "config.toml"
        assert C.Runner().max_concurrent_per_project == 2
        path.write_text("[runner]\nmax_concurrent_per_project = 0\n", encoding="utf-8")
        assert C.load(path).runner.max_concurrent_per_project == 1
        path.write_text("[runner]\nmax_concurrent_per_project = 3\n", encoding="utf-8")
        assert C.load(path).runner.max_concurrent_per_project == 3


@case
def a_place_that_was_never_filled_is_looked_at_before_a_session_ends(state_home):
    """The other half of the same fault, and the one that shows on a board.

    Tickets arrive one at a time: the first is started, the second place stays
    empty, and the pass then waited for the session in flight before reading the
    board again. Nothing else could read it either — the run lock is the pass's
    until it ends, and the timer meets it and leaves — so `max_concurrent = 2`
    ran one ticket at a time for as long as a ticket was in progress.

    Here: one long ticket, one free place, and a second ticket made ready while
    it runs. It must start while the long one is still in flight, without
    anything having ended.
    """
    second_started = threading.Event()
    started: list[str] = []
    witnessed: list[str] = []
    guard = threading.Lock()

    runner = _board_runner([_ready("p-long")], {})
    runner.config.runner.max_concurrent = 2
    # The cadence the pass looks at the board on, made a test's length.
    runner.config.runner.interval_seconds = 1
    runner.prepare = lambda ticket: ticket_module.Job(
        ticket,
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )

    def execute(job):
        name = job.ticket.page.id
        with guard:
            started.append(name)
        if name == "p-long":
            runner.client._pages.append(_ready("p-second"))
            second_started.wait(10)
            with guard:
                witnessed.extend(started)
        else:
            second_started.set()
        return {"ticket": name, "id": name, "status": "done"}

    runner.execute = execute
    results = runner._work(runner.queue()[0], None, refill=True)

    assert "p-second" in witnessed, "the empty place was filled with nothing ended"
    assert sorted(result["id"] for result in results) == ["p-long", "p-second"]


@case
def a_limit_caps_the_tickets_a_pass_takes_rather_than_the_column(state_home):
    """`--limit` names a number of tickets, and a queue that refills itself
    would otherwise run the whole board on a `--limit 1`."""
    runner = _board_runner([_ready("p-1"), _ready("p-2"), _ready("p-3")], {})
    runner.config.runner.max_concurrent = 4
    runner.prepare = lambda ticket: ticket_module.Job(
        ticket,
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )
    runner.execute = lambda job: {"id": job.ticket.page.id, "status": "done"}
    results = runner._work(runner.queue()[0], 2, refill=True)

    assert sorted(result["id"] for result in results) == ["p-1", "p-2"]


@case
def a_pass_stops_filling_places_once_the_credits_run_out(state_home):
    """A queue that refills itself would otherwise walk the whole column into
    the same wall — one spent session, then every ticket on the board failed."""
    started: list[str] = []

    runner = _board_runner([_ready("p-1"), _ready("p-2"), _ready("p-3")], {})
    runner.config.runner.max_concurrent = 1
    runner.prepare = lambda ticket: ticket_module.Job(
        ticket,
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )

    def execute(job):
        started.append(job.ticket.page.id)
        credits.hold(time.time() + 300)  # what a spent session leaves behind
        return {"id": job.ticket.page.id, "status": "waiting"}

    runner.execute = execute
    results = runner._work(runner.queue()[0], None, refill=True)

    assert started == ["p-1"], "the ticket in flight finished, and nothing else began"
    assert len(results) == 1


def _moved(page: notion.Page, status: str) -> None:
    """The page's status, changed the way a person or a run changes it."""
    page.properties["Status"] = {"type": "status", "status": {"name": status}}


@contextmanager
def _settling(seconds: float):
    """`board.SETTLE`, made a test's length."""
    from ponos import board as board_module

    before, board_module.SETTLE = board_module.SETTLE, seconds
    try:
        yield
    finally:
        board_module.SETTLE = before


@case
def a_new_ticket_is_taken_and_left_alone_once_its_run_has_moved_it(state_home):
    """The plain case, kept honest now that a finished ticket is no longer
    held out for the whole pass: once its status has moved, a reading of the
    board does not bring it back."""
    runs: list[str] = []
    with _settling(0.1):
        page = _ready("p-new")
        runner = _long_runner([page, _ready("p-long")])
        runner.config.runner.max_concurrent = 2

        def execute(job):
            name = job.ticket.page.id
            runs.append(name)
            if name == "p-new":
                _moved(page, "In review")
            else:
                time.sleep(2.5)  # two looks at the board while it runs
            return {"id": name, "status": "done"}

        runner.execute = execute
        runner._work(runner.queue()[0], None, refill=True)

    assert sorted(runs) == ["p-long", "p-new"], runs


@case
def a_ticket_played_by_this_pass_then_made_ready_again_is_played_again(state_home):
    """The fault of the 9th of October, on the real board: two Lead Finder
    tickets run at 22:53 by a pass that was still going at 23:50, blocked on
    their merge, moved back to ready by hand — and skipped by every reading of
    the column, because the pass held out every ticket it had *ever* started,
    while each new ticket went straight through."""
    runs: list[str] = []
    again = threading.Event()
    with _settling(0.1):
        page = _ready("p-again")
        runner = _long_runner([page, _ready("p-long")])
        runner.config.runner.max_concurrent = 2

        def execute(job):
            name = job.ticket.page.id
            runs.append(name)
            if name == "p-again":
                if runs.count("p-again") == 1:
                    _moved(page, "Blocked")
                else:
                    _moved(page, "In review")
                    again.set()
            else:
                time.sleep(0.5)
                _moved(page, "Ready")  # somebody asks for it again
                again.wait(10)
            return {"id": name, "status": "done"}

        runner.execute = execute
        results = runner._work(runner.queue()[0], None, refill=True)

    assert again.is_set(), "taken again by the pass that had already run it"
    assert runs.count("p-again") == 2, runs
    assert [result["id"] for result in results].count("p-again") == 2


@case
def a_ticket_still_in_a_session_of_this_pass_is_not_run_beside_it(state_home):
    """A live claim. Moved back to ready while its session runs — or served as
    ready by a Notion that has not caught up — the ticket waits for that
    session, says why on its card, and is played again once it is over."""
    runs: list[str] = []
    flying = peak = 0
    noted: list[dict] = []
    guard = threading.Lock()
    with _settling(0.1):
        page = _ready("p-one")
        runner = _long_runner([page])
        runner.config.runner.max_concurrent = 2

        def execute(job):
            nonlocal flying, peak
            with guard:
                runs.append(job.ticket.page.id)
                flying += 1
                peak = max(peak, flying)
            if len(runs) == 1:
                time.sleep(2.5)  # two looks at a column that still says ready
                noted.append(state.held())
            else:
                _moved(page, "In review")
            with guard:
                flying -= 1
            return {"id": job.ticket.page.id, "status": "done"}

        runner.execute = execute
        runner._work(runner.queue()[0], None, refill=True)
        left = state.held()
        assert runs == ["p-one"], "not beside itself, and not straight after either"
        # The next pass — the timer's — finds it still ready, and plays it.
        runner._work(runner.queue()[0], None, refill=True)

    assert peak == 1, "never two sessions on one ticket"
    assert runs == ["p-one", "p-one"], "and played again once the first was over"
    assert noted == [{"pone": ("running", "")}], noted
    assert left == {}, "the record goes with the pass"


@case
def a_ready_ticket_with_every_place_taken_says_so_once(state_home):
    said: list[str] = []
    runner = _board_runner([_ready("p-1"), _ready("p-2")], {})
    runner.say = said.append
    queued = runner.queue()[0][1:]
    runner.explain(queued, 1)
    runner.explain(queued, 1)
    assert state.held() == {"p2": ("places", "1")}
    runner.explain([], 1, done=True)
    assert state.held() == {}
    assert said == ["  … p-2 — waiting: all 1 place(s) taken — it starts at the next free one"]


@case
def an_orphan_claim_is_let_go_of_by_the_sweep(state_home):
    """A note of a claim whose ticket is no longer in progress — moved by hand,
    or its run gone without a word — is dropped; one still in progress is not."""
    live = _in_progress("p-live", None)
    live.raw["last_edited_time"] = datetime.now(UTC).isoformat()
    runner = _board_runner([live], {})
    state.claim("plive", "Validated")
    state.claim("pgone", "Validated")
    assert runner.sweep() == 0, "too recent to be called abandoned"
    assert state.claims() == {"plive": "Validated"}


@case
def a_schedules_database_that_answers_404_does_not_hold_the_queue_up(state_home):
    """A side feature down costs a line of the journal, not the whole board.

    The Schedules database was taken out of the integration: every reading of
    it is a 404. The pass says so and goes on, and the ticket in ready starts.
    """
    runner = _board_runner([_ready("p-1")], {})
    runner.config.runner.auto_update = False
    runner.config.runner.reply = False
    runner.announce_idle = False
    runner._workspace = workspace.Workspace(
        tickets="db", projects="projects", agents="agents", schedules="db-schedules"
    )
    read = runner.client.query

    def query(database_id, filter_=None):
        if database_id == "db-schedules":
            raise notion.NotionError("POST /databases/db-schedules/query: 404 object_not_found")
        return read(database_id, filter_)

    runner.client.query = query
    said: list[str] = []
    runner.say = said.append
    started: list[str] = []
    runner.prepare = lambda ticket: started.append(ticket.id)
    runner.tick()
    assert started == ["p1"], (started, said)
    assert any("404" in line for line in said), said

    # A network that is down is still the pass's own business: it stops.
    def unreachable(database_id, filter_=None):
        raise store.Unreachable("POST /databases/db-schedules/query: no DNS answer")

    runner.client.query = unreachable
    try:
        runner.born()
    except store.Unreachable:
        pass
    else:
        raise AssertionError("an unreachable board must stop the pass")


@case
def a_ticket_that_refuses_a_write_does_not_stop_the_sweep_or_the_closing(state_home):
    """One page Notion will not write leaves the others to be put right."""
    stale = "2020-01-01T00:00:00+00:00"
    first, second = _in_progress("p-a", None), _in_progress("p-b", None)
    first.raw["last_edited_time"] = second.raw["last_edited_time"] = stale
    runner = _board_runner([first, second], {})
    written = runner.client.update

    def update(database_id, page_id, values):
        if page_id == "p-a":
            raise notion.NotionError(f"PATCH /pages/{page_id}: 403 restricted_resource")
        written(database_id, page_id, values)

    runner.client.update = update
    said: list[str] = []
    runner.say = said.append
    assert runner.sweep() == 1
    assert [page for page, _ in runner.client.written] == ["p-b"]
    assert any("403" in line for line in said), said

    url = "https://github.com/x/y/pull/"
    runner = _board_runner(
        [_reviewed("p-a", "In review", url + "1"), _reviewed("p-b", "In review", url + "2")],
        {"review": "In review", "done": "Done"},
    )
    written = runner.client.update
    runner.client.update = update
    runner.say = said.append
    with _github({url + "1": "MERGED", url + "2": "MERGED"}):
        assert runner.close_merged() == 1
    assert [page for page, _ in runner.client.written] == ["p-b"]


@case
def a_ready_card_always_says_what_it_is_waiting_for():

    now = datetime(2026, 10, 9, 23, 50, tzinfo=UTC)
    card = {"id": "p1", "column": "ready", "scheduled": ""}

    def held(ticket=card, noted=None, passing=True, timer=True, waits=None):
        found = web_board.held(
            ticket, noted or {}, passing=passing, timer=timer, waits=waits, now=now
        )
        return found.get("reason"), found.get("detail")

    assert web_board.held({**card, "column": "review"}, {}, passing=True, timer=True) == {}
    later = {**card, "scheduled": "2026-10-10T09:00+02:00"}
    assert held(later, waits={"credits": "04:00"}) == ("date", "2026-10-10T09:00+02:00")
    assert held(waits={"credits": "04:00", "reserve": ""}) == ("credits", "04:00")
    assert held(noted={"p1": ("running", "")}) == ("running", "")
    assert held(noted={"p1": ("places", "2")}) == ("places", "2")
    assert held() == ("pass", "")
    assert held(noted={"p1": ("running", "")}, passing=False) == ("next", ""), "a dead pass's note"
    assert held(passing=False, timer=False) == ("timer", "")


# -- a validated ticket never waits for a session ----------------------------


def _long_runner(pages: list[notion.Page]) -> Runner:
    """A runner whose tickets are prepared for free and run for as long as asked."""
    runner = _board_runner(pages, {})
    # The cadence the pass looks at the board on, made a test's length.
    runner.config.runner.interval_seconds = 1
    runner.prepare = lambda ticket: ticket_module.Job(
        ticket,
        projects.Project(name="", path=None),
        branch="",
        base="",
        workdir=Path(tempfile.mkdtemp()) / "doc",
    )
    return runner


@case
def a_pull_request_validated_mid_pass_is_merged_without_waiting_for_the_session(state_home):
    """The fault on a real board: a column full of work you have accepted, and
    a two-hour session it has nothing to do with standing in front of it.

    Here the single place is taken for as long as the merge has not happened, so
    the only way out of the test is the pass looking at the validated column
    while its pool is full. The merge itself costs no place: two `gh` calls in
    the pass's own thread.
    """
    merges: list[str] = []
    merged = threading.Event()

    runner = _long_runner([_ready("p-long")])
    runner.config.runner.max_concurrent = 1  # every place taken, throughout

    def execute(job):
        # Validated by you while the session runs, as it happens on a board.
        runner.client._pages.append(
            _reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")
        )
        merged.wait(10)
        # Two more looks at the column, which still answers "Validated":
        # the fake board only remembers what was written, it does not move.
        time.sleep(2.2)
        return {"id": job.ticket.page.id, "status": "done"}

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        merges.append(url)
        merged.set()
        return "merged"

    runner.execute = execute
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge):
        results = runner._work(runner.queue()[0], None, refill=True)

    assert merged.is_set(), "merged while the session was still running"
    assert merges == ["https://github.com/x/y/pull/1"], "and merged once, not at every look"
    assert sorted(result["id"] for result in results) == ["p-long", "pvalidated"]
    assert ("p-validated", {"Status": "Done"}) in runner.client.written


@case
def a_merge_refused_then_retried_mid_pass_is_asked_for_again(state_home):
    """The cards of the 23rd of October: red at 15:00, blocked, validated
    again by "Retry the merge" — and never looked at by a pass that went on
    until night, which had settled them once and held them out ever after."""
    url = "https://github.com/x/y/pull/1"
    asked: list[str] = []
    merged = threading.Event()
    with _settling(0.1):
        runner = _long_runner([_ready("p-long")])
        runner.config.runner.max_concurrent = 1
        page = _reviewed("p-validated", "Validated", url)

        def execute(job):
            runner.client._pages.append(page)
            merged.wait(10)
            return {"id": job.ticket.page.id, "status": "done"}

        def merge(url: str, method: str = "squash", accounts=None) -> str:
            asked.append(url)
            if len(asked) == 1:
                # Red: the ticket is blocked, and somebody validates it again.
                _moved(page, "Blocked")
                threading.Timer(0.5, _moved, (page, "Validated")).start()
                raise git_module.ChecksNotGreen("failed", ["frontend"])
            merged.set()
            return "merged"

        runner.execute = execute
        with _github({url: "OPEN"}, merge=merge):
            results = runner._work(runner.queue()[0], None, refill=True)

    assert merged.is_set(), "asked for again within the same pass"
    assert asked == [url, url], asked
    assert [result["status"] for result in results if result["id"] == "pvalidated"] == [
        "blocked",
        "done",
    ]


@case
def a_publication_validated_mid_pass_takes_the_next_free_place(state_home):
    """A publication is a session, so it waits for a place — that one, not the
    end of the pass. And it takes it before a ticket nobody has read yet."""
    published: list[str] = []
    out = threading.Event()

    runner = _long_runner([_ready("p-long")])
    runner.config.runner.max_concurrent = 2  # one place taken, one free
    runner._project_of = lambda ticket: projects.Project(name="Blog", path=None)

    def publish(ticket, project):
        published.append(ticket.id)
        out.set()
        return {"ticket": ticket.title, "id": ticket.id, "status": "done"}

    def execute(job):
        runner.client._pages.append(_reviewed("p-post", "Validated", None))
        out.wait(10)
        return {"id": job.ticket.page.id, "status": "done"}

    runner._publish, runner.execute = publish, execute
    results = runner._work(runner.queue()[0], None, refill=True)

    assert published == ["ppost"], "published while the long session ran"
    assert sorted(result["id"] for result in results) == ["p-long", "ppost"]


@case
def a_pass_that_refills_nothing_leaves_the_validated_column_alone(state_home):
    """A named ticket and a dry run take nothing off the board — that column
    included, which `tick` has already read for them."""
    runner = _long_runner([_ready("p-one")])
    runner.client._pages.append(_reviewed("p-post", "Validated", None))
    runner._publish = lambda ticket, project: (_ for _ in ()).throw(
        AssertionError("published by a pass that refills nothing")
    )
    runner.execute = lambda job: {"id": job.ticket.page.id, "status": "done"}
    results = runner._work(runner.queue()[0], None, refill=False)

    assert [result["id"] for result in results] == ["p-one"]


def _paid_then_cut(failure: Exception) -> list[dict]:
    """A document ticket whose session was paid, on a board that refuses its closing write.

    A board in Markdown files rather than a fake: the whole pass runs, the
    session included, and only the write that would close the ticket fails.
    """
    from support import _board, _no_session

    with _board() as board:
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text(
            f'[storage]\nmode = "markdown"\npath = "{board.root}"\n'
            "[runner]\ndry_run = false\nprogress = false\nreply = false\n"
            "auto_update = false\nnotify = false\nattach_sessions = false\n",
            encoding="utf-8",
        )
        page_id = board.create_row(
            "tickets", "Écrire l'annonce", {"Status": "Ready", "Type": "Writing"}
        )
        board.append_markdown(page_id, "Rédige une annonce courte.")
        run = Runner(C.load(path), quiet=True)
        written = run.client.update

        def update(database_id, page_id, values):
            if values.get("Status", "In progress") != "In progress":
                raise failure
            written(database_id, page_id, values)

        run.client.update = update
        with _no_session(answer="C'est écrit.", writes={"ANSWER.md": "# Annonce\n\nVoilà."}):
            return run.tick()


@case
def a_session_whose_ticket_lost_the_network_still_counts_against_the_daily_limit(state_home):
    """Nothing is written for the ticket — it is the next pass's — but the session was paid."""
    results = _paid_then_cut(store.Unreachable("PATCH /pages: no DNS answer"))
    assert results == [], results
    assert state.spent_today() == 0.01, state.spent_today()


@case
def a_session_whose_ticket_crashed_after_it_still_counts_against_the_daily_limit(state_home):
    results = _paid_then_cut(RuntimeError("the board said something unexpected"))
    assert [result["status"] for result in results] == ["failed"], results
    assert state.spent_today() == 0.01, state.spent_today()


@case
def every_session_of_a_run_is_started_through_the_door_that_counts_its_cost():
    """`Base._paid`, and nothing else: a `session.run` called beside it is a
    session the day's limit never hears of."""
    import ponos

    source = Path(ponos.__file__).parent
    chapters = [
        path
        for path in source.glob("*.py")
        if path.name != "base.py" and "(Base)" in path.read_text(encoding="utf-8")
    ]
    assert len(chapters) > 5, chapters
    direct = [path.name for path in chapters if "session.run(" in path.read_text(encoding="utf-8")]
    assert direct == [], f"session.run called beside Base._paid in {direct}"


@case
def a_claim_the_board_refuses_fails_that_ticket_and_not_the_pass(state_home):
    """The audit of the 23rd of October: `prepare` ran in the pass's own thread
    with nothing around it, so a 400 on the claim of one ticket left the pass,
    waited for every session still in flight — hours, sometimes — and never
    recorded what they came to: missing from `ponos history`, and from the
    daily ceiling.

    Here: two places, a session on A, and B whose claim is refused. B fails
    alone, C takes the place, and A is recorded when it ends.
    """
    c_started = threading.Event()
    started: list[str] = []

    runner = _long_runner([_ready("p-a"), _ready("p-b"), _ready("p-c")])
    runner.config.runner.max_concurrent = 2
    prepared = runner.prepare

    def prepare(ticket):
        if ticket.page.id == "p-b":
            raise store.StoreError("400 Bad Request: the claim was refused")
        return prepared(ticket)

    def execute(job):
        name = job.ticket.page.id
        started.append(name)
        if name == "p-a":
            c_started.wait(5)
        else:
            c_started.set()
        return {"ticket": name, "id": name, "status": "done", "cost_usd": 1.5}

    runner.prepare, runner.execute = prepare, execute
    results = runner._work(runner.queue()[0], None, refill=False)

    assert c_started.is_set(), "C started while A was still running"
    assert sorted(started) == ["p-a", "p-c"], started
    statuses = {result["id"]: result["status"] for result in results}
    assert statuses == {"p-a": "done", "pb": "failed", "p-c": "done"}, statuses
    recorded = {entry.get("id") for entry in state.history(limit=10)}
    assert {"p-a", "pb", "p-c"} <= recorded, recorded


@case
def a_merge_that_raises_fails_its_ticket_and_the_next_one_is_merged(state_home):
    """The merges of the validated column happen in the pass's own thread too:
    one that raised used to end the pass, and leave the rest of the column."""
    first, second = "https://github.com/x/y/pull/1", "https://github.com/x/y/pull/2"
    runner = _long_runner(
        [_reviewed("p-one", "Validated", first), _reviewed("p-two", "Validated", second)]
    )
    merges: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        if url == first:
            raise store.StoreError("400 Bad Request")
        merges.append(url)
        return "merged"

    with _github({first: "OPEN", second: "OPEN"}, merge=merge):
        settled, _ = runner.delivering()

    assert merges == [second], merges
    statuses = {entry["id"]: entry["status"] for entry in settled}
    assert statuses == {"pone": "failed", "ptwo": "done"}, statuses
