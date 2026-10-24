"""`reports.py`: what a run writes on a ticket, and what it does when the board says no."""

from __future__ import annotations

import time
from pathlib import Path

from support import _board_runner, _BoardClient, _reviewed, case

from ponos import credits, notion, resources, session, state, store, sync
from ponos import question as question_module
from ponos.ticket import Ticket


def _runner(pages=None, client=None, waiting: bool = False):
    """A runner on a fake board, and the lines it says."""
    runner = _board_runner(list(pages or []), {}, waiting=waiting)
    if client is not None:
        runner.client = client
    runner._memory_warned, runner._disk_warned, runner._disk_tidied = False, False, 0.0
    said: list[str] = []
    runner.say = said.append
    runner._notify = lambda *args, **kwargs: said.append(f"notified: {args[0]}")
    return runner, said


def _ticket(page_id: str = "p-1", status: str = "In progress", **properties) -> Ticket:
    page = _reviewed(page_id, status, None)
    page.properties.update(properties)
    return Ticket(page=page)


def _outcome(**values) -> session.Outcome:
    fields = dict(ok=False, blocked=False, session_id="s-1", summary="", log=Path("/tmp/none"))
    fields.update(values)
    return session.Outcome(**fields)


SESSION = "0b6f1c2e-4a5d-4e6f-8a9b-0c1d2e3f4a5b"


class _Refusing(_BoardClient):
    """A board that refuses any write of more than one column — a Cost typed as text."""

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        if len(values) > 1:
            raise notion.NotionError("400 Cost is expected to be number")
        super().update(database_id, page_id, values)


class _Down(_BoardClient):
    """A board where nothing can be written, nor read back."""

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        raise RuntimeError("Notion is down")

    def page(self, page_id: str) -> notion.Page:
        raise notion.NotionError("503 service unavailable")


# -- the ticket's own columns -------------------------------------------------


@case
def a_column_notion_refuses_is_dropped_and_the_status_written_alone(state_home):
    ticket = _ticket()
    runner, said = _runner([ticket.page], _Refusing([ticket.page]))
    runner._set(ticket, Status="In review", Cost="a lot")
    assert runner.client.written == [("p-1", {"Status": "In review"})]
    assert any("writing the status alone" in line for line in said), said
    assert store.read(ticket.page, "Status") == "In review", "the run remembers what it wrote"


@case
def a_refused_write_without_a_status_is_not_swallowed(state_home):
    ticket = _ticket()
    runner, _ = _runner([ticket.page], _Refusing([ticket.page]))
    try:
        runner._set(ticket, Cost=1.0, Duration=2.0)
    except store.StoreError:
        pass
    else:
        raise AssertionError("only a status is worth a second try")


@case
def a_status_moved_during_the_run_is_left_alone_but_the_work_is_still_written(state_home):
    """You moved the ticket to Done yourself: the run does not put it back in review."""
    ticket = _ticket()
    runner, said = _runner([_reviewed("p-1", "Done", None)])
    runner._set(ticket, Status="In review", Cost=0.42)
    assert runner.client.written == [("p-1", {"Cost": 0.42})]
    assert store.read(ticket.page, "Status") == "Done", "the run now holds what the page says"
    assert any("moved to Done" in line for line in said), said
    conflicts = [entry for entry in sync.journal() if entry["what"] == "conflict"]
    assert conflicts and "In review" in conflicts[-1]["detail"]


@case
def a_write_that_was_only_a_moved_status_writes_nothing(state_home):
    ticket = _ticket()
    runner, _ = _runner([_reviewed("p-1", "Ready", None)])
    runner._set(ticket, Status="Failed")
    assert runner.client.written == []


@case
def a_claim_on_a_ticket_moved_meanwhile_refuses_the_whole_write(state_home):
    ticket = _ticket(status="Ready")
    runner, _ = _runner([_reviewed("p-1", "Cancelled", None)])
    assert not runner._claim(ticket, Status="In progress", Runner="ponos@laptop")
    assert runner.client.written == [], "no runner signature on a ticket it never took"


@case
def a_claim_on_a_page_that_cannot_be_read_back_goes_ahead(state_home):
    """The write that follows meets the same Notion; refusing here would gain nothing."""
    ticket = _ticket(status="Ready")
    runner, _ = _runner([])  # the board does not find the page again: a 404
    assert runner._claim(ticket, Status="In progress")
    assert runner.client.written == [("p-1", {"Status": "In progress"})]
    assert state.phases()[ticket.id][0] == "starting", "taken: its phase starts"


