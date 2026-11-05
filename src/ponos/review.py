"""The self-review: a second reading of a branch, before anybody else's.

The one review a pull request of Ponos used to get was the person's, and it
came late: a red CI, a test the ticket asked for and nobody wrote, a generated
file not regenerated, a translation forgotten — things a reading against the
ticket finds in a minute, found a day later by somebody who then has to send
the ticket back. So once the session has committed, and before the push, a
short session of its own reads the diff against the ticket — its done
criterion first — and the project's CLAUDE.md, and says `REVIEW: ok` or what
it finds blocking.

**A stranger reads, the author fixes.** The reviewer starts with nothing but
the ticket and the diff, which is what makes it a review rather than the
session agreeing with itself; and it runs in plan mode, so that a reading can
never become a second author. What it finds goes back to the ticket's own
session, picked up with `--resume`: it knows why every line it wrote is there,
and a stranger fixing them would not.

**Once, and the pull request opens whatever happens.** A review that could
send the work back again and again is a loop paid for by the ticket, and a
reviewer that disagrees with the author would hold the branch here forever. So
there is one pick-up a pass, and then the push: what was fixed and what was
left is said in the pull request and in the report, under « Review » — the
person reviewing reads it there, rather than finding it. A review with nothing
to say adds nothing to the pull request; one that cannot be read, or did not
run, is as if it had not been asked.

**Paid by the ticket.** Both halves go through `_paid`, so the day's limit
counts them, and their cost is added to the ticket's — what a ticket costs is
what it cost, the reading included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from . import git, project_settings, session, state
from . import prompt as prompt_module
from .base import Base
from .ticket import Job, short_id
from .voice import Voice

# At most this many points: a review that lists twenty is a review of the
# whole repository, and a session handed twenty fixes is a second ticket.
MOST = 8
# How much of the diff and of the project's instructions the reviewer is handed
# in its prompt. Past it, it is told so, and reads the rest in the worktree.
DIFF_LIMIT = 80_000
INSTRUCTIONS_LIMIT = 20_000
# Where a repository says how it is worked on, in the order they are read.
INSTRUCTIONS = ("CLAUDE.md", "AGENTS.md")

# The verdict line, with whatever Markdown a session puts around a line it is
# proud of: `**REVIEW: ok**`, `> REVIEW: blocking`.
_VERDICT = re.compile(r"^[\s*#>`_]*REVIEW\s*:\s*[*`_]*\s*([A-Za-z-]+)", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
# A point's file, before its reason: `path: reason`, `path — reason`.
_FILE = re.compile(r"^`?([^\s`:]+?)`?\s*(?::|—|–|\s-\s)\s*(.+)$")
_SAID = re.compile(r"^[\s*#>`_-]*(FIXED|LEFT)\s*:\s*[*`_]*\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Point:
    """One thing the review found blocking: the file it is in, and why."""

    file: str
    reason: str

    def __str__(self) -> str:
        return f"`{self.file}`: {self.reason}" if self.file else self.reason


def verdict(answer: str) -> list[Point] | None:
    """What a review said: [] for `REVIEW: ok`, its points otherwise — None when it said nothing.

    The last verdict line counts, as the last RESULT line does. A verdict that
    is not `ok` and names nothing is no verdict: there is nothing to hand back,
    and saying "nothing blocking" of it would be saying what it did not.
    """
    lines = answer.splitlines()
    found = next(
        (index for index in range(len(lines) - 1, -1, -1) if _VERDICT.match(lines[index])),
        None,
    )
    if found is None:
        return None
    said = _VERDICT.match(lines[found])
    assert said is not None
    if said.group(1).lower() == "ok":
        return []
    after = [line for line in lines[found + 1 :] if line.strip()]
    bullets = [matched.group(1) for line in after if (matched := _BULLET.match(line))]
    points = [_point(text) for text in (bullets or [line.strip() for line in after])]
    return points[:MOST] or None


def _point(text: str) -> Point:
    named = _FILE.match(text.strip())
    if named and ("/" in named.group(1) or "." in named.group(1)):
        return Point(named.group(1), named.group(2).strip())
    return Point("", text.strip())


def fixes(answer: str) -> tuple[list[str], list[str]]:
    """What the session picked up on the points says it fixed, and what it left."""
    fixed: list[str] = []
    left: list[str] = []
    for line in answer.splitlines():
        if said := _SAID.match(line):
            (fixed if said.group(1).upper() == "FIXED" else left).append(said.group(2))
    return fixed, left


def section(
    voice: Voice,
    points: list[Point],
    fixed: list[str],
    left: list[str],
    summary: str,
    *,
    finished: bool,
) -> str:
    """The « Review » section of the pull request: what was raised, what was fixed, what is left."""
    count = voice.count(len(points), "point")
    lines = [
        voice.say("review-heading"),
        "",
        voice.say("review-intro" if finished else "review-intro-unfinished", points=count),
        "",
        voice.say("review-raised"),
        *(f"- {point}" for point in points),
    ]
    if finished and (fixed or left):
        if fixed:
            lines += ["", voice.say("review-fixed"), *(f"- {said}" for said in fixed)]
        if left:
            lines += ["", voice.say("review-left"), *(f"- {said}" for said in left)]
    elif finished and summary.strip():
        lines += ["", voice.say("review-answer", summary=summary.strip())]
    return "\n".join(lines)


def note(
    voice: Voice, points: list[Point], fixed: list[str], left: list[str], *, finished: bool
) -> str:
    """The review's line in the ticket's report."""
    count = voice.count(len(points), "point")
    if not finished:
        return voice.say("review-unfinished", points=count)
    if fixed or left:
        return voice.say("review-told", points=count, fixed=len(fixed), left=len(left))
    return voice.say("review-untold", points=count)


def instructions(worktree: Path) -> str:
    """The repository's own instructions to whoever works on it, as far as the prompt holds them."""
    for name in INSTRUCTIONS:
        path = worktree / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return text[:INSTRUCTIONS_LIMIT]
    return ""


