"""A ticket that says what happens when its status changes: the « On » column.

A ticket carries a prompt, and every change of its status — yours in Notion,
the runner's when it claims or finishes it, a script's — runs that prompt in a
session of its own, told the old status, the new one and the ticket. The prompt
decides what the transition is worth: « when it goes to validated, create the
deployment ticket » is one line of text on the ticket rather than a feature.

**A change is something this module saw, not something it was told.** Nothing in
the runner announces a status moving; Notion's board is moved from four places,
one of them a person's browser. So the board is read — only the tickets whose
« On » is filled, at most once in `on_interval_seconds` — and compared with the
status each was last seen with. The first sight of a ticket is a starting point,
never a change: switching the feature on must not replay every ticket's history.
Two changes between two readings are one change, from the first status to the
last; there is no other way to be cheap on a rate-limited board.

**One execution per change, and written down before it starts.** `watched` moves
forward and `transitions` gains its row in the same transaction, so a restart
finds the change either on both sides or on neither. A row left `running` by a
run that died is closed as interrupted and *not* run again: the session may have
done half of what it was asked, and a second go at « create the ticket » is two
tickets. A session that never started for want of credit goes back to pending —
nothing was done, so nothing is repeated.

**Not a loop.** A prompt that moves a status would otherwise wake itself, or the
prompt of a ticket it just created, for ever. Every status that changed while an
execution ran (its own ticket's included) is adopted as the new starting point
without running anything, and a ticket the execution created is filed one
generation below it: past `on_max_depth` its changes run nothing. A person who
edits a ticket during those minutes loses that one transition — the price of not
asking the session to tell us what it touched.

An execution is a session that acts, so it has a ceiling on what it spends
(`budget.on_usd`, through the CLI's own budget) and its errors never reach the
status: they are a comment on the ticket and a line in `ponos.db`, which the
console shows beside the form.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import agents, conversation, db, session, state, store
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .ticket import Ticket, short_id

# The executions one pass may run. The others wait for the next, with their
# change already written down: a board of forty tickets moved at once is not
# forty sessions in a row in front of the ready column.
BATCH = 3

# How much of the result a row keeps: it is read in a table, not archived.
RESULT = 600

PENDING = "pending"
RUNNING = "running"
OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def observe(ticket: str, status: str, *, title: str, depth_limit: int) -> tuple[int, str]:
    """Remember the status a ticket has now; (the id of the change, the old status) if it moved.

    The comparison, the new baseline and the row of the change are one
    transaction — see the module docstring. `(0, "")` for no change, which
    includes a ticket never seen before and a change too deep down a chain to run.
    """
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT status, depth FROM watched WHERE ticket = ?", (ticket,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO watched (ticket, status, depth, at) VALUES (?, ?, 0, ?)",
                (ticket, status, _now()),
            )
            return 0, ""
        old, depth = str(row[0]), int(row[1])
        if old == status:
            return 0, ""
        connection.execute(
            "UPDATE watched SET status = ?, at = ? WHERE ticket = ?", (status, _now(), ticket)
        )
        too_deep = depth > depth_limit
        cursor = connection.execute(
            "INSERT INTO transitions"
            " (ticket, title, old, new, depth, state, seen_at, ended_at, result)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ticket, title, old, status, depth,
                SKIPPED if too_deep else PENDING, _now(), _now() if too_deep else "",
                f"chain deeper than {depth_limit} generation(s): not run" if too_deep else "",
            ),
        )
        return (0 if too_deep else int(cursor.lastrowid or 0)), old


def forget(kept: set[str]) -> None:
    """Stop watching the tickets that no longer carry a prompt.

    Their last status would be stale the day a prompt is written again, and the
    gap would run it for a change that happened long before. A ticket born of an
    execution (depth above zero) keeps its row, which is the only place its
    generation is written.
    """
    with db.transaction() as connection:
        known = [row[0] for row in connection.execute("SELECT ticket FROM watched WHERE depth = 0")]
        for ticket in known:
            if ticket not in kept:
                connection.execute("DELETE FROM watched WHERE ticket = ?", (ticket,))


def adopt(ticket: str, status: str, depth: int | None = None) -> None:
    """Take `status` as this ticket's starting point without running anything.

    `depth` is given for a ticket an execution created, and left alone for one
    it only moved.
    """
    with db.transaction() as connection:
        row = connection.execute("SELECT depth FROM watched WHERE ticket = ?", (ticket,)).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO watched (ticket, status, depth, at) VALUES (?, ?, ?, ?)",
                (ticket, status, depth or 0, _now()),
            )
        elif depth is not None:
            connection.execute(
                "UPDATE watched SET status = ?, depth = ?, at = ? WHERE ticket = ?",
                (status, depth, _now(), ticket),
            )
        else:
            connection.execute(
                "UPDATE watched SET status = ?, at = ? WHERE ticket = ?", (status, _now(), ticket)
            )


def abandon(older_than_seconds: float) -> int:
    """Close the executions a run died in the middle of. Never run again."""
    cutoff = datetime.fromtimestamp(time.time() - older_than_seconds, timezone.utc).isoformat(
        timespec="seconds"
    )
    try:
        with db.transaction() as connection:
            return connection.execute(
                "UPDATE transitions SET state = ?, ended_at = ?, result = ?"
                " WHERE state = ? AND started_at < ?",
                (FAILED, _now(), "interrupted: the runner stopped during this execution",
                 RUNNING, cutoff),
            ).rowcount
    except db.ERRORS:
        return 0


def pending(limit: int) -> list[dict]:
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT id, ticket, title, project, old, new, depth FROM transitions"
            " WHERE state = ? ORDER BY id LIMIT ?",
            (PENDING, limit),
        ).fetchall()
    keys = ("id", "ticket", "title", "project", "old", "new", "depth")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def start(identifier: int) -> bool:
    """Take a pending change for execution; False when somebody else has it."""
    with db.transaction() as connection:
        return connection.execute(
            "UPDATE transitions SET state = ?, started_at = ? WHERE id = ? AND state = ?",
            (RUNNING, _now(), identifier, PENDING),
        ).rowcount == 1


def requeue(identifier: int) -> None:
    """The session never started (no credit): the change is still to be run."""
    with db.transaction() as connection:
        connection.execute(
            "UPDATE transitions SET state = ?, started_at = '' WHERE id = ?", (PENDING, identifier)
        )


def finish(
    identifier: int, outcome: str, *, result: str = "", cost: float | None = None,
    seconds: float | None = None, session_id: str = "", project: str = "",
) -> None:
    with db.transaction() as connection:
        connection.execute(
            "UPDATE transitions SET state = ?, ended_at = ?, result = ?, cost_usd = ?,"
            " seconds = ?, session = ?, project = ? WHERE id = ?",
            (outcome, _now(), result[:RESULT], cost, seconds, session_id, project, identifier),
        )


def history(ticket: str, limit: int = 50) -> list[dict]:
    """The executions of one ticket's prompt, newest first. Empty when unreadable."""
    keys = ("id", "old", "new", "depth", "state", "seen_at", "started_at", "ended_at",
            "cost_usd", "seconds", "session", "result")
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(keys)} FROM transitions WHERE ticket = ? ORDER BY id DESC LIMIT ?",
                (ticket.replace("-", ""), limit),
            ).fetchall()
    except db.ERRORS:
        return []
    return [dict(zip(keys, row, strict=True)) for row in rows]


class Transitions(Base):
    """The runner reading its board for statuses that moved."""

    # When the board was last read for them. A class default and not a line of
    # `Base.__init__`: it is this chapter's own and nobody else reads it.
    _on_read = float("-inf")

    def transitions(self) -> list[dict]:
        """See what moved since the last reading, and run the prompts it wakes.

        Never raises and never touches a status: it is a pass about what the
        board already did.
        """
        if self.dry_run or not self.config.runner.on:
            return []
        now = time.monotonic()
        if now - self._on_read < self.config.runner.on_interval_seconds:
            return []
        self._on_read = now
        try:
            self._watch()
            if self.under_reserve():
                return []
            return self._run_pending()
        except store.Unreachable:
            # The pass's own business: it stops quietly, and so does this.
            raise
        except (store.StoreError, *db.ERRORS) as error:
            self.say(f"  ! « On » not read: {voice_module.line(error)}")
            return []

    def _watch(self) -> None:
        settings = self.config.notion
        column, status = settings.prop("on"), settings.prop("status")
        if column not in self.client.schema(self.database):
            return
        abandon(self.config.runner.on_timeout_minutes * 60 + 300)
        pages = self.client.query(
            self.database, {"property": column, "rich_text": {"is_not_empty": True}}
        )
        carrying = [page for page in pages if store.read(page, column)]
        forget({Ticket(page).id for page in carrying})
        for page in carrying:
            ticket = Ticket(page)
            current = str(store.read(page, status) or "")
            if not current:
                continue
            found, old = observe(
                ticket.id, current, title=ticket.title, depth_limit=self.config.runner.on_max_depth
            )
            if found:
                self.say(f"  ⇄ {ticket.title} — {old} → {current}")

    def _run_pending(self) -> list[dict]:
        results: list[dict] = []
        for row in pending(BATCH):
            if self.under_reserve():
                break
            if not start(row["id"]):
                continue
            try:
                result = self._fire(row)
            except (store.StoreError, OSError, ValueError) as error:
                reason = voice_module.line(error)
                finish(row["id"], FAILED, result=reason)
                self._complain(row, reason)
                result = None
            if result:
                state.record(result)
                results.append(result)
        return results

    def _complain(self, row: dict, reason: str) -> None:
        """Say on the ticket that its prompt failed. The status is not touched."""
        try:
            page = self.client.page(row["ticket"])
        except store.StoreError:
            return
        said = self.voice.say("on-failed", old=row["old"], new=row["new"], reason=reason)
        self._comment(Ticket(page), said)

    def _fire(self, row: dict) -> dict | None:
        """Run one change's prompt. The row is finished here, whatever happens."""
        settings = self.config.notion
        ticket = Ticket(self.client.page(row["ticket"]))
        prompt = str(store.read(ticket.page, settings.prop("on")) or "")
        if not prompt:
            finish(row["id"], SKIPPED, result="the prompt was emptied before it ran")
            return None
        project = self._project_of(ticket)
        short = short_id(ticket.id)
        if project.is_code and project.path:
            workdir = conversation.talk_dir(short)
            where = (
                f"Repository: {project.path} — read it as much as you need, and do not "
                f"change it. Your working directory is {workdir}, which belongs to nobody."
            )
        else:
            workdir = conversation.talk_dir(short)
            where = f"Working directory: {workdir} — this ticket has no repository."
        role = store.read(ticket.page, settings.prop("role")) or []
        agent = (
            agents.resolve(self.client, role[0], settings.prop("model")) if role else agents.Agent()
        )
        before = self._statuses()
        self.say(f"  ⇄ {ticket.title} — « On » : {row['old']} → {row['new']}")
        text = prompt_module.conversation(
            prompt_module.ON_STATUS,
            project=project.name,
            title=ticket.title,
            body=self._body(ticket),
            where=where,
            url=ticket.url,
            message=self._describe(ticket, row, prompt, project.name),
            brief=project.brief,
            context=self.workspace.context,
            agent_name=agent.name,
            agent_brief=agent.brief,
            comments=self.discussion(ticket),
            language=self.voice.instruction(reply=True),
        )
        limit = self.config.budget.on_usd
        outcome = session.run(
            text,
            cwd=workdir,
            log=state.log_file(f"{short}-on"),
            model=self.config.runner.allowed(
                str(store.read(ticket.page, settings.prop("model")) or "")
                or agent.model
                or self.config.runner.model
            ),
            permission_mode=self.config.runner.on_permission_mode
            or self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.on_timeout_minutes,
            session_id=session.new_id(),
            environment=self.environment,
            max_budget_usd=limit,
        )
        self._hold_credits(outcome)
        if self._out_of_credit(outcome):
            requeue(row["id"])
            self.say("    ⏸ out of credit — this one is run later")
            return None
        self._settle(before, row)
        said = self.voice
        if outcome.over_budget:
            reason = said.say("on-over-budget", limit=limit)
        elif not outcome.ok or outcome.blocked:
            reason = voice_module.line(outcome.error) or voice_module.line(outcome.summary) \
                or said.say("on-nothing")
        else:
            reason = ""
        summary = " ".join((outcome.summary or outcome.answer or "").split())
        if reason:
            finish(row["id"], FAILED, result=reason, cost=outcome.cost_usd,
                   seconds=outcome.seconds, session_id=outcome.session_id, project=project.name)
            self._complain(row, f"{reason} ({outcome.log})")
            self.say(f"    ! failed — {reason}")
            verdict = FAILED
        else:
            finish(row["id"], OK, result=summary, cost=outcome.cost_usd,
                   seconds=outcome.seconds, session_id=outcome.session_id, project=project.name)
            self.say(f"    ↳ done · {outcome.seconds / 60:.1f} min · ${outcome.cost_usd:.3f}")
            verdict = OK
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": f"on-{verdict}",
            "kind": "on",
            "project": project.name,
            "transition": f"{row['old']} → {row['new']}",
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    def _describe(self, ticket: Ticket, row: dict, prompt: str, project: str) -> str:
        """What the session is shown of the change: the facts, then the prompt."""
        settings = self.config.notion
        page = ticket.page
        facts = [
            f"- Old status: {row['old']}",
            f"- New status: {row['new']}",
            f"- Ticket: {ticket.title} ({ticket.url})",
            f"- Project: {project or '(none)'}",
        ]
        pull = store.read(page, settings.prop("pull_request"))
        if pull:
            facts.append(f"- Pull request: {pull}")
        for key, label in (("cost", "Cost ($)"), ("duration", "Duration (min)")):
            value = store.read(page, settings.prop(key))
            if value:
                facts.append(f"- {label}: {value}")
        if row["depth"]:
            facts.append(
                f"- Generation: this ticket was created by an execution of this kind, "
                f"{row['depth']} generation(s) down"
            )
        facts.append("- The result is in the discussion above: the last report is the run's own.")
        return "\n".join(facts) + "\n\n## The prompt of the ticket\n\n" + prompt.strip()

    def _statuses(self) -> dict[str, str]:
        """{ticket id: status} for the whole board, before an execution."""
        status = self.config.notion.prop("status")
        return {
            Ticket(page).id: str(store.read(page, status) or "")
            for page in self.client.query(self.database)
        }

    def _settle(self, before: dict[str, str], row: dict) -> None:
        """Adopt whatever the execution changed, so that none of it runs a prompt."""
        try:
            after = self._statuses()
        except store.StoreError:
            return
        for ticket, current in after.items():
            if ticket not in before:
                adopt(ticket, current, int(row["depth"]) + 1)
            elif before[ticket] != current:
                adopt(ticket, current)