@case
def a_dry_run_writes_nothing_and_takes_every_claim(state_home):
    ticket = _ticket()
    runner, _ = _runner([ticket.page])
    runner.dry_run = True
    runner._set(ticket, Status="Done")
    runner._comment(ticket, "Fait.")
    assert runner._claim(ticket, Status="In progress")
    assert runner.client.written == [] and runner.client.comments_written == []


@case
def leaving_blocked_empties_the_block_cell_and_failing_does_not(state_home):
    blocked = {"type": "select", "select": {"name": "session.question"}}
    ticket = _ticket(status="Blocked", Blocage=blocked)
    runner, _ = _runner([ticket.page])
    runner._set(ticket, Status="Failed")
    assert runner.client.written[-1] == ("p-1", {"Status": "Failed"}), "still a stop: kept"
    ticket = _ticket(status="Blocked", Blocage=blocked)
    runner, _ = _runner([ticket.page])
    runner._set(ticket, Status="Ready")
    assert runner.client.written[-1] == ("p-1", {"Blocage": "", "Status": "Ready"})
    clean = _ticket(status="Blocked")
    runner, _ = _runner([clean.page])
    runner._set(clean, Status="Ready")
    assert runner.client.written[-1] == ("p-1", {"Status": "Ready"}), "a blank cell is not written"


@case
def a_status_held_as_a_select_is_remembered_as_a_select(state_home):
    """A board whose Status column is a select: the page the run holds says it so too."""
    ticket = Ticket(page=notion.Page(id="p-1", url="", title="t", properties={}))
    client = _BoardClient([])
    client.columns["Status"] = "select"
    runner, _ = _runner(client=client)
    runner._set(ticket, Status="In review")
    assert ticket.page.properties["Status"] == {"type": "select", "select": {"name": "In review"}}


@case
def what_a_run_cost_is_written_in_minutes_and_dollars_only_when_there_were_any(state_home):
    runner, _ = _runner()
    assert runner._measures(_outcome(seconds=95)) == {"Duration": 1.6}, "a subscription: no cost"
    assert runner._measures(_outcome(seconds=600, cost_usd=0.12345)) == {
        "Duration": 10.0,
        "Cost": 0.123,
    }


@case
def the_session_cell_is_a_link_on_a_url_column_and_the_bare_id_otherwise(state_home):
    runner, _ = _runner()
    assert runner._session_value(SESSION, None) == SESSION
    runner.client.columns["Session"] = "url"
    runner.config.runner.session_host = "salva@vps"
    link = runner._session_value(SESSION, Path("/srv/work"))
    assert link == f"ponos://session/{SESSION}?cwd=/srv/work&host=salva@vps"


@case
def only_a_ticket_waiting_for_credit_carries_its_session_on(state_home):
    def carried(cell: dict | None, ticked: bool = True, waiting: bool = True) -> str:
        properties = {"Waiting for credit": {"type": "checkbox", "checkbox": ticked}}
        if cell is not None:
            properties["Session"] = cell
        runner, _ = _runner(waiting=waiting)
        return runner._carried_session(_ticket(**properties))

    text = {"type": "rich_text", "rich_text": [{"plain_text": f" {SESSION} "}]}
    link = {"type": "url", "url": f"ponos://session/{SESSION}/?cwd=/srv/work"}
    pasted = {"type": "url", "url": "https://claude.ai/chat/not-a-session"}
    assert carried(text) == SESSION
    assert carried(link) == SESSION, "read back through the deep link"
    assert carried(pasted) == "", "a link somebody pasted is no session"
    assert carried(None) == "", "an emptied cell"
    assert carried(text, ticked=False) == "", "a session that ended is not resumed"
    assert carried(text, waiting=False) == "", "a board without the checkbox"


# -- what is said on the page -------------------------------------------------


class _Mute(_BoardClient):
    """An integration without the comment capabilities."""

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        raise notion.NotionError("403 Insufficient permissions for this endpoint")

    def comments(self, page_id: str) -> list[notion.Comment]:
        raise notion.NotionError("403 Insufficient permissions for this endpoint")


@case
def a_comment_notion_refuses_says_which_capability_is_missing_and_is_not_remembered(state_home):
    ticket = _ticket()
    runner, said = _runner(client=_Mute([]))
    runner._comment(ticket, "Fait.")
    assert any("Insert comments" in line for line in said), said
    assert not runner.ledger.knows("p-1"), "a page nobody spoke on is not one to watch"


@case
def a_comment_written_forgets_the_cached_thread_and_remembers_the_page(state_home):
    ticket = _ticket("p-1-2")
    runner, _ = _runner()
    assert runner.comments("p12") == []
    assert "p12" in runner._comments, "cached under the id without its dashes"
    runner._comment(ticket, "Fait.")
    assert "p12" not in runner._comments, "one comment short: read again next time"
    assert runner.ledger.knows("p-1-2")


