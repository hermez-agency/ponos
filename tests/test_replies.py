"""`replies.py`: answering in the comments, thread by thread."""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from support import ME, _bare_runner, _config, _no_session, _said, case

from ponos import channels, conversation, prompt, store, workspace
from ponos.runner import Runner

# -- the « On » prompt -------------------------------------------------------


class _KnownCommentClient:
    """Comments that say who wrote them, as the board's do."""

    def __init__(self, comments: list[store.Comment]):
        self._comments = comments

    def comments(self, page_id: str) -> list[store.Comment]:
        return self._comments

    def me(self) -> str:
        return ME

    def my_name(self) -> str:
        return "Ponos"


def _knowing(comments: list[store.Comment]) -> Runner:
    runner = _bare_runner(_KnownCommentClient(comments))
    runner.config = _config("")
    runner._me = None  # asked of the board, as in a real run
    runner._spellings = None
    return runner


def _ticket() -> Any:
    """A ticket this machine claimed, so one whose comments are worth reading."""
    runner = {"type": "rich_text", "rich_text": [{"plain_text": "ponos@laptop"}]}
    page = store.Page(id="p", url="", title="t", properties={"Agent": runner})
    return type("T", (), {"page": page})()


REPORT_BY_US = _said("🙋 Blocked.\nQuel en-tête ?", by=ME)


@case
def talking_on_a_ticket_does_not_put_it_back_in_the_queue() -> None:
    """Its own answer is not an instruction it was given — or every conversation
    would end in a run nobody asked for."""
    talked = [
        REPORT_BY_US,
        _said("@claude pourquoi tu demandes ?"),
        _said("parce que la page en a deux.", by=ME),
    ]
    assert not _knowing(talked)._answered(_ticket())
    # And the moment you actually answer the question, it runs again.
    assert _knowing([*talked, _said("celui du dashboard.")])._answered(_ticket())


@case
def an_answer_given_on_your_phone_is_still_your_answer() -> None:
    """It carries the runner's token — the runner is what posts it — and it is
    the ticket's author speaking. So it wakes the ticket exactly as the same
    word typed onto the board would, rather than reading as the runner's own last
    word and closing the very question it answers."""
    relayed = channels.answer(
        channels.Reply(channel="telegram", text="oui", ticket="p", title="t", who="Salvador")
    )
    assert conversation.is_relayed(relayed), "channels and conversation share one sentence"
    assert not conversation.ours(_said(relayed, by=ME), ME)
    assert _knowing([REPORT_BY_US, _said(relayed, by=ME)])._answered(_ticket())
    # And what the runner says in its own voice still is not an answer to itself.
    assert not _knowing([REPORT_BY_US, _said("parce que la page en a deux.", by=ME)])._answered(
        _ticket()
    )


@case
def its_own_answers_are_not_read_back_as_yours() -> None:
    runner = _knowing(
        [
            REPORT_BY_US,
            _said("pourquoi ?"),
            _said("parce que la page en a deux.", by=ME),
            _said("celui du dashboard."),
        ]
    )
    lines = runner.discussion(_ticket())
    assert lines == [
        "a previous run: 🙋 Blocked. — asked: Quel en-tête ?",
        "the ticket's author: pourquoi ?",
        "answered in the comments, by us: parce que la page en a deux.",
        "the ticket's author: celui du dashboard.",
    ], lines


@case
def a_thread_transcript_tells_its_two_voices_apart() -> None:
    thread = conversation.threads(
        [
            _said("✅ Done.", by=ME),
            _said("pourquoi ?"),
            _said("parce que.", by=ME),
            _said("et sinon ?"),
        ]
    )[0]
    lines = conversation.transcript(thread, ME)
    assert lines == [
        "you: ✅ Done.",
        "them: pourquoi ?",
        "you: parce que.",
    ], lines
    assert all("et sinon" not in line for line in lines), (
        "the message being answered is not history"
    )


