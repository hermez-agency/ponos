"""`review.py`: what a review says, read back, and the one pick-up it is allowed."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from support import _board_runner, _reviewed, case

from ponos import git as git_module
from ponos import project_settings, projects, review, session
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.voice import Voice

# -- reading the verdict ---------------------------------------------------------


@case
def a_review_that_says_ok_has_no_point_and_one_that_says_nothing_has_no_verdict() -> None:
    assert review.verdict("Tout est là.\nREVIEW: ok") == []
    assert review.verdict("**REVIEW: OK**") == []
    assert review.verdict("Je n'ai rien trouvé.") is None, "no verdict line, no verdict"
    assert review.verdict("REVIEW: blocking") is None, "blocking, and nothing named"
    assert review.verdict("") is None


@case
def a_blocking_review_is_read_point_by_point_with_its_files() -> None:
    points = review.verdict(
        "J'ai lu le diff.\n"
        "> REVIEW: blocking\n"
        "- `src/ponos/review.py`: the cap is never applied\n"
        "* tests/test_review.py — no case for the limit\n"
        "\n"
        "1. the done criterion asks for a guide page\n"
    )
    assert points == [
        review.Point("src/ponos/review.py", "the cap is never applied"),
        review.Point("tests/test_review.py", "no case for the limit"),
        review.Point("", "the done criterion asks for a guide page"),
    ], points
    assert str(points[0]) == "`src/ponos/review.py`: the cap is never applied"
    assert str(points[2]) == "the done criterion asks for a guide page"


@case
def only_the_last_verdict_counts_and_no_more_than_the_cap_is_kept() -> None:
    assert review.verdict("REVIEW: blocking\n- a.py: x\n\nOn second thought:\nREVIEW: ok") == []
    many = "REVIEW: blocking\n" + "\n".join(f"- f{n}.py: reason {n}" for n in range(20))
    read = review.verdict(many)
    assert read is not None and len(read) == review.MOST, read
    assert read[0] == review.Point("f0.py", "reason 0"), "the most serious, first, are kept"
    # No bullets: every line after the verdict is a point.
    assert review.verdict("REVIEW: blocking\nsrc/a.ts: missing key") == [
        review.Point("src/a.ts", "missing key")
    ]


@case
def what_the_picked_up_session_fixed_and_left_is_read_from_its_lines() -> None:
    fixed, left = review.fixes(
        "J'ai repris les deux points.\n"
        "FIXED: src/a.py — the cap is applied\n"
        "- **LEFT:** docs/guide.md — out of the ticket\n"
        "RESULT: ok — done"
    )
    assert fixed == ["src/a.py — the cap is applied"], fixed
    assert left == ["docs/guide.md — out of the ticket"], left
    assert review.fixes("RESULT: ok — done") == ([], [])


@case
def the_pull_request_section_says_what_was_raised_fixed_and_left() -> None:
    points = [review.Point("a.py", "x"), review.Point("b.py", "y")]
    told = review.section(
        Voice("fr"), points, ["a.py — corrigé"], ["b.py — non"], "", finished=True
    )
    assert told.startswith("### Relecture\n"), told
    assert "2 points bloquants" in told and "- `a.py`: x" in told
    assert "Corrigés :\n- a.py — corrigé" in told and "Restants :\n- b.py — non" in told
    untold = review.section(Voice("en"), points, [], [], "both fixed", finished=True)
    assert "What the session says of it: both fixed" in untold, untold
    unfinished = review.section(Voice("en"), points[:1], [], [], "", finished=False)
    assert "1 blocking point" in unfinished and "did not finish" in unfinished, unfinished
    assert "Fixed:" not in unfinished


# -- the pass ----------------------------------------------------------------------


def _outcome(**values: Any) -> session.Outcome:
    fields: dict[str, Any] = {
        "ok": True,
        "blocked": False,
        "session_id": "s-ticket",
        "summary": "Fait.",
        "log": Path("/logs/x.jsonl"),
    }
    return session.Outcome(**{**fields, **values})


def _job() -> ticket_module.Job:
    root = Path(tempfile.mkdtemp())
    (root / "work").mkdir()
    (root / "work" / "CLAUDE.md").write_text("Un cas par module.", encoding="utf-8")
    page = _reviewed("p-ticket", "In progress", None)
    job = ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project(name="Northwind", path=root / "repository", notion_id="proj-1"),
        branch="ticket/x",
        base="main",
        workdir=root / "work",
        body="Le titre.\n\n## Critère de fin\n- un test",
    )
    job.log = root / "run.jsonl"
    return job


@contextmanager
def _reviewing(
    *outcomes: session.Outcome, diff: str = "+une ligne"
) -> Iterator[tuple[Runner, list[dict[str, Any]]]]:
    """A runner whose sessions answer `outcomes` in turn, on a branch whose diff is `diff`."""
    runner = _board_runner([], {"review": "In review", "done": "Done"})
    runner.say = lambda message: None  # type: ignore[method-assign]  # a double: quiet
    asked: list[dict[str, Any]] = []
    queue = list(outcomes)

    def paid(ticket: str, prompt_text: str, **options: Any) -> session.Outcome:
        asked.append({"prompt": prompt_text, **options})
        return queue.pop(0)

    runner._paid = paid  # type: ignore[method-assign, assignment]  # a double: the outcomes above, in turn
    saved = git_module.branch_diff
    git_module.branch_diff = lambda worktree, base: diff
    try:
        yield runner, asked
    finally:
        git_module.branch_diff = saved


@case
def a_blocking_review_picks_the_session_up_once_and_never_twice(state_home: Path) -> None:
    job = _job()
    blocking = _outcome(
        session_id="s-review",
        answer="REVIEW: blocking\n- a.py: no test\n- b.py: no doc",
        cost_usd=0.01,
    )
    fixed = _outcome(
        answer="FIXED: a.py — test added\nLEFT: b.py — out of scope\nRESULT: ok — fait",
        summary="fait",
        cost_usd=0.2,
        turns=4,
    )
    with _reviewing(blocking, fixed) as (runner, asked):
        outcome = runner._self_review(job, _outcome(cost_usd=1.0, turns=10))
    assert len(asked) == 2, "one review, one pick-up — and no second review"
    read, again = asked
    assert read["permission_mode"] == "plan" and read["model"] == "sonnet", read
    assert not read.get("resume"), "the review is a session of its own"
    assert "## Critère de fin" in read["prompt"] and "+une ligne" in read["prompt"]
    assert "Un cas par module." in read["prompt"], "the project's CLAUDE.md was not given"
    assert again["resume"] and again["session_id"] == "s-ticket", again
    assert "1. `a.py`: no test" in again["prompt"], again["prompt"]
    assert outcome.cost_usd == 1.21 and outcome.turns == 14, "all three were the ticket's"
    assert outcome.summary == "Fait.", "the report is the first half's"
    assert "### Review" in job.review and "- a.py — test added" in job.review, job.review
    assert job.notes == [
        "Review: 2 blocking points, the session picked up once — fixed: 1, left: 1."
    ]


@case
def a_review_with_nothing_blocking_adds_nothing_to_the_pull_request(state_home: Path) -> None:
    job = _job()
    with _reviewing(_outcome(answer="REVIEW: ok", cost_usd=0.01)) as (runner, asked):
        outcome = runner._self_review(job, _outcome(cost_usd=1.0))
    assert len(asked) == 1 and job.review == "", job.review
    assert job.notes == ["Review: nothing blocking."]
    assert outcome.cost_usd == 1.01, "the review is paid by the ticket all the same"


@case
def a_review_without_a_verdict_or_a_diff_changes_nothing(state_home: Path) -> None:
    job = _job()
    with _reviewing(_outcome(answer="Je regarde.")) as (runner, asked):
        runner._self_review(job, _outcome())
    assert len(asked) == 1 and job.review == "" and job.notes == []
    with _reviewing(_outcome(ok=False, error="boom", answer="REVIEW: blocking\n- a.py: x")) as (
        runner,
        asked,
    ):
        runner._self_review(job, _outcome())
    assert len(asked) == 1, "a review that failed is not handed back"
    with _reviewing(diff="") as (runner, asked):
        runner._self_review(job, _outcome())
    assert asked == [], "nothing committed against the base, nothing to read"


@case
def a_pick_up_that_does_not_finish_leaves_every_point_and_the_pull_request_opens(
    state_home: Path,
) -> None:
    job = _job()
    blocking = _outcome(answer="REVIEW: blocking\n- a.py: no test")
    with _reviewing(blocking, _outcome(ok=False, blocked=True, answer="RESULT: blocked — ?")) as (
        runner,
        _,
    ):
        outcome = runner._self_review(job, _outcome())
    assert outcome.ok, "the ticket's session stays the one it is judged on"
    assert "did not finish" in job.review and "Fixed:" not in job.review, job.review
    assert job.notes == [
        "Review: 1 blocking point; the session picked up on them did not finish — all left."
    ]


@case
def the_review_is_off_by_the_file_or_by_the_project(state_home: Path) -> None:
    job = _job()
    with _reviewing(_outcome(answer="REVIEW: ok")) as (runner, asked):
        runner.config.runner.self_review = False
        runner._self_review(job, _outcome())
        assert asked == [], "runner.self_review = false"
        project_settings.set_self_review("proj-1", "Northwind", True)
        runner._self_review(job, _outcome())
        assert len(asked) == 1, "the project's word over the file's"
        runner.config.runner.self_review = True
        project_settings.set_self_review("proj-1", "Northwind", False)
        runner._self_review(job, _outcome())
        assert len(asked) == 1, "turned off for the project"
    assert project_settings.self_review("proj-1") is False
    project_settings.set_self_review("proj-1", "Northwind", None)
    assert project_settings.self_review("proj-1") is None