@case
def unreadable_comments_are_an_empty_discussion_with_the_capability_named(state_home):
    runner, said = _runner(client=_Mute([]))
    assert runner.discussion(_ticket()) == []
    assert any("Read comments" in line for line in said), said
    assert runner.asked("p-1") is None, "and no question to read an answer against"


class _Thread(_BoardClient):
    def __init__(self, comments: list[notion.Comment]) -> None:
        super().__init__([])
        self.thread = comments

    def comments(self, page_id: str) -> list[notion.Comment]:
        return self.thread

    def me(self) -> str:
        return "u-runner"


CHOICE = (
    "🙋 Blocked — the brief is written\n"
    "Two headers fit the page.\n"
    "Which one goes on the home page?\n"
    "1. The dark one · 2. The light one\n"
    "\n"
    "The worktree is kept."
)


@case
def the_discussion_says_who_spoke_and_reads_an_option_as_what_it_names(state_home):
    runner, _ = _runner(
        client=_Thread(
            [
                notion.Comment("Le header   prend\ntrop de place.", created_by="u-salva"),
                notion.Comment(CHOICE, created_by="u-runner"),
                notion.Comment("Je regarde   ça.", created_by="u-runner"),
                notion.Comment("2", created_by="u-salva"),
            ]
        )
    )
    runner._me = None  # asked of Notion, as a run does
    lines = runner.discussion(_ticket())
    assert lines[0] == "the ticket's author: Le header prend trop de place."
    assert lines[1] == (
        "a previous run: 🙋 Blocked — the brief is written Two headers fit the page. — asked: "
        "Which one goes on the home page? (options: 1. The dark one; 2. The light one)"
    ), "a question is carried whole, not its note"
    assert lines[2] == "answered in the comments, by us: Je regarde ça."
    assert lines[3] == "the ticket's author: 2 (read as: option 2, “The light one”)"
    assert runner.asked("p-1") == question_module.found(CHOICE)


@case
def the_discussion_keeps_the_newest_comments_within_its_budget(state_home):
    many = [notion.Comment(f"remarque {index}", created_by="u-salva") for index in range(15)]
    runner, _ = _runner(client=_Thread(many))
    lines = runner.discussion(_ticket())
    assert len(lines) == 10 and lines[-1].endswith("remarque 14"), "the last ten, newest last"
    long = [notion.Comment(word * 900, created_by="u-salva") for word in "abc"]
    runner, _ = _runner(client=_Thread(long))
    lines = runner.discussion(_ticket())
    assert len(lines) == 2 and lines[-1].endswith("c" * 900), "the oldest is what goes"


@case
def a_report_without_a_question_is_carried_as_its_first_two_lines():
    from ponos.reports import Reports

    report = "✅ To review — 3 commits\nLe header est retiré.\n\nhttps://github.com/x/y/pull/4"
    assert Reports._reported(report) == "✅ To review — 3 commits Le header est retiré."


# -- the endings that are not a result ----------------------------------------


@case
def a_session_that_stopped_is_named_by_what_cut_it_short(state_home):
    runner, _ = _runner()
    killed = runner._why_stopped(_outcome(killed="SIGKILL"), "session.question")
    assert killed[0] == "session.killed" and "SIGKILL" in killed[2]
    runner.config.budget.per_ticket_usd = 2.0
    over = runner._why_stopped(_outcome(over_budget=True), "session.question")
    assert over[0] == "session.over-budget"
    code, _, detail = runner._why_stopped(
        _outcome(blocked=True, summary="Il manque la clé.", error="exit 1"), "session.question"
    )
    assert (code, detail) == ("session.question", "Il manque la clé."), "a blocked one: its summary"
    _, _, detail = runner._why_stopped(_outcome(error="exit 1"), "session.no-answer")
    assert detail == "exit 1", "a failed one: its error"


@case
def a_failure_needs_a_code_the_catalogue_knows(state_home):
    ticket = _ticket()
    runner, _ = _runner([ticket.page])
    try:
        runner._fail(ticket, "Raté", code="no.such-code")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown cause is refused")
    assert runner.client.written == [], "and nothing is written for it"


@case
def a_blocked_session_naming_its_own_cause_is_filed_under_it(state_home):
    ticket = _ticket()
    runner, _ = _runner([ticket.page])
    asked = question_module.Question(ask="Lancer la commande ?", code="access.sudo")
    result = runner._fail(
        ticket, "Il faut root", code="session.question", blocked=True, question=asked
    )
    assert result["code"] == "access.sudo" and result["status"] == "blocked"
    assert runner.client.written[-1][1]["Blocage"] == "access.sudo"
    assert "Lancer la commande ?" in runner.client.comments_written[-1]


