"""Running the session, and the two ways a ticket comes back from one.

`prepare` decided everything; here it happens. One function starts the session,
opens its run in the local journal and closes the live line whatever becomes
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
back as `ANSWER.md`, appended to the ticket's page. Same session,
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
import sqlite3
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import (
    adoption,
    blocks,
    browser,
    db,
    diagnostic,
    generated,
    git,
    github_token,
    journal,
    kinds,
    library,
    local_ci,
    memory,
    notes,
    planning,
    preview,
    progress,
    project_settings,
    resources,
    results,
    session,
    skills,
    state,
    stopping,
    store,
    subtypes,
    ticket_page,
    tickets,
    vault,
    vault_store,
    worktree_setup,
)
from . import config as config_module
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .question import Question
from .ticket import Job, short_id

logger = logging.getLogger(__name__)


def _both(
    first: Callable[[dict[str, Any]], None], second: Callable[[dict[str, Any]], None] | None
) -> Callable[[dict[str, Any]], None]:
    """One listener for the session's events, out of the journal and the page.

    Each is kept from the other's failures: `session.run` drops a listener
    that raises, and a board refusing a write must not cost the journal
    the rest of the run — nor the other way round.
    """

    listeners = [listener for listener in (first, second) if listener is not None]

    def listen(event: dict[str, Any]) -> None:
        for listener in list(listeners):
            try:
                listener(event)
            except Exception as error:
                logger.exception("    ! live report dropped: %s", error)
                listeners.remove(listener)

    return listen


def _added(first: session.Outcome, then: session.Outcome) -> session.Outcome:
    """The second try, carrying what the first one cost: both were paid for."""
    return replace(
        then,
        cost_usd=first.cost_usd + then.cost_usd,
        seconds=first.seconds + then.seconds,
        turns=first.turns + then.turns,
    )


# What a report says when the work it describes happened outside the repository:
# a hosting dashboard, a DNS zone, the board, a browser. Read on a code ticket that
# committed nothing and changed nothing, to tell a ticket done elsewhere from one
# that did not do its work — see `_done_elsewhere`.
_ELSEWHERE = re.compile(
    r"\b(?:dokploy|coolify|vercel|netlify|cloudflare|hostinger|ovh|registrar|dns|"
    r"slack|telegram|linkedin|google|search console|"
    r"browser|navigateur|chrome|dashboard|"
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


# What a verdict says when there was nothing to commit because the change is
# already made: on main, by a pull request or a commit it names — or because the
# ticket's work was other pull requests, rebased, fixed and merged on their own
# branches. Read on the RESULT line only: the report above it cites the files it
# checked as its evidence, and `_CODE_CLAIM` would take each for a change.
_SETTLED = re.compile(
    r"\b(?:rien à changer|aucun changement|aucun correctif[^.;\n]{0,30}? nécessaire|"
    r"pas de PR|nothing to change|no changes? (?:needed|required)|no PR)\b"
    r"|\b(?:déjà|already)\b[^.;\n]{0,40}?"
    r"\b(?:corrig|répar|fusionn|en place|correct|sur main|fixed|merged|in place|on main)"
    r"|(?:#\d+|\b[0-9a-f]{7,40}\b)[^;\n]{0,160}?\b(?:fusionn|merged)"
    r"|\b(?:fusionn|merged)\w*\b[^;\n]{0,160}?(?:#\d+|\b[0-9a-f]{7,40}\b)",
    re.IGNORECASE,
)


def _settled(summary: str) -> bool:
    """Does this verdict name what made the change needless, or the PRs it went to?"""
    return bool(_SETTLED.search(summary or "")) and not _CODE_CLAIM.search(summary or "")


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

    def execute(self, job: Job) -> dict[str, Any] | None:
        if self.dry_run:
            target = f"{job.branch} from {job.base}" if job.project.is_code else "document"
            self.say(f"    (dry run) {target}")
            return {"ticket": job.ticket.title, "id": job.ticket.id, "status": "dry-run"}
        return self._execute_code(job) if job.project.is_code else self._execute_document(job)

    def _run_session(
        self,
        job: Job,
        template: str,
        subtype: bool = False,
        phase: str = "session",
        detail: str = "",
    ) -> session.Outcome:
        """The session of a job, on that template.

        `subtype` is for the template a code ticket is worked on, and no other:
        a conflict resolved or a CI repaired is not where a CHANGELOG entry or
        a test reproducing a bug are asked for. `phase` is what the console
        says the ticket is going through meanwhile — see `state.enter`.
        A job marked `adoptable` is on its ticket's own session, the one a
        restart carries on (see adoption.py).
        """
        state.enter(job.ticket.id, phase, detail)
        job.secrets = self._secrets(job)
        text = self._session_prompt(job, template, subtype)
        log = job.log or state.log_file(short_id(job.ticket.id))
        # The ticket first, then its agent, then the runner: the narrower the
        # choice, the more deliberate it was.
        # Whoever named it, Fable only when `use_fable` allows it.
        chosen = self.config.runner.allowed(
            job.model or job.agent.model or self.config.runner.model
        )
        live = self._live(job)
        run = (
            journal.Run.resume(job.run, say=self.say)
            if job.adopted is not None and job.run is not None
            else None
        )
        if run is None or not run.open:
            run = self._journal(job, log, chosen)
        else:
            self._journals[job.ticket.id] = run
        job.run = run.id
        outcome = self._launch(job, text, log, chosen, live, run)
        run.answer, run.summary, run.caveats = outcome.answer, outcome.summary, outcome.caveats
        self._file_session(job, outcome)
        if live:
            live.close()
        self._hold_credits(outcome)
        self._propose_lesson(job, outcome)
        self._propose_memories(job, outcome)
        return outcome

    def _propose_lesson(self, job: Job, outcome: session.Outcome) -> None:
        """What a ticket answered after a stop says it learned, put to the project as a proposal."""
        if not (outcome.ok and outcome.lesson and job.comments) or self.dry_run:
            return
        if notes.propose(job.project.page_id, job.project.name, outcome.lesson):
            self.say(f"    · lesson proposed for {job.project.name}: {outcome.lesson}")

    def _propose_memories(self, job: Job, outcome: session.Outcome) -> None:
        """What a session that ended ok proposes to remember, put to the person as proposals."""
        if not (outcome.ok and outcome.memories) or self.dry_run:
            return
        for line in outcome.memories:
            read = memory.parse(line)
            if read is None:
                continue
            kind, where, fact = read
            project = job.project.page_id if where == "project" and job.project.page_id else ""
            if memory.propose(fact, kind, project, "ticket", job.ticket.id):
                self.say(f"    · memory proposed: {fact}")

    def _session_prompt(self, job: Job, template: str, subtype: bool) -> str:
        """The prompt of a job's session: its template, filled with the ticket."""
        section = subtypes.section(job.subtype) if subtype else ""
        return (
            prompt_module.build(
                template,
                project=job.project.name,
                title=job.ticket.title,
                body=job.body,
                repo=str(job.project.path or job.workdir),
                branch=job.branch,
                base=job.base,
                url=job.ticket.url,
                brief=job.project.brief,
                notes=notes.kept(job.project.page_id),
                memories=memory.for_prompt(job.project.page_id),
                library=library.for_prompt(job.project.page_id),
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
                owners=[*self.config.github, *self.config.github.values()],
                attribution=self.config.claude.attribution,
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
                )
                + (f"- {job.prepared}\n" if job.prepared else ""),
                secrets=sorted(name for name in job.secrets if name not in job.addresses),
                addresses=job.addresses,
                workers=self.workers,
            )
            + (self._planned(job) if subtype else "")
            + self._browser_prompt(job)
            + self._diagnostic_prompt(job)
            + self._result_prompt(job)
        )

    def _result_prompt(self, job: Job) -> str:
        """The result the ticket already delivered, to start a change from — see results.py."""
        try:
            versions = tickets.results(job.ticket.page.id)
        except db.ERRORS:
            return ""
        return (
            prompt_module.current_result(versions[0].text, versions[0].version) if versions else ""
        )

    def _diagnostic_prompt(self, job: Job) -> str:
        """What a diagnostic's session is told on top of the frame — see diagnostic.py."""
        if job.kind != "diagnostic":
            return ""
        access, variables = self._diagnostic_access(job)
        return "\n\n" + diagnostic.prompt(access, variables)

    def _diagnostic_access(self, job: Job) -> tuple[diagnostic.Access, dict[str, list[str]]]:
        """What the project lets its diagnostics reach, and the variables its hosts' entries become."""
        access = project_settings.diagnostic(job.project.page_id)
        if not access.entries:
            return access, {}
        try:
            listed = vault_store.listing()
        except (vault.VaultError, sqlite3.Error, OSError) as error:
            self.say(f"    ! the vault of Ponos cannot be read: {error}")
            listed = []
        return access, diagnostic.granted(access, listed)

    def _browser_prompt(self, job: Job) -> str:
        """Choose the browser of an external ticket, and what its session is told of it.

        Ponos's own unless the ticket, its project or `[browser]` say Claude in
        Chrome — and Claude in Chrome anyway, said once, on a machine where
        Playwright or its Chromium is missing. See browser.py.
        """
        job.browser = ""
        if job.kind != "external" or self.dry_run:
            return ""
        if browser.chosen(self.config, job.project.page_id, job.body) != browser.PONOS:
            return ""
        if why := browser.missing():
            self.say(f"    ! Ponos's browser: {why} — Claude in Chrome instead (ponos doctor)")
            return ""
        job.browser = browser.PONOS
        return "\n\n" + prompt_module.held_browser(self._logins(job))

    def _logins(self, job: Job) -> dict[str, str]:
        try:
            return vault_store.logins(job.project.name)
        except (sqlite3.Error, OSError) as error:
            self.say(f"    ! the vault of Ponos cannot be read: {error}")
            return {}

    def _browsing(self, job: Job, log: Path) -> dict[str, Any]:
        """What `session.run` is given for the browser: Claude in Chrome, or `ponos-browser`."""
        if job.browser != browser.PONOS:
            return {}
        environment = browser.server_environment(
            project=job.project.name,
            ticket=job.ticket.id,
            session=job.session_id,
            headless=self.config.browser.headless,
            logins=self._logins(job),
            downloads=job.workdir,
        )
        return {
            "chrome": False,
            "mcp_config": browser.mcp_config(log.with_suffix(".mcp.json"), environment),
        }

    @staticmethod
    def _planned(job: Job) -> str:
        """What a ticket ticked « Plan d'abord » adds to its prompt, last — see planning.py."""
        if job.planning == "propose":
            return "\n\n" + planning.propose_prompt(amending=job.plan)
        if job.planning == "carry" and job.plan:
            return "\n\n" + planning.approved_prompt(job.plan, job.answer)
        return ""

    def _launch(
        self,
        job: Job,
        text: str,
        log: Path,
        chosen: str,
        live: progress.Live | None,
        run: journal.Run,
    ) -> session.Outcome:
        """The session itself, picked up again or relaunched when it has to be."""
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
                outcome = _added(outcome, self._session(job, text, log, chosen, live, run))
            if reason := self._died(outcome):
                outcome = self._relaunch(job, text, log, chosen, live, run, outcome, reason)
            if self._report_missing(job, outcome):
                outcome = self._write_up(job, outcome, log, chosen, live, run)
        except BaseException:
            # A session that dies still leaves a column stuck on whatever it
            # was doing. Closing here is what makes the card tell the truth on
            # the way out too.
            if live:
                live.close()
            raise
        return outcome

    def _file_session(self, job: Job, outcome: session.Outcome) -> None:
        """The session filed under its project, when the configuration asks for it."""
        if self.config.runner.attach_sessions:
            # The session ran in a directory that is about to be deleted. Filed
            # under the project instead, it shows up in `claude --resume` there,
            # next to the sessions you started yourself.
            home = job.project.path or self.config.runner.workspace_root
            if session.relocate(outcome.session_id, home):
                job.session_home = home
                self.say(f"    session filed under {home}")

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

        Only for a ticket nobody let go of meanwhile. A kill from a terminal is
        often how somebody gives up on a session, and the pause is when the
        console's Abandon or a drag on the board lands: a Stop asked for ends it
        as the console's Stop does — see `_halted` — and a ticket no longer in
        progress keeps the column it was moved to, see `_still`.
        """
        delay = self.config.runner.relaunch_delay_seconds
        self.say(f"    ↻ session killed ({why}) — one more try in {delay}s if the network answers")
        time.sleep(delay)
        if action := stopping.requested(job.ticket.id):
            self.say(f"    · not tried again: {action} asked during the pause")
            outcome.stopped = True
            return outcome
        if moved := self._moved_away(job):
            self.say(f"    · not tried again: moved to {moved} during the pause")
            outcome.killed = why
            return outcome
        if not resources.reachable():
            outcome.killed = f"{why} ; {self.voice.say('killed-network')}"
            return outcome
        job.resume = session.exists(job.session_id)
        log = log.with_name(f"{log.stem}-again{log.suffix}")
        run.again(job.session_id, log)
        again = self._session(job, text, log, model, live, run)
        again.killed = self._died(again)
        return _added(outcome, again)

    def _moved_away(self, job: Job) -> str:
        """The column the ticket was moved to since its session began, or "".

        Read afresh: the page the run holds says what it was when claimed. One
        that cannot be read is relaunched as before — the session was the
        run's, and nothing says otherwise.
        """
        status = self.config.board.prop("status")
        try:
            found = store.read(self.client.page(job.ticket.page.id), status)
        except store.StoreError:
            return ""
        running = self.config.board.state("running")
        return "" if found == running else str(found or "no status")

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
        adopted, job.adopted = job.adopted, None
        opening = (
            "following session"
            if adopted is not None
            else "picking session"
            if job.resume
            else "Claude session"
        )
        self.say(f"    {opening} {job.session_id}{' · ' + model if model else ''} → {log}")
        return self._paid(
            job.ticket.id,
            text,
            cwd=job.workdir,
            log=log,
            model=model,
            # A session that only plans cannot write, whatever the runner's mode.
            permission_mode=planning.PERMISSION_MODE
            if job.planning == "propose"
            else self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.timeout_minutes,
            session_id=job.session_id,
            resume=job.resume,
            environment={**job.secrets, **self.environment_for(model), **self._github(job)},
            on_event=_both(run.event, live.event if live else None),
            max_budget_usd=self.config.budget.per_ticket_usd,
            adopted=adopted,
            record=adoption.record(job) if job.adoptable else "",
            **self._browsing(job, log),
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
        """The keys this job's project is given, read now — see vault.py.

        Read at every session rather than kept: a token rotated in the keyring
        is the one the next session gets. Under the runner's own variables, so
        that a project can never stand in for the provider's key or the GitHub
        App's token. What could not be read is said, by name only, and the
        ticket runs without it.

        Ponos's own vault adds the entries Context → Vault grants the project
        (vault_store.py), under what the project's Settings tab names: a line
        written for the one project is the more deliberate of the two. What the session is given of it is written
        in the vault's journal, with the ticket.
        """
        if self.dry_run:
            return {}
        project = job.project.name
        try:
            kept = vault_store.granted(project)
        except (sqlite3.Error, OSError) as error:
            self.say(f"    ! the vault of Ponos cannot be read: {error}")
            kept = {}
        granted = {**kept, **project_settings.vault(job.project.page_id)}
        if getattr(job, "kind", "") == "diagnostic":
            # The entries the project's SSH hosts name, declared on its settings
            # page for this road alone: a deliberate grant, read like the others.
            for variables in self._diagnostic_access(job)[1].values():
                for variable in variables:
                    granted.setdefault(variable, f"ponos:{variable}")
        if not granted:
            return {}
        found = vault.read(granted, self.config.vault.provider, config_module.kept_secrets())
        if found.values:
            self.say(f"    · secrets: {', '.join(sorted(found.values))}")
        for missing in found.missing:
            self.say(f"    ! secret not read: {missing}")
        given = [name for name in found.values if granted[name].startswith("ponos:")]
        if given:
            ticket = getattr(job, "ticket", None)
            try:
                vault_store.used(given, getattr(ticket, "id", ""), project)
            except (sqlite3.Error, OSError) as error:
                self.say(f"    ! the vault's journal: {error}")
        # The addresses of the entries it is granted, beside their values and
        # never over a variable `[vault]` names: no secret, so none is masked.
        try:
            places = {
                name: url
                for name, url in vault_store.addresses(project).items()
                if name not in granted
            }
        except (vault.VaultError, sqlite3.Error, OSError) as error:
            self.say(f"    ! the vault's addresses: {error}")
            places = {}
        job.addresses = sorted(places)
        return {**places, **found.values}

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
            **self._browsing(job, log),
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
            subtype=job.subtype,
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
            property_name=self.config.board.prop("progress"),
            interval=self.config.runner.progress_interval_seconds,
            say=self.say,
            # Never on the loop that reads the session: a board slow to answer
            # would stop that loop, and the CLI behind a full pipe — progress.py.
            background=True,
        )

    def _question(self, outcome: session.Outcome, detail: str) -> str | Question:
        """What a ticket that stopped asks: the session's own question, or ours."""
        if outcome.killed:
            return self.voice.say("session-killed-question")
        return (outcome.question or detail) if outcome.blocked else ""

    # -- a ticket on a repository ----------------------------------------------

    def _execute_code(self, job: Job) -> dict[str, Any] | None:
        ticket, project = job.ticket, job.project
        assert project.path is not None

        if job.adopted is not None:
            # A session a runner before this one started, in the worktree it
            # made: nothing is fetched, made or set up again under it.
            worktree = git.Worktree(reused=job.reused)
        else:
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
            job.reused = worktree.reused
            self._note_worktree(job, worktree)
            if failure := self._prepare_worktree(job):
                return failure
            self._place_skills(job)

        # The ticket's own session: written down so that a restart carries it on.
        job.adoptable = True
        try:
            outcome = self._run_session(
                job, prompt_module.template(self.config.runner.prompt_file), subtype=True
            )
        except (OSError, FileNotFoundError) as error:
            git.remove_worktree(project.path, job.workdir)
            return self._fail(
                ticket, self.voice.say("no-session"), str(error), code="session.not-started"
            )

        if stopped := self._halted(job, outcome):
            return stopped

        said = self.voice

        if self._out_of_credit(outcome):
            # Not a failure: there was nothing to work with. The worktree stays
            # where it is whatever `keep_worktree_on_failure` says — the branch
            # is what the next attempt picks up, commits and all, and throwing
            # it away would make the wait cost the work that came before it.
            return self._requeue(
                ticket,
                self.config.board.state("ready"),
                outcome,
                said.say("credit-spent-kept", branch=job.branch)
                if git.commits_ahead(job.workdir, job.base)
                else "",
                home=job.session_home or job.project.path,
            )

        if job.planning == "propose" and (proposed := self._plan_proposed(job, outcome)):
            return proposed

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

        # Read against the ticket before anything else is done with it, so
        # that what it has fixed is replayed and run by the local CI too.
        outcome = self._self_review(job, outcome)
        if stopped := self._halted(job, outcome):
            return stopped
        pull_request = ""
        replayed = False
        if self.config.runner.push and self.config.runner.rebase:
            replayed = self._replay_branch(job)
        # After the replay, so that what passes here is what is pushed.
        outcome, refused = self._local_ci(job, outcome)
        if refused:
            return refused
        commits = git.commits_ahead(job.workdir, job.base)
        shots = self._previews(job)
        if self.config.runner.push:
            if failure := self._push_branch(job, outcome, force=worktree.reused or replayed):
                return failure
            if self.config.runner.open_pull_request:
                pull_request = self._open_pull_request(job, outcome, commits)
                if pull_request and shots:
                    self._attach_previews(job, pull_request)

        return self._code_delivered(job, outcome, commits, pull_request)

    def _plan_proposed(self, job: Job, outcome: session.Outcome) -> dict[str, Any] | None:
        """A planning session's plan, asked about — None when it wrote none.

        The question is the runner's, not the session's: always the same
        yes-no, so that a yes is read as the plan approved (see planning.py),
        and the plan goes last in the report, under its heading, where it is
        read back from. A session that wrote no plan — it asked something
        instead, or was cut short — goes the ordinary way. Nothing is kept of
        its worktree: plan mode wrote nothing in it.
        """
        plan = planning.written(outcome.answer)
        if not plan or outcome.killed or outcome.over_budget:
            return None
        assert job.project.path is not None
        said = self.voice
        git.remove_worktree(job.project.path, job.workdir)
        self.say("    · plan proposed — waiting for a yes before any code")
        asked = Question(
            ask=said.say("plan-ask"),
            mode="yes-no",
            done=said.say("plan-done"),
            why=said.say("plan-why"),
            category="question",
        )
        return self._fail(
            job.ticket,
            said.say(blocks.cause("session.question").said[0]),
            code="session.question",
            blocked=True,
            question=asked,
            note=f"{said.say('plan-heading')}\n\n{planning.clipped(plan)}",
            outcome=outcome,
        )

    def _place_skills(self, job: Job) -> None:
        """The skills Ponos gives this project, put in the worktree for its session — see skills.py."""
        if self.dry_run:
            return
        try:
            placed = skills.install(job.workdir, job.project.page_id)
        except (OSError, *db.ERRORS) as error:
            logger.warning("skills not placed in %s: %s", job.workdir, error)
            return
        if placed.placed:
            self.say(f"    · skills placed: {', '.join(placed.placed)}")
        if placed.kept_from_repository:
            self.say(
                f"    · skills the repository already has, kept: {', '.join(placed.kept_from_repository)}"
            )

    def _prepare_worktree(self, job: Job) -> dict[str, Any] | None:
        """The project's setup command, run in the fresh worktree before any session.

        None when there was nothing to run or it went well — the session is
        then told it has already run, so that it does not install again.
        Otherwise what `_fail` made of it: the ticket is blocked with the end
        of the output, and no session was started or paid for. See
        worktree_setup.py.
        """
        ticket, project = job.ticket, job.project
        chosen = worktree_setup.plan(project_settings.setup(project.page_id), job.workdir)
        if not chosen or self.dry_run:
            return None
        minutes = self.config.runner.setup_timeout_minutes
        log = (job.log or state.log_file(short_id(ticket.id))).with_suffix(".setup.log")
        self.say(f"    · setup ({chosen.source}): {chosen.shown}")
        ran = worktree_setup.run(
            chosen, job.workdir, log, timeout_minutes=minutes, secrets=self._secrets(job)
        )
        self.say(f"    · setup {'done' if ran.ok else 'failed'} in {ran.seconds:.0f}s — {log}")
        if ran.ok:
            job.prepared = self.voice.say("setup-done", command=chosen.shown)
            return None
        detail = (
            f"`{chosen.shown}` — "
            + (f"stopped after {minutes} minutes" if ran.timed_out else f"exit {ran.code}")
            + f"\n\n```\n{vault.mask(ran.tail).strip() or '(no output)'}\n```"
        )
        said = self.voice
        kept = ""
        if self.config.runner.keep_worktree_on_failure:
            kept = said.say("worktree-kept", path=job.workdir, branch=job.branch)
        else:
            assert project.path is not None
            git.remove_worktree(project.path, job.workdir)
        return self._fail(
            ticket,
            said.say("setup-failed"),
            detail,
            code="worktree.setup-failed",
            blocked=True,
            question=said.say("setup-question"),
            note=kept,
        )

    # -- the captures, before the push ------------------------------------------

    def _previews(self, job: Job) -> bool:
        """Photograph the project's pages on the base and on the branch, when it asks to be.

        True when pairs of captures were kept for the ticket. Never a failure:
        a pass that cannot be taken is a line on the ticket and the work goes
        to review without pictures. See preview.py.
        """
        ticket, project = job.ticket, job.project
        setting = project_settings.preview(project.page_id)
        if not setting or self.dry_run or project.path is None:
            return False
        destination = preview.folder(ticket.id)
        preview.clear(destination)
        preview.write_pages(destination, setting)
        log = (job.log or state.log_file(short_id(ticket.id))).with_suffix(".preview.log")
        secrets = self._secrets(job)
        taken = preview.Taken()
        base_dir = job.workdir.with_name(job.workdir.name + "-base")
        self.say(f"    · captures: {setting.command} ({len(setting.pages)} page(s))")
        try:
            taken.files["after"], taken.skipped = preview.shoot(
                setting, job.workdir, destination, "after", log=log, env=secrets
            )
            if not taken.skipped:
                taken.skipped = git.add_base_worktree(project.path, base_dir, job.base)
            if not taken.skipped:
                chosen = worktree_setup.plan(project_settings.setup(project.page_id), base_dir)
                if chosen:
                    ran = worktree_setup.run(
                        chosen,
                        base_dir,
                        log.with_suffix(".base-setup.log"),
                        timeout_minutes=self.config.runner.setup_timeout_minutes,
                        secrets=secrets,
                    )
                    taken.skipped = "" if ran.ok else "the setup command failed on the base"
            if not taken.skipped:
                taken.files["before"], taken.skipped = preview.shoot(
                    setting, base_dir, destination, "before", log=log, env=secrets
                )
        except Exception as error:  # a capture is never a reason to lose the work
            logger.exception("captures failed")
            taken.skipped = str(error)
        finally:
            if base_dir.exists():
                git.remove_worktree(project.path, base_dir)
        if taken.pairs:
            self.say(f"    · captures: {taken.pairs} before/after pair(s) — {destination}")
            return True
        preview.clear(destination)
        self.say(f"    ! captures not taken: {taken.skipped}")
        job.notes.append(self.voice.say("previews-skipped", reason=taken.skipped))
        return False

    def _attach_previews(self, job: Job, pull_request: str) -> None:
        """The captures on the pull request, as a comment — and a line for the report.

        The pictures are pushed beside the branch (`git.push_pictures`) and
        shown from that commit, which any reader of the repository can see;
        when the push is refused, from the console, which only its owner can.
        """
        shots = preview.listing(job.ticket.id)
        bare = job.ticket.id.replace("-", "")
        destination = preview.folder(job.ticket.id)
        pushed = git.push_pictures(
            job.workdir,
            f"previews/{short_id(job.ticket.id)}",
            [destination / shot["file"] for shot in shots],
            self.config.github,
        )
        repository = pull_request.split("/pull/")[0]
        console = self.config.web.url.rstrip("/") if self.config.web.url else ""

        def link(name: str) -> str:
            if pushed and repository.startswith("https://github.com/"):
                return f"{repository}/blob/{pushed}/{name}?raw=true"
            return f"{console}/api/tickets/{bare}/previews/{name}" if console else ""

        body = self.voice.previews_comment(shots, link)
        if not git.comment_pull_request(pull_request, body, self.config.github):
            job.notes.append(self.voice.say("previews-not-posted"))

    # -- the local CI, before the push ------------------------------------------

    def _local_ci(
        self, job: Job, outcome: session.Outcome
    ) -> tuple[session.Outcome, dict[str, Any] | None]:
        """The project's CI run here, and handed back to the session while it is red.

        Returns the session as it now stands — the fixes cost what they cost —
        and, when the ticket cannot go on, what `_fail` or `_code_stopped`
        made of it. Off, without Docker, or with nothing to run, the ticket
        goes on exactly as it did before: see local_ci.py.
        """
        project = job.project
        own = project_settings.local_ci(project.page_id)
        enabled = own["enabled"] if own["enabled"] is not None else self.config.runner.local_ci
        if not enabled:
            return outcome, None
        docker = local_ci.docker()
        if not docker.available:
            self.say("    · local CI skipped: Docker does not answer here")
            return outcome, None
        chosen = local_ci.plan(own["command"], job.workdir, job.ticket.id)
        said = self.voice
        if not chosen:
            self.say("    · local CI skipped: no command declared, and no act to run workflows")
            job.notes.append(said.say("local-ci-none"))
            return outcome, None
        attempts = self.config.runner.local_ci_attempts
        log = job.log or state.log_file(short_id(job.ticket.id))
        ran: local_ci.Run | None = None
        for attempt in range(1, attempts + 1):
            ran = self._run_local_ci(job, chosen, log.with_name(f"{log.stem}-ci-{attempt}.log"))
            if ran.ok:
                job.notes.append(
                    said.say("local-ci-ok")
                    if attempt == 1
                    else said.say("local-ci-fixed", count=attempt)
                )
                return outcome, None
            if attempt == attempts:
                break
            outcome = self._fix_local_ci(job, outcome, chosen, ran, attempt, attempts, log)
            if not outcome.ok:
                return outcome, self._code_stopped(job, outcome)
        assert ran is not None
        detail = (
            said.say(
                "local-ci-timed-out",
                command=chosen.shown,
                minutes=self.config.runner.timeout_minutes,
            )
            if ran.timed_out
            else said.say("local-ci-detail", command=chosen.shown, code=ran.code)
        )
        kept = ""
        if self.config.runner.keep_worktree_on_failure:
            kept = said.say("worktree-kept", path=job.workdir, branch=job.branch)
        else:
            assert project.path is not None
            git.remove_worktree(project.path, job.workdir)
        return outcome, self._fail(
            job.ticket,
            said.say("local-ci-failed", count=attempts),
            detail,
            code="merge.local-ci-failed",
            blocked=True,
            question=said.say("local-ci-question", command=chosen.shown, count=attempts),
            note=self._filed(job, outcome, kept),
            outcome=outcome,
        )

    def _run_local_ci(self, job: Job, chosen: local_ci.Plan, log: Path) -> local_ci.Run:
        """One run of the CI, in one of the machine's places, and its containers gone after."""
        ci_name = local_ci.name(job.ticket.id)
        places = self.config.runner.local_ci_concurrent
        state.enter(job.ticket.id, "local-ci", chosen.shown)
        with local_ci.place(
            places, lambda: self.say(f"    · local CI waiting for a place ({places} at a time)")
        ):
            self.say(f"    · local CI: {chosen.shown} → {log}")
            try:
                ran = local_ci.run(
                    chosen,
                    job.workdir,
                    ci_name,
                    log,
                    timeout_minutes=self.config.runner.timeout_minutes,
                    secrets=job.secrets,
                )
            finally:
                removed = local_ci.clean(ci_name)
                if removed:
                    self.say(
                        f"    · local CI: {removed} container(s), network(s) or volume(s) removed"
                    )
        self.say(
            f"    · local CI {'green' if ran.ok else 'red'} in {ran.seconds:.0f}s"
            + ("" if ran.ok else f" (exit {ran.code})")
        )
        return ran

    def _fix_local_ci(
        self,
        job: Job,
        outcome: session.Outcome,
        chosen: local_ci.Plan,
        ran: local_ci.Run,
        attempt: int,
        attempts: int,
        log: Path,
    ) -> session.Outcome:
        """The same session, picked up to fix what the CI said — what both halves cost, added up."""
        self.say(f"    ↻ local CI red — asking session {outcome.session_id} to fix it")
        state.enter(job.ticket.id, "repair", chosen.shown)
        # Filed under the project once it ended: brought back beside its
        # worktree for as long as it is carried on, and filed again after.
        session.relocate(outcome.session_id, job.workdir)
        model = self.config.runner.allowed(job.model or job.agent.model or self.config.runner.model)
        run = self._journals.get(job.ticket.id)
        fixed = self._paid(
            job.ticket.id,
            prompt_module.local_ci(
                chosen.shown, ran.tail, attempt, attempts, self.voice.instruction()
            ),
            cwd=job.workdir,
            log=log.with_name(f"{log.stem}-fix-{attempt}{log.suffix}"),
            model=model,
            permission_mode=self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.timeout_minutes,
            session_id=outcome.session_id,
            resume=True,
            environment={**job.secrets, **self.environment_for(model), **self._github(job)},
            on_event=run.event if run else None,
            max_budget_usd=self.config.budget.per_ticket_usd,
        )
        if job.session_home:
            session.relocate(outcome.session_id, job.session_home)
        return replace(
            fixed,
            cost_usd=outcome.cost_usd + fixed.cost_usd,
            seconds=outcome.seconds + fixed.seconds,
            turns=outcome.turns + fixed.turns,
            # What the ticket's report says it did is what the first half
            # said: the fix is a footnote to it, said by the note.
            summary=outcome.summary if fixed.ok else fixed.summary,
            answer=outcome.answer if fixed.ok else fixed.answer,
            caveats=[*outcome.caveats, *fixed.caveats],
        )

    def _halted(self, job: Job, outcome: session.Outcome) -> dict[str, Any] | None:
        """A session the console asked to end: the ticket is theirs from here on.

        Neither a failure nor an answer, so nothing is written on the board —
        the console moves the ticket, and keeps or removes its worktree once the
        acknowledgement below says the session is gone. See stopping.py.
        """
        ticket = job.ticket
        action = stopping.requested(ticket.id)
        if not (outcome.stopped and action):
            return None
        self.say(f"    ■ {ticket.title} — ended on request ({action})")
        state.release(ticket.id)
        stopping.acknowledge(ticket.id)
        return {"ticket": ticket.title, "id": ticket.id, "status": "stopped", "reason": action}

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

    def _code_stopped(self, job: Job, outcome: session.Outcome) -> dict[str, Any]:
        """A session that did not succeed: blocked on a question, or killed."""
        ticket, project = job.ticket, job.project
        assert project.path is not None
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

    def _nothing_committed(self, job: Job, outcome: session.Outcome) -> dict[str, Any] | None:
        """A session that succeeded with no commit: done outside, or blocked."""
        ticket, project = job.ticket, job.project
        assert project.path is not None
        said = self.voice
        dirty = git.is_dirty(job.workdir)
        if not dirty and self.review_brief(ticket) and outcome.ok:
            # A review of the pull request that asked for nothing to change:
            # the reply in each thread says why, and the ticket goes back to
            # review as it was.
            git.remove_worktree(project.path, job.workdir)
            self.say("    · nothing committed, the review needed no change — back to review")
            self.answer_reviews(ticket, outcome.answer, changed=False, why=outcome.summary)
            return self._deliver_text(
                job,
                outcome,
                _report(outcome.answer) or outcome.summary,
                review=True,
                note=said.say("already-settled"),
            )
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
        if not dirty and _settled(outcome.summary):
            # Nothing to commit because the change was already made — on main,
            # by the pull request the verdict names — or went to other pull
            # requests. Its report is what it delivers, in review: whether the
            # ticket is closed by it is yours to say.
            git.remove_worktree(project.path, job.workdir)
            self.say("    · nothing committed, the change was already made — sent to review")
            return self._deliver_text(
                job,
                outcome,
                _report(outcome.answer) or outcome.summary,
                review=True,
                note=said.say("already-settled"),
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
        assert project.path is not None
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
        state.enter(job.ticket.id, "rebase", job.base)
        was = git.head(job.workdir)
        if failure := git.rebase(job.workdir, start, generated.settle):
            self.say(f"    ! not replayed onto {start}: {failure}")
            job.notes.append(said.say("rebase-refused", base=start, error=failure))
        elif git.head(job.workdir) != was:
            replayed = True
            self.say(f"    · replayed onto {start}")
            job.notes.append(said.say("rebased-onto", base=start))
        return replayed

    def _push_branch(
        self, job: Job, outcome: session.Outcome, *, force: bool
    ) -> dict[str, Any] | None:
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
        # The self-review's section under the summary, above the footer: what
        # the person reviewing reads before the diff — see review.py.
        summary = f"{outcome.summary}\n\n{job.review}" if job.review else outcome.summary
        body = said.pull_request_body(summary, ticket.url, outcome.session_id, commits)
        try:
            # Prefixed the conventional way when the sub-type is known:
            # squashed, the title is the commit that lands on the base.
            pull_request = git.open_pull_request(
                job.workdir,
                subtypes.titled(job.subtype, ticket.title),
                body,
                job.base,
                accounts=self.config.github,
                signed=self.config.claude.attribution,
            )
        except git.GitError as error:
            self.say(f"    ! pull request not opened: {error}")
            job.notes.append(said.say("no-pull-request-opened", error=error))
        return pull_request

    def _code_delivered(
        self, job: Job, outcome: session.Outcome, commits: int, pull_request: str
    ) -> dict[str, Any]:
        """A branch with commits: merged when forced, the board moved, and the ticket told."""
        ticket, project = job.ticket, job.project
        assert project.path is not None
        # The pushed commits are what answers the reviewers' threads on GitHub.
        self.answer_reviews(ticket, outcome.answer, changed=True)
        outcome, result = self._code_result(job, outcome, pull_request)
        forced, refused, later = self._merge_forced(job, pull_request)
        merged = bool(forced and not refused)
        git.remove_worktree(project.path, job.workdir)
        self._code_moved(job, outcome, pull_request, merged, refused, later)
        self._code_told(job, outcome, commits, pull_request, forced, refused, later, result)
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

    def _code_result(
        self, job: Job, outcome: session.Outcome, pull_request: str
    ) -> tuple[session.Outcome, str]:
        """The result of a code ticket: the session's own, and the files its branch touches.

        Read from the worktree before it goes. A session that wrote none is
        not taken for finished all the same: it is said, as a line to check,
        and the ticket keeps the result it had. See results.py.
        """
        said = self.voice
        written, _ = results.extract(outcome.answer)
        if not written:
            missing = said.say("no-result")
            self.say(f"    ! {job.ticket.title}: no result rendered")
            outcome = replace(outcome, caveats=[*outcome.caveats, missing])
            if (run := self._journals.get(job.ticket.id)) is not None:
                run.caveats = outcome.caveats
            return outcome, ""
        appendix = results.code_appendix(
            git.diff_stat(job.workdir, job.base),
            pull_request,
            files=said.say("result-files"),
            diff=said.say("result-diff"),
        )
        text = f"{written}\n\n{appendix}".strip()
        self._write_result(job.ticket, text)
        return outcome, text

    def _merge_forced(self, job: Job, pull_request: str) -> tuple[str, str, bool]:
        """Force validated: the merge that moving the ticket to validated would
        have asked for, asked now — before the worktree goes, since the CI it
        waits for is read from it. Only this far down: every road out of a
        session that did not succeed has already been taken above. A merge
        that is only *not yet* — a branch overtaken while its CI ran, a CI
        still running — is left in validated, for `_merge` to finish.

        What forced it, why it was refused, and whether that is only for later.
        """
        forced = refused = ""
        later = False
        if pull_request:
            forced = self._forced("code", job.project)
        if forced:
            self.say(f"    · {forced}")
            refused, later = self._force_merge(job, pull_request)
        return forced, refused, later

    def _refusal(self, refused: str, later: bool) -> str:
        """What a forced merge that did not happen says, postponed or refused."""
        said = self.voice
        if later:
            return said.say("forced-merge-postponed", reason=refused)
        return said.say("forced-merge-refused", error=refused)

    def _code_moved(
        self,
        job: Job,
        outcome: session.Outcome,
        pull_request: str,
        merged: bool,
        refused: str,
        later: bool,
    ) -> None:
        """The ticket's column and properties, once its branch is delivered."""
        said = self.voice
        # With a pull request the ticket is not finished, it is waiting for you:
        # it goes to "in review", and `close_merged` takes it to done once you
        # have merged. Without one there is nothing to wait for — and on a board
        # with no review column, `review` is `done` and nothing changes. A merge
        # forced and refused waits there too, with the refusal on its card; one
        # postponed waits in validated, with the reason on its card.
        column = "validated" if later else "review" if pull_request and not merged else "done"
        values: dict[str, object] = {
            self.config.board.prop("status"): self.config.board.state(column),
            self.config.board.prop("agent"): self.agent_label,
        }
        if pull_request:
            values[self.config.board.prop("pull_request")] = pull_request
        if refused:
            # The card's line outlives the column it was written in: you
            # validate from review, and a line saying "left in review" would
            # then stand in validated. So it says what happened, not where.
            card = (
                self._refusal(refused, later)
                if later
                else said.say("forced-merge-refused-card", error=refused)
            )
            values[self.config.board.prop("progress")] = said.brief(card)
        values[self.config.board.prop("session")] = self._session_value(
            outcome.session_id, job.session_home or job.project.path
        )
        values.update(self._measures(outcome))
        self._set(job.ticket, **values)

    def _code_told(
        self,
        job: Job,
        outcome: session.Outcome,
        commits: int,
        pull_request: str,
        forced: str,
        refused: str,
        later: bool,
        result: str = "",
    ) -> None:
        """The report of a delivered branch: on the ticket, in the log, on your phone."""
        ticket = job.ticket
        said = self.voice
        merged = bool(forced and not refused)
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
        forced_lines = (forced, said.brief(self._refusal(refused, later)) if refused else "")
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
            project=job.project.name,
            facts=placed,
            summary=outcome.summary,
            pull_request=pull_request,
            result=result,
        )

    # -- a ticket that has none -------------------------------------------------

    def _execute_document(self, job: Job) -> dict[str, Any] | None:
        """A ticket with no repository: the deliverable is the ticket's own page."""
        ticket = job.ticket
        job.workdir.mkdir(parents=True, exist_ok=True)
        job.adoptable = True
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

        if stopped := self._halted(job, outcome):
            return stopped

        if self._out_of_credit(outcome):
            # The working directory is left as it is: whatever the session had
            # written into ANSWER.md before the quota ran out is what the next
            # attempt opens on.
            return self._requeue(
                ticket,
                self.config.board.state("ready"),
                outcome,
                home=job.session_home,
            )

        if switched := self._switch_to_code(job, outcome):
            return switched

        answer_file = job.workdir / "ANSWER.md"
        # The deliverable is ANSWER.md; a session that wrote it in its message
        # instead, between the lines of a code session's result, is read there.
        content = _answer(job.workdir) or results.extract(outcome.answer)[0]

        # Answered and finished, but said as a stop: read, rather than asked
        # again — see `_answered_anyway`. In review, since it said blocked.
        # Never a diagnostic: one that stopped did not find its cause, and what
        # it wrote is not to become tickets.
        anyway = bool(content) and _answered_anyway(job, outcome) and job.kind != "diagnostic"
        if anyway:
            self.say("    · blocked without a question, its answer written — sent to review")
            outcome = replace(outcome, ok=True, blocked=False)

        if not outcome.ok or not content:
            return self._document_failed(job, outcome, content)

        if job.kind == "diagnostic":
            return self._diagnosed(job, outcome, content)

        opened, note = self._adopted(outcome)
        return self._deliver_text(
            job,
            outcome,
            content,
            review=anyway or bool(opened),
            kept=answer_file,
            note=note,
            pull_request=opened[-1] if opened else "",
        )

    def _switch_to_code(self, job: Job, outcome: session.Outcome) -> dict[str, Any] | None:
        """A session that says the ticket was code, believed once: None otherwise.

        Its `KIND: code` line — see `kinds.claimed` — on a ticket that was given
        no repository although its project has one, and that the runner has
        never switched before: the type column says Code, a comment says why,
        and the ticket goes back to ready for the next pass to run it in a
        worktree, with a session of its own. Not asked, and nobody's phone
        rings: the session already said what a person would have answered.
        A second claim is not believed — the ticket ends as its session did.
        """
        # A diagnostic that needs code says so in a fix ticket, and is not made code.
        if (
            job.kind in ("code", "diagnostic")
            or not job.reference
            or kinds.claimed(outcome.answer) != "code"
        ):
            return None
        ticket = job.ticket
        column = self.type_column()
        if not column:
            return None
        if state.switched_kind(ticket.id):
            self.say("    · it says it is code again — already switched once, not again")
            return None
        name = self.kind_name("code")
        said = self.voice
        try:
            self.client.update(self.database, ticket.page.id, {column: name})
        except store.StoreError as error:
            self.say(f"  ! the type could not be written: {voice_module.line(error)}")
            return None
        state.switch_kind(ticket.id)
        shutil.rmtree(job.workdir, ignore_errors=True)
        self.say(f"    ↩ {ticket.title} — the session says it is code: made {name}, back in ready")
        self._set(
            ticket,
            **{
                self.config.board.prop("status"): self.config.board.state("ready"),
                **self._measures(outcome),
            },
        )
        self._comment(
            ticket,
            said.report(
                said.verdict("requeued", *said.spent(outcome.seconds, outcome.cost_usd)),
                said.brief(outcome.summary),
                said.say("kind-switched", property=column, kind=name),
            ),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "requeued",
            "project": job.project.name,
            "kind": "code",
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    def _document_failed(
        self, job: Job, outcome: session.Outcome, content: str
    ) -> dict[str, Any] | None:
        """A ticket with no repository whose session stopped, or wrote no answer."""
        said = self.voice
        # A session that stopped on its question asked something, like a
        # code ticket's: "no answer" is for the one that wrote neither.
        code, reason, detail = self._why_stopped(
            outcome,
            "session.question"
            if outcome.blocked
            else "session.no-answer"
            if not content
            else "session.killed",
        )
        if not content and outcome.ok:
            detail = said.say("no-answer-detail", summary=outcome.summary)
        kept = ""
        if self.config.runner.keep_worktree_on_failure:
            kept = said.say("workdir-kept", path=job.workdir)
        else:
            shutil.rmtree(job.workdir, ignore_errors=True)
        return self._fail(
            job.ticket,
            reason,
            detail,
            code=code,
            blocked=outcome.blocked or not content or bool(outcome.killed),
            question=self._question(outcome, detail) or outcome.question or detail,
            note=self._filed(job, outcome, kept),
            outcome=outcome,
        )

    def _adopted(self, outcome: session.Outcome) -> tuple[list[str], str]:
        """The pull requests a session opened by itself, and the line saying so."""
        said = self.voice
        # A session that was not on a code ticket's road opened a pull request
        # anyway: attached to the ticket and sent to review, so it is merged
        # through the validated column like any other — rather than left on
        # GitHub, out of sight of the board, under a ticket that says done.
        opened = session.pull_requests(outcome.log)
        if not opened:
            return opened, ""
        self.say(f"    · the session opened {', '.join(opened)} itself — attached, sent to review")
        return opened, said.paragraphs(
            said.say("pull-request-adopted", url=opened[-1]),
            said.say("pull-requests-also", urls=", ".join(opened[:-1])) if opened[1:] else "",
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
    ) -> dict[str, Any] | None:
        """A ticket whose deliverable is a text, written into its page.

        `review` sends it to be read rather than to done; `kept` is where the
        text still is on disk, should the page refuse it; `note` is one more
        line for the report; `pull_request` is one the session opened itself,
        written into the ticket's column so validating it merges it.
        """
        ticket = job.ticket
        said = self.voice
        # The text is the ticket's result, a version of its own; the session's
        # message, the report of its part « What was done » — written now, a
        # page that refuses either fails the ticket, and the report again, with
        # its line of history, when the run is closed. See results.py.
        try:
            self._write_result(ticket, content, strict=True)
            self._write_done(
                ticket,
                ticket_page.report(
                    said,
                    status="done",
                    summary=outcome.summary,
                    pull_request=pull_request,
                    answer=outcome.answer,
                ),
                strict=True,
            )
        except store.StoreError as error:
            return self._fail(
                ticket,
                said.say("answer-not-written"),
                voice_module.line(error),
                code="board.write-failed",
                note=self._filed(
                    job, outcome, said.say("answer-on-disk", path=kept) if kept else ""
                ),
                outcome=outcome,
            )
        blocks = len([part for part in content.split("\n\n") if part.strip()])

        shutil.rmtree(job.workdir, ignore_errors=True)
        # A publication is only prepared: it waits in review for you to read it,
        # and `Delivery._publish` puts it out once you have moved it to
        # validated. On a board whose review is its done there is no such
        # gesture, and it ends there as any text does — prepared, not published.
        prepared = job.kind == "publication"
        following, forced, postponed = self._publication_forced(job, prepared, pull_request)
        column = ""
        if not forced or postponed:
            column = "validated" if postponed else "review" if prepared or review else "done"
        self._text_moved(job, outcome, pull_request, column)
        if forced:
            self.say(f"    · {following}")
            if not postponed:
                # One report for the two sessions, the publication's: a ticket
                # saying “to validate” a second before it says “published”
                # would be telling you to do what is already being done.
                return self._publish(ticket, job.project, forced=following, prepared=outcome)
            following = said.paragraphs(following, said.say("forced-postponed"))
        elif prepared and self.validated_column():
            following = said.say("prepared-next", validated=self.config.board.state("validated"))
        else:
            following = ""
        verdict = (
            "waiting" if forced else "prepared" if prepared else "review" if review else "read"
        )
        self._text_told(job, outcome, blocks, verdict, following, note, content)
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

    def _publication_forced(
        self, job: Job, prepared: bool, pull_request: str
    ) -> tuple[str, bool, bool]:
        """Force validated on a publication: what forced it, whether it is, and
        whether it waits for credit.

        Nothing waits for you, and the publishing session is started as soon
        as this one is done — `Delivery._publish`, exactly as moving the ticket
        to validated would have started it. Under the credit reserve it is not
        started here: the ticket goes to validated, for the pass that has
        credit again to publish it, as it would one you had moved there
        yourself. A board with no such column has nowhere to hold it, and the
        ticket waits in review as it always did.
        """
        following = (
            self._forced("publication", job.project) if prepared and not pull_request else ""
        )
        forced = bool(following)
        postponed = forced and bool(self.under_reserve())
        if postponed and not self.validated_column():
            forced = postponed = False
        return following, forced, postponed

    def _text_moved(
        self, job: Job, outcome: session.Outcome, pull_request: str, column: str
    ) -> None:
        """The ticket's properties once its text is written — and its column, unless ''."""
        values: dict[str, object] = {
            self.config.board.prop("agent"): self.agent_label,
            self.config.board.prop("session"): self._session_value(
                outcome.session_id, job.session_home or job.project.path
            ),
            **self._measures(outcome),
        }
        if pull_request:
            values[self.config.board.prop("pull_request")] = pull_request
        if column:
            values[self.config.board.prop("status")] = self.config.board.state(column)
        self._set(job.ticket, **values)

    def _text_told(
        self,
        job: Job,
        outcome: session.Outcome,
        blocks: int,
        verdict: str,
        following: str,
        note: str,
        content: str = "",
    ) -> None:
        """The report of a text written into its page: on the ticket, in the log, on your phone."""
        ticket = job.ticket
        said = self.voice
        prepared = job.kind == "publication"
        placed = (
            said.say("in-the-page"),
            said.say("nothing-published") if prepared else said.count(blocks, "block"),
        )
        facts = (*placed, *said.spent(outcome.seconds, outcome.cost_usd))
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
            + (", nothing published: in review" if prepared and verdict != "waiting" else "")
        )
        self._tell(
            "done",
            ticket,
            verdict,
            said.report(said.facts(*facts), brief, following),
            project=job.project.name,
            facts=placed,
            summary=outcome.summary,
            result=content,
        )
