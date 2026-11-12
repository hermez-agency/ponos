"""Talking rather than working: the comments that are waiting for an answer.

A pass, not a run. Nothing is claimed, no status moves, no worktree is made,
and the session it starts runs under `reply_permission_mode` — the guardrail
that cannot write, in the repository itself rather than in a copy of it, since
there is nothing to isolate when nothing can be changed.

Everything here gives way to the work. A ticket this pass is about to handle is
left alone, because the comment is already going into its prompt; the daemon
starts the pass when a comment arrives rather than on a clock; and no failure
of it ever reaches a ticket.

`conversation.py` reads the threads and decides which are being spoken to; this
is what is done about them — one thread per page per pass, answered in the
thread it was asked in, and the session kept so the next question lands in the
same conversation rather than in a stranger.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import agents, conversation, session, state, store
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .ticket import Ticket, short_id

logger = logging.getLogger(__name__)


class Replies(Base):
    """The runner answering, in the thread it was spoken to in."""

    def talk(self, said: list[dict[str, Any]]) -> None:
        """The answers and the blocked tickets, as one place of a pass's pool.

        They used to come before the pass's first ticket, and `converse` waits
        for the sessions it starts: a ticket made ready alongside a comment
        waited up to `reply_timeout_minutes` for a conversation, with every
        place free. Here they take a place once the tickets have taken theirs,
        and one place only — the answers one after the other — so that what
        runs at once is still `max_concurrent`, whatever it is.

        What they record is put in `said` rather than returned: the place they
        hold is a ticket's, and a ticket's place hands back one result or none.
        Never raises, as neither of the two does a ticket any harm.
        """
        try:
            said += self.converse(places=1)
            said += self.unblock()
        except Exception:
            logger.exception("the comments and the blocked tickets were not looked at")

    def converse(self, *, places: int | None = None) -> list[dict[str, Any]]:
        """Answer the comments that are waiting for an answer.

        A pass, not a run: nothing is claimed, no status moves, no worktree is
        made. It reads the threads on the pages where a conversation could be —
        the tickets this run already looked at, and the ones most recently
        commented on — and replies where it is being spoken to.

        Everything here gives way to the work. A ticket about to be handled is
        left alone, because the comment is already going into its prompt; and
        no failure of it ever reaches a ticket.

        `places` is how many answers may be written at once — `max_concurrent`
        when nothing else is running, one when the pass's tickets are.
        """
        if self.dry_run or not self.config.runner.reply:
            return []
        # An answer is a session too, and the reserve is about sessions. The
        # thread is left unanswered rather than answered badly: the pass that has
        # credit again finds it exactly where it is, with nothing said in between.
        if self.under_reserve():
            return []

        me = self.myself()
        if not me:
            # Without an identity there is no telling our own last word from
            # yours — and a runner answering itself would never stop. Said once,
            # then the tickets.
            reason = self._identity_error or "no user ID came back"
            self.say(f"  ! comments not answered: the board would not say who we are ({reason})")
            return []

        pending = self._pending(me)
        if not pending:
            return []

        self.say(f"  ✎ {len(pending)} comment(s) waiting for an answer")
        workers = min(len(pending), max(1, places or self.config.runner.max_concurrent))
        if workers == 1:
            answers = [self._answer(me, *pending[0])]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                answers = list(pool.map(lambda pair: self._answer(me, *pair), pending))
        results = [answer for answer in answers if answer]
        for result in results:
            state.record(result)
        return results

    def _pending(self, me: str) -> list[tuple[str, conversation.Thread]]:
        """The threads to answer this pass, page by page.

        The pages this run has already read first — their comments are in hand —
        then the tickets most recently commented on.
        """
        spellings = self.spellings()
        seen = list(self._comments)
        recent = [page for page in self.threads.recent() if page not in self._comments]

        pending: list[tuple[str, conversation.Thread]] = []
        for page_id in [*seen, *recent]:
            if page_id in self._claimed:
                continue
            try:
                comments = self.comments(page_id)
            except store.StoreError:
                # Unreadable comments, or a page that has since been deleted.
                # Neither is this pass's business to report on.
                continue
            for thread in conversation.waiting(comments, me=me, spellings=spellings):
                pending.append((page_id, thread))
                break  # one answer per page per pass: a thread at a time
            if len(pending) >= conversation.ANSWERS:
                break
        return pending

    def _answer(self, me: str, page_id: str, thread: conversation.Thread) -> dict[str, Any] | None:
        """Answer one comment, in its thread. Never raises."""
        try:
            return self._answer_thread(me, page_id, thread)
        except store.StoreError as error:
            self.say(f"    ! comment not answered: {voice_module.line(error)}")
        except (OSError, ValueError) as error:
            self.say(f"    ! comment not answered: {error}")
        return None

    def _answer_thread(
        self, me: str, page_id: str, thread: conversation.Thread
    ) -> dict[str, Any] | None:
        ticket = Ticket(self.client.page(page_id))
        spellings = self.spellings()
        message = conversation.strip_mention(thread.last.text, spellings)
        self.say(f"  ✎ {ticket.title} — {' '.join(message.split())[:70]}")

        project = self._project_of(ticket)
        short = short_id(ticket.id)
        if project.is_code and project.path:
            workdir = project.path
            where = (
                f"Repository: {project.path} — read as much of it as you need. "
                "You are not changing it, and the permissions you are running under "
                "will not let you."
            )
        else:
            workdir = conversation.talk_dir(short)
            where = f"Working directory: {workdir} — this ticket has no repository."

        agent = self._agent(ticket)
        text = prompt_module.conversation(
            prompt_module.CONVERSATION,
            project=project.name,
            title=ticket.title,
            body=self._body(ticket),
            where=where,
            url=ticket.url,
            message=message,
            thread=conversation.transcript(thread, me),
            brief=project.brief,
            context=self.workspace.context,
            agent_name=agent.name,
            agent_brief=agent.brief,
            comments=self.discussion(ticket),
            language=self.voice.instruction(reply=True),
        )

        # A comment that names no discussion is a thread of one, keyed by its
        # own id (`conversation.threads`). The answer goes into that id: posted
        # with no discussion it would be a thread of its own, the question would
        # stay the last word of its thread, and every pass would answer it again.
        discussion = thread.last.discussion_id or thread.comments[0].id
        resumed = self.threads.session_of(page_id, discussion) if discussion else ""
        outcome = self._reply_session(
            text,
            workdir,
            short,
            agent,
            ticket,
            session_id=resumed or session.new_id(),
            resume=bool(resumed),
        )
        if not outcome.ok and resumed and not outcome.exhausted:
            # A session Claude Code no longer has — pruned, or filed on another
            # machine. The thread's history is on the board, so a fresh one starts
            # from everything except the tone of the last exchange.
            self.say("    ↻ that conversation could not be resumed — starting a new one")
            self.threads.forget(page_id, discussion)
            outcome = self._reply_session(
                text, workdir, short, agent, ticket, session_id=session.new_id(), resume=False
            )

        if self._out_of_credit(outcome):
            # An answer nobody could afford is not an answer to write down: the
            # thread is left as it was, unanswered, and the pass that runs once
            # the credits are back finds it exactly where it is.
            self.say("    ⏸ out of credit — this one is answered later")
            return None

        answer = conversation.trim(outcome.answer if outcome.ok else "")
        if not answer:
            said = self.voice
            answer = said.say(
                "no-reply",
                error=voice_module.line(outcome.error) or said.say("said-nothing"),
                log=outcome.log,
            )
        self._comment(ticket, answer, discussion)
        if discussion:
            self.threads.remember(page_id, discussion, outcome.session_id)
        cost = f" · ${outcome.cost_usd:.3f}" if outcome.cost_usd else ""
        self.say(f"    ↳ answered · {outcome.seconds / 60:.1f} min{cost}")
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "answered",
            "kind": "comment",
            "project": project.name,
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    def _reply_session(
        self,
        text: str,
        workdir: Path,
        short: str,
        agent: agents.Agent,
        ticket: Ticket,
        *,
        session_id: str,
        resume: bool,
    ) -> session.Outcome:
        """One turn of a conversation, in a permission mode that cannot write.

        `reply_permission_mode` is the guardrail; the prompt only explains it.
        A conversation runs in the repository itself rather than in a worktree —
        there is nothing to isolate when nothing can be changed, and a stable
        directory is what lets the next question land in the same session.
        """
        # A resumed session already carries the frame; what it has not seen is
        # the new message, which is the last section of the prompt we built.
        prompt_text = (
            prompt_module.follow_up(
                prompt_module.message_of(text), self.voice.instruction(reply=True)
            )
            if resume
            else text
        )
        chosen = self.config.runner.allowed(
            str(store.read(ticket.page, self.config.board.prop("model")) or "")
            or agent.model
            or self.config.runner.model
        )
        outcome = self._paid(
            ticket.id,
            prompt_text,
            cwd=workdir,
            log=state.log_file(f"{short}-talk"),
            model=chosen,
            permission_mode=self.config.runner.reply_permission_mode,
            timeout_minutes=self.config.runner.reply_timeout_minutes,
            session_id=session_id,
            resume=resume,
            environment=self.environment_for(chosen),
        )
        self._hold_credits(outcome)
        return outcome
