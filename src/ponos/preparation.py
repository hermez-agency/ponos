"""Everything between a ticket coming off the board and a session starting.

Locate the project, read the body, give the page a title if it has none, draw
the branch and the directory the work will happen in, and *claim* the ticket by
moving it to "in progress". What comes out is a `Job`: the ticket, plus every
decision a session needs taken before it can be started.

Claiming is why this happens in the pass's own thread and nowhere else — see
`Runner._work`. Two tickets prepared side by side would race over the same
repository index, and a ticket not claimed before it is worked on is a ticket
the next tick of the timer would happily pick up as well.

A ticket that cannot be used is failed here rather than carried further: no
project anybody can find, a body Notion will not hand over, a page with neither
title nor content. Each of them returns `None`, and the pass goes on to the
next ticket. So does one moved out of ready while it was being prepared — the
claim did not take, and the move is the answer. So does one whose type nobody wrote and the runner could not tell
for sure: it is blocked with the question before anything is claimed — see
kinds.py for why a doubt is never settled by running the ticket.
"""

from __future__ import annotations

import shutil

from . import (
    agents,
    git,
    goals,
    journal,
    kinds,
    models,
    naming,
    priority,
    provider,
    session,
    state,
    store,
    subtypes,
)
from . import voice as voice_module
from .base import Base
from .config import state_dir
from .projects import Project
from .ticket import Job, Ticket, is_blank, short_id, slugify


