"""`conversation.py`: the discussion on a ticket, and what wakes it back up."""

from __future__ import annotations

import tempfile
from pathlib import Path

from support import (
    ME,
    _bare_runner,
    _CommentClient,
    _config,
    _runner_reading,
    _said,
    _Unblocking,
    case,
)

from ponos import conversation, legacy, notion, session, workspace
from ponos import ticket as ticket_module
from ponos.runner import Runner

# -- the discussion on a ticket ----------------------------------------------


@case
def a_question_a_run_asked_comes_back_with_its_answer():
    _, lines = _runner_reading(
        [
            f"{legacy.OLD}@laptop — blocked.\nThe ticket does not say which header.\n\n"
            "Session: `abc-123` — `claude --resume abc-123`\nLog: /home/x/log.jsonl",
            "Celui du dashboard, pas du site public.",
        ]
    )
    assert lines == [
        "a previous run: blocked. The ticket does not say which header.",
        "the ticket's author: Celui du dashboard, pas du site public.",
    ], lines
    assert "Session:" not in "".join(lines), "the machinery of a past run is not context"


@case
def a_long_discussion_is_cut_from_the_oldest_end():
    _, lines = _runner_reading([f"comment number {index} " + "x" * 300 for index in range(20)])
    assert len(lines) <= 10, "at most the last ten"
    assert sum(len(line) for line in lines) <= 2000
    assert "number 19" in lines[-1], "the newest survives"
    assert "number 0" not in " ".join(lines), "the oldest is what goes"


@case
def comments_the_integration_cannot_read_are_not_a_failure():
    _, lines = _runner_reading([], error="403 API token does not have access")
    assert lines == []


def _answered(texts: list[str], error: str = "", agent: str = "") -> bool:
    """Would a reply on that ticket put it back in the queue?"""
    runner = _bare_runner(_CommentClient(texts, error))
    properties = {}
    if agent:
        properties["Runner"] = {"type": "rich_text", "rich_text": [{"plain_text": agent}]}
    page = notion.Page(id="p-ticket", url="", title="t", properties=properties)
    return runner._answered(type("T", (), {"page": page})())


REPORT = "🙋 Stuck — the ticket does not say which header"


DONE = "✅ To review — PR #1 · 1 commit\nFait."


@case
def answering_a_ticket_the_runner_handled_puts_it_back_in_the_queue():
    """The reply is the whole gesture: nothing to move on the board."""
    assert _answered([REPORT, "Celui du dashboard, pas du site public."])
    # Several rounds, and the answer is still the last word.
    assert _answered([REPORT, "réponse", DONE, "et le footer ?"])


@case
def a_ticket_wakes_only_once_per_answer():
    assert not _answered([REPORT]), "the runner having the last word is not an answer"
    assert not _answered([REPORT, "réponse", DONE]), (
        "the report the next run posts is what closes the ticket again"
    )
    assert not _answered([])


@case
def a_ticket_no_run_of_ours_ever_touched_is_left_alone():
    assert not _answered(["Une question posée avant qu'aucun run n'y touche."])
    # A report no longer says which machine wrote it — the board's own Runner
    # column does, and it is what a second machine reads to leave this alone.
    assert not _answered([DONE, "et pour le footer ?"], agent="ponos@vps"), (
        "a ticket handled by another host is that host's to pick up"
    )
    assert _answered([DONE, "et pour le footer ?"], agent="ponos@laptop")
    assert not _answered([REPORT, "réponse"], error="403 API token does not have access")


