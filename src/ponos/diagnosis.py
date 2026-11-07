"""A diagnostic that found its cause: its fix tickets created, its report written, closed.

The session wrote the report and the tickets (see diagnostic.py for why it is
the one that writes them and the runner the one that creates them); what is
left is the board's part, and it is done in an order that keeps the board
honest at every step. The tickets first, each « after » the diagnostic and
after the fixes it names, so that one created in Ready cannot start before the
report it is built on is on the page; then the report; then the diagnostic
closes — to done, not to review: there is no gesture left for anybody to make
on it, and its tickets are where the next decision is.
"""

from __future__ import annotations

import shutil
from typing import Any

from . import diagnostic, project_settings, session, store, subtypes, ticket_page
from . import voice as voice_module
from .base import Base
from .ticket import Job

# Created ones listed by title on the diagnostic's report, at most this many:
# a series longer than that is read on the board.
LISTED = 10


class Diagnosis(Base):
    """The end of a diagnostic whose session found the cause."""

    def _diagnosed(self, job: Job, outcome: session.Outcome, content: str) -> dict[str, Any] | None:
        """The report and the fix tickets of a diagnostic that ended well."""
        said = self.voice
        fixes, problem = diagnostic.read_fixes(job.workdir)
        if problem:
            self.say(f"    ! {problem}")
            return self._diagnostic_refused(job, outcome, problem)
        made, failure = self._open_fixes(job, fixes)
        titles = ", ".join(title for _, title in made[:LISTED])
        if len(made) > LISTED:
            titles += ", …"
        column = self.config.board.state("ready" if self._fixes_ready(job) else "draft")
        note = said.paragraphs(
            said.say("diagnostic-fixes", count=len(made), column=column, titles=titles)
            if made
            else said.say("diagnostic-no-fix")
            if not failure
            else "",
            said.say("diagnostic-fix-failed", error=failure) if failure else "",
        )
        return self._deliver_text(job, outcome, content, kept=job.workdir / "ANSWER.md", note=note)

    def _fixes_ready(self, job: Job) -> bool:
        return project_settings.diagnostic(job.project.page_id).ready

    def _open_fixes(
        self, job: Job, fixes: list[diagnostic.Fix]
    ) -> tuple[list[tuple[str, str]], str]:
        """Create the fix tickets, in order: what was created, and why the rest was not.

        Each one in the diagnostic's project, of the type the session gave it,
        « after » the diagnostic itself and after the earlier fixes it names. A
        board that refuses one stops the series there — the next may well come
        after it — and says so on the diagnostic.
        """
        if not fixes:
            return [], ""
        ticket, said = job.ticket, self.voice
        settings = self.config.board
        status = settings.state("ready" if self._fixes_ready(job) else "draft")
        project = store.read(ticket.page, settings.prop("project"))
        headings = {
            part: said.say(f"fix-{part}") for part in ("context", "expected", "done", "out", "from")
        }
        made: list[tuple[str, str]] = []
        for fix in fixes:
            values: dict[str, object] = {
                settings.prop("status"): status,
                settings.prop("type"): self.kind_name(fix.kind),
                settings.prop("after"): [ticket.page.id, *(made[one][0] for one in fix.after)],
            }
            if project:
                values[settings.prop("project")] = project
            if fix.subtype:
                values[settings.prop("subtype")] = subtypes.option(fix.subtype)
            if fix.priority is not None:
                values[settings.prop("priority")] = self.priority_cell(fix.priority)
            mission = diagnostic.body(fix, headings, ticket.url or ticket.title)
            try:
                page_id = self.client.create_row(self.database, fix.title, values)
                self.client.append_markdown(page_id, ticket_page.template(said, mission))
            except store.StoreError as error:
                failure = voice_module.line(error)
                self.say(f"    ! the fix ticket “{fix.title}” could not be created: {failure}")
                return made, failure
            made.append((page_id, fix.title))
            self.say(f"    + fix ticket: {fix.title} ({status})")
        return made, ""

    def _diagnostic_refused(
        self, job: Job, outcome: session.Outcome, problem: str
    ) -> dict[str, Any]:
        """A cause found, and fix tickets nobody can read: blocked, nothing created."""
        said = self.voice
        kept = ""
        if self.config.runner.keep_worktree_on_failure:
            kept = said.say("workdir-kept", path=job.workdir)
        else:
            shutil.rmtree(job.workdir, ignore_errors=True)
        return self._fail(
            job.ticket,
            said.say("diagnostic-fixes-unreadable"),
            problem,
            code="session.no-answer",
            blocked=True,
            question=said.say("diagnostic-fixes-unreadable-question", problem=problem),
            note=self._filed(job, outcome, kept),
            outcome=outcome,
        )
