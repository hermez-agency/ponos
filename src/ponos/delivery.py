"""The last column: carrying out the tickets you have validated.

With *Ready*, the only other place on the board where moving a ticket sets
something off. *In review* asks a question — is this what you wanted? — and
moving the ticket to *Validated* answers it: yes, and now do the last thing.
What that last thing is, the ticket already says: one that came back as a pull
request has a merge waiting, one that came back as a text has a publication
waiting. Which leaves the decision exactly where it was — nothing is merged or
published because a session felt sure of itself, only because you moved a
ticket one column to the right.

Unless you said so once and for all. `force_validated_<type>` is that gesture
made in advance, for every ticket of one type: the session succeeds, and what
this column would set off is set off straight away — `_force_merge` for a pull
request, `_publish` for a publication — without the ticket passing through it.
Only on a success, never on a ticket already in review, and said in the report.
A project may make that gesture for itself, against the file in either
direction — see project_settings.py — and the report says whose it was.
Writing and external action have nothing to set off: they end in done already.

The two are not carried out the same way, and the asymmetry is the module.
A merge is two `gh` calls and is done in the pass's own thread — three and a
rebase when GitHub refuses it for being behind, which is what a repository
taking ten tickets a day does to a pull request opened this morning. A
publication is a Claude session, so publications run the way tickets run — side
by side, never more than `max_concurrent` at once — and are claimed before they
are done, because publishing twice is the one mistake this must not make.

A merge whose rebase stops on a conflict crosses over to the second kind: the
conflict is resolved by a session, so it takes a place like a publication and
is claimed like one — see `_resolve`. Everything it does is a question the
moment it is not sure: a conflict that is a decision, checks that stay red, a
branch somebody else pushed to, a base that keeps moving. Checks that stay red
means red twice and red only here — a flaky test is run again before anything
is concluded, and a check `main` fails too is not the pull request's to answer
for — it waits for the base to be green again instead: see `_checked`. The branch it pushes is the pull request's own, on a
lease; the base is never touched. Before any session, the replay settles what
has only one answer — generated files and the changelog, see generated.py — and
the merges of one repository go through a line, one at a time: see `_queue`.
A ticket typed as a publication comes here the same way, whatever its project
holds: it was prepared in its page, and its page is what goes out.

And the column is read more than once. `deliver` settles it at the top of a
pass; `delivering` is the same reading, offered to a pass that is already
running, so that a ticket validated at 14:20 is merged at 14:20 rather than
when the two-hour session that began at 14:04 finally ends — see `_work`.
"""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from . import agents, generated, git, kinds, project_settings, session, state, store, subtypes
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .config import state_dir
from .projects import Project
from .ticket import Job, Ticket, short_id

# How many times one validated ticket's branch is replayed and pushed before
# the runner stops chasing its base and asks: twice is a base that moved once
# more while the first replay was being merged, three times is a repository
# moving faster than a replay, and a loop nobody is watching.
MOST_REBASES = 2

# The score of the ticket that repairs a red base: ahead of ordinary work, the
# other tickets of that repository waiting on it, but behind what was said urgent.
REPAIR_PRIORITY = 75

# What a merge refusal would have said, for a pull request GitHub already calls
# conflicting or behind before one is asked — see `git.merge_blocker`.
BLOCKERS = {
    "CONFLICTING": "Pull Request has merge conflicts",
    "BEHIND": "the head branch is not up to date with the base branch",
}


def _report_of(answer: str) -> str:
    """What a resolving session wrote above its RESULT line: its report."""
    lines = answer.strip().splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip().lstrip("*# ").upper().startswith("RESULT:"):
            lines = lines[:index]
            break
    report = "\n".join(lines).strip()
    return report if len(report) <= 3000 else report[:3000].rsplit("\n", 1)[0] + "\n…"


def _repository(url: str) -> str:
    """The repository a pull request belongs to: its address up to `/pull/`."""
    return url.split("/pull/")[0]


def _named(checks: list[str]) -> str:
    """Check names, the way a report quotes them."""
    return ", ".join(f"`{name}`" for name in checks)