@case
def waking_looks_everywhere_but_where_a_status_already_speaks():
    """Done stays done, in review waits on a merge, validated on the runner."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config("")
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    offered: list[str] = []
    runner.client = type(
        "S",
        (),
        {
            "schema": lambda self, database: {"Status": "status"},
            "options": lambda self, database, name: offered,
        },
    )()
    excluded = {
        condition["status"]["does_not_equal"] for condition in runner._woken_filter()["and"]
    }
    assert excluded == {"In review", "Validated", "Done", "Ready", "In progress"}
    assert all(condition["property"] == "Status" for condition in runner._woken_filter()["and"])
    # Five names spoken, and everything else — failed, blocked, whatever the
    # board adds later — left in, because that is where an answer is expected.
    # A ticket waiting for credit is not among them: it never left Ready.
    assert len(runner._woken_filter()["and"]) == 5
    # A cancelled ticket is given up on: a comment under it wakes nothing — on
    # a board that offers the option, since Notion refuses a filter on one it
    # does not know.
    offered.append("Cancelled")
    excluded = {
        condition["status"]["does_not_equal"] for condition in runner._woken_filter()["and"]
    }
    assert excluded == {"In review", "Validated", "Done", "Ready", "In progress", "Cancelled"}


# -- talking in the comments -------------------------------------------------


def _pending(comments: list[notion.Comment], mention: str = "") -> list[conversation.Thread]:
    return conversation.waiting(comments, me=ME, spellings=conversation.names(mention, "Ponos"))


@case
def comments_are_grouped_into_the_threads_they_belong_to():
    grouped = conversation.threads(
        [
            _said("le rapport", by=ME, thread="d1"),
            _said("une remarque sans rapport", thread="d2"),
            _said("et pourquoi ?", thread="d1"),
        ]
    )
    assert [thread.discussion for thread in grouped] == ["d1", "d2"], "in the order they appear"
    assert len(grouped[0].comments) == 2
    assert grouped[0].last.text == "et pourquoi ?"
    assert grouped[0].spoken_by(ME) and not grouped[1].spoken_by(ME)


@case
def a_comment_with_no_thread_of_its_own_is_not_lumped_with_the_others():
    """Notion answered without a discussion: two remarks are still two remarks."""
    grouped = conversation.threads(
        [
            notion.Comment("une chose", id="c1"),
            notion.Comment("une autre", id="c2"),
        ]
    )
    assert len(grouped) == 2


@case
def replying_under_its_report_is_how_you_talk_to_it():
    pending = _pending(
        [
            _said(f"{legacy.OLD}@laptop — done.\nFait.", by=ME),
            _said("pourquoi ce nom de branche ?"),
        ]
    )
    assert [thread.last.text for thread in pending] == ["pourquoi ce nom de branche ?"]


@case
def naming_it_reaches_it_in_a_thread_it_never_spoke_in():
    """A remark of yours is a remark of yours — until you name it."""
    remark = [_said("il faudra penser à prévenir Marie", thread="d9")]
    assert _pending(remark) == []
    assert len(_pending([_said("@claude tu en penses quoi ?", thread="d9")])) == 1
    # The word is yours to choose, and its own name always works.
    assert len(_pending([_said("@ia une idée ?", thread="d9")], mention="@ia")) == 1
    assert len(_pending([_said("Ponos, une idée ?", thread="d9")])) == 1


@case
def it_never_answers_itself():
    """The one failure mode here that would never stop on its own."""
    conversed = [
        _said(f"{legacy.OLD}@laptop — done.\nFait.", by=ME),
        _said("pourquoi ?"),
        _said("parce que la branche existait déjà.", by=ME),
    ]
    assert _pending(conversed) == [], "we had the last word"
    # And without knowing who we are, nothing is answered at all: our own
    # replies would read as somebody else's questions.
    assert conversation.waiting(conversed, me="", spellings=conversation.names()) == []


@case
def a_question_it_has_already_answered_is_not_answered_twice():
    """Notion hands back a thread whose reply is still in flight."""
    ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    ledger.remember_thread("d1", session="s-1", comment="c-42")
    assert ledger.answered("d1") == "c-42"
    assert ledger.session_of("d1") == "s-1", "the next question resumes the same session"
    ledger.forget_session("d1")
    assert ledger.session_of("d1") == "" and ledger.answered("d1") == "c-42"


@case
def naming_it_asks_for_words_where_a_bare_answer_asks_for_work():
    """The `blocked` loop is untouched; the mention is what opts out of it."""
    report = f"{legacy.OLD}@laptop — blocked.\nQuel en-tête ?"
    assert _answered([report, "celui du dashboard."]), "a plain answer still runs the ticket"
    assert not _answered([report, "@claude pourquoi tu demandes ?"])
    assert not _answered([report, "Ponos, pourquoi tu demandes ?"])


@case
def the_name_is_stripped_from_the_message_but_only_where_it_is_a_salutation():
    spellings = conversation.names("", "Ponos")
    assert conversation.strip_mention("@claude pourquoi ?", spellings) == "pourquoi ?"
    assert conversation.strip_mention("@claude — pourquoi ?", spellings) == "pourquoi ?"
    kept = "demande à claude ce qu'il en pense"
    assert conversation.strip_mention(kept, spellings) == kept


@case
def an_unblocking_needs_a_decision_and_a_reason():
    from ponos import unblocking

    said = (
        "Le ticket B est en Done.\nDECISION: unblock\nREASON: B, dont il dépendait,\nest terminé."
    )
    assert unblocking.decision(said) == ("unblock", "B, dont il dépendait, est terminé.")
    assert (
        unblocking.decision(
            "Réflexion.\nDECISION: unblock\nDECISION: keep\nREASON: toujours en attente"
        )[0]
        == "keep"
    ), "the last decision wins"
    for unreadable in ("", "peut-être débloqué", "DECISION: unblock", "DECISION: maybe\nREASON: x"):
        assert unblocking.decision(unreadable) == ("", ""), unreadable


def _unblocking(answer: str, already: list[str] | None = None):
    runner = _bare_runner(None)
    runner.__class__ = _Unblocking
    runner.moved, runner.comments_written = [], list(already or [])
    page = notion.Page(id="p-ticket", url="", title="Ticket A")
    sessions: list[str] = []

    def fake_run(prompt_text, **kwargs):
        sessions.append(prompt_text)
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s-1",
            summary="",
            log=Path("/tmp/none.jsonl"),
            answer=answer,
        )

    original, session.run = session.run, fake_run
    try:
        result = runner._examine(ticket_module.Ticket(page), "- [Done] Ticket B (b)")
    finally:
        session.run = original
    return runner, result, sessions


@case
def a_blocked_ticket_whose_cause_is_gone_goes_back_to_ready_with_the_reason():
    runner, result, sessions = _unblocking("DECISION: unblock\nREASON: Le ticket B est en Done.")
    assert runner.moved == [{"Status": runner.config.notion.state("ready")}], runner.moved
    assert (
        len(runner.comments_written) == 1
        and "Le ticket B est en Done." in runner.comments_written[0]
    )
    assert (result["status"], result["reason"]) == ("unblocked", "Le ticket B est en Done.")
    assert "[Done] Ticket B" in sessions[0], "the session reads the whole board"


@case
def a_blocked_ticket_that_is_still_blocked_stays_and_says_why_once():
    runner, result, _ = _unblocking("DECISION: keep\nREASON: B n'est pas fini.")
    assert runner.moved == [], "nothing moves"
    assert "B n'est pas fini." in runner.comments_written[0]
    assert result["status"] == "kept-blocked"
    again, traced, _ = _unblocking(
        "DECISION: keep\nREASON: B n'est pas fini.", runner.comments_written
    )
    assert len(again.comments_written) == 1, "the same reason is not written twice"
    assert traced["status"] == "kept-blocked", "but the decision is still traced"


@case
def a_session_that_does_not_conclude_never_unblocks_anything():
    runner, result, _ = _unblocking("Je ne sais pas trop.")
    assert runner.moved == [] and runner.comments_written == [] and result is None