@case
def the_scan_moves_across_the_board_a_window_at_a_time() -> None:
    """One request per page, and a run that can come round every ten seconds."""
    ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    pages = [f"p{index}" for index in range(5)]
    assert ledger.rotate(pages, 2) == ["p0", "p1"]
    assert ledger.rotate(pages, 2) == ["p2", "p3"]
    assert ledger.rotate(pages, 2) == ["p4", "p0"], "it wraps rather than starting over"
    assert ledger.rotate(pages, 10) == pages, "a window wider than the board is the board"
    assert ledger.rotate([], 2) == []


@case
def the_pass_holds_off_until_its_own_interval_has_passed() -> None:
    ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    assert ledger.due(60), "a runner that has never looked is due at once"
    ledger.stamp()
    assert not ledger.due(60)
    assert ledger.due(0)


@case
def what_the_runner_remembers_survives_a_restart() -> None:
    path = Path(tempfile.mkdtemp()) / "ponos.db"
    ledger = conversation.Ledger(database=path)
    ledger.remember_page("3ca45168-0af4-80ae-9443-de0b65d9abf8")
    ledger.remember_thread("d1", session="s-1", comment="c-1")
    ledger.cursor = 3
    ledger.save()

    again = conversation.Ledger.load(path)
    assert again.known_pages() == ["3ca451680af480ae9443de0b65d9abf8"], "dashes and all"
    assert again.session_of("d1") == "s-1"
    assert again.cursor == 3
    assert conversation.Ledger.load(Path(tempfile.mkdtemp()) / "ponos.db").known_pages() == []


class _ThreadClient:
    """Pages with comments on them, and nothing else."""

    def __init__(self, pages: dict[str, list[store.Comment]]):
        self.pages = pages
        self.asked: list[str] = []

    def comments(self, page_id: str) -> list[store.Comment]:
        self.asked.append(page_id)
        if page_id not in self.pages:
            raise store.StoreError("404 could not find block")
        return self.pages[page_id]

    def my_name(self) -> str:
        return "Ponos"


def _talking(
    pages: dict[str, list[store.Comment]], *, claimed: Iterable[str] = frozenset(), scan: int = 20
) -> Runner:
    runner = _bare_runner(_ThreadClient(pages))
    runner.config = _config("")
    runner.config.runner.reply_scan = scan
    runner._spellings = None  # resolved from the client, as in a real run
    runner._me = ME
    runner._claimed = set(claimed)
    runner._ledger_lock = threading.Lock()
    runner._ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    for page in pages:
        runner._ledger.remember_page(page)
    return runner


def _ledger(runner: Runner) -> conversation.Ledger:
    """The ledger `_talking` gave the runner, which a run may not have."""
    assert runner._ledger is not None
    return runner._ledger


REPLIED_TO = [
    _said("✅ Done.\nFait.", by=ME),
    _said("pourquoi ce nom de branche ?"),
]


@case
def a_ticket_about_to_run_is_left_to_the_run_that_will_read_it() -> None:
    """The comment is already going into its prompt; two answers would be one
    too many, and one of them would be the runner talking over itself."""
    runner = _talking({"pone": REPLIED_TO, "ptwo": REPLIED_TO}, claimed={"ptwo"})
    assert [page for page, _ in runner._pending(ME)] == ["pone"]


@case
def a_pass_answers_one_thread_per_page_and_stops_at_five() -> None:
    two = [
        _said("✅ Done.", by=ME, thread="d1"),
        _said("pourquoi ?", thread="d1"),
        _said("@claude et ici ?", thread="d2"),
    ]
    runner = _talking({"pone": two})
    pending = runner._pending(ME)
    assert len(pending) == 1 and pending[0][1].discussion == "d1", "the next pass takes the other"

    crowd = {f"page{index}": REPLIED_TO for index in range(9)}
    assert len(_talking(crowd)._pending(ME)) == conversation.ANSWERS


@case
def a_page_that_cannot_be_read_costs_that_page_and_nothing_else() -> None:
    runner = _talking({"ptwo": REPLIED_TO})
    _ledger(runner).remember_page("pgone")
    assert [page for page, _ in runner._pending(ME)] == ["ptwo"]


