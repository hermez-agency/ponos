"""Looking again at what is blocked, and letting go of what no longer is.

A ticket stops on a question, a missing access, another ticket not done yet —
and then nobody goes back to see whether that still holds. The answer may have
been written somewhere the runner does not watch (the other ticket is done, the
information is now on the page), and the ticket sits in blocked until a person
happens to remember it.

So this is a pass of its own, and the judgement is not a rule: why a ticket
stopped is a sentence, and whether the sentence is still true is a reading of
the board, the page and the repository. A session reads them, under the same
guardrail as a reply (`reply_permission_mode`: it cannot write), and ends on
`DECISION: unblock` or `DECISION: keep` with the reason. Nothing is moved on a
reading the runner cannot parse — a ticket is never unblocked by default.

Every decision is traced twice: on the ticket, where the reason is a comment a
person reads, and in the history (`unblocked` / `kept-blocked`), where it is
counted. What stays blocked says why only when the why changed — the same
sentence every six hours would be the whole of the discussion.

**It is opt-in** (`runner.unblock`), because it spends a session per ticket it
looks at, and it looks at few: at most `BATCH` a pass, each ticket once every
`unblock_interval_seconds`, and never one somebody touched in the last `GRACE`
— a question asked an hour ago is waiting for its answer, not for a second
opinion.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

from . import agents, conversation, credits, session, state, store
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .ticket import Ticket, short_id

# How often the board is asked for what is blocked. The ticket's own clock is
# `unblock_interval_seconds`; this one only keeps a ten-second runner from
# reading the column six times a minute.
PASS = 300

# A ticket edited more recently than this is left alone: it just stopped.
GRACE = 3600

# The sessions one pass may start. The others come at the next one.
BATCH = 3

# How much of the board the session is shown, to find a dependency in.
OVERVIEW = 200

_DECISION = re.compile(r"^\W*DECISION\s*:\s*(unblock|keep)\b", re.IGNORECASE | re.MULTILINE)
_REASON = re.compile(
    r"^\W*REASON\s*:\s*(.+(?:\n(?!\W*DECISION\b).+)*)", re.IGNORECASE | re.MULTILINE
)


def decision(text: str) -> tuple[str, str]:
    """What the session decided and why, or `("", "")` when it did not say.

    The last `DECISION:` line wins — a session thinks aloud before it concludes —
    and a reason is required: an unblocking nobody can justify is not one.
    """
    found = _DECISION.findall(text or "")
    reasons = _REASON.findall(text or "")
    if not found or not reasons:
        return "", ""
    reason = " ".join(reasons[-1].split())
    return (found[-1].lower(), reason) if reason else ("", "")


class Unblocking(Base):
    """The runner reading its blocked column again."""

    def unblock(self) -> list[dict[str, Any]]:
        """Examine a few blocked tickets, and move back the ones that can go.

        Never raises, and never a reason to fail a ticket: it is a pass about
        tickets that already stopped.
        """
        if self.dry_run or not self.config.runner.unblock:
            return []
        if self.under_reserve() or credits.held(what="unblock"):
            return []
        credits.hold(time.time() + PASS, what="unblock")
        try:
            return self._unblock()
        except store.StoreError as error:
            self.say(f"  ! blocked tickets not examined: {voice_module.line(error)}")
            return []

    def _unblock(self) -> list[dict[str, Any]]:
        settings = self.config.notion
        status = settings.prop("status")
        kind = self.client.schema(self.database).get(status, "status")
        blocked = self.client.query(
            self.database, {"property": status, kind: {"equals": settings.state("blocked")}}
        )
        due = [ticket for ticket in map(Ticket, blocked) if self._worth_a_look(ticket)]
        if not due:
            return []
        board = self._overview()
        results: list[dict[str, Any]] = []
        for ticket in due[:BATCH]:
            if self.under_reserve():
                break
            credits.hold(
                time.time() + self.config.runner.unblock_interval_seconds,
                what=f"unblock:{ticket.id}",
            )
            try:
                result = self._examine(ticket, board)
            except (store.StoreError, OSError, ValueError) as error:
                self.say(f"    ! {ticket.title} not examined: {voice_module.line(error)}")
                continue
            if result:
                state.record(result)
                results.append(result)
        return results

    def _worth_a_look(self, ticket: Ticket) -> bool:
        """Not claimed by this pass, not about to be woken, not just stopped, not seen lately."""
        if ticket.id in self._claimed or credits.held(what=f"unblock:{ticket.id}"):
            return False
        flag = self.waiting_flag()
        if flag and store.read(ticket.page, flag):
            return False
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(
                ticket.page.raw.get("last_edited_time", "")
            )
            if age.total_seconds() < GRACE:
                return False
        except ValueError:
            pass
        # An answer under its question already puts it back in the queue.
        return not self._answered(ticket)

    def _overview(self) -> str:
        """Every ticket of the board, a line each: the dependencies are in there."""
        status = self.config.notion.prop("status")
        pages = self.client.query(self.database)
        lines = [
            f"- [{store.read(page, status) or '?'}] {Ticket(page).title} ({short_id(Ticket(page).id)})"
            for page in pages[:OVERVIEW]
        ]
        more = f"\n(and {len(pages) - OVERVIEW} more)" if len(pages) > OVERVIEW else ""
        return "\n".join(lines) + more

    def _examine(self, ticket: Ticket, board: str) -> dict[str, Any] | None:
        project = self._project_of(ticket)
        short = short_id(ticket.id)
        if project.is_code and project.path:
            workdir = project.path
            where = (
                f"Repository: {project.path} — read it if the blockage depends on it. "
                "You are not changing it, and the permissions you are running under will not let you."
            )
        else:
            workdir = conversation.talk_dir(short)
            where = f"Working directory: {workdir} — this ticket has no repository."
        role = store.read(ticket.page, self.config.notion.prop("role")) or []
        agent = (
            agents.resolve(self.client, role[0], self.config.notion.prop("model"))
            if role
            else agents.Agent()
        )
        self.say(f"  🔓 {ticket.title} — is it still blocked?")
        text = prompt_module.conversation(
            prompt_module.UNBLOCK,
            project=project.name,
            title=ticket.title,
            body=self._body(ticket),
            where=where,
            url=ticket.url,
            message=board,
            brief=project.brief,
            context=self.workspace.context,
            agent_name=agent.name,
            agent_brief=agent.brief,
            comments=self.discussion(ticket),
            language=self.voice.instruction(reply=True),
        )
        outcome = self._paid(
            ticket.id,
            text,
            cwd=workdir,
            log=state.log_file(f"{short}-unblock"),
            model=self.config.runner.allowed(
                str(store.read(ticket.page, self.config.notion.prop("model")) or "")
                or agent.model
                or self.config.runner.model
            ),
            permission_mode=self.config.runner.reply_permission_mode,
            timeout_minutes=self.config.runner.reply_timeout_minutes,
            session_id=session.new_id(),
            environment=self.environment,
        )
        self._hold_credits(outcome)
        if self._out_of_credit(outcome):
            credits.release(what=f"unblock:{ticket.id}")
            self.say("    ⏸ out of credit — this one is looked at later")
            return None
        verdict, reason = decision(outcome.answer if outcome.ok else "")
        if not verdict:
            # Unreadable is not "unblock": the ticket stays where it is, and is
            # looked at again when its clock says so.
            self.say("    ? no decision — left blocked, nothing written")
            return None
        said = self.voice
        if verdict == "unblock":
            self._set(
                ticket, **{self.config.notion.prop("status"): self.config.notion.state("ready")}
            )
            self._comment(
                ticket,
                said.report(said.verdict("requeued"), said.say("unblocked", reason=reason)),
            )
            self.say(f"    ↳ unblocked — {reason}")
            outcome_status = "unblocked"
        else:
            note = said.say("kept-blocked", reason=reason)
            if not self._said_last(ticket, note):
                self._comment(ticket, note)
            self.say(f"    ↳ kept blocked — {reason}")
            outcome_status = "kept-blocked"
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": outcome_status,
            "kind": "unblock",
            "project": project.name,
            "reason": reason,
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    def _said_last(self, ticket: Ticket, note: str) -> bool:
        """Is this exact note the last thing on the page? Then it is not said twice."""
        try:
            comments = self.comments(ticket.page.id)
        except store.StoreError:
            return False
        return bool(comments) and comments[-1].text.strip() == note.strip()