@case
def a_crash_whose_failure_cannot_be_written_is_still_a_result(state_home):
    """Notion is the thing that is down: the pass gets its result all the same."""
    ticket = _ticket()
    runner, said = _runner(client=_Down([]))

    def work():
        raise KeyError("Status")

    result = runner._guarded(ticket, work)
    assert result == {
        "ticket": "p-1",
        "id": "p1",
        "status": "failed",
        "reason": "KeyError: 'Status'",
        "code": "runner.crashed",
    }
    assert any("could not be written" in line for line in said), said


@case
def a_ticket_the_network_went_away_under_is_marked_nothing(state_home):
    ticket = _ticket()
    runner, said = _runner([ticket.page])

    def work():
        raise store.Unreachable("Name or service not known")

    assert runner._guarded(ticket, work) is None
    assert runner.client.written == [] and runner.client.comments_written == []
    assert any("unreachable" in line for line in said), said
    assert runner._guarded(ticket, lambda: "a job") == "a job", "anything else comes back as is"


# -- nothing left to spend ----------------------------------------------------


@case
def only_the_subscription_waits_for_its_credits(state_home):
    runner, _ = _runner()
    spent = _outcome(exhausted=True)
    assert runner._out_of_credit(spent)
    assert not runner._out_of_credit(_outcome()), "a session that failed otherwise"
    runner.config.claude.provider = "anthropic"
    assert not runner._out_of_credit(spent), "a key is billed as it goes: no window"
    runner.config.claude.provider = ""
    runner.config.runner.wait_for_credits = False
    assert not runner._out_of_credit(spent), "told not to wait"
    runner._hold_credits(spent)
    assert credits.held() == 0.0, "and nothing is held"


@case
def a_ticket_out_of_credit_goes_back_ticked_with_its_session(state_home):
    ticket = _ticket()
    runner, _ = _runner([ticket.page], waiting=True)
    until = time.time() + 3600
    result = runner._requeue(ticket, "Ready", _outcome(session_id=SESSION, resets_at=until))
    assert runner.client.written[-1] == (
        "p-1",
        {"Status": "Ready", "Waiting for credit": True, "Session": SESSION},
    )
    assert result["status"] == "waiting" and credits.when(until) in result["reason"]
    assert runner.client.comments_written[-1].startswith("⏸"), runner.client.comments_written


@case
def parking_ticks_each_ticket_once_and_empties_its_session(state_home):
    runner, _ = _runner(waiting=True)
    fresh = _ticket("p-fresh", status="Ready", Session={"type": "url", "url": "ponos://x"})
    ticked = _ticket(
        "p-ticked", status="Ready", **{"Waiting for credit": {"type": "checkbox", "checkbox": True}}
    )
    parked = runner.park([fresh, ticked], until=time.time() + 600)
    assert [entry["id"] for entry in parked] == ["pfresh"], "a ticked ticket is left alone"
    assert runner.client.written == [("p-fresh", {"Waiting for credit": True, "Session": ""})]
    assert len(runner.client.comments_written) == 1


@case
def parking_on_a_board_without_the_checkbox_writes_nothing(state_home):
    runner, _ = _runner()
    assert runner.park([_ticket(status="Ready")], until=time.time() + 600) == []
    assert runner.client.written == []


@case
def parking_under_the_days_limit_says_so_rather_than_blaming_the_credit(state_home):
    runner, _ = _runner(waiting=True)
    runner._announce = lambda title, body: None
    runner.config.budget.daily_usd = 1.0
    state.spend(2.5, "p-earlier")
    runner.park([_ticket(status="Ready")])
    budget = runner.voice.say("budget-parked", when="")
    assert budget.split()[0] in runner.client.comments_written[-1], runner.client.comments_written
    assert credits.held(what="budget") > time.time(), "held until midnight"


@case
def a_tidy_that_raises_does_not_stop_the_pass(state_home):
    runner, said = _runner()
    runner.dry_run = False
    runner.config.runner.min_free_disk_mb = 5000

    def broken(now=False):
        raise OSError("permission denied")

    runner.tidy = broken
    original = resources.disk_mb
    resources.disk_mb = lambda path: (1000, 100000)
    try:
        assert not runner.room_on_disk()
    finally:
        resources.disk_mb = original
    assert any("tidy failed: permission denied" in line for line in said), said
    assert "notified: Ponos — disk full" in said


@case
def a_usage_nobody_could_read_is_said_once_and_stops_nothing(state_home):
    runner, said = _runner()
    runner.config.runner.credit_reserve_percent = 5
    original = credits.used
    credits.used = lambda: None
    try:
        assert runner._reserve() == 0.0 and runner._reserve() == 0.0
    finally:
        credits.used = original
    assert sum("could not be read" in line for line in said) == 1, said