@case
def the_pages_this_run_has_already_read_cost_no_second_request() -> None:
    runner = _talking({"pone": REPLIED_TO})
    runner._comments["pone"] = REPLIED_TO  # as `woken` leaves it
    assert len(runner._pending(ME)) == 1
    assert cast(_ThreadClient, runner.client).asked == [], "nothing was asked of the board twice"


class _TalkingClient(_ThreadClient):
    """A page, its discussion, and what got written back into it."""

    def __init__(self, pages: dict[str, list[store.Comment]], body: str = "Supprimer l'entête."):
        super().__init__(pages)
        self._body = body
        self.posted: list[tuple[str, str, str]] = []

    def me(self) -> str:
        return ME

    def page(self, page_id: str) -> store.Page:
        return store.Page(id=page_id, url=f"https://board.invalid/{page_id}", title="Un ticket")

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._body

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.posted.append((page_id, text, discussion_id))

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        raise AssertionError("a conversation moves nothing on the board")


@case
def answering_a_comment_writes_in_its_thread_and_nowhere_else(state_home: Path) -> None:
    with _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        client = _TalkingClient({"pone": REPLIED_TO})
        runner.client = client  # type: ignore[assignment]  # a fake: a page and its thread
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", context="Je suis Salvador.")
        answered = runner.converse()

    assert len(answered) == 1 and answered[0]["status"] == "answered"
    page, text, discussion = client.posted[0]
    assert (page, discussion) == ("pone", "d1"), "under the question, not at the bottom"
    assert text == "Parce que la branche d'hier était déjà en revue."

    asked = calls[0]
    assert asked["permission_mode"] == "plan", "it talks; it does not work"
    assert asked["resume"] is False and asked["timeout_minutes"] == 10
    assert "pourquoi ce nom de branche ?" in asked["prompt"]
    assert "Supprimer l'entête." in asked["prompt"], "it knows the ticket it is under"
    assert "Je suis Salvador." in asked["prompt"], "and who it is answering"


@case
def a_second_question_lands_in_the_same_conversation(state_home: Path) -> None:
    with _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        client = _TalkingClient({"pone": REPLIED_TO})
        runner.client = client  # type: ignore[assignment]  # a fake: a page and its thread
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
        runner.converse()

        again = [*REPLIED_TO, _said("et le footer ?", ident="c-later")]
        client.pages["pone"] = again
        runner._comments.clear()
        _ledger(runner).at = 0.0  # the interval, not the point of this test
        runner.converse()

    assert len(calls) == 2
    assert calls[1]["resume"] is True and calls[1]["session_id"] == calls[0]["session_id"]
    assert calls[1]["prompt"].strip().endswith("et le footer ?")
    assert "Supprimer l" not in calls[1]["prompt"], "a resumed session has the frame already"


@case
def a_session_that_says_nothing_is_still_answered_for(state_home: Path) -> None:
    """Silence in a thread reads as being ignored, which is worse than a failure."""
    with _no_session(ok=False) as calls:
        runner = _talking({"pone": REPLIED_TO})
        client = _TalkingClient({"pone": REPLIED_TO})
        runner.client = client  # type: ignore[assignment]  # a fake: a page and its thread
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
        runner.converse()

    assert len(calls) == 1, "nothing to resume, so nothing to retry"
    assert "could not answer" in client.posted[0][1]
    assert "log is" in client.posted[0][1], "and where to go and look"


@case
def a_conversation_whose_session_is_gone_starts_a_new_one(state_home: Path) -> None:
    """The transcript was pruned, or the machine changed. The board still has the
    thread, which is enough to carry on from."""
    with _no_session(ok=[True, False, True]) as calls:
        runner = _talking({"pone": REPLIED_TO})
        client = _TalkingClient({"pone": REPLIED_TO})
        runner.client = client  # type: ignore[assignment]  # a fake: a page and its thread
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
        runner.converse()

        client.pages["pone"] = [*REPLIED_TO, _said("et le footer ?", ident="c-later")]
        runner._comments.clear()
        _ledger(runner).at = 0.0
        runner.converse()

    assert [call["resume"] for call in calls] == [False, True, False]
    assert calls[2]["session_id"] != calls[1]["session_id"]
    assert "Supprimer l" in calls[2]["prompt"], "a fresh session is told everything again"
    assert len(client.posted) == 2 and "could not answer" not in client.posted[1][1]


