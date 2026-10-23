"""Running the session, and the two ways a ticket comes back from one.

`prepare` decided everything; here it happens. One function starts the session,
opens its run in the local journal and closes the live block whatever becomes
of it — `_run_session` — and two
say what a finished session was worth, depending on what the ticket had to
begin with.

**A ticket on a repository** works in a worktree of its own, cut from the
project's default branch, and comes back as commits, a push and a pull request.
The branch is replayed onto its base between the commits and the push, because
a session takes an hour and a base branch does not wait for it: what opens is a
pull request on top of what the repository holds now. Nothing is written into
the project itself, ever: the worktree is the isolation, and it is removed on
the way out — kept only when a run failed and the configuration asked for it.

**A ticket with no repository** works in an empty scratch directory and comes
back as `ANSWER.md`, appended to the Notion page it came from. Same session,
same prompt machinery, same reports; what differs is where the deliverable
lands, and that is the whole of the difference. Three of the four types of
ticket take this road whatever their project holds — see kinds.py — and one of
them stops halfway: a publication comes back as what it *would* publish, and
waits in review for the gesture that publishes it.

Both share the rule that a session ending badly is not the same thing as a
session that asked a question: one goes to failed with its trace, the other to
blocked with the question, and an exhausted quota goes to neither — see
`Reports._requeue`.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from . import config as config_module
from . import (
    generated,
    git,
    github_token,
    journal,
    progress,
    resources,
    session,
    state,
    store,
    subtypes,
    vault,
)
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .ticket import Job, short_id

logger = logging.getLogger(__name__)


def _both(
    first: Callable[[dict], None], second: Callable[[dict], None] | None
) -> Callable[[dict], None]:
    """One listener for the session's events, out of the journal and the page.

    Each is kept from the other's failures: `session.run` drops a listener
    that raises, and a Notion page refusing a write must not cost the journal
    the rest of the run — nor the other way round.
    """

    listeners = [listener for listener in (first, second) if listener is not None]

    def listen(event: dict) -> None:
        for listener in list(listeners):
            try:
                listener(event)
            except Exception as error:
                logger.exception("    ! live report dropped: %s", error)
                listeners.remove(listener)

    return listen


# What a report says when the work it describes happened outside the repository:
# a hosting dashboard, a DNS zone, the board, a browser. Read on a code ticket that
# committed nothing and changed nothing, to tell a ticket done elsewhere from one
# that did not do its work — see `_done_elsewhere`.
_ELSEWHERE = re.compile(
    r"\b(?:dokploy|coolify|vercel|netlify|cloudflare|hostinger|ovh|registrar|dns|"
    r"notion|slack|telegram|linkedin|browser|navigateur|chrome|dashboard|"
    r"tableau de bord|traefik|en prod(?:uction)?|in production|prod|"
    r"(?:re)?deploy(?:ed|ment)?|(?:re)?d[ée]ploy[ée]e?s?|(?:re)?d[ée]ploiement|"
    r"environment variables?|variables? d'environnement|env vars?)\b",
    re.IGNORECASE,
)
# And what it says when it claims to have changed the code itself: that work
# should be in a commit, and a report of it is not the deliverable.
_CODE_CLAIM = re.compile(
    r"\b(?:modified|changed|edited|rewrote|fixed|modifi[ée]e?s?|chang[ée]e?s?|"
    r"[ée]dit[ée]e?s?|r[ée][ée]crit|corrig[ée]e?s?)\b[^.\n]{0,60}?"
    r"\b(?:the code|code|files?|fichiers?|functions?|fonctions?|components?|composants?)\b"
    r"|\b[\w/-]+\.(?:py|ts|tsx|js|jsx|mjs|go|rs|rb|php|java|kt|swift|vue|svelte|css|scss)\b",
    re.IGNORECASE,
)


def _done_elsewhere(answer: str) -> bool:
    """Does this report describe work done outside the repository, and only there?"""
    return bool(_ELSEWHERE.search(answer or "")) and not _CODE_CLAIM.search(answer or "")


def _report(answer: str) -> str:
    """A session's answer as a report for the page: without its RESULT line."""
    lines = (answer or "").strip().splitlines()
    while lines and lines[-1].strip().lstrip("*# ").upper().startswith("RESULT:"):
        lines.pop()
    return "\n".join(lines).strip()


def _answer(workdir: Path) -> str:
    """What a document session left in `ANSWER.md`, or "" when it left nothing."""
    answer_file = workdir / "ANSWER.md"
    if not answer_file.exists():
        return ""
    return answer_file.read_text(encoding="utf-8", errors="replace").strip()