def _paid_for(outcome: session.Outcome, other: session.Outcome) -> session.Outcome:
    """The ticket's session, carrying what another session spent for it."""
    return replace(
        outcome,
        cost_usd=outcome.cost_usd + other.cost_usd,
        seconds=outcome.seconds + other.seconds,
    )


class Review(Base):
    """The branch read against its ticket before the push, and handed back once."""

    def _reviews(self, job: Job) -> bool:
        """Whether this ticket's branch is read before its push: the project's word, else the file's."""
        own = project_settings.self_review(job.project.notion_id)
        return own if own is not None else self.config.runner.self_review

    def _self_review(self, job: Job, outcome: session.Outcome) -> session.Outcome:
        """The branch reviewed, and the session picked up once on what was found blocking.

        Returns the ticket's session as it now stands — what the review and
        the pick-up cost added to it — and leaves on the job what the pull
        request and the report say of it. `stopped` when it was ended from the
        console meanwhile: the caller hands the ticket back, as after its session.
        """
        if not self._reviews(job):
            return outcome
        diff = git.branch_diff(job.workdir, job.base)
        if not diff.strip():
            return outcome
        log = job.log or state.log_file(short_id(job.ticket.id))
        model = self.config.runner.allowed(
            self.config.runner.review_model
            or job.model
            or job.agent.model
            or self.config.runner.model
        )
        state.enter(job.ticket.id, "review", model)
        self.say(f"    · self-review on {model or 'the default model'}")
        read = self._paid(
            job.ticket.id,
            prompt_module.review(
                job.ticket.title,
                job.body,
                job.base,
                diff[:DIFF_LIMIT],
                instructions(job.workdir),
                cut=len(diff) > DIFF_LIMIT,
                most=MOST,
            ),
            cwd=job.workdir,
            log=log.with_name(f"{log.stem}-review{log.suffix}"),
            model=model,
            # The guardrail rather than the prompt: a reader that can write is
            # a second author nobody asked for.
            permission_mode="plan",
            timeout_minutes=self.config.runner.timeout_minutes,
            environment=self.environment_for(model),
            max_budget_usd=self.config.budget.per_ticket_usd,
        )
        outcome = _paid_for(outcome, read)
        if read.stopped:
            return replace(outcome, stopped=True)
        points = verdict(read.answer) if read.ok else None
        said = self.voice
        if points is None:
            self.say("    · self-review gave no verdict — the pull request opens without it")
            return outcome
        if not points:
            self.say("    · self-review: nothing blocking")
            job.notes.append(said.say("review-ok"))
            return outcome
        self.say(
            f"    ↻ self-review: {len(points)} blocking — asking session "
            f"{outcome.session_id} to deal with them"
        )
        fixed = self._fix_review(job, outcome, points, log)
        finished = fixed.ok
        # What the ticket's report says it did is what the first half said:
        # the review is a section of it, said by the note.
        total = replace(
            outcome,
            cost_usd=outcome.cost_usd + fixed.cost_usd,
            seconds=outcome.seconds + fixed.seconds,
            turns=outcome.turns + fixed.turns,
            caveats=[*outcome.caveats, *fixed.caveats],
        )
        if fixed.stopped:
            return replace(total, stopped=True)
        done, left = fixes(fixed.answer) if finished else ([], [])
        job.review = section(said, points, done, left, fixed.summary, finished=finished)
        job.notes.append(note(said, points, done, left, finished=finished))
        return total

    def _fix_review(
        self, job: Job, outcome: session.Outcome, points: list[Point], log: Path
    ) -> session.Outcome:
        """The ticket's session, picked up once on the review's points — as it ended."""
        state.enter(job.ticket.id, "session", "review")
        # Filed under the project once it ended: brought back beside its
        # worktree for as long as it is carried on, and filed again after.
        session.relocate(outcome.session_id, job.workdir)
        model = self.config.runner.allowed(job.model or job.agent.model or self.config.runner.model)
        run = self._journals.get(job.ticket.id)
        try:
            return self._paid(
                job.ticket.id,
                prompt_module.review_fix(
                    [str(point) for point in points], self.voice.instruction()
                ),
                cwd=job.workdir,
                log=log.with_name(f"{log.stem}-review-fix{log.suffix}"),
                model=model,
                permission_mode=self.config.runner.permission_mode,
                timeout_minutes=self.config.runner.timeout_minutes,
                session_id=outcome.session_id,
                resume=True,
                environment={**job.secrets, **self.environment_for(model), **self._github(job)},
                on_event=run.event if run else None,
                max_budget_usd=self.config.budget.per_ticket_usd,
            )
        finally:
            if job.session_home:
                session.relocate(outcome.session_id, job.session_home)