@case
def a_pass_that_is_turned_off_or_too_soon_asks_the_board_nothing(state_home: Path) -> None:
    with _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        client = _TalkingClient({"pone": REPLIED_TO})
        runner.client = client  # type: ignore[assignment]  # a fake: a page and its thread
        runner.dry_run = False
        runner.config.runner.reply = False
        assert runner.converse() == []

        runner.config.runner.reply = True
        _ledger(runner).stamp()
        assert runner.converse() == [], "the interval has not passed"
        assert client.asked == [] and calls == []


@case
def a_conversation_prompt_says_what_it_is_not_allowed_to_do() -> None:
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="Northwind",
        title="t",
        body="b",
        where="Repository: /r",
        url="u",
        message="pourquoi ce nom ?",
        thread=["them: pourquoi ?"],
        context="Je suis Salvador.",
        brief="Ton: direct.",
        agent_name="Rédacteur",
        agent_brief="Deux angles.",
        comments=["a previous run: done. fait"],
    )
    assert "talking, not working" in text
    order = [
        text.index(mark)
        for mark in (
            "b",  # the ticket itself
            "already been said",  # then what was said about it
            "Je suis Salvador.",  # then the widest frame
            "Ton: direct.",  # then the project
            "Deux angles.",  # then the role
            "# Context",  # then the mechanics
            "This thread so far",  # then the conversation being had
            "pourquoi ce nom ?",  # and last, the message to answer
        )
    ]
    assert order == sorted(order), order
    # A resumed session is sent the message and not the whole frame again.
    assert prompt.message_of(text) == "pourquoi ce nom ?"


@case
def a_ticket_without_a_project_still_reads_as_a_sentence() -> None:
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="",
        title="t",
        body="",
        where="Working directory: /tmp/x",
        url="u",
        message="et alors ?",
    )
    assert "that belongs to no project" in text
    assert "This thread so far" not in text and "# Your role" not in text
    assert "everything is in the title" in text


@case
def an_answer_too_long_for_a_comment_is_cut_where_it_breathes() -> None:
    assert conversation.trim("court") == "court"
    long = ("Une phrase. " * 200).strip()
    cut = conversation.trim(long, limit=200)
    assert len(cut) < 400 and cut.endswith("ask for it in pieces.")
    assert cut.split("[…]")[0].rstrip().endswith("."), "cut on a sentence, not mid-word"


@case
def the_role_sits_between_the_project_and_the_mechanics() -> None:
    text = prompt.build(
        prompt.DEFAULT,
        project="Northwind",
        title="t",
        body="b",
        repo="/r",
        branch="br",
        base="main",
        url="u",
        context="Je suis Salvador.",
        brief="Ton: direct.",
        agent_name="Rédacteur",
        agent_brief="Deux ou trois angles, toujours.",
        comments=["the ticket's author: plutôt court."],
    )
    order = [
        text.index(mark)
        for mark in (
            "b",  # the ticket itself
            "already been said",  # then what was said about it
            "Je suis Salvador.",  # then the widest frame
            "Ton: direct.",  # then the project
            "Deux ou trois angles",  # then the role
            "# Context",  # then the mechanics
        )
    ]
    assert order == sorted(order), order
    assert "# Your role — Rédacteur" in text


@case
def a_ticket_with_no_agent_and_no_comments_reads_as_before() -> None:
    common: dict[str, Any] = dict(
        project="Northwind", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    bare = prompt.build(prompt.DEFAULT, **common)
    assert "# Your role" not in bare and "already been said" not in bare
    assert prompt.build(prompt.DEFAULT, **common, comments=[], agent_brief="  ") == bare