def _answered_anyway(job: Job, outcome: session.Outcome) -> bool:
    """A blocked verdict that asks nothing, on a ticket somebody spoke on.

    What a session does when it answers a question it was asked in a comment —
    “what is X?” — and has nothing left to do: it repeats the answer as the
    reason it stops. With no QUESTION written, there is nothing to wait for;
    the caller checks the deliverable is there before finishing the ticket.
    """
    return bool(
        outcome.blocked and outcome.question is None and not outcome.over_budget and job.comments
    )


class Execution(Base):
    """A session started, and what its outcome makes of the ticket."""

    def execute(self, job: Job) -> dict:
        if self.dry_run:
            target = f"{job.branch} from {job.base}" if job.project.is_code else "document"
            self.say(f"    (dry run) {target}")
            return {"ticket": job.ticket.title, "id": job.ticket.id, "status": "dry-run"}
        return self._execute_code(job) if job.project.is_code else self._execute_document(job)

    def _run_session(self, job: Job, template: str, subtype: bool = False) -> session.Outcome:
        """The session of a job, on that template.

        `subtype` is for the template a code ticket is worked on, and no other:
        a conflict resolved or a CI repaired is not where a CHANGELOG entry or
        a test reproducing a bug are asked for.
        """
        section = subtypes.section(job.subtype) if subtype else ""
        job.secrets = self._secrets(job)
        text = prompt_module.build(
            template,
            project=job.project.name,
            title=job.ticket.title,
            body=job.body,
            repo=str(job.project.path or job.workdir),
            branch=job.branch,
            base=job.base,
            url=job.ticket.url,
            brief=job.project.brief,
            context=self.workspace.context,
            agent_name=job.agent.name,
            agent_brief=job.agent.brief,
            goal_name=job.goal.name,
            goal_brief=job.goal.brief,
            goal_criterion=job.goal.criterion,
            goal_due=job.goal.due,
            comments=job.comments,
            language=self.voice.instruction(),
            allowed=self.config.permissions.allowed,
            ask=self.config.permissions.ask,
            kind=section
            if job.project.is_code
            else prompt_module.kind(job.kind, job.reference or ""),
            # A branch picked up from an earlier attempt: the session is told,
            # because a worktree that opens on somebody's half-done work and
            # reads as empty is how the same thing gets written twice.
            resumed=(
                f"- This ticket has run before, and its branch already carries what that "
                f"session committed, replayed on top of `{job.base}`. Read "
                f"`git log {job.base}..HEAD` and its diff first: you are continuing that "
                f"work, not starting it again.\n"
                if job.resumed
                else ""
            )
            + (
                f"- A worktree of this ticket was left interrupted (a rebase, a merge or a "
                f"detached HEAD with changes) by an earlier session. Everything it held, "
                f"conflict markers included, is saved on the local branch `{job.backup}`: "
                f"`git log -p {job.base}..{job.backup}` shows it, and `git diff HEAD "
                f"{job.backup}` compares it with what you have. Take from it what is worth "
                f"keeping.\n"
                if job.backup
                else ""
            ),
            secrets=sorted(job.secrets),
        )
        log = job.log or state.log_file(short_id(job.ticket.id))
        # The ticket first, then its agent, then the runner: the narrower the
        # choice, the more deliberate it was.
        # Whoever named it, Fable only when `use_fable` allows it.
        chosen = self.config.runner.allowed(
            job.model or job.agent.model or self.config.runner.model
        )
        live = job.live = self._live(job)
        run = self._journal(job, log, chosen)
        try:
            outcome = self._session(job, text, log, chosen, live, run)
            if job.resume and session.lost(outcome):
                # A session Claude Code no longer has — pruned, filed on another
                # machine, or a worktree it cannot be resumed from. The ticket
                # and its branch are still here, so a fresh session starts from
                # everything except the thread of the interrupted one.
                #
                # Only *that* failure. A resumed session that asked a question,
                # timed out or crashed did so on its own account, and would do
                # it again: redoing it costs a second full session — under a
                # reserve whose whole point is to save credit — and throws away
                # what the first one had to say.
                self.say("    ↻ that session could not be picked up — starting a new one")
                job.session_id, job.resume = session.new_id(), False
                # Its own log, or the second attempt would open the first one's
                # with "w" and truncate the very transcript that explains it.
                log = log.with_name(f"{log.stem}-again{log.suffix}")
                run.again(job.session_id, log)
                outcome = self._session(job, text, log, chosen, live, run)
            if reason := self._died(outcome):
                outcome = self._relaunch(job, text, log, chosen, live, run, outcome, reason)
            if self._report_missing(job, outcome):
                outcome = self._write_up(job, outcome, log, chosen, live, run)
        except BaseException:
            # A session that dies still leaves a ticket saying “⏳ Live” and a
            # column stuck on whatever it was doing. Closing here is what makes
            # the page tell the truth on the way out too.
            if live:
                live.close(self.voice.say("live-interrupted"), ok=False)
            raise
        if self.config.runner.attach_sessions:
            # The session ran in a directory that is about to be deleted. Filed
            # under the project instead, it shows up in `claude --resume` there,
            # next to the sessions you started yourself.
            home = job.project.path or self.config.runner.workspace_root
            if session.relocate(outcome.session_id, home):
                job.session_home = home
                self.say(f"    session filed under {home}")
        if live:
            # The block's last word: what the session achieved, or which of the
            # ways of not achieving it this was. After the session has been
            # filed, because a run that went wrong puts the way back into it in
            # this very block — see `_filed` — and that sentence names where the
            # session now lives.
            said = self.voice
            if self._out_of_credit(outcome):
                closing, ended_well = said.say("live-waiting"), True
            elif outcome.ok:
                closing, ended_well = said.brief(outcome.summary, 120), True
            else:
                closing = said.say("live-blocked" if outcome.blocked else "live-stopped")
                ended_well = False
            live.close(closing, ok=ended_well)
        self._hold_credits(outcome)
        return outcome

    def _died(self, outcome: session.Outcome) -> str:
        """Why a session that did not end by itself was cut, or '' when it was not.

        Two kinds of death that are not the ticket's doing: a signal nobody on
        our side sent — and when the kernel says it ran out of memory, the line
        it wrote — and a stream that stopped before its last event while the
        network was down. Anything else is the session's own ending, and keeps
        the road it always had.
        """
        said = self.voice
        if session.signalled(outcome):
            why = said.say("killed-signal", signal=resources.signal_name(outcome.code))
            oom = resources.oom_killed()
            return f"{why} ; {said.say('killed-oom', line=oom)}" if oom else why
        cut = not (
            outcome.ok
            or outcome.blocked
            or outcome.stopped
            or outcome.timed_out
            or outcome.exhausted
            or outcome.resulted
            or session.lost(outcome)
        )
        return said.say("killed-network") if cut and not resources.reachable() else ""

    def _relaunch(
        self,
        job: Job,
        text: str,
        log: Path,
        model: str,
        live: progress.Live | None,
        run: journal.Run,
        outcome: session.Outcome,
        why: str,
    ) -> session.Outcome:
        """The one more try a killed session gets — after a pause, if anybody answers.

        Once, and the outcome that comes back says so by itself: still dead,
        `killed` holds the reason and the ticket is blocked on it. A session
        killed twice is not bad luck, and a third start would only spend the
        same minutes again. The conversation is carried on when Claude Code
        filed it, and opened afresh under the same identifier when the kill came
        before it wrote a line.
        """
        delay = self.config.runner.relaunch_delay_seconds
        self.say(f"    ↻ session killed ({why}) — one more try in {delay}s if the network answers")
        time.sleep(delay)
        if not resources.reachable():
            outcome.killed = f"{why} ; {self.voice.say('killed-network')}"
            return outcome
        job.resume = session.exists(job.session_id)
        log = log.with_name(f"{log.stem}-again{log.suffix}")
        run.again(job.session_id, log)
        again = self._session(job, text, log, model, live, run)
        again.killed = self._died(again)
        return again

    def _session(
        self,
        job: Job,
        text: str,
        log: Path,
        model: str,
        live: progress.Live | None,
        run: journal.Run,
    ) -> session.Outcome:
        """One attempt at this job's session, opened or carried on.

        A carried one is sent the short message instead of the frame: it has the
        ticket, the brief and the context already, and resending them would cost
        on every resumption what they cost once. See `prompt.CARRY_ON`.
        """
        if job.resume:
            text = prompt_module.carry_on(self.voice.instruction())
        opening = "picking session" if job.resume else "Claude session"
        self.say(f"    {opening} {job.session_id}{' · ' + model if model else ''} → {log}")
        return self._paid(
            job.ticket.id,
            text,
            cwd=job.workdir,
            log=log,
            model=model,
            permission_mode=self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.timeout_minutes,
            session_id=job.session_id,
            resume=job.resume,
            environment={**job.secrets, **self.environment_for(model), **self._github(job)},
            on_event=_both(run.event, live.event if live else None),
            max_budget_usd=self.config.budget.per_ticket_usd,
        )

    def _github(self, job: Job) -> dict[str, str]:
        """The GitHub App's token for this job's repository, or the machine's own token.

        Nothing for a ticket without code, and nothing when neither reaches the
        repository's owner: the session then answers as `gh` does, as before.
        See `github_token.session_environment`.
        """
        if not job.project.is_code or self.dry_run:
            return {}
        owner = git.owner(git.remote_url(job.workdir))
        return github_token.session_environment(owner) if owner else {}

    def _secrets(self, job: Job) -> dict[str, str]:
        """The keys `[vault]` grants this job's project, read now — see vault.py.

        Read at every session rather than kept: a token rotated in the keyring
        is the one the next session gets. Under the runner's own variables, so
        that a project can never stand in for the provider's key or the GitHub
        App's token. What could not be read is said, by name only, and the
        ticket runs without it.
        """
        granted = self.config.vault.granted(job.project.name)
        if not granted or self.dry_run:
            return {}
        stored = config_module.read_secrets(config_module.secrets_path(self.config.path))
        found = vault.read(granted, self.config.vault.provider, stored)
        if found.values:
            self.say(f"    · secrets: {', '.join(sorted(found.values))}")
        for missing in found.missing:
            self.say(f"    ! secret not read: {missing}")
        return found.values

    def _report_missing(self, job: Job, outcome: session.Outcome) -> bool:
        """Did this session stop without its report, and may it be asked for it?

        Without it: on a document ticket, no `ANSWER.md`; on a code ticket,
        nothing committed, nothing changed and not a word of a verdict. Only a
        session that ended on its own: one that asked a question, crashed,
        timed out, was stopped or ran out of credit did not forget a report,
        and picking it up again would pay twice for the same failure. And not
        twice for one ticket, ever — see `state.written_up`.
        """
        if not outcome.ok:
            return False
        if job.project.is_code:
            if (
                outcome.concluded
                or git.commits_ahead(job.workdir, job.base)
                or git.is_dirty(job.workdir)
            ):
                return False
        elif _answer(job.workdir):
            return False
        if state.written_up(job.ticket.id):
            self.say("    · stopped without its report, and was already asked for one once")
            return False
        return True

    def _write_up(
        self,
        job: Job,
        outcome: session.Outcome,
        log: Path,
        model: str,
        live: progress.Live | None,
        run: journal.Run,
    ) -> session.Outcome:
        """The same session, picked up once to write the report it stopped without.

        A session that did the work and stopped before saying so — no
        `ANSWER.md`, no RESULT line — used to block its ticket, and the ticket
        ran again from the start once somebody had answered a question that
        was never one. Its conversation still holds everything it did, so it is
        asked for that, and for nothing else: no more work, only the account
        of it. What the two halves cost is added up; whatever the second one
        says is what the ticket is judged on.
        """
        state.wrote_up(job.ticket.id)
        self.say(f"    ↻ stopped without its report — asking session {outcome.session_id} for it")
        asked = self._paid(
            job.ticket.id,
            prompt_module.write_up(
                "" if job.project.is_code else job.workdir, self.voice.instruction()
            ),
            cwd=job.workdir,
            # Its own log, so the first half's transcript is not truncated.
            log=log.with_name(f"{log.stem}-report{log.suffix}"),
            model=model,
            permission_mode=self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.timeout_minutes,
            session_id=outcome.session_id,
            resume=True,
            environment={**job.secrets, **self.environment_for(model), **self._github(job)},
            on_event=_both(run.event, live.event if live else None),
            max_budget_usd=self.config.budget.per_ticket_usd,
        )
        if session.lost(asked):
            return outcome
        return replace(
            asked,
            cost_usd=outcome.cost_usd + asked.cost_usd,
            seconds=outcome.seconds + asked.seconds,
            turns=outcome.turns + asked.turns,
        )

    def _journal(self, job: Job, log: Path, model: str = "") -> journal.Run:
        """The run this session is about to be, opened in the local journal.

        Whatever the board, and whatever `runner.progress` says: the page gets
        what the agent says, the journal every step — see journal.py. Kept for
        `_guarded`, which closes it once the ticket's outcome is known.
        """
        run = journal.Run.start(
            ticket=job.ticket.id,
            title=job.ticket.title,
            kind=job.kind or ("code" if job.project.is_code else "document"),
            project=job.project.name,
            agent=job.agent.name,
            session=job.session_id,
            log=log,
            model=model,
            chosen=job.chosen,
            escalated=job.escalated,
            say=self.say,
        )
        self._journals[job.ticket.id] = run
        return run

    def _live(self, job: Job) -> progress.Live | None:
        """The ticket's live report, or None when it is not wanted.

        Off in a dry run, since a dry run writes nothing anywhere, and off when
        `runner.progress` says so. Everything else it needs — the page, the
        board and the column — it already has.
        """
        if self.dry_run or not self.config.runner.progress:
            return None
        return progress.Live(
            self.client,
            job.ticket.page.id,
            database=self.database,
            property_name=self.config.notion.prop("progress"),
            interval=self.config.runner.progress_interval_seconds,
            words=self.voice,
            say=self.say,
        )

    def _question(self, outcome: session.Outcome, detail: str) -> str | object:
        """What a ticket that stopped asks: the session's own question, or ours."""
        if outcome.killed:
            return self.voice.say("session-killed-question")
        return (outcome.question or detail) if outcome.blocked else ""

    # -- a ticket on a repository ----------------------------------------------

    def _execute_code(self, job: Job) -> dict:
        ticket, project = job.ticket, job.project

        if self.config.runner.fetch:
            git.fetch(project.path)
        try:
            worktree = git.add_worktree(
                project.path,
                job.workdir,
                job.branch,
                job.base,
                git.exclusions(self.config.runner.worktree_exclude),
            )
        except git.GitError as error:
            return self._fail(
                ticket, self.voice.say("no-worktree"), str(error), code="worktree.residue"
            )
        self._note_worktree(job, worktree)

        try:
            outcome = self._run_session(
                job, prompt_module.template(self.config.runner.prompt_file), subtype=True
            )
        except (OSError, FileNotFoundError) as error:
            git.remove_worktree(project.path, job.workdir)
            return self._fail(
                ticket, self.voice.say("no-session"), str(error), code="session.not-started"
            )

        said = self.voice

        if self._out_of_credit(outcome):
            # Not a failure: there was nothing to work with. The worktree stays
            # where it is whatever `keep_worktree_on_failure` says — the branch
            # is what the next attempt picks up, commits and all, and throwing
            # it away would make the wait cost the work that came before it.
            return self._requeue(
                ticket,
                self.config.notion.state("ready"),
                outcome,
                said.say("credit-spent-kept", branch=job.branch)
                if git.commits_ahead(job.workdir, job.base)
                else "",
                home=job.session_home or job.project.path,
            )

        if _answered_anyway(job, outcome) and git.commits_ahead(job.workdir, job.base):
            # The work is committed and nothing was asked: it goes to review
            # with its pull request, the answer in its report — see
            # `_answered_anyway`.
            self.say("    · blocked without a question, its work committed — sent to review")
            outcome = replace(outcome, ok=True, blocked=False)

        if not outcome.ok:
            return self._code_stopped(job, outcome)

        commits = git.commits_ahead(job.workdir, job.base)
        if commits == 0:
            return self._nothing_committed(job, outcome)

        pull_request = ""
        replayed = False
        if self.config.runner.push and self.config.runner.rebase:
            replayed = self._replay_branch(job)
        if self.config.runner.push:
            if failure := self._push_branch(job, outcome, force=worktree.reused or replayed):
                return failure
            if self.config.runner.open_pull_request:
                pull_request = self._open_pull_request(job, outcome, commits)

        return self._code_delivered(job, outcome, commits, pull_request)

    def _note_worktree(self, job: Job, worktree: git.Worktree) -> None:
        """What the session is about to meet in its worktree, said before it starts."""
        if worktree.reused:
            # A ticket that has run before: said out loud, because the session
            # about to start is continuing somebody's work rather than opening
            # on an empty branch, and the comment should carry that too — the
            # journal in English, like the rest of it, the comment in its voice.
            self.say("    · " + voice_module.Voice().branch_note(worktree).replace("`", ""))
            job.notes.append(self.voice.branch_note(worktree))
            job.resumed = worktree.reused
        if worktree.backup:
            # Said to the session as well as to the ticket: the half-done work
            # it is about to meet is no longer in its worktree, and nothing but
            # this sentence tells it where it went.
            self.say(f"    · interrupted worktree saved to {worktree.backup}")
            job.notes.append(self.voice.backup_note(worktree, job.base))
            job.backup = worktree.backup

    def _code_stopped(self, job: Job, outcome: session.Outcome) -> dict:
        """A session that did not succeed: blocked on a question, or killed."""
        ticket, project = job.ticket, job.project
        said = self.voice
        code, reason, detail = self._why_stopped(
            outcome, "session.question" if outcome.blocked else "session.killed"
        )
        # An agent that asked a question is waiting for you; a session that
        # crashed is waiting for someone to look at the log. Different rows
        # on the board, when the board has somewhere to put them.
        kept = ""
        if self.config.runner.keep_worktree_on_failure:
            kept = said.say("worktree-kept", path=job.workdir, branch=job.branch)
        else:
            git.remove_worktree(project.path, job.workdir)
        return self._fail(
            ticket,
            reason,
            detail,
            code=code,
            blocked=outcome.blocked or bool(outcome.killed),
            question=self._question(outcome, detail),
            note=self._filed(job, outcome, kept),
            outcome=outcome,
        )

    def _nothing_committed(self, job: Job, outcome: session.Outcome) -> dict:
        """A session that succeeded with no commit: done outside, or blocked."""
        ticket, project = job.ticket, job.project
        said = self.voice
        dirty = git.is_dirty(job.workdir)
        if not dirty and _done_elsewhere(outcome.answer):
            # Nothing to commit because nothing was to be: the work was a
            # deployment, a setting, a board — and its report is what it
            # delivers, written into the page as a document ticket's is. A
            # session that changed files and left them uncommitted, or says
            # it changed the code, is still blocked below.
            git.remove_worktree(project.path, job.workdir)
            self.say("    · nothing committed, the work was done outside the repository")
            return self._deliver_text(
                job,
                outcome,
                _report(outcome.answer) or outcome.summary,
                note=said.say("done-elsewhere"),
            )
        if not dirty:
            git.remove_worktree(project.path, job.workdir)
        return self._fail(
            ticket,
            said.say("nothing-committed"),
            outcome.summary,
            code="session.no-commit",
            blocked=True,
            question=outcome.summary,
            note=self._filed(job, outcome),
            outcome=outcome,
        )

    def _replay_branch(self, job: Job) -> bool:
        """The branch replayed onto where its base is now; True when it moved."""
        project = job.project
        said = self.voice
        replayed = False
        # The base has moved under this session: the ticket started on the
        # `main` of an hour ago, and one of the other nine tickets aimed at
        # this repository has been merged since. Replaying the branch now is
        # what makes the pull request open on top of what the repository
        # actually holds rather than as a conflict somebody has to come and
        # sort out by hand.
        #
        # A rebase that cannot be done is not a reason to keep the work
        # here: `git.rebase` puts the branch back as it was, the pull
        # request opens all the same, and the conflict is said on the ticket
        # — which is the one place a person will look at it.
        if self.config.runner.fetch:
            git.fetch(project.path)
        start = (
            f"origin/{job.base}" if git.has_ref(project.path, f"origin/{job.base}") else job.base
        )
        was = git.head(job.workdir)
        if failure := git.rebase(job.workdir, start, generated.settle):
            self.say(f"    ! not replayed onto {start}: {failure}")
            job.notes.append(said.say("rebase-refused", base=start, error=failure))
        elif git.head(job.workdir) != was:
            replayed = True
            self.say(f"    · replayed onto {start}")
            job.notes.append(said.say("rebased-onto", base=start))
        return replayed

    def _push_branch(self, job: Job, outcome: session.Outcome, *, force: bool) -> dict | None:
        """The branch pushed — or the ticket failed on the refusal, as `_fail` returns it."""
        ticket = job.ticket
        said = self.voice
        pushed = git.push(
            job.workdir,
            job.branch,
            force=force,
            accounts=self.config.github,
        )
        if not pushed.ok:
            message = pushed.err or pushed.out
            if resources.network_error(message) and not resources.reachable():
                # Not a refusal: GitHub was never asked. The branch and its
                # commits stay where they are for the attempt after.
                raise store.Unreachable(f"git push: {message}")
            return self._fail(
                ticket,
                said.say("push-refused"),
                pushed.err or pushed.out,
                code="merge.push-refused",
                note=self._filed(job, outcome, said.say("push-refused-detail", branch=job.branch)),
                outcome=outcome,
            )
        return None

    def _open_pull_request(self, job: Job, outcome: session.Outcome, commits: int) -> str:
        """The pull request's address — empty when it could not be opened, which is said."""
        ticket = job.ticket
        said = self.voice
        pull_request = ""
        body = said.pull_request_body(outcome.summary, ticket.url, outcome.session_id, commits)
        try:
            # Prefixed the conventional way when the sub-type is known:
            # squashed, the title is the commit that lands on the base.
            pull_request = git.open_pull_request(
                job.workdir,
                subtypes.titled(job.subtype, ticket.title),
                body,
                job.base,
                accounts=self.config.github,
            )
        except git.GitError as error:
            self.say(f"    ! pull request not opened: {error}")
            job.notes.append(said.say("no-pull-request-opened", error=error))
        return pull_request

    def _code_delivered(
        self, job: Job, outcome: session.Outcome, commits: int, pull_request: str
    ) -> dict:
        """A branch with commits: merged when forced, the board moved, and the ticket told."""
        ticket, project = job.ticket, job.project
        said = self.voice
        # Force validated: the merge that moving the ticket to validated would
        # have asked for, asked now — before the worktree goes, since the CI it
        # waits for is read from it. Only this far down: every road out of a
        # session that did not succeed has already been taken above. A merge
        # that is only *not yet* — a branch overtaken while its CI ran, a CI
        # still running — is left in validated, for `_merge` to finish.
        forced = refused = ""
        later = False
        if pull_request:
            forced = self._forced("code", project)
        if forced:
            self.say(f"    · {forced}")
            refused, later = self._force_merge(job, pull_request)
        merged = bool(forced and not refused)

        git.remove_worktree(project.path, job.workdir)

        # With a pull request the ticket is not finished, it is waiting for you:
        # it goes to "in review", and `close_merged` takes it to done once you
        # have merged. Without one there is nothing to wait for — and on a board
        # with no review column, `review` is `done` and nothing changes. A merge
        # forced and refused waits there too, with the refusal on its card; one
        # postponed waits in validated, with the reason on its card.
        column = "validated" if later else "review" if pull_request and not merged else "done"
        values: dict[str, object] = {
            self.config.notion.prop("status"): self.config.notion.state(column),
            self.config.notion.prop("agent"): self.agent_label,
        }
        if pull_request:
            values[self.config.notion.prop("pull_request")] = pull_request
        if refused:
            refusal = (
                said.say("forced-merge-postponed", reason=refused)
                if later
                else said.say("forced-merge-refused", error=refused)
            )
            values[self.config.notion.prop("progress")] = said.brief(refusal)
        values[self.config.notion.prop("session")] = self._session_value(
            outcome.session_id, job.session_home or project.path
        )
        values.update(self._measures(outcome))
        self._set(ticket, **values)

        # Where the work is comes first, because it is what you act on: the
        # pull request when there is one, and the branch when there is not.
        placed: tuple[str, ...] = (
            said.pull_request(pull_request) or said.say("on-branch", branch=job.branch),
            said.count(commits, "commit"),
        )
        if merged:
            placed = (
                *placed[:1],
                said.say("merged-with", method=self.config.runner.merge_method),
                *placed[1:],
            )
        facts = (*placed, *said.spent(outcome.seconds, outcome.cost_usd))
        verdict = "merged" if merged else "waiting" if later else "review"
        brief = said.brief(outcome.summary)
        # Said on the ticket whichever way it went: a pull request nobody read
        # was merged, or would have been, and that is not the board's usual day.
        forced_lines = (forced, said.brief(refusal) if refused else "")
        self._comment(
            ticket,
            said.report(
                said.verdict(verdict, *facts),
                brief,
                pull_request,
                *said.caveats(outcome.caveats),
                *forced_lines,
                *(said.brief(note) for note in job.notes),
            ),
        )
        self.say(
            f"    ✓ {ticket.title} — {pull_request or job.branch}"
            + (" merged, moved to done" if merged else "")
            + (" not merged yet, moved to validated" if later else "")
        )
        self._tell(
            "done",
            ticket,
            verdict,
            said.report(said.facts(*facts), brief, pull_request, *forced_lines),
            project=project.name,
            facts=placed,
            summary=outcome.summary,
            pull_request=pull_request,
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "done",
            "project": project.name,
            "branch": job.branch,
            "pull_request": pull_request,
            **({"merged": pull_request} if merged else {}),
            **({"forced": "code", "refused": refused} if forced else {}),
            **({"postponed": True} if later else {}),
            "session": outcome.session_id,
            "commits": commits,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    # -- a ticket that has none -------------------------------------------------

    def _execute_document(self, job: Job) -> dict:
        """A ticket with no repository: the deliverable is the ticket's own page."""
        ticket = job.ticket
        job.workdir.mkdir(parents=True, exist_ok=True)
        try:
            outcome = self._run_session(
                job,
                prompt_module.template(
                    self.config.runner.document_prompt_file, prompt_module.DOCUMENT
                ),
            )
        except (OSError, FileNotFoundError) as error:
            return self._fail(
                ticket, self.voice.say("no-session"), str(error), code="session.not-started"
            )

        said = self.voice
        if self._out_of_credit(outcome):
            # The working directory is left as it is: whatever the session had
            # written into ANSWER.md before the quota ran out is what the next
            # attempt opens on.
            return self._requeue(
                ticket,
                self.config.notion.state("ready"),
                outcome,
                home=job.session_home,
            )

        answer_file = job.workdir / "ANSWER.md"
        content = _answer(job.workdir)

        # Answered and finished, but said as a stop: read, rather than asked
        # again — see `_answered_anyway`. In review, since it said blocked.
        anyway = bool(content) and _answered_anyway(job, outcome)
        if anyway:
            self.say("    · blocked without a question, its answer written — sent to review")
            outcome = replace(outcome, ok=True, blocked=False)

        if not outcome.ok or not content:
            code, reason, detail = self._why_stopped(
                outcome, "session.no-answer" if outcome.blocked or not content else "session.killed"
            )
            if not content and outcome.ok:
                detail = said.say("no-answer-detail", summary=outcome.summary)
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = said.say("workdir-kept", path=job.workdir)
            else:
                shutil.rmtree(job.workdir, ignore_errors=True)
            return self._fail(
                ticket,
                reason,
                detail,
                code=code,
                blocked=outcome.blocked or not content or bool(outcome.killed),
                question=self._question(outcome, detail) or outcome.question or detail,
                note=self._filed(job, outcome, kept),
                outcome=outcome,
            )

        # A session that was not on a code ticket's road opened a pull request
        # anyway: attached to the ticket and sent to review, so it is merged
        # through the validated column like any other — rather than left on
        # GitHub, out of sight of the board, under a ticket that says done.
        opened = session.pull_requests(outcome.log)
        note = ""
        if opened:
            self.say(
                f"    · the session opened {', '.join(opened)} itself — attached, sent to review"
            )
            note = said.paragraphs(
                said.say("pull-request-adopted", url=opened[-1]),
                said.say("pull-requests-also", urls=", ".join(opened[:-1])) if opened[1:] else "",
            )
        return self._deliver_text(
            job,
            outcome,
            content,
            review=anyway or bool(opened),
            kept=answer_file,
            note=note,
            pull_request=opened[-1] if opened else "",
        )

    def _deliver_text(
        self,
        job: Job,
        outcome: session.Outcome,
        content: str,
        *,
        review: bool = False,
        kept: Path | None = None,
        note: str = "",
        pull_request: str = "",
    ) -> dict:
        """A ticket whose deliverable is a text, written into its page.

        `review` sends it to be read rather than to done; `kept` is where the
        text still is on disk, should the page refuse it; `note` is one more
        line for the report; `pull_request` is one the session opened itself,
        written into the ticket's column so validating it merges it.
        """
        ticket = job.ticket
        said = self.voice
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        try:
            blocks = self.client.append_markdown(
                ticket.page.id,
                f"\n---\n{content}\n\n*ponos · {stamp} · session `{outcome.session_id}`*",
            )
        except store.StoreError as error:
            return self._fail(
                ticket,
                said.say("answer-not-written"),
                voice_module.line(error),
                code="notion.write-failed",
                note=self._filed(
                    job, outcome, said.say("answer-on-disk", path=kept) if kept else ""
                ),
                outcome=outcome,
            )

        shutil.rmtree(job.workdir, ignore_errors=True)
        # A publication is only prepared: it waits in review for you to read it,
        # and `Delivery._publish` puts it out once you have moved it to
        # validated. On a board whose review is its done there is no such
        # gesture, and it ends there as any text does — prepared, not published.
        prepared = job.kind == "publication"
        # Force validated: nothing waits for you, and the publishing session is
        # started as soon as this one is done — `Delivery._publish`, exactly as
        # moving the ticket to validated would have started it. Under the
        # credit reserve it is not started here: the ticket goes to validated,
        # for the pass that has credit again to publish it, as it would one you
        # had moved there yourself. A board with no such column has nowhere to
        # hold it, and the ticket waits in review as it always did.
        following = (
            self._forced("publication", job.project) if prepared and not pull_request else ""
        )
        forced = bool(following)
        postponed = forced and bool(self.under_reserve())
        if postponed and not self.validated_column():
            forced = postponed = False
        values: dict[str, object] = {
            self.config.notion.prop("agent"): self.agent_label,
            self.config.notion.prop("session"): self._session_value(
                outcome.session_id, job.session_home or job.project.path
            ),
            **self._measures(outcome),
        }
        if pull_request:
            values[self.config.notion.prop("pull_request")] = pull_request
        if not forced or postponed:
            column = "validated" if postponed else "review" if prepared or review else "done"
            values[self.config.notion.prop("status")] = self.config.notion.state(column)
        self._set(ticket, **values)
        if forced:
            self.say(f"    · {following}")
            if not postponed:
                # One report for the two sessions, the publication's: a ticket
                # saying “to validate” a second before it says “published”
                # would be telling you to do what is already being done.
                return self._publish(ticket, job.project, forced=following, prepared=outcome)
            following = said.paragraphs(following, said.say("forced-postponed"))
        elif prepared and self.validated_column():
            following = said.say("prepared-next", validated=self.config.notion.state("validated"))
        else:
            following = ""
        placed = (
            said.say("in-the-page"),
            said.say("nothing-published") if prepared else said.count(blocks, "block"),
        )
        facts = (*placed, *said.spent(outcome.seconds, outcome.cost_usd))
        verdict = (
            "waiting" if forced else "prepared" if prepared else "review" if review else "read"
        )
        brief = said.brief(outcome.summary)
        self._comment(
            ticket,
            said.report(
                said.verdict(verdict, *facts),
                brief,
                *said.caveats(outcome.caveats),
                following,
                note,
            ),
        )
        self.say(
            f"    ✓ {ticket.title} — {blocks} block(s) written to the ticket"
            + (", nothing published: in review" if prepared and not forced else "")
        )
        self._tell(
            "done",
            ticket,
            verdict,
            said.report(said.facts(*facts), brief, following),
            project=job.project.name,
            facts=placed,
            summary=outcome.summary,
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "done",
            "project": job.project.name,
            "kind": "publication" if prepared else "document",
            "blocks": blocks,
            **({"pull_request": pull_request} if pull_request else {}),
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }
