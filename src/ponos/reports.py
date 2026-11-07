"""What a run writes down: on the ticket, on the board, on your phone.

A session does the work; this is everything said *about* it. The columns a
finished ticket fills in, the comment under it, the same words pushed to
Telegram or Slack, and the answer you type back there written onto the page as
an ordinary comment — one road in, one road out, nothing kept in sync on
the side.

The two ways a run ends without a result live here too, and for the same
reason: both are made of what is written rather than of what was done. `_fail`
takes a ticket to failed — or to blocked, when the agent asked a question
rather than guessed — and `_requeue` puts it back in the column it was taken
from, which is the whole of what an exhausted quota has to say.

`voice.py` decides the words and the language; this decides what is worth
saying at all, and where.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from . import (
    blocks,
    board_journal,
    channels,
    conversation,
    credits,
    journal,
    log,
    notifications,
    openrouter,
    priority,
    provider,
    push,
    resources,
    session,
    state,
    store,
    ticket_page,
)
from . import config as config_module
from . import question as question_module
from . import voice as voice_module
from .base import Base
from .channels import capture
from .ticket import Job, Ticket

T = TypeVar("T")

logger = logging.getLogger(__name__)

# How much of a ticket's own history is worth carrying into the prompt.
COMMENT_LIMIT = 10

# How often a low disk may cost a tidy: it reads the whole board.
DISK_TIDY_INTERVAL = 600
COMMENT_CHARS = 2000

# The endings of a run that did no work — out of credit, put back in the queue,
# cut by the network: its line goes into the ticket's history, but the report
# above it stays the last one a session wrote (ticket_page.py).
UNWORKED = ("waiting", "requeued", "interrupted")

# What a session identifier looks like — `session.new_id` draws a UUID4. Matched
# rather than trusted because the Session column is a column like any other: a
# cell somebody typed into must not become a `claude --resume` of its own.
_SESSION_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class Reports(Base):
    """Everything a run says, and everywhere it says it."""

    # -- the ticket's own columns --------------------------------------------

    def _set(self, ticket: Ticket, **values: object) -> None:
        """Write ticket properties, the status above all.

        The status is what the board runs on: it says whether a ticket is taken,
        finished or waiting for someone. The others — who ran it, the session
        link, the cost — are commentary. So a write the board rejects is tried
        again with the status alone, rather than leaving a finished ticket stuck
        in "in progress" because an optional column disagreed about its type.
        """
        if self.dry_run:
            return
        status = self.config.board.prop("status")
        if status in values and not self._still(ticket, str(values[status])):
            values = {name: value for name, value in values.items() if name != status}
            if not values:
                return
        self._write(ticket, values)

    def _claim(self, ticket: Ticket, **values: object) -> bool:
        """Write the status that takes a ticket, and say whether it took.

        Not `_set`: there a status somebody else wrote leaves the other columns
        to be written, since they describe work that was done. A claim comes
        before any work — a ticket moved out of ready while it was being
        prepared (a clone, the naming and classifying sessions: minutes) is
        not to be run at all, nor signed with a runner and a session it never
        had. So a refused status refuses the whole write, and the caller drops
        the ticket.
        """
        if self.dry_run:
            return True
        if not self._still(ticket, str(values[self.config.board.prop("status")])):
            return False
        self._write(ticket, values)
        return True

    def _write(self, ticket: Ticket, values: dict[str, object]) -> None:
        """The write itself, once the status in it is known to be the run's to write."""
        status = self.config.board.prop("status")
        if status in values:
            values = {**self._block_cleared(ticket, str(values[status])), **values}
        try:
            self.client.update(self.database, ticket.page.id, values)
        except store.StoreError as error:
            if status not in values:
                raise
            self.say(
                f"    ! the board refused some properties ({error}) — writing the status alone"
            )
            self.client.update(self.database, ticket.page.id, {status: values[status]})
        if status in values:
            self._remember(ticket, str(values[status]))
            # Taken: it starts. Moved anywhere else: whatever it was going
            # through is over — see `state.enter`.
            if values[status] == self.config.board.state("running"):
                state.enter(ticket.id, "starting")
            else:
                state.leave(ticket.id)

    def _blocked_by(self, code: str) -> dict[str, object]:
        """The board's « Blocage » column, saying which cause a ticket stopped on."""
        return {self.config.board.prop("block"): code}

    def _block_cleared(self, ticket: Ticket, target: str) -> dict[str, object]:
        """The « Blocage » cell emptied, when a ticket that stopped leaves for anywhere else.

        Ridden on whatever status write moves it — taken again, merged, put
        back in ready — so that no road out of blocked has to remember it. Only
        on a card that says something, as for the refusal below.
        """
        settings = self.config.board
        if target == settings.state("blocked"):
            return {}
        block = settings.prop("block")
        return {block: ""} if store.read(ticket.page, block) else {}

    def _refusal_cleared(self, ticket: Ticket) -> dict[str, object]:
        """The card's line emptied, when a forced merge left its refusal there
        — or a killed run its last step, see `sweep`.

        Only on a card that says something: a board without the column, or a
        ticket whose card is already blank, is not written to for nothing.
        """
        progress = self.config.board.prop("progress")
        return {progress: ""} if store.read(ticket.page, progress) else {}

    def _still(self, ticket: Ticket, target: str) -> bool:
        """Is the page still in the column this run last saw it in?

        A session lasts minutes, sometimes half an hour, and the board is yours
        meanwhile: a ticket you moved to done because you did it yourself, or
        back to ready because you rewrote it, must not be put in review by a run
        that has not looked since. So the page is read again before its status
        is written, and a status that is neither what the run last saw nor what
        it is about to write is somebody else's — left alone, said in the log,
        and written in the journal, where the console finds it and marks the
        card. The other columns are still written: they describe the work, and
        the work was done.

        A page that cannot be read is written as before: the write that follows
        would meet the same board, and a refusal there is already handled.
        """
        status = self.config.board.prop("status")
        known = store.read(ticket.page, status)
        try:
            fresh = self.client.page(ticket.page.id)
        except store.StoreError:
            return True
        found = store.read(fresh, status)
        if found in (known, target):
            return True
        if status in fresh.properties:
            ticket.page.properties[status] = fresh.properties[status]
        self.say(
            f"    ! {ticket.title} — moved to {found or 'no status'} on the board during the run; "
            f"{target} is not written over it"
        )
        report = board_journal.Report()
        report.note(
            "conflict",
            "tickets",
            ticket.id,
            ticket.title,
            f"the runner would have written {target}, but the page says {found or 'no status'} "
            f"(it said {known or 'no status'} when the runner last read it); not overwritten",
        )
        board_journal.write_journal(report)
        return False

    def _remember(self, ticket: Ticket, value: str) -> None:
        """What this run just wrote, as the page it holds now says it — so the
        next write compares against the column the ticket is really in."""
        status = self.config.board.prop("status")
        kind = (ticket.page.properties.get(status) or {}).get("type") or self.client.schema(
            self.database
        ).get(status, "status")
        shaped = store.written(kind, value)
        if shaped is not None:
            ticket.page.properties[status] = shaped

    def _measures(self, outcome: session.Outcome) -> dict[str, object]:
        """What the run cost, for the columns that want to know.

        Skipped silently when the database has no such columns — and `cost` is
        zero on a subscription, where the CLI reports none, so it is only
        written when there is something to write.
        """
        values: dict[str, object] = {
            self.config.board.prop("duration"): round(outcome.seconds / 60, 1)
        }
        if outcome.cost_usd:
            values[self.config.board.prop("cost")] = round(outcome.cost_usd, 3)
        return values

    def _session_value(self, session_id: str, home: Path | None) -> str:
        """A deep link if the Session property is a URL, the bare ID otherwise.

        The property's declared type decides: a URL column gets something
        clickable, a text column gets the identifier. Nobody has to configure
        which — the column's type is the switch.
        """
        kind = self.client.schema(self.database).get(self.config.board.prop("session"))
        if kind == "url":
            return session.deep_link(
                session_id,
                home or self.config.runner.workspace_root,
                self.config.runner.session_host,
            )
        return session_id

    def _carried_session(self, ticket: Ticket) -> str:
        """The session to carry on for this ticket, when there is one to carry on.

        Only for a ticket ticked as waiting for credit, and that narrowness is
        the point: everywhere else a ticket runs again, the Session column holds
        a conversation that *ended* — reported on, commented, answered — and
        resuming it would have the agent argue with its own verdict. A window
        that closed mid-sentence is the one case where the conversation is
        genuinely unfinished, and `park` empties the cell of the tickets it
        ticks that were never started at all.

        Read back through whichever shape `_session_value` wrote: a deep link on
        a URL column, the bare identifier on a text one. Anything that is not an
        identifier — a link somebody pasted, an emptied cell — reads as none,
        and the ticket opens a session of its own.
        """
        flag = self.waiting_flag()
        if not flag or not store.read(ticket.page, flag):
            return ""
        raw = str(store.read(ticket.page, self.config.board.prop("session")) or "").strip()
        if "://" in raw:
            raw = raw.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return raw if _SESSION_ID.fullmatch(raw) else ""

    # -- what is said on the page ---------------------------------------------

    def _comment(self, ticket: Ticket, text: str, discussion: str = "") -> None:
        """Say something on a ticket, and remember that we said it.

        Remembering matters: a comment does not change a ticket's columns, so
        there is no asking them which tickets have been commented on since. The pages
        the runner has spoken on are the only affordable place to look for an
        answer — see `conversation.Ledger`.
        """
        if self.dry_run:
            return
        try:
            self.client.comment(ticket.page.id, text, discussion)
        except store.StoreError as error:
            self.say(f"    ! the board refused the comment: {error}")
            return
        self.forget_comments(ticket.page.id)
        with self._ledger_lock:
            self.ledger.remember_page(ticket.page.id)
            self.ledger.save()

    def comments(self, page_id: str) -> list[store.Comment]:
        """The comments of a page, once per run, and never a reason to fail.

        An integration without the *Read comments* capability is the common
        case, not an accident: it is off by default. So a refusal is an empty
        discussion — said once, in `discussion` — rather than a lost ticket.
        """
        key = page_id.replace("-", "")
        if key not in self._comments:
            self._comments[key] = self.client.comments(page_id)
        return self._comments[key]

    def forget_comments(self, page_id: str) -> None:
        """We just wrote on that page; what we cached is one comment short."""
        self._comments.pop(page_id.replace("-", ""), None)

    @property
    def ledger(self) -> conversation.Ledger:
        if self._ledger is None:
            self._ledger = conversation.Ledger.load()
        return self._ledger

    def discussion(self, ticket: Ticket) -> list[str]:
        """What was said on the ticket, ready for the prompt, newest last.

        Bounded twice — the last few comments, and a character budget — because
        a ticket that has been round three times would otherwise spend more of
        the prompt on its own history than on the work.
        """
        try:
            comments = self.comments(ticket.page.id)
        except store.StoreError as error:
            self.say(f"    ! comments not readable: {error}")
            return []

        me = self.myself()
        lines: list[str] = []
        budget = COMMENT_CHARS
        window = comments[-COMMENT_LIMIT:]
        # The question each comment was written under — the last report's, when
        # it asked one — so that a “2” reaches the next session as the option it
        # names rather than as a digit nobody remembers the list of.
        under: list[question_module.Question | None] = []
        asked: question_module.Question | None = None
        for comment in window:
            under.append(asked)
            if voice_module.is_report(comment.text):
                asked = question_module.found(comment.text)
        for index in reversed(range(len(window))):
            comment = window[index]
            text = comment.text
            if conversation.ours(comment, me) and not voice_module.is_report(text):
                # Something the runner said in a thread rather than reported.
                # Attributing it to the ticket's author would have the next run
                # read its own words back as an instruction.
                text = " ".join(text.split())
                who = "answered in the comments, by us"
            elif voice_module.is_report(text):
                # Our own report. Its first two lines hold the verdict and the
                # sentence under it; anything after is a link and, on the
                # reports older runs wrote, the machinery they ended on. A
                # question is the exception: it is said whole, with its options.
                text = self._reported(text)
                who = "a previous run"
            else:
                text = " ".join(text.split())
                who = "the ticket's author"
                meant = question_module.meant(
                    question_module.read(conversation.said(comment.text), under[index])
                )
                if meant:
                    text = f"{text} (read as: {meant})"
            line = f"{who}: {text}"
            budget -= len(line)
            if budget < 0:
                break
            lines.append(line)
        return list(reversed(lines))

    @staticmethod
    def _reported(text: str) -> str:
        """A report as the next session reads it: one line, the question whole."""
        asked = question_module.found(text)
        if not asked:
            return " ".join("\n".join(text.splitlines()[:2]).split())
        told = text.split("\n\n", 1)[0].splitlines()
        told = told[: -2 if asked.mode == "choice" else -1]
        return " ".join(" ".join(told).split()) + f" — asked: {question_module.context(asked)}"

    # -- what reaches you, wherever you are -----------------------------------

    def _tell(
        self,
        event: str,
        ticket: Ticket,
        verdict: str,
        body: str,
        *,
        ask: bool = False,
        code: str = "",
        project: str = "",
        facts: tuple[object, ...] = (),
        summary: str = "",
        pull_request: str = "",
    ) -> None:
        """One moment of a ticket, said everywhere it is worth saying.

        The screen of the machine the runner sits on, and the messaging app you
        actually have on you. Same words as the comment — the same verdict, the
        same sentence under it — because the console's notification and a Telegram
        one are the same event reaching you twice, and telling it twice in two
        ways is how you end up reading both. A question is the same lines too —
        what is done, why it stops, what to answer — so a message you can
        answer already says how; and both carry the ticket's page, because a
        notification you then have to go and find is a notification you do not
        act on.

        `event` is which of them you asked to be told about — `notify.events` —
        and `verdict` is what is being said, which is not the same question: a
        merge and a pull request to read are both `done` to a setting, and *To
        review* and *Merged* to a reader.

        The screen of this machine is the exception to “same words”: it cannot
        follow a link written in them and draws no Markdown, so it is told the
        ticket again — `project` and the session's `summary` — in
        `Voice.desktop`'s words, one notification per ticket, and the pull request goes on a button of its own. It stays on
        screen for a question only, which is the one thing waiting for you.
        """
        said = self.voice
        headline = said.headline(verdict, ticket.title)
        title, text = said.desktop(verdict, ticket.title, project=project, summary=summary or body)
        if not self.dry_run:
            # The bell in the console, which keeps what the screen and the phone
            # only say once. `code` is the cause of a stop, when it is one. A
            # bell rung anew is pushed to the phones subscribed to it, in the
            # desktop's words: plain text, for a lock screen.
            bell = notifications.kind_of(verdict, code)
            if bell and notifications.add(bell, ticket.id, ticket.title):
                push.ring(bell, ticket.id, title, text, contact=self.config.web.email)
        self._notify(
            title,
            text,
            urgent=verdict == "blocked",
            warning=verdict == "failed",
            link=ticket.url,
            pull_request=pull_request,
        )
        settings = self.config.notify
        if self.dry_run or not settings.remote or not settings.wants(event):
            return
        channels.announce(
            settings,
            f"{voice_module.MARKS[verdict]} {headline}\n{body}\n{ticket.url}",
            ticket=ticket.page.id,
            title=ticket.title,
            ask=ask,
        )

    def answers(self) -> int:
        """What you replied in Telegram or Slack, written onto its ticket.

        The bridge is deliberately one line long: an answer becomes a comment,
        and a comment is *already* how a blocked ticket wakes up. A "yes" typed
        on a phone therefore travels the exact path a "yes" typed into the
        console does — same waking rules, same prompt, nothing kept in sync
        on the side.

        First thing in a run, before the queue is read, so that a ticket
        answered thirty seconds ago is picked up by this very run.
        """
        settings = self.config.notify
        if self.dry_run or not settings.replies or not settings.remote:
            return 0

        answered = 0
        for channel in channels.open(settings):
            try:
                replies = channel.collect()
            except channels.ChannelError as error:
                if channels.news(channel.name, str(error)):
                    self.say(f"  ! {channel.name} not readable: {error}")
                continue
            if channels.news(channel.name, ""):
                self.say(f"  ✓ {channel.name} readable again")
            for reply in replies:
                command = capture.parse(reply.text)
                if command:
                    self.ticketed(channel, reply, command)
                    continue
                if not reply.ticket:
                    # Silence for ordinary talk in the room — a bot answering
                    # every message is why nobody keeps one in a channel. A
                    # plain "yes" that landed nowhere is the exception: that one
                    # was meant for us and deserves to be told it missed.
                    if channels.decide(reply.text):
                        channel.acknowledge(reply, self.voice.say("nothing-waiting"))
                    continue
                try:
                    self.client.comment(
                        reply.ticket, channels.answer(reply, self.voice, self.asked(reply.ticket))
                    )
                except store.StoreError as error:
                    self.say(f"    ! the answer could not be written to the board: {error}")
                    channel.acknowledge(reply, self.voice.say("answer-refused", error=error))
                    continue
                answered += 1
                label = reply.title or reply.ticket
                self.say(f"  ↩ {label} — answered from {channel.name}, back in the queue")
                channel.acknowledge(reply, self.voice.say("noted", title=label))
        return answered

    def ticketed(
        self, channel: channels.Channel, reply: channels.Reply, command: capture.Command
    ) -> None:
        """A ticket written from a phone, and told back with its link.

        Only where `allowed_users` names who may write one: a ticket put in Ready
        is a session with `bypassPermissions`, and « anybody who can write in
        the chat » is the right reach for an answer to a question and the wrong
        one for a command. A message from somebody not named never gets here —
        the channel read past it.
        """
        said = self.voice
        if not channel.allowed:
            channel.acknowledge(reply, said.say("ticket-unnamed"))
            return
        text = command.text
        if reply.audio:
            asked = self.config.runner.language.strip()
            try:
                audio, kind = channel.recording(reply)
                heard = openrouter.transcribe(
                    self.config.openrouter,
                    audio,
                    kind,
                    voice_module.understood(asked) if asked else "",
                )
            except (
                channels.ChannelError,
                openrouter.Unavailable,
                openrouter.TranscriptionError,
                ValueError,
            ) as error:
                channel.acknowledge(reply, said.say("ticket-unheard", error=error))
                return
            text = f"{text}\n{heard}".strip()
        known: dict[str, str] = {}
        if self.workspace.projects:
            try:
                for page in self.client.query(self.workspace.projects):
                    if page.title:
                        known[page.title] = page.id
            except store.StoreError:
                pass
        chosen, text = capture.project(text, list(known))
        if not chosen and channel.default_project:
            chosen = capture.project(f"{channel.default_project} .", list(known))[0]
        if not text.strip():
            channel.acknowledge(reply, said.say("ticket-empty"))
            return
        if not chosen and known:
            channel.acknowledge(reply, said.say("ticket-which", names=", ".join(sorted(known))))
            return
        title, body = capture.title_of(text)
        try:
            page_id, url = self._write_ticket(title, body, known.get(chosen, ""), command.ready)
        except store.StoreError as error:
            channel.acknowledge(reply, said.say("ticket-refused", error=error))
            return
        self.say(f"  + {title} — written from {channel.name}")
        channel.acknowledge(
            reply,
            said.say(
                "ticket-created",
                state=said.say("ticket-ready" if command.ready else "ticket-draft"),
                title=title,
                project=chosen or "—",
                url=url,
            ),
        )

    def _write_ticket(self, title: str, body: str, project: str, ready: bool) -> tuple[str, str]:
        """The row for a ticket written from a channel, and its address.

        Type and sub-type are left empty: the classifier fills them in before
        the ticket runs, as on a ticket written in the console. A draft is written
        in the drafts' status — the same rule as the console's « New ticket ».
        """
        settings = self.config.board
        values: dict[str, Any] = {}
        if ready:
            values[settings.prop("status")] = settings.state("ready")
        else:
            values[settings.prop("status")] = settings.state("draft")
        if project:
            values[settings.prop("project")] = [project]
        if settings.prop("priority") in self.client.schema(self.database):
            values[settings.prop("priority")] = self.priority_cell(priority.DEFAULT)
        page_id = self.client.create_row(self.database, title, values)
        self.client.append_markdown(page_id, ticket_page.template(self.voice, body))
        return page_id, self.client.page(page_id).url

    def asked(self, page_id: str) -> question_module.Question | None:
        """The question a ticket is waiting on, read off its last report.

        Only the last one: a ticket that asked, was answered and has reported
        since is waiting on nothing, and an old question must not turn today's
        “2” into an option of yesterday's list. Unreadable comments are no
        question — the answer is still written, as it was typed.
        """
        try:
            comments = self.comments(page_id)
        except store.StoreError:
            return None
        return question_module.waiting(comment.text for comment in comments)

    # -- the endings that are not a result -------------------------------------

    def _why_stopped(self, outcome: session.Outcome, code: str) -> tuple[str, str, str]:
        """The code a session that did not finish ends a ticket on, its sentence and its detail.

        `code` is the runner's word for the ordinary case, and the sentence is
        the one its cause is said with. A session the CLI cut short at the
        ticket's spending limit says so instead, because "it asked you
        something" would send somebody looking for a question that is not there.
        """
        said = self.voice
        if outcome.killed:
            return (
                "session.killed",
                said.say("session-killed"),
                said.say("session-killed-detail", why=outcome.killed),
            )
        if outcome.over_budget:
            limit = said.money(self.config.budget.per_ticket_usd)
            return (
                "session.over-budget",
                said.say("over-ticket-budget", limit=limit),
                said.say("over-ticket-budget-detail"),
            )
        sentence = said.say(blocks.cause(code).said[0])
        return code, sentence, (outcome.summary if outcome.blocked else outcome.error) or ""

    def _fail(
        self,
        ticket: Ticket,
        reason: str,
        detail: str = "",
        *,
        code: str,
        blocked: bool = False,
        question: str | question_module.Question | None = "",
        note: str = "",
        outcome: session.Outcome | None = None,
    ) -> dict[str, Any]:
        """A run that did not get there, said in as few lines as it takes.

        A blocked ticket is laid out as its **question** — what is done, why it
        stops, what to answer: see question.py — because that is the thing
        somebody has to read and answer. The question is the session's own when
        it wrote one, and otherwise whatever the caller asks, as a free one. A
        failed ticket opens on the reason, and says under it what the session
        said before it stopped. `note` is where the rest went — the folded
        block, usually, and the trace itself on a ticket that has no such block:
        see `_filed`.

        `outcome` is the session that ended this way, when there was one: what it
        cost is written like any other run's — a session that asked a question
        or crashed has been paid for all the same, and the day's limit counts it.

        `code` is the cause, from the catalogue (blocks.py) — required, and
        refused when the catalogue does not know it: it goes into the history,
        the run, and the board's « Blocage » column, where the reason's
        sentence could only be read, never counted.
        """
        # A session that stopped on an action it cannot take names it itself
        # (`CODE: access.sudo`): that is the cause, more precisely than ours.
        if (
            blocked
            and isinstance(question, question_module.Question)
            and blocks.known(question.code)
        ):
            code = question.code
        blocks.cause(code)
        spent = {**(self._measures(outcome) if outcome else {}), **self._blocked_by(code)}
        ended: dict[str, object] = (
            {"seconds": round(outcome.seconds, 1), "cost_usd": outcome.cost_usd} if outcome else {}
        )
        if blocked:
            return self._block(ticket, reason, detail, question, note, spent, ended, code)
        said = self.voice
        self.say(f"    ✗ {ticket.title} — {reason}")
        asked = said.sentence(reason)
        self._tell("failed", ticket, "failed", said.brief(asked))
        self._set(
            ticket,
            **{self.config.board.prop("status"): self.config.board.state("blocked"), **spent},
        )
        self._comment(
            ticket,
            said.report(said.verdict("failed", said.brief(asked)), said.brief(detail), note),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "failed",
            "reason": reason,
            "code": code,
            **ended,
        }

    def _block(
        self,
        ticket: Ticket,
        reason: str,
        detail: str,
        question: str | question_module.Question | None,
        note: str,
        spent: dict[str, object],
        ended: dict[str, object],
        code: str,
    ) -> dict[str, Any]:
        """A ticket that stopped on a question, asked in four lines at most.

        Nothing under it says how to answer — the question does, by its kind —
        and nothing says where the rest is: the folded block is on the same
        page, and pointing at it was one more line between the reader and the
        question. A note that *is* the rest, because the page has no such
        block, and a detail the question does not already say, go under a
        blank line, where `question.found` knows not to look.
        """
        said = self.voice
        self.say(f"    ✗ {ticket.title} — {reason}")
        # The session's own question already says everything its RESULT line
        # did; one the runner asks on its behalf may leave a detail out.
        under = said.brief(detail)
        if isinstance(question, question_module.Question):
            under = ""
        else:
            question = question_module.Question(
                ask=str(question or "").strip() or said.sentence(reason)
            )
        lines = said.question(question)
        done = said.brief(question.done)
        # A blocked ticket is a question, and a question is the one thing worth
        # waking somebody for — so it travels with what the agent actually
        # asked, laid out the same way, not with the runner's own summary.
        self._tell(
            "blocked",
            ticket,
            "blocked",
            "\n".join(line for line in (done, *lines) if line),
            ask=True,
            code=code,
            summary=question.ask,
        )
        self._set(
            ticket,
            **{self.config.board.prop("status"): self.config.board.state("blocked"), **spent},
        )
        if under == said.brief(question.ask):
            under = ""
        self._comment(
            ticket,
            said.paragraphs(
                said.report(said.verdict("blocked", done), *lines),
                under,
                note,
            ),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "blocked",
            "reason": reason,
            "code": code,
            **ended,
        }

    def _guarded(
        self, ticket: Ticket, work: Callable[..., T], *arguments: object
    ) -> T | dict[str, Any] | None:
        """Run one ticket's work so that whatever it raises is that ticket's alone.

        A pass runs several tickets at once, and an exception from any of them
        used to come back out of `future.result()` and end the pass: the other
        sessions ran on with nobody left to report them, and the ticket that
        raised stayed "in progress" until a later run swept it back to ready —
        to fail the same way again. Here it fails *as a ticket*, on the board and
        in the history, with what it raised.

        And if even that cannot be written — the board is the thing that is down —
        the pass is still not the one to pay: the result is recorded here, and
        the next run's sweep finds the ticket where it was left.

        Not only sessions come through here: `prepare` and a merge run in the
        pass's own thread, and one that raised there used to leave the pass with
        every session still in flight — waited for, hours sometimes, and never
        recorded. A work that returns something else than a result (`prepare`'s
        `Job`) gets it back as it is; a failure is always a result.
        """
        result: T | dict[str, Any] | None
        try:
            result = work(*arguments)
        except store.Unreachable as error:
            # The network went away under this ticket, not the ticket under the
            # network: it is marked nothing. Left where it is, it is put back to
            # ready by the sweep of the first pass that can reach the board, and
            # its branch — commits and all — is picked up by the attempt after.
            # Its claim is kept, though: a ticket taken from the validated
            # column has to be found as one, and asked about rather than
            # requeued — its post may already be out (see `state.claim`).
            self.say(
                f"    ⏸ {ticket.title} — unreachable ({voice_module.line(error)}); "
                "not marked failed, the next pass carries on"
            )
            self._journal_end(ticket, {"status": "interrupted", "reason": "network"})
            return None
        except Exception as error:  # the point is to catch it all
            logger.exception("%s crashed", ticket.title, extra=log.FILE_ONLY)
            detail = f"{type(error).__name__}: {voice_module.line(error)}"
            state.release(ticket.id)
            try:
                result = self._fail(
                    ticket, self.voice.say("crashed"), detail, code="runner.crashed"
                )
            except Exception as unwritten:
                logger.exception(
                    "%s: the failure could not be written", ticket.title, extra=log.FILE_ONLY
                )
                self.say(
                    f"    ✗ {ticket.title} — {detail}, and the failure could not be "
                    f"written: {voice_module.line(unwritten)}"
                )
                result = {
                    "ticket": ticket.title,
                    "id": ticket.id,
                    "status": "failed",
                    "reason": detail,
                    "code": "runner.crashed",
                }
        if result is None or isinstance(result, dict):
            self._journal_end(ticket, result)
        return result

    def _journal_end(self, ticket: Ticket, result: dict[str, Any] | None) -> None:
        """The run this ticket's session opened, closed on what the ticket came to.

        Here, where every road out of a ticket's work meets — a pull request, a
        question, a crash — rather than after the session: a session that ended
        well and committed nothing is a blocked ticket, and that is what its
        run should say. A piece of work that ran no session has no run to close.
        """
        run = self._journals.pop(ticket.id, None)
        if run is None:
            return
        result = result or {}
        status = str(result.get("status") or "done")
        pull_request = str(result.get("pull_request") or result.get("merged") or "")
        reason = str(result.get("reason") or "")
        report = ticket_page.report(
            self.voice,
            status=status,
            # The session's own sentence when it ended on one; the runner's
            # reason when the ticket stopped on something else than its answer.
            summary=run.summary if status == "done" else reason or run.summary,
            pull_request=pull_request if pull_request.startswith("http") else "",
            answer=run.answer,
            caveats=run.caveats,
        )
        if status in UNWORKED:
            # A session that did no work says nothing of the work: the last
            # report that did stays, and this one is only a line of history.
            earlier = (one.get("report") for one in reversed(journal.history(ticket.id)))
            report = next((said for said in earlier if said), report)
        said = pull_request or reason or run.summary
        run.end(status, said, str(result.get("code") or ""), report)
        if not self.dry_run:
            self._write_done(ticket, report)

    def _write_done(self, ticket: Ticket, report: str, *, strict: bool = False) -> int:
        """The ticket's part « What was done », written again from the journal.

        Replaced and never appended to: the last session's report, then one
        line per session the journal has of the ticket — see ticket_page.py.
        Commentary like the rest of a report: a page that refuses it costs the
        ticket nothing but the part, which the next session writes again —
        unless `strict`, for a text whose deliverable the part is: the error is
        then the caller's. Returns the count of blocks written.
        """
        lines = [
            ticket_page.history_line(self.voice, run, self.config.web.url)
            for run in journal.history(ticket.id)
        ]
        try:
            count = self.client.replace_section(
                ticket.page.id,
                ticket_page.DONE,
                ticket_page.section(self.voice, report, lines),
            )
        except store.StoreError as error:
            if strict:
                raise
            self.say(f"    ! {ticket.title}: its part “what was done” was not written: {error}")
            return 0
        return count

    def _filed(self, job: Job, outcome: session.Outcome, *rest: object) -> str:
        """The machinery of a failed run, said under its report.

        The command that resumes the session, its log, the worktree that was
        kept: worth one look on the day a run failed, and nothing at all on
        every other day — nothing of this is said when a run went right.
        """
        return self.voice.paragraphs(self._trace(job, outcome), *rest)

    def _trace(self, job: Job, outcome: session.Outcome) -> str:
        """Where to look when the report was not enough — and only then.

        One sentence, and only under the report of a run that failed, which is
        the only day anybody has wanted to read it. See `_filed`.
        """
        return self.voice.trace(outcome.resume_command, outcome.log, job.session_home)

    # -- nothing left to spend -------------------------------------------------

    @property
    def _waits_for_credits(self) -> bool:
        """`wait_for_credits`, for the one provider whose credits come in windows.

        A key — Anthropic's or OpenRouter's — is billed as it is used: there is
        no window to wait for and no share of one to keep in reserve, and a
        reading of the subscription's usage says nothing about it. See provider.py.
        """
        return self.config.runner.wait_for_credits and provider.chosen(self.config) == "cli"

    def _out_of_credit(self, outcome: session.Outcome) -> bool:
        """Did this session die on the subscription's quota, and do we wait?

        The two halves of the same question: what happened, which `session.run`
        read off the CLI, and what the configuration says to do about it. With
        `wait_for_credits` off, an exhausted quota is a session failure like any
        other and is reported as one — which is what the runner always did.
        """
        return bool(outcome.exhausted and self._waits_for_credits)

    def _hold_credits(self, outcome: session.Outcome) -> None:
        """Put the runner to sleep until the credits come back.

        On disk rather than in memory: a run is a process the timer starts, so
        the runs that follow only learn this by reading it — see credits.py.
        Said out loud here, once, because those runs are silent about it.
        """
        if not self._out_of_credit(outcome):
            return
        if outcome.signed_out:
            # Said once, however many sessions die on it: the first wins the
            # note, and the passes after it start nothing that could die again.
            if credits.hold_once(outcome.resets_at, what="login"):
                self.say(f"  ⏸ signed out of Claude — nothing is run until `{provider.LOGIN}`")
                self._announce(
                    self.voice.say("signed-out"),
                    self.voice.say("signed-out-detail", command=provider.LOGIN),
                )
            return
        credits.hold(outcome.resets_at)
        when = credits.when(outcome.resets_at)
        self.say(f"  ⏸ out of credit — nothing is run until {when}")
        self._announce(
            self.voice.say("out-of-credit"), self.voice.say("out-of-credit-detail", when=when)
        )

    def _requeue(
        self,
        ticket: Ticket,
        status: str,
        outcome: session.Outcome,
        note: str = "",
        home: Path | None = None,
    ) -> dict[str, Any]:
        """Put a ticket back in the column it came from, ticked, and say why.

        The one way out of a run that is neither a success nor a failure:
        nothing was wrong with the ticket, there was simply nothing left to work
        on it with. So no question is asked and nobody's phone rings — the tick
        is the whole of the message, and the first run with credit again picks
        the ticket up before anything that never started.

        The caller names the column because the two roads out of here come back
        by different doors. A *ticket* goes back to ready and is picked up by
        the queue. A *publication* goes back to validated and is picked up by
        `deliver`, which is the only thing that reads that column — the decision
        to publish has already been taken, and putting it anywhere else would
        both take that decision back and hand a delivery session to the queue as
        though it were work to do. Neither of them moves anywhere it had not
        already been: the attribute is what says that the credit, and not the
        board, is why the ticket is sitting there.
        """
        said = self.voice
        when = credits.when(outcome.resets_at)
        # A sign-in that expired has no hour to give: the ticket waits for one.
        why = (
            said.say("signed-out-back", status=status, command=provider.LOGIN)
            if outcome.signed_out
            else said.say("credits-out", status=status, when=when)
        )
        self.say(f"    ⏸ {ticket.title} — {why}")
        # The session goes with it, because it is what the pass with credit
        # again picks the ticket back up by — and it may not be the one the
        # claim wrote, if the one the claim wrote could not be resumed.
        self._set(
            ticket,
            **{
                self.config.board.prop("status"): status,
                self.config.board.prop("waiting"): True,
                self.config.board.prop("session"): self._session_value(outcome.session_id, home),
            },
        )
        self._comment(
            ticket,
            said.report(
                said.verdict("waiting", why),
                note,
            ),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "waiting",
            "reason": "signed out of Claude"
            if outcome.signed_out
            else f"out of credit until {when}",
        }

    def room_for_a_session(self) -> bool:
        """Is there memory for one more session? Said once while there is not.

        Asked at every free place, like the reserve, and for the same reason:
        what a session costs is not known until it runs, but what the machine
        has left is. Below `min_free_memory_mb` nothing new is started — the
        ticket stays in ready, and a pass with nothing in flight simply ends,
        the next one asking again. What is running is left alone: killing a
        session to save memory would spend what it has already cost.
        """
        free = (
            None
            if self.dry_run
            else resources.short_of_memory(self.config.runner.min_free_memory_mb)
        )
        if free is None:
            self._memory_warned = False
            return self.room_on_cpu() and self.room_on_disk()
        if not self._memory_warned:
            self._memory_warned = True
            self.say(
                self.voice.say(
                    "memory-short", free=free, minimum=self.config.runner.min_free_memory_mb
                )
            )
        return False

    def room_on_cpu(self) -> bool:
        """Are the cores free enough for one more session? Said once while not.

        The memory guard's twin, for the load over the last minute: above
        `max_load_per_core` times the cores nothing new is started, the ticket
        stays in ready, and what is running is left alone. One minute rather
        than five or fifteen: a pass asks again every few seconds, and a load
        that has just come down is room now, not in a quarter of an hour.
        """
        per_core = self.config.runner.max_load_per_core
        measured = None if self.dry_run else resources.overloaded(per_core)
        if measured is None:
            self._load_warned = False
            return True
        if not self._load_warned:
            self._load_warned = True
            load, cores = measured
            self.say(
                self.voice.say(
                    "load-high",
                    load=f"{load:.1f}",
                    ceiling=f"{per_core * cores:g}",
                    per_core=f"{per_core:g}",
                    cores=cores,
                )
            )
        return False

    def room_on_disk(self) -> bool:
        """Is there disk for one more worktree? A tidy first, then a refusal.

        The 19 October 2026 failure: the disk filled, and fifteen tickets
        failed at once on `git worktree add`. Under `min_free_disk_mb` a tidy
        runs (at most every ten minutes — it reads the board), and only if the
        space is still short is nothing started. The ticket is left in ready
        and not blocked: it did nothing wrong, and it starts by itself the
        pass after room is back. What is running is left alone.
        """
        minimum, home = self.config.runner.min_free_disk_mb, config_module.state_dir()
        if self.dry_run or resources.short_of_disk(minimum, home) is None:
            self._disk_warned = False
            return True
        if time.time() - self._disk_tidied > DISK_TIDY_INTERVAL:
            self._disk_tidied = time.time()
            self.say("Disk space is low — tidying before starting anything.")
            try:
                self.tidy(now=True)
            except Exception as error:  # a failed tidy must not stop the pass
                logger.exception("tidy failed", extra=log.FILE_ONLY)
                self.say(f"  ! tidy failed: {error}")
        free = resources.short_of_disk(minimum, home)
        if free is None:
            self._disk_warned = False
            return True
        if not self._disk_warned:
            self._disk_warned = True
            message = self.voice.say("disk-short", free=free, minimum=minimum)
            self.say(message)
            self._notify("Ponos — disk full", message, urgent=True)
        return False

    def under_reserve(self) -> float:
        """The moment nothing new may be started until, or 0.0 while there is room.

        Three lines answer it, and a place that is about to start a session asks
        all of them at once: the subscription spent outright —
        `waiting_for_credits` —, its reserve, below, and the day's spending
        limit — `budget_reached`. Any one is "do not start anything", so every
        gate that already stops on the reserve stops on the other two.
        """
        return self.waiting_for_credits() or self._reserve() or self.budget_reached()

    def budget_reached(self) -> float:
        """The next midnight, once `budget.daily_usd` has been spent; 0.0 before.

        What the sessions cost is written down as each one ends (`state.spend`),
        so a session still in flight counts when it ends, not before: the limit is a gate on starting,
        and a session that began under it is left to finish. Said once — by the
        note, as the reserve is — to the journal and to the phone, because
        a ready column that stays full with nothing running reads as a broken
        runner.
        """
        limit = self.config.budget.daily_usd
        if limit <= 0:
            return 0.0
        spent = state.spent_today()
        if spent < limit:
            if credits.release(what="budget"):
                self.say("  ▶ a new day — carrying on")
            return 0.0
        tomorrow = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        until = tomorrow.timestamp()
        if not credits.held(what="budget"):
            credits.hold(until, what="budget")
            when = credits.when(until)
            self.say(
                f"  ⏸ {spent:.2f} $ spent today, limit {limit:.2f} $ — nothing new until {when}"
            )
            self._announce(
                self.voice.say("budget-reached"),
                self.voice.say(
                    "budget-reached-detail",
                    spent=self.voice.money(spent),
                    limit=self.voice.money(limit),
                    when=when,
                ),
            )
        return until

    def _reserve(self) -> float:
        """The moment the reserve lifts, or 0.0 while there is credit to spend.

        `credit_reserve_percent` is the share of the window this runner refuses
        to touch, so that a subscription the runner has been chewing on all
        afternoon still has something left for the terminal you open yourself.
        Past `100 - reserve`, no session is started — not a ticket's, not a
        publication's, not an answer in a thread. What *is* still done is
        everything that costs nothing: a validated pull request is merged, a
        merged one is closed, the board is swept.

        Asked again every time rather than once per run, and that is the point:
        a pass lasts as long as its longest session, and the sessions in flight
        are what fills the window. Reading it afresh at each free place is what
        makes the line hold *during* a pass rather than only at its top. What is
        said out loud is held to once — by the note, not by a flag, since a run
        is a process the timer starts and the pass after it must stay quiet.

        Three ways this is 0.0, and only one of them is "there is room": the
        setting belongs to a metered subscription, so a runner told not to wait
        for credits has no window to reserve a slice of; and a reading nobody
        could take is a warning, not a stop — see `credits.used`.
        """
        if not self._waits_for_credits:
            return 0.0
        reading = credits.used()
        if reading is None:
            # Once per run, not once per free place: the cache is not going to
            # appear halfway through a pass, and a warning repeated every ten
            # seconds is a warning nobody reads.
            if not self._usage_warned:
                self._usage_warned = True
                self.say(
                    "  ! how much of the subscription is spent could not be read — "
                    "carrying on without the reserve"
                )
            return 0.0
        used, resets_at = reading
        reserve = self.config.runner.credit_reserve_percent
        if used < 100 - reserve:
            # Back under the line: said once, and only by the run that finds it,
            # exactly as the end of a spent window is.
            if credits.release(what="reserve"):
                self.say(f"  ▶ {used:.0f}% of the subscription spent — carrying on")
                self._announce(
                    self.voice.say("credit-again"),
                    self.voice.say("credit-again-detail", used=f"{used:.0f}"),
                )
            return 0.0
        # A window that names no moment still stops the runner; it simply stops
        # it for as long as a blind wait, and the next run asks the cache again.
        until = resets_at or time.time() + credits.BLIND_WAIT
        if not credits.held(what="reserve"):
            credits.hold(until, what="reserve")
            when = credits.when(until)
            self.say(
                f"  ⏸ {used:.0f}% of the subscription spent, {reserve}% reserved — "
                f"nothing new until {when}"
            )
            self._announce(
                self.voice.say("reserve-reached"),
                self.voice.say(
                    "reserve-reached-detail", used=f"{used:.0f}", reserve=reserve, when=when
                ),
            )
        return until

    def park(self, tickets: list[Ticket], until: float = 0.0) -> list[dict[str, Any]]:
        """Tick the tickets nothing could be started for, and leave them be.

        Said on the board rather than only in a journal nobody reads: a ready
        column that stays full while the in-progress one stays empty tells you
        the runner is broken, which is the one thing it is not. And said without
        moving anything, because nothing happened to these tickets — they are
        still ready, which is exactly what they were a second ago, and a column
        they had disappeared into would have claimed otherwise. Ticked once: a
        ticket already ticked is left alone, which is what keeps a wait of four
        hours from being four hours of writes.

        Nothing here asks anything of anybody: no question, no phone. The
        notification for this went out once, when the line was reached.

        `until` is the moment being waited for; unnamed, it is read off whichever
        of the two waits is standing.
        """
        flag = self.waiting_flag()
        if not flag or self.dry_run:
            return []
        said = self.voice
        when = credits.when(until or self.under_reserve() or credits.held())
        # The day's limit has its own sentence: "the credit comes back" would be
        # a lie about money that is not missing, only not to be spent.
        parked_for = (
            "budget-parked"
            if self.budget_reached()
            else "login-parked"
            if credits.held(what="login")
            else "credit-parked"
        )
        parked: list[dict[str, Any]] = []
        for ticket in tickets:
            if store.read(ticket.page, flag):
                continue
            self.say(f"  ⏸ {ticket.title} — {said.say(parked_for, when=when)}")
            # The Session cell is emptied on the way in, and that is what tells
            # this ticket from one `_requeue` ticked on its way out: nothing was
            # started for this one, so there is no conversation to carry on.
            # Whatever was in the cell belongs to a run that *finished* and was
            # reported on — resuming it would have the agent argue with its own
            # verdict. That is not a corner case here: a ticket woken by a
            # comment is queued from `failed`, and is ticked where it stands
            # like any other, so its old session is exactly what would be found.
            self._set(ticket, **{flag: True, self.config.board.prop("session"): ""})
            self._comment(
                ticket,
                said.report(said.verdict("waiting", said.say(parked_for, when=when))),
            )
            parked.append(
                {
                    "ticket": ticket.title,
                    "id": ticket.id,
                    "status": "waiting",
                    "reason": f"out of credit until {when}",
                }
            )
        return parked

    def waiting_for_credits(self) -> float:
        """The moment the credits come back, or 0.0 when there is nothing to wait for.

        Reading it is also what ends the wait: a note whose moment has passed is
        removed here, so the run that finds the credits back is the one that
        says so.
        """
        if not self._waits_for_credits:
            return 0.0
        # Before the credits, and asked of the CLI rather than of a clock:
        # nobody knows when you will sign in again, only whether you have.
        signed_out = credits.held(what="login")
        if signed_out:
            if not provider.cli_login().ok:
                return signed_out
            credits.release(what="login")
            self.say("  ▶ signed in to Claude again — carrying on")
        until = credits.held()
        if until:
            return until
        if credits.release():
            self.say("  ▶ the credits are back — carrying on")
        return 0.0