class Preparation(Base):
    """A ticket turned into the job a session can be started on."""

    def prepare(self, ticket: Ticket) -> Job | None:
        """Locate the project and claim the ticket. None if it is unusable."""
        relation = store.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            # No project at all is not an error: it is the plainest possible
            # document ticket. "Draft me an email", "summarise this" — there is
            # nothing to commit and nowhere to commit it, so the answer goes
            # back into the page, exactly as for a project without a repository.
            project = Project(name="", path=None)
        else:
            try:
                # The one caller allowed to fetch a repository that is declared
                # but not on this machine: a ticket about to run needs the
                # clone to exist, and a project created from its GitHub link
                # alone has never had one made. A dry run stays a dry run.
                project = self.resolver.resolve(self.client, relation[0], clone=not self.dry_run)
            except (LookupError, store.StoreError) as error:
                self._fail(
                    ticket,
                    self.voice.say("no-project"),
                    str(error),
                    code="project.no-repo",
                    blocked=True,
                )
                return None

        short = short_id(ticket.id)
        try:
            body = self.client.blocks_text(ticket.page.id, live=False)
        except store.StoreError as error:
            self._fail(ticket, self.voice.say("unreadable"), str(error), code="notion.read-failed")
            return None
        if is_blank(body):
            body = ""
            if not ticket.page.title.strip():
                self._fail(
                    ticket,
                    self.voice.say("empty-ticket"),
                    self.voice.say("empty-ticket-detail"),
                    code="ticket.empty",
                    blocked=True,
                )
                return None
        elif not ticket.page.title.strip() and not self.dry_run:
            # Named before the branch is drawn, since the branch is made of the
            # title. Only a page whose title is empty ever gets here, so the
            # common case costs nothing — and a dry run writes nowhere.
            self._name(ticket, body, short)

        # After the name, which the classification reads, and before the branch
        # is drawn, which the type decides whether there is one at all.
        kind, answer = self._kind(ticket, body, project)
        if kind is None:
            return None
        reference = None
        worked = kinds.worked_in(project, kind)
        if worked is not project:
            reference, project = project.path, worked
        # Only on the road of a code ticket: the column is ignored on the others.
        subtype, note = self._subtype(ticket, body, answer) if project.is_code else ("", "")

        stem = f"{slugify(project.name, 24)}-{short}"
        if project.path is not None:  # `is_code`, spelled out for mypy to narrow
            base = self.config.runner.base_branch or git.default_branch(project.path)
            branch = f"{self.config.runner.branch_prefix}{slugify(ticket.title)}-{short}"
            workdir = state_dir() / "worktrees" / stem
        else:
            # No repository: an empty scratch directory, and the answer goes
            # back into the Notion page instead of into a pull request.
            base, branch = "", ""
            workdir = state_dir() / "scratch" / stem

        # Both are optional and neither can fail a ticket: a database with no
        # Agent column reads as no agent, and unreadable comments as none.
        role = store.read(ticket.page, self.config.notion.prop("role")) or []
        agent = (
            agents.resolve(self.client, role[0], self.config.notion.prop("model"))
            if role
            else agents.Agent()
        )
        # The same for the goal it serves, a relation too: no Objectif column,
        # an empty one or an unreadable page all read as no goal.
        pointed = goals.pointed(ticket.page, self.config.notion.prop("goal"))
        goal = goals.resolve(self.client, pointed) if pointed else goals.Goal()

        # A ticket ticked as waiting for credit already has a session, stopped
        # mid-sentence by a spent window rather than finished. Carrying it on
        # costs a message where starting over costs the whole ticket again
        # — and the session is what remembers the half of the work that is not
        # in a commit yet. Anything else gets a fresh identifier, as ever.
        carried = self._carried_session(ticket)
        job = Job(
            ticket,
            project,
            branch,
            base,
            workdir,
            body,
            session_id=carried or session.new_id(),
            resume=bool(carried),
            log=state.log_file(short),
            model=self._written_model(ticket),
            agent=agent,
            goal=goal,
            comments=self.discussion(ticket),
            kind=kind,
            reference=reference,
            subtype=subtype,
        )
        if note:
            job.notes.append(note)
        written = job.model or agent.model
        if written and self.config.runner.allowed(written) != written:
            # Written by somebody, so said on the ticket: a Model that is not
            # the one it ran on would otherwise read as the runner's mistake.
            job.model = self.config.runner.allowed(written)
            job.notes.append(self.voice.say("fable-refused"))
        if provider.on_openrouter(job.model or agent.model) and not self.config.openrouter.key:
            # A slug means something only to OpenRouter: without its key the CLI
            # would fail on a model it has never heard of, and say so obscurely.
            self._fail(
                ticket,
                self.voice.say("openrouter-key-missing", model=job.model or agent.model),
                self.voice.say("openrouter-key-missing-detail"),
                code="access.credentials",
                blocked=True,
            )
            return None
        if not job.model and not agent.model and self.config.runner.auto_model:
            self._choose_model(ticket, job)
        where = f"{project.path} · {branch}" if project.is_code else "document → the ticket's page"
        said = f" · {len(job.comments)} comment(s)" if job.comments else ""
        role = f" · as {agent.name}" if agent else ""
        typed = f" · {kind}" if kind else ""
        model = f" · {job.model} (chosen)" if job.chosen else ""
        self.say(
            f"  → {ticket.title}\n    {project.name or 'no project'} · {where}{typed}{role}"
            f"{model}{said}"
        )
        # `cloned` says the repository was not here until a minute ago — worth a
        # line, since the ticket is running on a folder nobody made by hand.
        # `note` says it was found by a way of last resort: the ticket runs, and
        # the ticket's comment says which declaration on the project page to
        # correct — or the page stays wrong for as long as the fallback works.
        for line in (project.cloned, project.note):
            if line:
                self.say("    · " + line)
                job.notes.append(line)
        if not self.dry_run:
            # The session identifier is written now, not at the end: a ticket
            # still in progress is exactly the one you want to look into, and
            # `claude --resume <id>` replays it even while it runs.
            claimed = self._claim(
                ticket,
                **{
                    self.config.notion.prop("status"): self.config.notion.state("running"),
                    self.config.notion.prop("agent"): self.agent_label,
                    # The wait is over for this one: see the same line in
                    # `_publish`. Read before this write, by `_carried_session`.
                    self.config.notion.prop("waiting"): False,
                    self.config.notion.prop("session"): self._session_value(
                        job.session_id, project.path
                    ),
                },
            )
            if not claimed:
                # Moved by somebody while it was being prepared: their move is
                # the answer, so no failure is written over it — only the log.
                self.say(f"    · {ticket.title} — not started: it left ready before its claim")
                return None
        return job

    def _written_model(self, ticket: Ticket) -> str:
        """The model somebody wrote on the ticket — not the one this runner did.

        The choice is written into the Model column (see `_choose_model`), so
        on the next attempt the column holds the runner's own pick. That one
        reads as no model at all, or a run that failed could never climb. A
        model that differs from the last pick is somebody's, and stays theirs.
        """
        written = str(store.read(ticket.page, self.config.notion.prop("model")) or "")
        earlier = journal.chosen(ticket.id)
        return "" if written and earlier and earlier["model"] == written else written

    def _choose_model(self, ticket: Ticket, job: Job) -> None:
        """Pick the model of a ticket nobody gave one, and say so on it.

        Rules rather than a session — see models.py — so it costs nothing and
        cannot fail a ticket: a journal that cannot be read is a ticket chosen
        for as if it had never run. The reason goes into a comment, and the
        model into the Model column, so the board shows what the ticket ran
        on. `_written_model` is what keeps that from reading, on the next
        attempt, as a model somebody chose.
        """
        settings = self.config.runner
        earlier = journal.chosen(ticket.id)
        choice = models.choose(
            ticket.title,
            job.body,
            kind=job.kind,
            code=job.project.is_code,
            priority=priority.score(store.read(ticket.page, self.config.notion.prop("priority"))),
            grid=settings.model_grid(),
            # A run begun on Fable before it was turned off carries on, or
            # stays, on what is allowed now.
            earlier=(
                models.Earlier(**{**earlier, "model": settings.allowed(earlier["model"])})
                if earlier
                else None
            ),
            escalate=settings.auto_model_escalate,
            subtype=job.subtype,
        )
        if not choice.model:
            return
        job.model, job.chosen, job.escalated = choice.model, True, choice.escalated
        said = self.voice
        parts = []
        for key, values in choice.signals:
            if "kind" in values:
                # As the board spells it: “ticket Rédaction”, not “ticket writing”.
                values = {**values, "kind": self.kind_name(values["kind"])}
            if "subtype" in values:
                values = {**values, "subtype": subtypes.option(values["subtype"])}
            parts.append(said.say(key, **values))
        reason = ", ".join(parts)
        self.say(f"    · model {choice.model} ({choice.level}) — {reason}")
        # Commentary, like the cost: a column Notion refuses is a line in the
        # log and the run carries on; a board without one is left out by the store.
        try:
            self._set(ticket, **{self.config.notion.prop("model"): choice.model})
        except store.StoreError as error:
            self.say(f"    ! the model could not be written on the ticket ({error})")
        if choice.signals and choice.signals[0][0] == "model-resumed":
            # The session carried on is the one the first comment was about.
            return
        self._comment(
            ticket,
            said.report(said.verdict("chosen", choice.model), said.sentence(reason)),
        )

    def _name(self, ticket: Ticket, body: str, short: str) -> None:
        """Give a nameless ticket a title, and write it on the page.

        Into Notion rather than into this run's memory alone: the board has to
        show it too, or the page stays anonymous for whoever reads it back. And
        the page is what the runner then works from, so the branch, the report
        and the pull request all carry the same name.

        Never a reason to fail a ticket. A session that will not start, an
        answer that says nothing, a Notion that refuses the write: each of them
        is one line in the journal, and the ticket runs under the default
        label as it did before. The title is only kept once Notion has taken
        it — a branch named after something the board does not show would be a
        worse outcome than a ticket with no name.
        """
        title = ""
        workdir = state_dir() / "scratch" / f"name-{short}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = self._paid(
                ticket.id,
                naming.prompt(body),
                cwd=workdir,
                log=state.log_file(f"{short}-name"),
                model=self.config.runner.allowed(self.config.runner.model),
                # It reads one page and answers one line: the mode a
                # conversation runs in is more than it needs.
                permission_mode=self.config.runner.reply_permission_mode,
                timeout_minutes=naming.TIMEOUT_MINUTES,
                environment=self.environment,
            )
            if outcome.ok:
                title = naming.clean(outcome.answer)
            if not title:
                self.say("  ! the naming session said nothing usable — reading the content")
        except (OSError, ValueError) as error:
            self.say(f"  ! the ticket could not be named by a session: {voice_module.line(error)}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        title = title or naming.fallback(body)
        if not title:
            return
        try:
            self.client.update(
                self.database,
                ticket.page.id,
                {self.client.title_property(self.database): title},
            )
        except store.StoreError as error:
            self.say(f"  ! the title could not be written to Notion: {voice_module.line(error)}")
            return
        ticket.page.title = title
        self.say(f"  · named “{title}” — the ticket had none of its own")

    def _kind(self, ticket: Ticket, body: str, project: Project) -> tuple[str | None, str]:
        """The type this ticket runs as — "" for the old road, None to stop here.

        A type somebody wrote is taken as written, always: the classification
        only ever fills an empty cell, so correcting it is one click that no
        later pass undoes. An option that is none of the four is not rewritten
        either — it is somebody's own column — and the ticket runs by what its
        project holds, as every ticket did before there were types.

        Beside it, what the classifying session answered, "" when none ran: the
        same answer says a code ticket's sub-type — see `_subtype`.
        """
        column = self.type_column()
        if not column:
            return "", ""
        written = str(store.read(ticket.page, column) or "").strip()
        if written:
            kind = self.config.notion.kind_of(written)
            if not kind:
                self.say(
                    f"    · type “{written}” is none of the four — run by what its project holds"
                )
            return kind, ""
        if not self.config.runner.classify:
            return "", ""
        if self.dry_run:
            self.say("    (dry run) no type — it would be classified before it runs")
            return "", ""
        return self._classify(ticket, body, project)

    def _subtype(self, ticket: Ticket, body: str, answer: str = "") -> tuple[str, str]:
        """A code ticket's sub-type, and the note its report carries about it.

        Written by somebody, taken as written — never rewritten, like a type.
        Empty, the title's prefix says it when it has one, and that costs
        nothing; otherwise the classification that just ran for the type said
        it too, or a session of its own is asked. Either way a doubt is settled
        as `subtypes.DOUBT` and said in the report, without stopping anything:
        see subtypes.py. A board without the column reads the prefix and asks
        nobody — there would be nowhere to keep the answer.
        """
        column = self.subtype_column()
        if column:
            written = str(store.read(ticket.page, column) or "").strip()
            if written:
                key = subtypes.of(written)
                if not key:
                    self.say(
                        f"    · sub-type “{written}” is none of the {len(subtypes.KEYS)} — left out"
                    )
                return key, ""
        key = subtypes.from_prefix(ticket.title)
        if key:
            self.say(f"    · sub-type {key}, from the title's prefix")
            self._write_subtype(ticket, column, key)
            return key, ""
        if not column or not self.config.runner.classify:
            return "", ""
        if self.dry_run:
            self.say("    (dry run) no sub-type — it would be deduced before it runs")
            return "", ""
        if not answer:
            answer = self._ask_subtype(ticket, body)
        said = self.voice
        guess = subtypes.parse(answer)
        key, doubted = subtypes.settle(guess, self.config.runner.classify_confidence)
        if answer:
            # No answer at all is a session that did not run, not a doubt about
            # the ticket: nothing is written, and the next attempt asks again.
            self._write_subtype(ticket, column, key)
        self.say(
            f"    · sub-type {key}"
            + (" — in doubt" if doubted else f" ({guess.confidence}) — {guess.reason}")
        )
        if doubted:
            return key, said.say("subtype-doubt", subtype=subtypes.option(key), property=column)
        return key, said.say(
            "subtype-guessed",
            subtype=subtypes.option(key),
            level=said.say(f"confidence-{guess.confidence}"),
            reason=guess.reason,
        )

    def _write_subtype(self, ticket: Ticket, column: str, key: str) -> None:
        if not column or self.dry_run:
            return
        try:
            self.client.update(self.database, ticket.page.id, {column: subtypes.option(key)})
        except store.StoreError as error:
            self.say(f"  ! the sub-type could not be written: {voice_module.line(error)}")

    def _ask_subtype(self, ticket: Ticket, body: str) -> str:
        """What a short session says the sub-type is — "" when it said nothing."""
        short = short_id(ticket.id)
        workdir = state_dir() / "scratch" / f"subtype-{short}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = self._paid(
                ticket.id,
                subtypes.prompt(ticket.title, body),
                cwd=workdir,
                log=state.log_file(f"{short}-subtype"),
                model=self.config.runner.allowed(self.config.runner.classify_model),
                permission_mode=self.config.runner.reply_permission_mode,
                timeout_minutes=kinds.TIMEOUT_MINUTES,
                environment=self.environment,
            )
            return outcome.answer if outcome.ok else ""
        except (OSError, ValueError) as error:
            self.say(f"  ! the sub-type could not be deduced: {voice_module.line(error)}")
            return ""
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _classify(self, ticket: Ticket, body: str, project: Project) -> tuple[str | None, str]:
        """Work out a ticket's type, write it on the page, and say why.

        The type goes into the column and the reason into a comment, so that the
        decision is where the ticket is read and can be corrected there. A guess
        the runner will not act on — see `kinds.doubt` — blocks the ticket with
        the question instead, and leaves the column empty for you to fill: a
        type written by the runner would read, on the next pass, as a type you
        had chosen.
        """
        short = short_id(ticket.id)
        workdir = state_dir() / "scratch" / f"kind-{short}"
        answer = ""
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = self._paid(
                ticket.id,
                kinds.prompt(
                    ticket.title,
                    body,
                    project=project.name,
                    repository=project.is_code,
                    comments=self.discussion(ticket),
                ),
                cwd=workdir,
                log=state.log_file(f"{short}-kind"),
                model=self.config.runner.allowed(self.config.runner.classify_model),
                # It reads one page and answers one object: the mode a
                # conversation runs in is more than it needs.
                permission_mode=self.config.runner.reply_permission_mode,
                timeout_minutes=kinds.TIMEOUT_MINUTES,
                environment=self.environment,
            )
            if self._out_of_credit(outcome):
                # Not a doubt about the ticket: there was nothing to ask with.
                # It stays in ready, untouched, for the pass that has credit.
                self._hold_credits(outcome)
                self.say("    · out of credit before it could be classified — left in ready")
                return None, ""
            answer = outcome.answer if outcome.ok else ""
        except (OSError, ValueError) as error:
            self.say(f"  ! the ticket could not be classified: {voice_module.line(error)}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        guess = kinds.settle(kinds.parse(answer))
        column = self.config.notion.prop("type")
        said = self.voice
        why = kinds.doubt(guess, self.config.runner.classify_confidence)
        if why:
            between = [kind for kind in (guess.kind, guess.alternative) if kind]
            if len(between) == 2:
                question = said.say(
                    "kind-question-between",
                    first=self.kind_name(between[0]),
                    second=self.kind_name(between[1]),
                    property=column,
                    prudent=self.kind_name(kinds.prudent(*between)),
                )
            else:
                question = said.say(
                    "kind-question",
                    choices=", ".join(self.kind_name(kind) for kind in kinds.KINDS),
                    property=column,
                )
            reason = said.say(f"kind-{why}")
            self._fail(
                ticket,
                reason,
                said.paragraphs(said.sentence(reason), guess.reason),
                code="ticket.kind-unsure",
                blocked=True,
                question=question,
            )
            return None, ""

        name = self.kind_name(guess.kind)
        try:
            self.client.update(self.database, ticket.page.id, {column: name})
        except store.StoreError as error:
            # Run as classified all the same: the comment below still says which
            # type it was run as, and why.
            self.say(f"  ! the type could not be written: {voice_module.line(error)}")
        self.say(
            f"    · classified as {guess.kind} ({guess.confidence}) — {guess.reason}"
            + (f" — rather than {guess.settled}, which needs a commit" if guess.settled else "")
        )
        level = said.say(f"confidence-{guess.confidence}")
        self._comment(
            ticket,
            said.report(
                said.verdict("classified", name, said.say("confidence", level=level)),
                said.brief(guess.reason),
                said.say("kind-settled", kind=name, other=self.kind_name(guess.settled))
                if guess.settled
                else "",
                said.say("classified-fix", property=column),
            ),
        )
        return guess.kind, answer