class Delivery(Base):
    """What a validated ticket sets off, and how far it is taken."""

    def delivered(self) -> list[dict[str, Any]]:
        """`deliver`, with what it did written into the history.

        Merged, published, or refused: as much a run of this ticket as a session
        is, and `ponos history` should say so. It runs in a dry run too,
        where it only says what it would do — the one gesture that cannot be
        taken back is the one worth rehearsing — and a rehearsal is not history.

        A refusal from the board on the way stops the delivering, not the pass:
        the queue after it still runs, and the next pass delivers again.
        """
        try:
            done = self.deliver()
        except store.Unreachable:
            raise
        except store.StoreError as error:
            self.say(f"  ! the validated column was not carried out: {voice_module.line(error)}")
            return []
        for entry in done:
            if entry.get("status") != "dry-run":
                state.record(entry)
        return done

    def deliver(self) -> list[dict[str, Any]]:
        """Carry out the tickets you have validated.

        The last column, and with *Ready* one of the only two where moving a
        ticket sets something off. *In review* asks a question — is this what you
        wanted? — and moving the ticket to *Validated* answers it: yes, and now
        do the last thing. What that last thing is, the ticket already says. One
        that came back as a pull request has a merge waiting; one that came back
        as a text has a publication waiting — a post, an email, a page. The
        runner does it, and only then is the ticket done.

        Which leaves the decision exactly where it was: nothing is merged or
        published because a session felt sure of itself, only because you moved
        a ticket one column to the right.

        Optional, like the columns before it. A board whose status property does
        not offer the validated option has no such gesture and is never even
        queried — `ponos init` adds the option to a board that predates
        it, and until then you merge by hand as before.

        A date on the ticket is honoured here too. `Scheduled` means "not before
        this moment" wherever it is written, so a validated ticket dated Thursday
        is left in its column until Thursday and carried out then — which is what
        turns the board into a calendar for work that is *finished*: the post is
        written, you have read it and said yes, and it still goes out at the hour
        you chose. Merges wait the same way, for the same reason: one column, one
        rule.

        Merges are two `gh` calls and are done one after another. A publication
        is a Claude session, so publications are run the way tickets are run:
        side by side, never more than `max_concurrent` at once. They still
        finish before the queue is looked at — a ticket you have accepted comes
        before a ticket nobody has read yet — but a board with four of them
        costs one session's wait rather than four.

        This is the reading a pass does at its top, on a board nothing is
        running against yet. The same column is read again while the pass runs,
        by `delivering`, which is where the sorting actually lives.
        """
        results, publishing = self.delivering()
        return results + self._publish_all(publishing)

    def delivering(
        self, taken: set[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[tuple[Ticket, Project]]]:
        """Sort the validated column: what is settled here, what needs a session.

        Two kinds of work sit in that column, and only one of them costs a
        place. A merge is two `gh` calls, so it happens here and now, in the
        thread that asked — which is what lets a pass with every place taken
        still merge a pull request you validated while it ran. A publication is
        a Claude session, so it is only *named* here: the caller runs it, in the
        pool it already keeps, and `deliver` is the caller that runs them all at
        once at the top of a pass. So is a merge whose conflicts need resolving,
        which is a session too — both go out through `_carry_out`.

        `taken` is what this pass has already carried out. Notion may still be
        serving the status a publication in flight has just overwritten, and
        publishing twice is the one mistake this must not make — so a ticket the
        caller has already taken off the column is skipped rather than trusted
        to have moved.

        A board that will not answer leaves the column where it is: the next
        look asks again, and neither a pass in flight nor the sessions in it
        have any business failing over a reading of a column they are not in.
        """
        settings = self.config.notion
        taken = taken or set()
        results: list[dict[str, Any]] = []
        publishing: list[tuple[Ticket, Project]] = []
        held: list[tuple[Ticket, datetime]] = []
        now = datetime.now().astimezone()
        try:
            pages = self.validated()
        except store.StoreError as error:
            self.say(f"  ! the validated column could not be read: {voice_module.line(error)}")
            return [], []
        for page in pages:
            ticket = Ticket(page)
            if ticket.id in taken:
                continue
            url = str(store.read(page, settings.prop("pull_request")) or "")
            moment = self._moment(ticket)
            if moment and moment > now:
                # A date says "not before this moment", and it says it here as
                # much as in the ready column: the post accepted on Tuesday for
                # Thursday goes out on Thursday. Merges wait with publications —
                # validating asks one question, and the date answers *when*.
                held.append((ticket, moment))
                if not url.startswith("http"):
                    # Its comments travel into the publication when the moment
                    # comes, exactly as a scheduled ready ticket's do, so the
                    # runner does not also answer them in the meantime. A ticket
                    # with a pull request is left talkable-to: there, a comment
                    # is a conversation about work already done.
                    self._claimed.add(ticket.id)
                continue
            if self.dry_run:
                # A dry run says what it would do here as everywhere else. It
                # matters more here than anywhere: this is the only column whose
                # gesture cannot be taken back.
                what = f"merge {url}" if url.startswith("http") else "publish what it holds"
                self.say(f"  (dry run) {ticket.title} — validated: would {what}")
                results.append({"ticket": ticket.title, "id": ticket.id, "status": "dry-run"})
                continue
            if url.startswith("http"):
                done = self._merge(ticket, url, publishing)
                if done:
                    results.append(done)
                continue
            if self.under_reserve():
                # A publication is a session; a merge is two `gh` calls. So the
                # merges above happen and this one waits, left validated, for
                # the pass that has credit again — the decision to publish it is
                # not being reconsidered, only postponed.
                self._claimed.add(ticket.id)
                continue
            # The type decides, as it did on the way in: a publication on a
            # project with a repository was prepared in the page, not in a pull
            # request, and that page is what is published.
            project = kinds.worked_in(self._project_of(ticket), self.kind(ticket))
            if project.is_code:
                # A ticket on a repository carries a pull request or it carries
                # nothing: there is no text on the page to publish, and starting
                # a session to look for one would be guessing.
                said = self.voice
                results.append(
                    self._fail(
                        ticket,
                        said.say("no-pull-request"),
                        said.say("no-pull-request-detail", project=project.name),
                        code="merge.no-pr",
                        blocked=True,
                        question=said.say("no-pull-request-question"),
                    )
                )
                continue
            publishing.append((ticket, project))
        self._deferred = sorted(held, key=lambda pair: pair[1])
        return results, publishing

    def validated(self) -> list[store.Page]:
        """The pages sitting in the validated column.

        None at all where the board has no such column: the gesture is opt-in,
        and a board that never offers it is never even queried.
        """
        if not self.validated_column():
            return []
        settings = self.config.notion
        validated = settings.state("validated")
        status_property = settings.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        return self.client.query(
            self.database, {"property": status_property, kind: {"equals": validated}}
        )

    def validated_column(self) -> bool:
        """Does this board offer the validated column at all?

        Asked by `validated` before it queries, and by a publication before it
        says “move it to validated”: on a board without the column that would be
        an instruction nobody can follow.
        """
        settings = self.config.notion
        validated = settings.state("validated")
        if validated in (settings.state("review"), settings.state("done")):
            return False
        return validated in self.client.options(self.database, settings.prop("status"))

    def scheduled(self) -> list[tuple[Ticket, datetime]]:
        """Validated tickets whose moment has not come, soonest first.

        What `deliver` will carry out later rather than now. Read for the sake
        of saying so — a post you accepted on Tuesday for Thursday is as much a
        thing waiting to happen as a ticket sitting in ready with a date on it,
        and `ponos list` shows the whole calendar rather than half of it.
        """
        now = datetime.now().astimezone()
        held: list[tuple[Ticket, datetime]] = []
        for page in self.validated():
            ticket = Ticket(page)
            moment = self._moment(ticket)
            if moment and moment > now:
                held.append((ticket, moment))
        return sorted(held, key=lambda pair: pair[1])

    def _merge(
        self, ticket: Ticket, url: str, resolving: list[tuple[Ticket, Project]]
    ) -> dict[str, Any] | None:
        """A validated pull request: merge it, and take the ticket to done.

        `resolving` is where a pull request whose conflicts need a session is
        put, for the caller to run it as it runs a publication — see `_carry_out`.
        """
        state_of = git.pull_request_state(url, self.config.github)
        if not state_of:
            # The same rule as `close_merged`: a ticket is never moved on an
            # answer GitHub did not give. The next run asks again.
            self.say(f"  · {ticket.title} — GitHub did not answer about {url}, left validated")
            return None
        said = self.voice
        if state_of == "CLOSED":
            state.forget_rebases(ticket.id)
            return self._fail(
                ticket,
                said.say("pull-request-closed"),
                said.say("pull-request-closed-detail", url=url),
                code="merge.pr-closed",
                blocked=True,
                question=said.say("pull-request-closed-question", url=url),
            )
        if state_of == "MERGED":
            return self._merged(ticket, url, said.say("merged-before"))
        if self._waits_for_base(ticket, url):
            return None
        method = self.config.runner.merge_method
        with self._queue(url):
            # Asked first rather than read in a refusal: a pull request GitHub
            # already calls conflicting is replayed before anything is merged,
            # and one it calls mergeable goes the way every merge always went.
            # Asked once it is this one's turn, so it is the base as the last
            # merge left it that is read.
            blocker = (
                git.merge_blocker(url, self.config.github) if self.config.runner.rebase else ""
            )
            if blocker:
                self.say(f"  · {ticket.title} — GitHub says {url} is {blocker.lower()}")
                return self._catch_up(ticket, url, BLOCKERS[blocker], resolving)
            try:
                git.merge_pull_request(url, method, self.config.github)
            except git.GitError as error:
                if self.config.runner.rebase and git.is_behind(error):
                    return self._catch_up(ticket, url, error, resolving)
                return self._refused(ticket, url, error)
        return self._merged(ticket, url, said.say("merged-with", method=method))

    def _merged(
        self, ticket: Ticket, url: str, *facts: str, notes: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        """Done, and said so: the pull request is in."""
        state.forget_rebases(ticket.id)
        state.forget_base_wait(ticket.id)
        self._landed_in(url)
        said = self.voice
        self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
        self._set(
            ticket,
            **{self.config.notion.prop("status"): self.config.notion.state("done")},
            **self._refusal_cleared(ticket),
        )
        self._comment(
            ticket,
            said.report(said.verdict("merged", said.pull_request(url), *facts), url, *notes),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": "done", "merged": url}

    def _forced(self, kind: str, project: Project, ticket: Ticket | None = None) -> str:
        """The line saying a ticket of that type is validated without you, or "".

        The project's own automatic validation when it has one, the file's
        otherwise; the line says which of the two decided. Asked only once the
        session has succeeded — a failed or blocked ticket never gets this far.

        The ticket that repairs a red base is validated whatever those say:
        every other pull request of the repository waits behind it, and one
        left in review for a person is how #331 stayed open, green, while the
        rest stood still. `_force_merge` still waits for its CI to be green.
        """
        source = project_settings.forced_validation(self.config, kind, project.notion_id)
        if not source and ticket and kind == "code" and state.is_repair(ticket.id):
            source = "repair"
        if not source:
            return ""
        return self.voice.say(
            "forced-validation",
            kind=self.kind_name(kind),
            source=self.voice.say(f"forced-by-{source}"),
        )

    def _force_merge(self, job: Job, url: str) -> tuple[str, bool]:
        """Merge a pull request just opened, for a type whose validation is forced.

        What `_merge` does for a ticket you validated, minus what a pull request
        opened a minute ago does not need: its branch was replayed onto its base
        on the way out, so there is nothing to catch up with. What it does need
        is its CI — nobody has looked at it, so nobody has seen it go green — and
        it is waited for, `checks_timeout_minutes` at the most, from the worktree
        it was pushed from. Then the merge, with `merge_method`, as always.

        Red checks are read the way `_checked` reads them: run again once, and
        compared with the base: a flaky test does not keep a forced ticket out,
        and a red `main` sets it aside until the base is green again.

        Returns why it was not merged, or "" once it is — and whether that is
        only *not yet*. Nothing to catch up with is true when the pull request
        opens, not when the merge is asked: with two tickets on one repository,
        the other lands while this one waits for its CI, and the branch is behind
        or conflicting by the time it is its turn. That refusal is about the
        branch, not the work, and the validated column is where it is answered —
        `_merge` replays it, hands a conflict to a session, asks again — on the
        next pass and without holding a place here. So is CI still running when
        the wait runs out. Behind or conflicting already, GitHub is not even
        asked. What is left — checks red here and only here, jobs GitHub never
        started, a review or a rule of the branch — is a question, and waits in
        review, where you would have found it without the option: the work is
        done and the pull request is open. The card says which, in the words
        `_checked` found for it: “its checks fail” told nobody whether to look
        at the code or at the account. On a board with no validated column,
        everything waits there.
        """
        accounts = self.config.github
        rebase = self.config.runner.rebase
        checks, checked = self._checked(job.ticket, url, job.workdir, job.base)
        later = False
        if checks in ("failed", "unstarted"):
            refusal = checked or self.voice.say("forced-checks-red")
        elif checks == "base-red" and self.validated_column():
            self._set_aside(job.ticket, job.project, url, job.base)
            refusal, later = self.voice.say("forced-base-red"), True
        else:
            with self._queue(url):
                if (
                    rebase
                    and self.validated_column()
                    and (blocker := git.merge_blocker(url, accounts))
                ):
                    refusal, later = self.voice.say(f"forced-{blocker.lower()}"), True
                else:
                    try:
                        git.merge_pull_request(url, self.config.runner.merge_method, accounts)
                    except git.GitError as error:
                        refusal = voice_module.line(error)
                        behind = rebase and git.is_behind(error)
                        if isinstance(error, git.ChecksNotGreen):
                            refusal = self.voice.say(
                                "forced-checks-red" if error.state == "failed" else "checks-pending"
                            )
                            later = error.state == "pending" and self.validated_column()
                        elif checks == "pending" and not behind:
                            refusal = f"{self.voice.say('checks-pending')} {refusal}"
                        later = (behind or checks == "pending") and self.validated_column()
                    else:
                        state.forget_rebases(job.ticket.id)
                        self._landed_in(url)
                        return "", False
        self.say(
            f"    ! {url} not merged: {refusal}"
            + (" — left validated for the next pass" if later else "")
        )
        return refusal, later

    def _checked(self, ticket: Ticket, url: str, workdir: Path, base: str) -> tuple[str, str]:
        """The pull request's CI, read for what it says about *this* pull request.

        Red is not one thing, and only one of its kinds is a question. A flaky
        test goes green when it is run again, so the failed jobs are run again,
        once, before anything is concluded — the gesture you would make by hand.
        A check still red that is red on the newest commit of `base` too was
        inherited, not caused: the pull request makes nothing worse, and is
        put aside, not blamed: the ticket waits for the base to be green again —
        see `_set_aside` — instead of stopping on an error that is not its own.
        What is left is red here and only here, and that is the one answer that
        still stops the merge — with the checks named, rather than “CI: red”.

        And a red that is no verdict at all: jobs GitHub refused to start, an
        account's billing rather than the code. That is `unstarted`, with
        GitHub's own reason, and it is neither run again nor blamed on anybody.

        Returns `passed`, `pending`, `none`, `base-red`, `unstarted` or
        `failed`, and the sentence that says it.
        """
        accounts = self.config.github
        said = self.voice
        state.enter(ticket.id, "checks", url)
        checks = git.wait_for_checks(
            url, workdir, self.config.runner.checks_timeout_minutes, accounts
        )
        if checks != "failed":
            return checks, said.say(f"checks-{checks}")
        failing = git.failing_checks(url, accounts)
        if unstarted := git.unstarted_checks(url, accounts):
            # Not red: never run. A second run is refused the same way, and the
            # base has nothing to say about an account.
            self.say(f"    · checks never started — {unstarted}")
            return "unstarted", said.say("checks-unstarted", reason=unstarted)
        if git.rerun_failed_checks(url, accounts):
            self.say(f"    · checks red ({', '.join(failing) or '?'}) — run again once")
            checks = git.wait_for_checks(
                url, workdir, self.config.runner.checks_timeout_minutes, accounts
            )
            if checks == "passed":
                return checks, said.say("checks-flaky", names=_named(failing) or "?")
            if checks != "failed":
                return checks, said.say(f"checks-{checks}")
            failing = git.failing_checks(url, accounts) or failing
        if not failing:
            return "failed", said.say("checks-failed")
        if set(failing) <= set(git.failing_on(url, base, accounts)):
            self.say(f"    · {', '.join(failing)} red on {base} too — not this pull request's")
            return "base-red", said.say("checks-base-red", names=_named(failing), base=base)
        return "failed", said.say("checks-failed-on", names=_named(failing), base=base)

    def _mend(self, job: Job, url: str, checked: str) -> tuple[str, str, session.Outcome | None]:
        """A pull request red by its own fault: a session reads the log and tries once.

        The red `_checked` could not excuse — still red after the failed jobs
        were run again, and not red on the base — is most often a line: a test
        that looked for a name the branch changed, a link written the wrong way.
        It used to be a question (51 tickets blocked on it); a session now gets
        the checks' names and the end of their log, on the very branch of the
        pull request, as for a conflict. One attempt per ticket and per head
        commit, written down before it starts (`state.mending`), and the
        commit the repair pushes is written down too: whatever happens next, the
        runner never sends a second session after the same red.

        Returns the checks as they stand — `passed` when the fix went green,
        anything `_checked` says otherwise — and what to report, and the session
        when there was one, for its cost and its credit.
        """
        ticket, said = job.ticket, self.voice
        head = git.head(job.workdir)
        if not head or state.mended(ticket.id, head):
            return "failed", checked, None
        accounts = self.config.github
        failing = git.failing_checks(url, accounts)
        names = _named(failing) or "?"
        state.mending(ticket.id, head)
        self.say(f"    ↻ checks red ({', '.join(failing) or '?'}) — sending a session after them")
        log = git.failed_log(url, accounts)
        brief = "\n\n".join(
            part
            for part in (
                self._body(ticket).strip(),
                f"# The pull request — {url}",
                git.pull_request_body(url, accounts).strip() or "(no description)",
                "# The checks that fail on it, and not on the base",
                "\n".join(f"- `{name}`" for name in failing) or "(gh did not name them)",
                "# The end of the failed jobs' log",
                f"```\n{log}\n```" if log else "(gh could not read the log: open the runs)",
            )
            if part
        )
        short = short_id(ticket.id)
        repairing = replace(
            job,
            body=brief,
            session_id=session.new_id(),
            log=state.log_file(f"{short}-repair"),
            resume=False,
        )
        try:
            outcome = self._run_session(repairing, prompt_module.REPAIR, phase="repair", detail=url)
        except (OSError, FileNotFoundError) as error:
            self.say(f"    ! the repair could not start: {error}")
            return "failed", checked, None
        self._add_cost(ticket, outcome)
        if self._out_of_credit(outcome):
            state.forget_mending(ticket.id, head)
            return "failed", checked, outcome
        told = _report_of(outcome.answer)
        if not outcome.ok:
            return (
                "failed",
                said.paragraphs(
                    checked, said.say("repair-blocked", names=names), outcome.summary, told
                ),
                outcome,
            )
        if git.rebasing(job.workdir) or git.is_dirty(job.workdir):
            return "failed", said.paragraphs(checked, told, said.say("repair-unfinished")), outcome
        fixed = git.head(job.workdir)
        if not fixed or fixed == head:
            return (
                "failed",
                said.paragraphs(checked, said.say("repair-nothing", names=names), told),
                outcome,
            )
        state.mending(ticket.id, fixed)
        failure = git.push_leased(job.workdir, job.branch, head, accounts)
        if failure:
            return (
                "failed",
                said.paragraphs(checked, told, said.say("repair-push-refused", error=failure)),
                outcome,
            )
        pushed = said.say("repair-fixed", names=names)
        git.comment_pull_request(url, f"Ponos — {said.paragraphs(pushed, told)}", accounts)
        checks, again = self._checked(ticket, url, job.workdir, job.base)
        if checks == "failed":
            again = said.paragraphs(said.say("repair-still-red"), again)
        return checks, said.paragraphs(pushed, told, again), outcome

    def _set_aside(self, ticket: Ticket, project: Project, url: str, base: str) -> str:
        """A pull request stopped by a red base, set aside until the base is green.

        Red on `base` too, so the pull request is not what is wrong, and a
        session sent after an error that is not its own would only pay to find
        that out (48 tickets, in waves of seven to eleven, one repository and
        one day at a time). Its place is written down — `_merge` looks at the
        base again at every pass and replays it once it is green — and the
        repair of the base is opened once, however many pull requests wait for
        it. Returns the ticket that repairs it, to be named on the card.
        """
        failures = git.base_failures(url, base, self.config.github)
        state.wait_for_base(ticket.id, base, url, [name for name, _ in failures])
        return self._repair(ticket, project, url, base, failures)

    def _repair(
        self, ticket: Ticket, project: Project, url: str, base: str, failures: list[tuple[str, str]]
    ) -> str:
        """The ticket that repairs a red base: the one already open, else a new one.

        Ready, a Code ticket of sub-type Bug, at priority 75 (`REPAIR_PRIORITY`), with the
        failing jobs and the link of their run. One per base: the table remembers the ticket opened for a
        repository's base, and a second is only opened once that one is done or
        failed — a base still red after a repair deserves a new look, not
        silence. Under a lock, because two pull requests of one repository can
        be put aside by two threads of the same pass.
        """
        settings = self.config.notion
        repository = _repository(url)
        said = self.voice
        with self._landed_lock:
            known = state.repair_of(repository, base)
            if known:
                try:
                    page = self.client.page(known)
                except store.StoreError:
                    page = None
                if page and str(store.read(page, settings.prop("status")) or "") not in (
                    settings.state("done"),
                    settings.state("failed"),
                ):
                    return page.title
            if self.dry_run:
                return ""
            title = said.say("repair-title", base=base, project=project.name or repository)
            values: dict[str, object] = {
                settings.prop("status"): settings.state("ready"),
                settings.prop("priority"): self.priority_cell(REPAIR_PRIORITY),
                settings.prop("type"): self.kind_name("code"),
                settings.prop("subtype"): subtypes.option("bug"),
            }
            if relation := store.read(ticket.page, settings.prop("project")):
                values[settings.prop("project")] = relation
            jobs = "\n".join(
                f"- `{name}`" + (f" — {link}" if link else "") for name, link in failures
            )
            try:
                page_id = self.client.create_row(self.database, title, values)
                state.repairing(repository, base, page_id)
                self.client.append_markdown(
                    page_id,
                    said.say(
                        "repair-body",
                        base=base,
                        project=project.name or repository,
                        jobs=jobs or "-",
                        url=url,
                    ),
                )
            except store.StoreError as error:
                self.say(
                    f"    ! the repair of {base} could not be opened: {voice_module.line(error)}"
                )
                return ""
        self.say(f"  ✳ {title} — opened, ready")
        return title

    def _waits_for_base(self, ticket: Ticket, url: str) -> bool:
        """Is this validated ticket still set aside for a base that is red?

        Asked at the top of `_merge`. The base is read again, and the ticket
        goes on as any validated one the moment the checks it was set aside for
        are no longer red there — said on its card, once. A base that cannot be
        read counts as green: the merge is asked, and GitHub answers for it.
        """
        waited = state.waiting_for_base(ticket.id)
        if not waited:
            return False
        base, _, names = waited
        if set(names) & set(git.failing_on(url, base, self.config.github)):
            self.say(f"  · {ticket.title} — {base} is still red, left aside")
            return True
        state.forget_base_wait(ticket.id)
        self._comment(ticket, self.voice.say("base-green-again", base=base))
        return False

    def _refused(
        self, ticket: Ticket, url: str, refusal: object, *notes: str
    ) -> dict[str, Any] | None:
        """A merge GitHub would not make, and nothing more the runner can do about it."""
        state.forget_rebases(ticket.id)
        said = self.voice
        if isinstance(refusal, git.ChecksNotGreen):
            names = _named(refusal.names)
            if refusal.state == "pending":
                # Not a refusal about the work: the next pass asks again.
                self.say(f"    · {ticket.title} — {said.say('merge-checks-running', names=names)}")
                return None
            return self._fail(
                ticket,
                said.say("merge-checks-red"),
                said.paragraphs(url, *notes, names),
                code="merge.checks-failed",
                blocked=True,
                question=said.say("merge-checks-red-question", names=names, url=url),
            )
        return self._fail(
            ticket,
            said.say("merge-refused"),
            said.paragraphs(url, *notes, refusal),
            code="merge.refused",
            blocked=True,
            question=said.say("merge-refused-question", error=voice_module.line(refusal)),
        )

    def _catch_up(
        self,
        ticket: Ticket,
        url: str,
        refusal: object,
        resolving: list[tuple[Ticket, Project]],
    ) -> dict[str, Any] | None:
        """Put the branch back on top of its base, when that is what was wrong.

        A pull request opened this morning is behind by noon on a repository
        that takes ten tickets a day: GitHub refuses the merge, and the refusal
        is about the *branch*, not about the work. So the branch is replayed
        onto its base and pushed again, and the merge is asked a second time —
        which is exactly the gesture you would make by hand, and the one nobody
        should have to make ten times a day.

        Only that refusal. A check still red and a review still missing are
        refusals a rebase does not answer, and pushing the branch again would
        only spend a CI run to be refused the same way.

        A replay that stops on a conflict is not the end of it any more: the
        conflict is handed to a session — `_resolve` — at the next free place,
        unless the project is one whose conflicts are left to you. And a base
        that moves faster than the replays is not chased for ever: past
        `MOST_REBASES`, the ticket asks.

        Asked a second time at once only on a repository without CI of its
        own: elsewhere the pushed commit has not been tested yet, and the
        merge is left to the next pass — see `merge_pull_request`, for which
        no check at all is no check red.
        """
        branch, base = git.pull_request_branches(url, self.config.github)
        project = self._project_of(ticket)
        if not branch or project.path is None:  # `not is_code`, spelled out for mypy to narrow
            return self._refused(ticket, url, refusal)
        self._forgiven(ticket, url)
        if state.rebases(ticket.id) >= MOST_REBASES:
            return self._too_often(ticket, url, base)
        workdir = state_dir() / "scratch" / f"rebase-{short_id(ticket.id)}"
        self.say(f"  · {ticket.title} — merge refused, replaying {branch} onto {base}")
        failure = git.replay_pushed(
            project.path, branch, base, workdir, self.config.github, generated.settle
        )
        if (
            failure
            and git.is_conflict(failure)
            and self.config.runner.resolves_conflicts(project.name)
        ):
            if self.under_reserve():
                # A resolution is a session, and waits for credit the way a
                # publication does: left validated, not reconsidered.
                self._claimed.add(ticket.id)
                return None
            self.say(f"    ! {failure} — resolving it at the next free place")
            resolving.append((ticket, project))
            return None
        if failure:
            self.say(f"    ! {branch} not replayed: {failure}")
            return self._refused(ticket, url, refusal, failure)
        count = self._replayed(ticket, url)
        if project.path and (project.path / ".github" / "workflows").is_dir():
            # The commit just pushed has no check yet: GitHub takes a few
            # seconds to declare them, and `merge_pull_request` reads that
            # empty list as nothing red. Waiting here would hold the queue for
            # a build, so the next pass merges what CI has seen.
            self.say(f"    · {branch} replayed — left validated for its checks")
            return None
        replayed = self.voice.say("merge-rebased", branch=branch, base=base)
        method = self.config.runner.merge_method
        try:
            git.merge_pull_request(url, method, self.config.github)
        except git.GitError as error:
            if git.is_behind(error):
                if count < MOST_REBASES:
                    # The base moved again between the push and the merge: the
                    # next pass replays it once more, on what it holds then.
                    self.say(f"    · {base} moved again — left validated for the next pass")
                    return None
                return self._too_often(ticket, url, base)
            return self._refused(ticket, url, error, replayed)
        return self._merged(
            ticket, url, self.voice.say("merged-with", method=method), notes=(replayed,)
        )

    def _queue(self, url: str) -> threading.Lock:
        """The line merges into that pull request's repository wait in.

        One merge at a time per repository, and each pull request replayed on
        the base as the one before it left it, just before its own merge: with
        the merges of this pass and the forced ones of its sessions all racing
        to the same base, each one made the others "behind" while they were
        being replayed — which is what blocked tickets as “`main` keeps moving
        faster”. Held across the replay and the merge it ends in, never across
        a wait for CI: the line must not stand still for a build.
        """
        with self._landed_lock:
            return self._queues.setdefault(_repository(url), threading.Lock())

    def _landed_in(self, url: str) -> None:
        """One more pull request this runner has merged into that repository."""
        repository = _repository(url)
        with self._landed_lock:
            self._landed[repository] = self._landed.get(repository, 0) + 1

    def _forgiven(self, ticket: Ticket, url: str) -> None:
        """Strike off the replays this runner's own merges made necessary.

        `MOST_REBASES` is there for a base that *somebody else* keeps moving.
        A board that validates ten pull requests on one repository moves the
        base itself: each merge leaves the nine others behind — and, when they
        all touch the changelog or a generated bundle, conflicting — so the
        fourth in line was replayed twice and blocked as "`main` keeps moving
        faster", while all that moved it was the queue it stood in (01/10/2026:
        three tickets blocked that way in five minutes). That queue is finite
        and loses one pull request at every merge: if this runner has merged
        into the repository since the ticket was last replayed, the ticket's
        count starts again. Each such pardon needs a merge of its own, so a
        base moved by anyone else still runs out of replays as before.
        """
        repository = _repository(url)
        with self._landed_lock:
            landed = self._landed.get(repository, 0)
            last = self._replayed_after.get(ticket.id)
        if last is not None and landed > last:
            state.forget_rebases(ticket.id)

    def _replayed(self, ticket: Ticket, url: str) -> int:
        """`state.rebased`, noting how many merges of this runner it came after."""
        with self._landed_lock:
            self._replayed_after[ticket.id] = self._landed.get(_repository(url), 0)
        return state.rebased(ticket.id)

    def _too_often(self, ticket: Ticket, url: str, base: str) -> dict[str, Any]:
        """A base that moves faster than the replays: asked, rather than chased."""
        state.forget_rebases(ticket.id)
        said = self.voice
        return self._fail(
            ticket,
            said.say("rebased-too-often", base=base),
            url,
            code="merge.base-moving",
            blocked=True,
            question=said.say("rebased-too-often-question", count=MOST_REBASES, base=base),
        )

    def _carry_out(self, ticket: Ticket, project: Project) -> dict[str, Any] | None:
        """A validated ticket that needs a session: a publication, or a conflict.

        The two things of the validated column that cost a place, told apart by
        what the ticket carries: a pull request here can only be one whose merge
        stopped on a conflict — every other one was settled by `_merge`.
        """
        url = str(store.read(ticket.page, self.config.notion.prop("pull_request")) or "")
        if url.startswith("http"):
            return self._resolve(ticket, project, url)
        return self._publish(ticket, project)

    def _resolve(self, ticket: Ticket, project: Project, url: str) -> dict[str, Any] | None:
        """Resolve a validated pull request's conflicts, then merge it.

        The replay `_catch_up` gave up on, taken to its end: the branch as
        origin holds it, in a detached worktree of its own, rebased onto its
        base — and where git stops, a session takes over, told what the ticket
        wanted, what the pull request changes and what landed underneath it.
        What it leaves is checked before anything leaves the machine: no rebase
        half done, no marker left in a file, the base underneath. Then the push,
        on a lease on the commit it was replayed from; the pull request's CI;
        and the merge.

        Claimed like a publication, and for the same reason: two runners must
        not both resolve and push the same branch. Anything short of the merge
        is a question on the ticket — what conflicts and what it asks, not only
        GitHub's refusal — with whatever resolution was reached pushed to a
        branch of its own for you to look at.
        """
        settings = self.config.notion
        branch, base = git.pull_request_branches(url, self.config.github)
        if not branch:
            self.say(f"  · {ticket.title} — GitHub did not answer about {url}, left validated")
            return None
        short = short_id(ticket.id)
        role = store.read(ticket.page, settings.prop("role")) or []
        job = Job(
            ticket,
            project,
            branch=branch,
            base=base,
            workdir=state_dir() / "scratch" / f"resolve-{short}",
            session_id=session.new_id(),
            log=state.log_file(short),
            # The model the ticket was worked with, unless the configuration
            # names one for resolving: the session reads the same code again.
            model=self.config.runner.resolve_model
            or str(store.read(ticket.page, settings.prop("model")) or ""),
            agent=(
                agents.resolve(self.client, role[0], settings.prop("model"))
                if role
                else agents.Agent()
            ),
            comments=self.discussion(ticket),
        )
        self.say(f"  ▸ {ticket.title}\n    validated · resolving the conflicts of {url}")
        if self.dry_run:
            return None
        self._claimed.add(ticket.id)
        state.claim(ticket.id, settings.state("validated"))
        self._set(
            ticket,
            **{
                settings.prop("status"): settings.state("running"),
                settings.prop("agent"): self.agent_label,
                settings.prop("waiting"): False,
                settings.prop("session"): self._session_value(job.session_id, project.path),
            },
        )
        try:
            return self._resolved(job, url)
        finally:
            state.release(ticket.id)
            if project.path:
                git.remove_worktree(project.path, job.workdir)

    def _resolved(self, job: Job, url: str) -> dict[str, Any] | None:
        """`_resolve`, once the ticket is claimed: every road out of it."""
        ticket, project = job.ticket, job.project
        assert project.path is not None
        said = self.voice
        accounts = self.config.github
        validated = self.config.notion.state("validated")
        state.enter(ticket.id, "rebase", job.base)
        replay = git.begin_replay(project.path, job.branch, job.base, job.workdir, generated.settle)
        if replay.error:
            return self._refused(ticket, url, replay.error)
        conflicts = replay.conflicts or []
        facts = said.say(
            "conflict-facts",
            branch=job.branch,
            base=job.base,
            onto=replay.onto[:7],
            files=", ".join(f"`{name}`" for name in conflicts) or said.say("conflict-none"),
        )
        outcome: session.Outcome | None = None
        if conflicts:
            job.body = self._conflict_brief(job, url, replay)
            try:
                outcome = self._run_session(
                    job, prompt_module.RESOLVE, phase="resolve", detail=job.base
                )
            except (OSError, FileNotFoundError) as error:
                return self._fail(
                    ticket, said.say("no-session"), str(error), code="session.not-started"
                )
            self._add_cost(ticket, outcome)
            if self._out_of_credit(outcome):
                return self._requeue(ticket, validated, outcome)
            told = _report_of(outcome.answer)
            if not outcome.ok:
                question = outcome.summary or said.say("conflict-open", base=job.base)
                return self._fail(
                    ticket,
                    said.say("conflict-open", base=job.base),
                    outcome.summary or outcome.error,
                    code="merge.conflict-decision",
                    blocked=True,
                    question=outcome.question or question,
                    note=said.paragraphs(
                        facts, told, self._aside(job, replay), self._filed(job, outcome)
                    ),
                )
            problem = self._unfinished(job, replay) or generated.rebuild(
                job.workdir, f"origin/{job.base}"
            )
            if problem:
                return self._fail(
                    ticket,
                    said.say("conflict-unfinished"),
                    problem,
                    code="merge.conflict-unfinished",
                    blocked=True,
                    question=said.say("conflict-unfinished-question", problem=problem),
                    note=said.paragraphs(facts, told, self._aside(job, replay)),
                )
        else:
            told = ""
        failure = git.push_leased(job.workdir, job.branch, replay.was, accounts)
        if failure:
            aside = self._aside(job, replay)
            if git.pushed_over(failure):
                state.forget_rebases(ticket.id)
                return self._fail(
                    ticket,
                    said.say("pushed-over", branch=job.branch),
                    failure,
                    code="merge.pushed-over",
                    blocked=True,
                    question=said.say("pushed-over-question", branch=job.branch),
                    note=said.paragraphs(facts, aside),
                )
            return self._fail(
                ticket, said.say("push-refused"), failure, code="merge.push-refused", note=aside
            )
        self._forgiven(ticket, url)
        count = self._replayed(ticket, url)
        record = said.paragraphs(facts, told)
        git.comment_pull_request(url, f"Ponos — {record}", accounts)
        checks, checked = self._checked(ticket, url, job.workdir, job.base)
        repair: session.Outcome | None = None
        if checks == "failed":
            checks, checked, repair = self._mend(job, url, checked)
            if repair and self._out_of_credit(repair):
                return self._requeue(ticket, validated, repair)
        if checks in ("failed", "unstarted"):
            state.forget_rebases(ticket.id)
            return self._fail(
                ticket,
                said.say("checks-red"),
                url,
                code="merge.checks-failed",
                blocked=True,
                question=said.say("checks-red-question", url=url),
                note=said.paragraphs(record, checked),
            )
        if checks == "base-red":
            return self._left_for_base(ticket, project, url, job.base, record, checked)
        method = self.config.runner.merge_method
        try:
            git.merge_pull_request(url, method, accounts)
        except git.GitError as error:
            if git.is_behind(error) and count < MOST_REBASES:
                # Resolved and pushed, and the base moved again meanwhile: back
                # to the column it came from, for the next pass to replay what
                # is — with a little luck — only a replay this time.
                self.say(f"    · {job.base} moved again — left validated for the next pass")
                self._set(ticket, **{self.config.notion.prop("status"): validated})
                self._comment(ticket, said.report(record, checked, said.say("base-moved-again")))
                return {"ticket": ticket.title, "id": ticket.id, "status": "validated"}
            if git.is_behind(error):
                return self._too_often(ticket, url, job.base)
            return self._refused(ticket, url, error, record, checked)
        spent = said.spent(outcome.seconds, outcome.cost_usd) if outcome else ()
        done = self._merged(
            ticket,
            url,
            said.say("merged-with", method=method),
            said.say("conflicts-resolved") if conflicts else "",
            *spent,
            notes=(said.brief(outcome.summary) if outcome else "", record, checked),
        )
        if outcome:
            done.update(session=outcome.session_id, seconds=round(outcome.seconds, 1))
        # The repair is on the ticket's Cost already (`_add_cost`): its line in
        # the history says the same.
        cost = sum(one.cost_usd for one in (outcome, repair) if one)
        if cost:
            done.update(cost_usd=cost)
        return done

    def _left_for_base(
        self, ticket: Ticket, project: Project, url: str, base: str, *notes: str
    ) -> dict[str, Any]:
        """A resolved pull request whose checks fail where its base fails too.

        Back to the validated column with the line on its card, and no question
        — nobody has anything to answer, `_merge` replays it when the base is
        green. The session that resolved it is not started again.
        """
        said = self.voice
        repair = self._set_aside(ticket, project, url, base)
        state.forget_rebases(ticket.id)
        line = said.say("base-red")
        self.say(f"    ⏸ {ticket.title} — {line}, left validated")
        self._set(
            ticket,
            **{
                self.config.notion.prop("status"): self.config.notion.state("validated"),
                self.config.notion.prop("progress"): said.brief(line),
            },
        )
        self._comment(
            ticket,
            said.report(
                said.verdict("waiting", line),
                said.say("base-red-held", base=base, repair=repair or "-"),
                url,
                *notes,
            ),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "waiting",
            "reason": "merge.base-red",
        }

    def _conflict_brief(self, job: Job, url: str, replay: git.Replay) -> str:
        """Everything the resolving session is told, under the ticket's own text."""
        said = [
            self._body(job.ticket).strip(),
            f"# The pull request — {url}",
            git.pull_request_body(url, self.config.github).strip() or "(no description)",
            "# Where the rebase stopped",
            f"`{job.branch}` (at `{replay.was[:7]}`) is being replayed onto "
            f"`origin/{job.base}` (at `{replay.onto[:7]}`). Git stopped on:\n"
            + "\n".join(f"- `{name}`" for name in replay.conflicts or []),
            f"# What landed on `{job.base}` since the branch left it",
            f"```\n{replay.arrived or '(nothing git could list)'}\n```",
            "# What the pull request changes",
            f"```diff\n{replay.diff}\n```\n"
            f"The whole of it, and each commit: `git log -p origin/{job.base}..{replay.was}`.",
        ]
        return "\n\n".join(part for part in said if part)

    def _unfinished(self, job: Job, replay: git.Replay) -> str:
        """What a resolution that said it was done has not actually done, or nothing."""
        said = self.voice
        if git.rebasing(job.workdir):
            return said.say("unfinished-rebase")
        marked = git.with_markers(job.workdir, replay.conflicts or [])
        if marked:
            return said.say("unfinished-markers", files=", ".join(f"`{name}`" for name in marked))
        if not git.contains(job.workdir, replay.onto):
            return said.say("unfinished-base", base=job.base)
        if git.is_dirty(job.workdir):
            return said.say("unfinished-dirty")
        return ""

    def _aside(self, job: Job, replay: git.Replay) -> str:
        """The resolution as far as it got, on a branch of its own — said, or nothing.

        Only a rebase carried to its end: a worktree still in the middle of one
        holds no branch worth reading, only an index somebody has to finish.
        """
        head = git.head(job.workdir)
        if git.rebasing(job.workdir) or not head or head == replay.was:
            return ""
        name = f"{job.branch}-rebased-{head[:7]}"
        if git.push_aside(job.workdir, name, self.config.github):
            return ""
        return self.voice.say("conflict-aside", branch=name)

    def _add_cost(self, ticket: Ticket, outcome: session.Outcome) -> None:
        """A resolution's price, added to what the ticket had already cost."""
        if not outcome.cost_usd or self.dry_run:
            return
        column = self.config.notion.prop("cost")
        before = store.read(ticket.page, column)
        spent = (before if isinstance(before, (int, float)) else 0.0) + outcome.cost_usd
        try:
            self.client.update(self.database, ticket.page.id, {column: round(spent, 3)})
        except store.StoreError as error:
            self.say(f"    ! the cost could not be written: {voice_module.line(error)}")

    def _publish_all(self, publishing: list[tuple[Ticket, Project]]) -> list[dict[str, Any]]:
        """Every validated publication of this pass, up to `max_concurrent` at once.

        A batch, unlike the ticket queue in `_work`, and deliberately so: the
        whole list is handed to `pool.map`, which starts the next publication as
        soon as a worker frees, so no place is ever left idle. What it does not
        do is look at the board again mid-list — and it has no reason to: this
        is the top of a pass, and a ticket validated a minute later is picked up
        by `_work`, which looks at that column for as long as the pass lasts.
        """
        if not publishing:
            return []
        if len(publishing) == 1:
            done = self._guarded(publishing[0][0], self._carry_out, *publishing[0])
            return [done] if done else []
        workers = min(len(publishing), max(1, self.config.runner.max_concurrent))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(
                pool.map(lambda pair: self._guarded(pair[0], self._carry_out, *pair), publishing)
            )
        return [done for done in results if done]

    def _publish(
        self,
        ticket: Ticket,
        project: Project,
        forced: str = "",
        prepared: session.Outcome | None = None,
    ) -> dict[str, Any] | None:
        """A validated ticket with no pull request: publish what it holds.

        The Instagram post drafted last week, the email written into the page,
        the announcement waiting on somebody to press send: work whose last step
        is not a commit. A session is given the page as it stands — the ask, and
        the answer a previous run wrote under it — and told to put it where the
        ticket says, changing nothing on the way.

        Claimed like any other work, by moving the ticket to "in progress":
        publishing twice is the one mistake this must not make, and two runners
        looking at the same board would otherwise both take it. The column it
        was claimed from is written down first — see `state.claim` — so that a
        run dying mid-publication comes back as a question rather than as a
        second post.

        `forced` is the line saying nobody moved it: a ticket whose type has its
        validation forced comes here straight from the session that prepared it
        — see `Execution._execute_document` — and its report says so; `prepared`
        is that session, whose price and time are added to this one's, in the
        columns as in the history, rather than written over by them.
        """
        short = short_id(ticket.id)
        # The role, if the ticket names one: the account to post to and the
        # voice to post in are exactly the sort of thing an agent page carries.
        role = store.read(ticket.page, self.config.notion.prop("role")) or []
        job = Job(
            ticket,
            project,
            branch="",
            base="",
            workdir=state_dir() / "scratch" / f"deliver-{short}",
            body=self._body(ticket),
            session_id=session.new_id(),
            log=state.log_file(short),
            model=str(store.read(ticket.page, self.config.notion.prop("model")) or ""),
            agent=(
                agents.resolve(self.client, role[0], self.config.notion.prop("model"))
                if role
                else agents.Agent()
            ),
            comments=self.discussion(ticket),
        )
        self.say(f"  ▸ {ticket.title}\n    validated · publishing what the ticket holds")
        if self.dry_run:
            return None
        # A comment on a ticket being published is a conversation about the
        # work, not an instruction: the same rule as a ticket about to be run.
        self._claimed.add(ticket.id)
        state.claim(ticket.id, self.config.notion.state("validated"))
        self._set(
            ticket,
            **{
                self.config.notion.prop("status"): self.config.notion.state("running"),
                self.config.notion.prop("agent"): self.agent_label,
                # Unticked by the same write that claims it: the wait is over
                # the moment something is started, and a tick left behind would
                # have the next pass resume a session that is running.
                self.config.notion.prop("waiting"): False,
                self.config.notion.prop("session"): self._session_value(
                    job.session_id, project.path
                ),
            },
        )
        job.workdir.mkdir(parents=True, exist_ok=True)
        try:
            outcome = self._run_session(
                job,
                prompt_module.template(
                    self.config.runner.delivery_prompt_file, prompt_module.DELIVERY
                ),
            )
        except (OSError, FileNotFoundError) as error:
            failed = self._fail(
                ticket,
                self.voice.say("no-session"),
                str(error),
                code="session.not-started",
                outcome=prepared,
            )
            state.release(ticket.id)
            return failed
        if prepared:
            outcome = replace(
                outcome,
                cost_usd=prepared.cost_usd + outcome.cost_usd,
                seconds=prepared.seconds + outcome.seconds,
                turns=prepared.turns + outcome.turns,
            )
        # Every road from here writes a status that is not "in progress", and
        # the note about where it came from is let go once that write is in —
        # not before: a write Notion never received leaves the ticket in
        # progress, and without the note `sweep` would put a post that is
        # already out back to ready, to be published a second time.
        said = self.voice
        if self._out_of_credit(outcome):
            # Back to validated, not to ready: the decision to publish it has
            # already been taken, and the wait does not take it back.
            requeued = self._requeue(ticket, self.config.notion.state("validated"), outcome)
            state.release(ticket.id)
            return requeued

        if not outcome.ok:
            # Kept, always: a publication that half happened is exactly the log
            # somebody is going to want to read before trying again.
            failed = self._fail(
                ticket,
                said.say("not-published"),
                outcome.summary or outcome.error,
                code="publish.failed",
                blocked=outcome.blocked,
                question=outcome.question or outcome.summary,
                note=said.paragraphs(
                    forced,
                    self._filed(job, outcome, said.say("workdir-kept", path=job.workdir)),
                ),
                outcome=outcome,
            )
            state.release(ticket.id)
            return failed

        shutil.rmtree(job.workdir, ignore_errors=True)
        self._set(
            ticket,
            **{
                self.config.notion.prop("status"): self.config.notion.state("done"),
                self.config.notion.prop("agent"): self.agent_label,
                self.config.notion.prop("session"): self._session_value(
                    outcome.session_id, job.session_home
                ),
                **self._measures(outcome),
            },
        )
        state.release(ticket.id)
        facts = said.spent(outcome.seconds, outcome.cost_usd)
        brief = said.brief(outcome.summary)
        self._comment(ticket, said.report(said.verdict("published", *facts), brief, forced))
        self.say(f"    ✓ {ticket.title} — published")
        self._tell(
            "done",
            ticket,
            "published",
            said.report(said.facts(*facts), brief, forced),
            project=project.name,
            summary=outcome.summary,
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "done",
            "project": project.name,
            "kind": "delivery",
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }
