"""`git.py`: worktrees, branches, and the repository they never touch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import (
    ROOT,
    _bare_runner,
    _board_runner,
    _config,
    _git_answering,
    _github,
    _reviewed,
    _state_home,
    case,
)

from ponos import git as git_module
from ponos import notion, projects, state, voice, workspace
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import api as web_api
from ponos.web import base as web_base

# -- worktrees ---------------------------------------------------------------


def _worktree_for(
    branch="ticket/le-header-9d2cb790",
    *,
    refs=("main", "origin/main"),
    held="",
    held_here=False,
    commits=0,
    dirty=False,
    rebase="",
    path_exists=False,
):
    """Make the ticket's worktree against an invented repository.

    `refs` is what git can resolve, `held` the worktree that already has the
    branch checked out — `held_here` when that worktree is the ticket's own —
    and `rebase` what a rebase would print instead of working.
    Returns what `add_worktree` answered — or the GitError it raised — and every
    command it ran, which is where the interesting part of this lives.
    """

    commands: list[list[str]] = []

    def fake(args, cwd, timeout=300, **_):
        commands.append(list(args))
        head = args[:1]
        if args[:3] == ["rev-parse", "--verify", "--quiet"]:
            return git_module.Result(0 if args[3] in refs else 1, "", "")
        if args[:2] == ["worktree", "list"]:
            listing = f"worktree {held}\nHEAD abc\nbranch refs/heads/{branch}\n" if held else ""
            return git_module.Result(0, listing, "")
        if head == ["rev-list"]:
            return git_module.Result(0, str(commits), "")
        if args[:2] == ["status", "--porcelain"]:
            return git_module.Result(0, "M src/x.py" if dirty else "", "")
        if args[:2] == ["rebase", "--autostash"]:
            if rebase:
                return git_module.Result(
                    1, f"CONFLICT (content): {rebase}", "error: could not apply"
                )
            return git_module.Result(0, "", "")
        return git_module.Result(0, "", "")

    with tempfile.TemporaryDirectory() as home:
        repo, path = Path(home) / "repo", Path(home) / "worktrees" / "site-9d2cb790"
        if held_here:
            held = str(path)
        if path_exists:
            path.mkdir(parents=True)
            # What a worktree has instead of a repository: the file that points
            # back at the one it belongs to.
            (path / ".git").write_text(f"gitdir: {repo}/.git/worktrees/site-9d2cb790\n")
        with _git_answering(git=fake):
            try:
                made = git_module.add_worktree(repo, path, branch, "main")
            except git_module.GitError as error:
                made = error
    return made, commands


def _one(commands: list[list[str]], prefix: list[str]) -> list[str]:
    """The one command that starts like that — there is never a second."""
    found = [command for command in commands if command[: len(prefix)] == prefix]
    assert len(found) == 1, f"{prefix} ran {len(found)} time(s): {commands}"
    return found[0]


def _aged_page(page_id: str, status: str, edited_days_ago: float) -> notion.Page:
    edited = datetime.now(UTC) - timedelta(days=edited_days_ago)
    return notion.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"Status": {"type": "status", "status": {"name": status}}},
        raw={"last_edited_time": edited.isoformat()},
    )


class _BoardOf:
    """A board that answers one query — every ticket — and nothing else."""

    def __init__(self, pages: list[notion.Page], error: str = "") -> None:
        self._pages = pages
        self._error = error

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        if self._error:
            raise notion.NotionError(self._error)
        return self._pages


def _tidying(pages: list[notion.Page], body: str = "", error: str = "") -> Runner:
    runner = _bare_runner(_BoardOf(pages, error))
    runner.config = _config(body)
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    return runner


def _aged(path: Path, days: float, *, directory: bool = True) -> Path:
    if directory:
        path.mkdir(parents=True)
        (path / "work.txt").write_text("x" * 1000)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("log")
    moment = time.time() - days * 86400
    os.utime(path, (moment, moment))
    return path


@case
def a_pass_tidies_what_done_tickets_left_and_nothing_else(state_home):
    """The ticket: 44 worktrees, 25 GB, because `clean` only ran when somebody
    typed it. A pass now applies the retention once a day — and the board says
    what may go: done for long enough, or a scratch directory nobody can reach."""
    tail = {
        name: f"{index:08x}"
        for index, name in enumerate(
            ["done", "fresh", "blocked", "review", "claimed", "gone", "gone2"], start=0x1A2B3C40
        )
    }
    pages = [
        _aged_page(f"page-{tail['done']}", "Done", 30),
        _aged_page(f"page-{tail['fresh']}", "Done", 2),
        _aged_page(f"page-{tail['blocked']}", "Blocked", 30),
        _aged_page(f"page-{tail['review']}", "In review", 30),
        _aged_page(f"page-{tail['claimed']}", "Done", 30),
    ]
    worktrees, scratch = state_home / "worktrees", state_home / "scratch"
    done = _aged(worktrees / f"app-{tail['done']}", 30)
    done_scratch = _aged(scratch / f"deliver-{tail['done']}", 30)
    fresh = _aged(worktrees / f"app-{tail['fresh']}", 30)
    blocked = _aged(worktrees / f"app-{tail['blocked']}", 30)
    blocked_scratch = _aged(scratch / f"notes-{tail['blocked']}", 30)
    review = _aged(worktrees / f"app-{tail['review']}", 30)
    claimed = _aged(worktrees / f"app-{tail['claimed']}", 30)
    orphan = _aged(scratch / f"notes-{tail['gone']}", 30)
    orphan_worktree = _aged(worktrees / f"app-{tail['gone2']}", 30)
    young_orphan = _aged(scratch / f"kind-{tail['gone2']}", 1)
    old_log = _aged(state_home / "logs" / "old.jsonl", 30, directory=False)
    new_log = _aged(state_home / "logs" / "new.jsonl", 1, directory=False)
    state.claim(f"page-{tail['claimed']}", "Validated")

    runner = _tidying(pages)
    tidied = runner.tidy()
    assert tidied is not None
    assert not done.exists() and not done_scratch.exists(), "done for a month: gone"
    assert not orphan.exists(), "a scratch directory whose ticket left the board: gone"
    assert not old_log.exists() and new_log.exists()
    for kept in (
        fresh,
        blocked,
        blocked_scratch,
        review,
        claimed,
        orphan_worktree,
        young_orphan,
    ):
        assert kept.exists(), f"{kept.name} was removed"
    assert tidied.logs == 1 and tidied.freed >= 3000, tidied
    assert runner.tidy() is None, "once a day, not every pass"


@case
def a_done_tickets_worktree_with_uncommitted_work_is_kept(state_home):
    worktree = _aged(state_home / "worktrees" / "app-1a2b3c4d", 30)
    removed: list[Path] = []
    with _git_answering(
        repository_of=lambda _path: state_home,
        is_dirty=lambda _path: True,
        remove_worktree=lambda _repo, path: removed.append(path),
    ):
        _tidying([_aged_page("page-1a2b3c4d", "Done", 30)]).tidy()
    assert worktree.exists() and not removed
    with _git_answering(
        repository_of=lambda _path: state_home,
        is_dirty=lambda _path: False,
        remove_worktree=lambda _repo, path: (removed.append(path), shutil.rmtree(path)),
    ):
        _tidying([_aged_page("page-1a2b3c4d", "Done", 30)]).tidy(now=True)
    assert removed == [worktree] and not worktree.exists()


@case
def a_board_that_cannot_be_read_tidies_the_logs_and_nothing_else(state_home):
    """No board, no verdict: an unreadable one — or an empty one, which is more
    likely a board not read than a board whose every ticket was deleted —
    removes no directory at all."""
    scratch = _aged(state_home / "scratch" / "notes-1a2b3c4d", 30)
    log = _aged(state_home / "logs" / "old.jsonl", 30, directory=False)
    _tidying([], error="502 bad gateway").tidy()
    assert scratch.exists() and not log.exists()
    _tidying([]).tidy(now=True)
    assert scratch.exists(), "an empty board orphaned everything"


@case
def the_retention_can_be_turned_off(state_home):
    scratch = _aged(state_home / "scratch" / "notes-1a2b3c4d", 30)
    page = _aged_page("page-1a2b3c4d", "Done", 30)
    _tidying([page], "[runner]\nclean_done_worktrees = false\n").tidy()
    assert scratch.exists()
    _tidying([page], "[runner]\nlog_retention_days = 0\n").tidy(now=True)
    assert scratch.exists()
    example = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    assert "clean_done_worktrees = true" in example


@case
def a_cancelled_ticket_loses_its_worktree_like_a_done_one_and_a_validated_one_keeps_it(state_home):
    cancelled = _aged(state_home / "worktrees" / "app-1a2b3c41", 30)
    validated = _aged(state_home / "worktrees" / "app-1a2b3c42", 20)
    pages = [
        _aged_page("page-1a2b3c41", "Cancelled", 30),
        _aged_page("page-1a2b3c42", "Validated", 30),
    ]
    with _git_answering(
        repository_of=lambda _path: state_home,
        is_dirty=lambda _path: False,
        unpushed=lambda _path: 0,
        current_branch=lambda _path: "",
        remove_worktree=lambda _repo, path: shutil.rmtree(path),
    ):
        _tidying(pages).tidy()
    assert not cancelled.exists() and validated.exists()


@case
def a_forgotten_worktree_goes_unless_its_ticket_runs_or_it_holds_work_nobody_else_has(state_home):
    tail = ["1a2b3c51", "1a2b3c52", "1a2b3c53", "1a2b3c54", "1a2b3c55", "1a2b3c56", "1a2b3c57"]
    pages = [
        _aged_page(f"page-{tail[0]}", "Failed", 40),
        _aged_page(f"page-{tail[1]}", "In progress", 40),
        _aged_page(f"page-{tail[2]}", "Blocked", 40),
        _aged_page(f"page-{tail[3]}", "Blocked", 40),
        _aged_page(f"page-{tail[4]}", "Blocked", 3),
    ]
    names = ["failed", "running", "dirty", "unpushed", "young", "gone", "stray"]
    places = {
        name: _aged(state_home / "worktrees" / f"app-{owner}", 3 if name == "young" else 40)
        for name, owner in zip(names, tail, strict=True)
    }
    # Not a worktree any repository knows: not ours to guess about.
    (places["stray"] / "notes.txt").write_text("x")
    branches: list[str] = []

    def dirty(path):
        return path.name.endswith(tail[2])

    def unpushed(path):
        return 2 if path.name.endswith(tail[3]) else 0

    def repository_of(path):
        return None if path.name.endswith(tail[6]) else state_home

    with _git_answering(
        repository_of=repository_of,
        is_dirty=dirty,
        unpushed=unpushed,
        current_branch=lambda path: f"ticket/{path.name}",
        remove_worktree=lambda _repo, path: shutil.rmtree(path),
        delete_branch=lambda _repo, branch: branches.append(branch),
    ):
        _tidying(pages, "[runner]\nlog_retention_days = 0\n").tidy()
        gone = {name for name, path in places.items() if not path.exists()}
        assert gone == {"failed", "gone"}, gone
        assert sorted(branches) == [f"ticket/app-{tail[0]}", f"ticket/app-{tail[5]}"]
        # A ticket still in progress, and every one when it is turned off.
        again = _aged(state_home / "worktrees" / f"app-{tail[0]}", 40)
        _tidying(pages, "[runner]\nstale_worktree_days = 0\n").tidy(now=True)
        assert again.exists()
        # Nothing is guessed from a board that was not read.
        _tidying([]).tidy(now=True)
        assert again.exists()


@case
def a_low_disk_tidies_first_then_starts_nothing_and_leaves_the_ticket_in_ready():
    from ponos import resources

    runner = _tidying([])
    runner.dry_run = False
    runner._memory_warned, runner._disk_warned, runner._disk_tidied = False, False, 0.0
    runner.config.runner.min_free_memory_mb = 0
    runner.config.runner.min_free_disk_mb = 5000
    said: list[str] = []
    tidied: list[bool] = []
    runner.say = said.append
    runner.tidy = lambda now=False: tidied.append(now)
    runner._notify = lambda *args, **kwargs: said.append("notified")
    original = resources.disk_mb
    try:
        resources.disk_mb = lambda path: (1000, 100000)
        assert not runner.room_for_a_session() and not runner.room_for_a_session()
        assert tidied == [True], "one tidy, not one per place"
        assert sum("1000" in line for line in said) == 1 and "notified" in said, said
        resources.disk_mb = lambda path: (9000, 100000)
        assert runner.room_for_a_session()
        runner.config.runner.min_free_disk_mb = 0
        resources.disk_mb = lambda path: (1, 100000)
        assert runner.room_for_a_session(), "zero switches the guard off"
        # A tidy that freed the room is the whole answer: the ticket starts.
        runner.config.runner.min_free_disk_mb = 5000
        runner._disk_tidied = 0.0
        measures = iter([(1000, 100000), (8000, 100000)])
        resources.disk_mb = lambda path: next(measures)
        assert runner.room_for_a_session()
    finally:
        resources.disk_mb = original


@case
def a_worktree_is_made_without_the_excluded_folders_and_the_main_checkout_keeps_them():

    assert git_module.exclusions(" docs/media/, ,assets ") == ["docs/media", "assets"]
    with tempfile.TemporaryDirectory() as home:
        repo, path = Path(home) / "repo", Path(home) / "worktrees" / "site-9d2cb790"
        for step in (
            ["init", "-q", "-b", "main"],
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
        ):
            assert (
                git_module.git(step, repo.mkdir() or repo).ok
                if step[0] == "init"
                else git_module.git(step, repo).ok
            )
        (repo / "docs" / "media").mkdir(parents=True)
        (repo / "docs" / "media" / "promo.mp4").write_text("big")
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("x")
        assert git_module.git(["add", "."], repo).ok
        assert git_module.git(["commit", "-qm", "first"], repo).ok
        git_module.add_worktree(repo, path, "ticket/x-9d2cb790", "main", ["docs/media"])
        assert (path / "src" / "a.py").exists() and not (path / "docs" / "media").exists()
        assert not git_module.is_dirty(path), "an excluded folder is not a deletion"
        assert (repo / "docs" / "media" / "promo.mp4").exists()
        assert git_module.git(["status", "--porcelain"], repo).out == ""
        other = Path(home) / "worktrees" / "site-aaaaaaaa"
        git_module.add_worktree(repo, other, "ticket/y-aaaaaaaa", "main")
        assert (other / "docs" / "media" / "promo.mp4").exists(), (
            "nothing excluded, everything checked out"
        )


@case
def the_console_measures_the_disk_and_cleans_only_between_runs(state_home):

    _aged(state_home / "scratch" / "notes-1a2b3c4d", 30)
    console = web_api.Api.__new__(web_api.Api)
    console._config = _config("")
    console._stamp = web_base._stamp(console._config.path)
    console._runner = _tidying([_aged_page("page-1a2b3c4d", "Done", 30)])
    measured = console.disk()
    assert measured["sizes"]["scratch"] >= 1000 and measured["retention_days"] == 14
    with state.lock():
        try:
            console.clean()
        except RuntimeError as error:
            assert "run is in progress" in str(error)
        else:
            raise AssertionError("a tidy ran under a pass")
    cleaned = console.clean()
    assert cleaned["removed"] == 1 and cleaned["sizes"]["scratch"] == 0, cleaned


@case
def a_ticket_that_never_ran_gets_its_branch_drawn_fresh():
    made, commands = _worktree_for()
    assert voice.Voice().branch_note(made) == "", "nothing happened worth telling anyone about"
    assert not made.reused
    assert commands[-1][:4] == ["worktree", "add", "-b", "ticket/le-header-9d2cb790"]
    assert not any(command[:1] == ["rebase"] for command in commands)


@case
def a_branch_left_by_an_earlier_attempt_is_picked_up_and_replayed():
    """The failure this whole thing exists to stop.

    A branch is named after the ticket's ID, so every attempt asks for the same
    one: a session that failed, or a pull request nobody merged, used to leave a
    branch that refused that ticket for ever — “already exists — ticket already
    handled?” on every pass, until somebody ran `clean` by hand. It is checked
    out again and rebased onto the newest base instead.
    """
    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"), commits=2
    )
    assert made.reused, "the push that follows is not a fast-forward any more"
    note = voice.Voice().branch_note(made)
    assert "2 commit(s)" in note and "rebased onto `origin/main`" in note
    said = voice.Voice("fr").branch_note(made)
    assert said.startswith("La branche `ticket/le-header-9d2cb790` existait déjà"), said
    assert "rejouée sur `origin/main`" in said, "and the comment says it in its own voice"
    added = _one(commands, ["worktree", "add"])
    assert added[-1] == "ticket/le-header-9d2cb790", "checked out, not drawn again"
    assert "-b" not in added
    assert commands[-1] == ["rebase", "--autostash", "origin/main"]


@case
def a_branch_that_only_exists_on_origin_comes_back_with_its_commits():
    """A push that landed and a run that died after it: the work is on origin.

    Checking out a fresh branch of the same name would silently drop it — and
    the pull request open on it would sit there, describing commits nobody can
    see any more.
    """
    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/remotes/origin/ticket/le-header-9d2cb790"), commits=1
    )
    assert made.reused
    note = voice.Voice().branch_note(made)
    assert "it was pushed but never merged" in note
    added = _one(commands, ["worktree", "add"])
    assert added[:4] == ["worktree", "add", "--track", "-b"]
    assert added[-1] == "origin/ticket/le-header-9d2cb790"


@case
def a_worktree_kept_for_a_post_mortem_is_worked_in_again():
    """`keep_worktree_on_failure` leaves the directory *and* the branch in it.

    Nothing needs creating there — the branch is already checked out where the
    ticket wants it. Asking git for it again would only be told that it is.
    """

    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"),
        held_here=True,
        path_exists=True,
    )
    assert isinstance(made, git_module.Worktree) and made.reused
    note = voice.Voice().branch_note(made)
    assert "its worktree was still there" in note
    assert not any(command[:2] == ["worktree", "add"] for command in commands)
    assert commands[-1] == ["rebase", "--autostash", "origin/main"]


@case
def a_branch_held_by_another_worktree_is_never_taken_from_it():
    """The one case that still stops the ticket, and it should.

    Two runs of the same ticket at once, or a worktree kept somewhere else: what
    is in there is someone's work in progress, and moving its branch out from
    under it would break both. The message says where it is and how to let go.
    """

    made, _commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"),
        held="/somewhere/else",
    )
    assert isinstance(made, git_module.GitError)
    assert "/somewhere/else" in str(made) and "worktree remove" in str(made)


@case
def a_rebase_that_conflicts_is_undone_and_the_session_runs_anyway():
    """A conflict is not a reason to refuse the ticket a second time.

    The branch goes back to exactly what it was — an agent that opened on a
    half-applied rebase would spend its session resolving somebody else's merge
    — the session runs on it, and the comment says what it is behind on.
    """
    made, commands = _worktree_for(
        refs=("main", "origin/main", "refs/heads/ticket/le-header-9d2cb790"),
        commits=1,
        rebase="src/app.py",
    )
    assert made.reused
    note = voice.Voice().branch_note(made)
    assert "reused as it stands" in note and "src/app.py" in note
    assert commands[-1] == ["rebase", "--abort"], "nothing is left half-applied"


@case
def a_replay_still_happens_where_git_has_no_identity_of_its_own():
    """The CI runner, the container, the server nobody configured.

    A rebase writes commits, and git refuses to write one where it cannot tell
    who is writing. The replay failed there for that, the failure read as the
    branch refusing to move, and the ticket landed in Blocked saying the pull
    request would not merge — true, and not the reason. The identity is a
    fallback: a machine that has one of its own keeps committing under it.
    """

    with tempfile.TemporaryDirectory() as home:
        repo = Path(home) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)

        bare = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        with _patched_environ(bare):
            lent = git_module.identity(repo)
            assert lent["GIT_COMMITTER_EMAIL"], "a machine with no identity is lent one"
            assert lent["GIT_AUTHOR_NAME"] == lent["GIT_COMMITTER_NAME"]

            subprocess.run(
                ["git", "config", "user.email", "someone@example.invalid"], cwd=repo, check=True
            )
            assert git_module.identity(repo) == {}, "an identity of its own is left alone"


@contextmanager
def _patched_environ(values):
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@case
def a_repository_is_worked_under_the_account_its_owner_names():
    """Two GitHubs on one machine, and the command that goes out as the right one.

    Everything the runner asks `gh` about a repository — its name, its pull
    request, its merge — has to go out as the account that can see it. What
    designates it is the owner, read off whatever the caller has in hand: a
    remote, a pull request URL, or `owner/name` as a project page spells it.
    """

    for reference in (
        "https://github.com/Northwind/site/pull/12",
        "git@github.com:northwind/site.git",
        "https://github.com/northwind/site",
        "northwind/site",
    ):
        assert git_module.owner(reference) == "northwind", reference
    assert git_module.owner("site") == "", "a name alone designates no owner"

    asked: list[str] = []

    def token(account: str) -> str:
        asked.append(account)
        return f"gho-{account}" if account != "nobody" else ""

    accounts = {"northwind": "dev-northwind", "hermez-agency": "hermez-bot"}
    with _git_answering(account_token=token):
        assert git_module.token_for("northwind/site", accounts) == "gho-dev-northwind"
        assert (
            git_module.token_for("https://github.com/hermez-agency/x/pull/1", accounts)
            == "gho-hermez-bot"
        )
        # An owner nobody named, and a machine that names nobody: both are the
        # account `gh` is signed in as, which is what one GitHub always did.
        assert git_module.token_for("someone-else/x", accounts) == ""
        assert git_module.token_for("northwind/site", {}) == ""
        # And an account `gh` is not signed in as is not a ticket's problem:
        # `doctor` says so, the command runs as whoever is active.
        assert git_module.token_for("x/y", {"x": "nobody"}) == ""
    assert asked == ["dev-northwind", "hermez-bot", "nobody"], asked


@case
def a_gh_call_about_a_repository_carries_that_account_and_nothing_else():
    """The token reaches the command, and only through the environment.

    `GH_TOKEN` is what `gh` reads before anything on disk — and what the
    credential helper it installs reads too, which is how the push and the pull
    request that follows it go out as the same account.
    """

    seen: list[dict] = []

    class _Done:
        returncode, stdout, stderr = 0, "OPEN", ""

    def fake(args, cwd=None, capture_output=True, text=True, timeout=300, env=None):
        seen.append({"args": list(args), "env": env})
        return _Done()

    # `gh` is looked for before it is asked anything: a machine without it —
    # a CI runner, most of all — would otherwise skip the very call under test.
    original, original_which = git_module.subprocess.run, git_module.shutil.which
    git_module.subprocess.run = fake
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        with _git_answering(account_token=lambda account: "gho-secret"):
            git_module.pull_request_state(
                "https://github.com/northwind/site/pull/3", {"northwind": "dev-northwind"}
            )
            git_module.pull_request_state("https://github.com/x/y/pull/3", {})
    finally:
        git_module.subprocess.run = original
        git_module.shutil.which = original_which

    assert seen[0]["env"]["GH_TOKEN"] == "gho-secret"
    assert seen[0]["env"]["GITHUB_TOKEN"] == "gho-secret"
    assert "--json" in seen[0]["args"], seen[0]["args"]
    assert seen[1]["env"] is None, "no account named, no environment touched"


@case
def only_a_merge_a_rebase_could_answer_is_retried():
    """A refusal about the branch, told apart from a refusal about the work.

    A base branch that moved is what replaying answers. A check still red, a
    review still missing, a branch whose policy forbids this merge: pushing the
    branch again would spend a CI run to be refused in the same words.
    """

    for refusal in (
        "gh pr merge: Pull request is not mergeable: the merge commit cannot be cleanly created",
        "GraphQL: Base branch was modified. Review and try the merge again.",
        "the head branch is out of date",
    ):
        assert git_module.is_behind(refusal), refusal
    for refusal in (
        "gh pr merge: Pull request is not mergeable: the base branch policy prohibits the merge",
        "GraphQL: 1 approving review is required by reviewers with write access",
        "Required status check “ci” is expected",
    ):
        assert not git_module.is_behind(refusal), refusal


@case
def a_merge_refused_for_being_behind_is_replayed_and_asked_again():
    """The gesture you would make by hand, and nobody should make ten times a day.

    A pull request opened this morning is behind by noon on a repository that
    takes ten tickets a day. The refusal is about the branch, not about the
    work, so the branch is replayed onto its base, pushed, and the merge is
    asked once more — and the ticket says so rather than coming back as a
    question.
    """

    runner = _board_runner([_reviewed("pbehind", "Validated", "https://github.com/x/y/pull/1")], {})
    runner.config.runner.rebase = True
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    attempts: list[str] = []
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        if len(attempts) == 1:
            raise git_module.GitError("gh pr merge: Pull request is not mergeable")
        return "merged"

    def replay(repo, branch, onto, workdir, accounts=None, settle=None) -> str:
        replayed.append((repo, branch, onto))
        return ""

    with (
        _state_home(),
        _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge),
        _git_answering(
            pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
            replay_pushed=replay,
        ),
    ):
        results = runner.deliver()

    assert len(attempts) == 2, "the merge was not asked again"
    assert replayed == [(Path("/repo"), "ticket/le-header-9d2cb790", "main")], replayed
    assert results[0]["status"] == "done", results
    said = runner.client.comments_written[-1]
    assert "replayed onto" in said, said


@case
def a_replay_pushed_on_a_repository_with_ci_is_not_merged_before_its_checks(state_home):
    """The commit just pushed has no check yet: an empty list is not a green one.

    GitHub takes a few seconds to declare the checks of a new head, and
    `merge_pull_request` read that silence as nothing red and nothing running —
    on a branch nobody protects, the replayed commit landed on `main` untested.
    So the ticket stays validated, and the next pass merges what CI has seen.
    """
    url = "https://github.com/x/y/pull/1"
    repo = state_home / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    runner = _board_runner([_reviewed("pfresh", "Validated", url)], {})
    runner.config.runner.rebase = True
    runner._project_of = lambda ticket: projects.Project("Site", repo)
    attempts: list[str] = []
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        if len(attempts) == 1:
            raise git_module.GitError("gh pr merge: Pull request is not mergeable")
        return "merged"

    with (
        _github({url: "OPEN"}, merge=merge),
        _git_answering(
            pull_request_branches=lambda url, accounts=None: ("ticket/x-9d2cb790", "main"),
            replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
        ),
    ):
        first = runner.deliver()
        assert len(replayed) == 1 and len(attempts) == 1, (replayed, attempts)
        assert first == [], "merged in the same breath as the push"
        second = runner.deliver()

    assert len(replayed) == 1, "the next pass replays nothing GitHub did not refuse"
    assert second[0]["status"] == "done", second


@case
def a_merge_refused_for_anything_else_is_still_a_question():
    """Nothing is pushed again to answer a review that has not happened."""

    runner = _board_runner([_reviewed("preview", "Validated", "https://github.com/x/y/pull/1")], {})
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        raise git_module.GitError("gh pr merge: 1 approving review is required")

    with (
        _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge),
        _git_answering(
            replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
        ),
    ):
        results = runner.deliver()

    assert not replayed, "a review that has not happened is not a stale branch"
    assert results[0]["status"] == "blocked", results


@case
def a_replay_that_conflicts_leaves_the_merge_refused():
    """The branch goes back as it was, and the ticket asks rather than guesses."""

    runner = _board_runner(
        [_reviewed("pconflict", "Validated", "https://github.com/x/y/pull/1")], {}
    )
    # Resolution off: what is under test is the replay giving up, as it did
    # before conflicts were handed to a session — and as it still does then.
    runner.config.runner.resolve_conflicts = False
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    attempts: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        raise git_module.GitError("gh pr merge: Pull request is not mergeable")

    with (
        _state_home(),
        _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=merge),
        _git_answering(
            pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
            replay_pushed=lambda *args, **kwargs: "CONFLICT (content): src/app.py",
        ),
    ):
        results = runner.deliver()

    assert len(attempts) == 1, "the merge is not asked again on a branch nothing moved"
    assert results[0]["status"] == "blocked", results


@case
def github_calling_a_pull_request_conflicting_is_heard_before_any_merge():
    """Asked first, rather than read in a refusal.

    A pull request GitHub already calls conflicting — or behind, on a
    repository that wants branches up to date — is replayed before the merge is
    asked at all: asking would only earn the refusal it has already announced.
    """

    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([_reviewed("pdirty", "Validated", url)], {})
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    attempts: list[str] = []
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        attempts.append(url)
        return "merged"

    with (
        _state_home(),
        _github({url: "OPEN"}, merge=merge, blockers={url: "BEHIND"}),
        _git_answering(
            pull_request_branches=lambda url, accounts=None: ("ticket/le-header-9d2cb790", "main"),
            replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
        ),
    ):
        results = runner.deliver()

    assert len(replayed) == 1 and len(attempts) == 1, (replayed, attempts)
    assert results[0]["status"] == "done", results

    for refusal in (
        "gh pr merge: GraphQL: Pull Request has merge conflicts (mergePullRequest)",
        "gh pr merge: the head branch is not up to date with the base branch",
    ):
        assert git_module.is_behind(refusal), refusal


@case
def a_replay_that_conflicts_is_handed_to_a_session_rather_than_to_you():
    """The conflict takes a place, like a publication; a project left out asks.

    Nothing is merged and nothing is blocked while the column is read: the
    ticket is named for a session — `_carry_out` — and the pass runs it at the
    next free place. A project named in `resolve_conflicts_except` keeps the
    old answer: the ticket asks.
    """
    url = "https://github.com/x/y/pull/1"
    for left_out, expected in (("", "session"), ("Autre, site ", "blocked")):
        runner = _board_runner([_reviewed("pconflict", "Validated", url)], {})
        runner.config.runner.resolve_conflicts_except = left_out
        runner.under_reserve = lambda: 0.0
        runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))

        def merge(url: str, method: str = "squash", accounts=None) -> str:
            raise AssertionError("a pull request GitHub calls conflicting is not merged as is")

        with (
            _state_home(),
            _github({url: "OPEN"}, merge=merge, blockers={url: "CONFLICTING"}),
            _git_answering(
                pull_request_branches=lambda url, accounts=None: (
                    "ticket/le-header-9d2cb790",
                    "main",
                ),
                replay_pushed=lambda *args, **kwargs: "CONFLICT in src/app.py",
            ),
        ):
            settled, sessions = runner.delivering()

        if expected == "session":
            assert not settled, settled
            assert [ticket.id for ticket, _ in sessions] == ["pconflict"], sessions
        else:
            assert not sessions, sessions
            assert settled[0]["status"] == "blocked", settled
            assert "src/app.py" in runner.client.comments_written[-1]


@case
def a_base_that_keeps_moving_is_replayed_twice_then_asked_about(state_home):
    """Two replays, and then a question rather than a third.

    A repository merging every ten minutes can move its base between the push
    and the merge, every time. The runner replays, pushes, is refused again —
    leaves the ticket validated for the next pass — and on the second refusal
    stops chasing: the ticket asks, and says why.
    """
    from ponos import delivery

    url = "https://github.com/x/y/pull/1"
    page = _reviewed("pmoving", "Validated", url)
    replayed: list[tuple] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:

        raise git_module.GitError("gh pr merge: Pull Request is not mergeable")

    passes = []
    for _ in range(3):
        runner = _board_runner([page], {"blocked": "Blocked"})
        runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
        with (
            _github({url: "OPEN"}, merge=merge),
            _git_answering(
                pull_request_branches=lambda url, accounts=None: ("ticket/x-9d2cb790", "main"),
                replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
            ),
        ):
            passes.append(runner.deliver())
        if passes[-1]:
            break

    assert len(replayed) == delivery.MOST_REBASES == 2, replayed
    assert passes[0] == [], "the first refusal leaves it validated for the next pass"
    assert passes[-1][0]["status"] == "blocked", passes
    said = runner.client.comments_written[-1]
    assert "2 times" in said and "`main`" in said, said


@case
def a_base_moved_by_the_runners_own_merges_is_not_held_against_the_ticket(state_home):
    """Ten pull requests validated on one repository: the queue is not "a base that keeps moving".

    Each merge the runner makes leaves the others behind. Between two replays
    of this ticket the runner merged a sibling into the same repository, so the
    replay is owed to its own queue and the count starts again: the ticket is
    replayed a third time and merged, not blocked. With nothing merged by the
    runner in between, the limit holds — see the case above.
    """
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("pqueued", "Validated", url)
    replayed: list[tuple] = []
    refusals = ["not mergeable"] * 5

    def merge(url: str, method: str = "squash", accounts=None) -> str:

        if refusals:
            raise git_module.GitError(f"gh pr merge: Pull Request is {refusals.pop()}")
        return "merged"

    runner = _board_runner([page], {"blocked": "Blocked"})
    runner._project_of = lambda ticket: projects.Project("Site", Path("/repo"))
    passes = []
    for sibling in (2, 3, 4):
        with (
            _github({url: "OPEN"}, merge=merge),
            _git_answering(
                pull_request_branches=lambda url, accounts=None: ("ticket/x-9d2cb790", "main"),
                replay_pushed=lambda *args, **kwargs: replayed.append(args) or "",
            ),
        ):
            passes.append(runner.deliver())
        if passes[-1]:
            break
        # A sibling of the same repository, merged by this runner meanwhile.
        runner._landed_in(f"https://github.com/x/y/pull/{sibling}")

    assert len(replayed) == 3, (replayed, passes)
    assert passes[-1][0]["status"] == "done", passes


def _reading_checks(
    verdicts: list[str],
    failing: list[list[str]],
    on_base: list[str],
    rerun: bool = True,
    unstarted: str = "",
):
    """`_checked` against a CI that answers `verdicts` in turn, and what it was asked."""
    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([], {})
    asked: list[str] = []
    verdicts, failing = list(verdicts), list(failing)

    def wait(url, worktree, minutes, accounts=None):
        asked.append("wait")
        return verdicts.pop(0)

    def again(url, accounts=None):
        asked.append("rerun")
        return rerun

    with _git_answering(
        wait_for_checks=wait,
        failing_checks=lambda url, accounts=None: failing.pop(0) if failing else [],
        unstarted_checks=lambda url, accounts=None: unstarted,
        rerun_failed_checks=again,
        failing_on=lambda url, base, accounts=None: asked.append(f"base {base}") or on_base,
    ):
        checks, said = runner._checked(
            ticket_module.Ticket(_reviewed("t-1", "In progress", "")), url, Path("/work"), "main"
        )
    return checks, said, asked


@case
def a_check_that_goes_green_once_run_again_is_a_flake_not_a_question():
    """The failed jobs are run again once, and the second verdict is the one kept."""
    checks, said, asked = _reading_checks(["failed", "passed"], [["frontend"]], [])
    assert checks == "passed", checks
    assert asked == ["wait", "rerun", "wait"], asked
    assert "`frontend`" in said and "flaky" in said, said

    checks, said, asked = _reading_checks(["passed"], [], [])
    assert (checks, asked) == ("passed", ["wait"]), "a green CI is not run again"


@case
def a_check_main_fails_too_is_the_bases_red_and_not_the_pull_requests():
    """Red twice, but red on the base as well: not the pull request's doing."""
    checks, said, asked = _reading_checks(
        ["failed", "failed"], [["frontend"], ["frontend"]], ["frontend", "core (3.11)"]
    )
    assert checks == "base-red", checks
    assert asked == ["wait", "rerun", "wait", "base main"], asked
    assert "`frontend`" in said and "`main`" in said, said


@case
def a_check_red_only_here_still_stops_the_merge_and_is_named():
    """The one red that is a question — and it says which checks, not “CI: red”."""
    checks, said, _ = _reading_checks(
        ["failed", "failed"], [["frontend"], ["core (3.11)", "frontend"]], ["frontend"]
    )
    assert checks == "failed", "one check red on main does not excuse another"
    assert "`core (3.11)`" in said and "`main`" in said, said

    # Nothing to run again (a check another app posts) and nothing gh can name:
    # red, as before — never green for want of knowing.
    checks, said, asked = _reading_checks(["failed"], [[]], ["frontend"], rerun=False)
    assert checks == "failed" and said == "CI: red.", (checks, said)
    assert asked == ["wait", "rerun"], asked


_NOT_STARTED = (
    "The job was not started because recent account payments have failed or your "
    "spending limit needs to be increased."
)


@case
def a_ci_github_never_started_is_said_as_such_and_not_run_again():
    """Red in two seconds, every job refused by GitHub's billing: nothing ran.

    It used to read “its checks fail” on every pull request of a private
    repository, and a forced merge stopped there without saying the one thing
    that mattered — not the code, the account. Running the jobs again would be
    refused the same way, so it is not asked.
    """
    checks, said, asked = _reading_checks(
        ["failed"], [["Tests", "Lint"]], [], unstarted=_NOT_STARTED
    )
    assert checks == "unstarted", checks
    assert asked == ["wait"], "neither run again nor compared with the base"
    assert "did not start" in said and "spending limit" in said, said


@case
def a_forced_merge_says_on_the_ticket_why_the_ci_stopped_it():
    """The sentence `_checked` wrote, not a generic “its checks fail”."""
    from types import SimpleNamespace

    url = "https://github.com/x/y/pull/1"
    for checks, sentence in (
        ("failed", "CI: red on `core (3.11)`, where `main` is not."),
        ("unstarted", f"CI: did not start — GitHub says: {_NOT_STARTED}"),
    ):
        runner = _board_runner([], {})
        runner._checked = lambda ticket, url, workdir, base, said=(checks, sentence): said
        job = SimpleNamespace(
            ticket=SimpleNamespace(id="p-forced"), workdir=Path("/work"), base="main"
        )
        merges: list[str] = []
        with (
            _state_home(),
            _github({}, merge=lambda *args, merges=merges, **kept: merges.append(args) or "merged"),
        ):
            why, later = runner._force_merge(job, url)
        assert (why, later, merges) == (sentence, False, []), (checks, why, later, merges)


@case
def an_older_gh_reads_the_checks_from_the_pull_request_itself():
    """`gh pr checks --json` is gh 2.48 and later; Ubuntu ships 2.46.

    Without the fallback every check read as unknown on such a machine — no
    names, nothing run again, no comparison with the base, and nothing the
    console could show — and a forced merge only ever said “its checks fail”.
    """

    rollup = {
        "statusCheckRollup": [
            {
                "__typename": "CheckRun",
                "name": "Tests",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "detailsUrl": "https://github.com/x/y/actions/runs/38/job/116",
            },
            {
                "__typename": "CheckRun",
                "name": "Lint",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://github.com/x/y/actions/runs/38/job/117",
            },
            {
                "__typename": "CheckRun",
                "name": "Build",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": "https://github.com/x/y/actions/runs/38/job/118",
            },
            {
                "__typename": "StatusContext",
                "context": "GitGuardian",
                "state": "SUCCESS",
                "targetUrl": "https://dashboard.gitguardian.com",
            },
        ]
    }
    annotations = {"116": _NOT_STARTED, "117": ""}
    asked: list[list[str]] = []

    def run(args, *rest, **kept):
        asked.append(args)
        if args[:3] == ["gh", "pr", "checks"]:
            return git_module.Result(1, "", "unknown flag: --json\n\nUsage:  gh pr checks")
        if args[:3] == ["gh", "pr", "view"] and "statusCheckRollup" in args:
            return git_module.Result(0, json.dumps(rollup), "")
        if args[:2] == ["gh", "api"]:
            job = next(part for part in args if "check-runs/" in part).split("/")[-2]
            return git_module.Result(0, annotations.get(job, ""), "")
        return git_module.Result(1, "", "")

    original_which = shutil.which
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        with _git_answering(run=run, token_for=lambda reference, accounts=None: ""):
            url = "https://github.com/x/y/pull/1"
            listed = git_module.checks(url)
            assert [(one["name"], one["bucket"]) for one in listed] == [
                ("Tests", "fail"),
                ("Lint", "pass"),
                ("Build", "pending"),
                ("GitGuardian", "pass"),
            ], listed
            assert listed[0]["link"].endswith("/actions/runs/38/job/116"), listed[0]
            assert git_module.failing_checks(url) == ["Tests"]
            assert git_module.unstarted_checks(url) == _NOT_STARTED
            assert any(
                "repos/x/y/check-runs/116/annotations" in part for one in asked for part in one
            )

            # One red check that did run is enough: that red is the code's.
            rollup["statusCheckRollup"][1]["conclusion"] = "FAILURE"
            assert git_module.unstarted_checks(url) == ""
    finally:
        git_module.shutil.which = original_which


def _forcing(checks: str, refuses: str = "", blocker: str = "", options=None):
    """`_force_merge` after a CI that said `checks`: what it answered, and the merges asked."""
    from types import SimpleNamespace

    url = "https://github.com/x/y/pull/1"
    runner = _board_runner([], {}, options)
    runner._checked = lambda ticket, url, workdir, base: (checks, "")
    job = SimpleNamespace(ticket=SimpleNamespace(id="p-forced"), workdir=Path("/work"), base="main")
    merges: list[str] = []

    def merge(url: str, method: str = "squash", accounts=None) -> str:
        merges.append(url)
        if refuses:
            raise git_module.GitError(f"gh pr merge: {refuses}")
        return "merged"

    with _state_home(), _github({}, merge=merge, blockers={url: blocker} if blocker else {}):
        return runner._force_merge(job, url), merges


@case
def a_forced_merge_that_is_only_not_yet_is_left_to_the_validated_column():
    """Behind, conflicting, CI still running: postponed, never a question in review."""
    (why, later), merges = _forcing("passed", refuses="Head branch is out of date")
    assert later and "out of date" in why and len(merges) == 1, (why, later, merges)

    (why, later), merges = _forcing("pending", refuses="the base branch policy prohibits the merge")
    assert later and "still running" in why, (why, later)

    # GitHub already says so: not even asked.
    (why, later), merges = _forcing("passed", blocker="CONFLICTING")
    assert later and merges == [] and "conflicts with its base" in why, (why, later, merges)

    (why, later), _ = _forcing("passed")
    assert (why, later) == ("", False), "a merge that went through is not postponed"


@case
def a_forced_merge_that_is_a_question_still_waits_in_review():
    """Red here and only here, a rule of the branch, or no validated column to wait in."""
    (why, later), merges = _forcing("failed", blocker="BEHIND")
    assert not later and merges == [] and why == "its checks fail", (why, later, merges)

    (why, later), _ = _forcing("passed", refuses="the base branch policy prohibits the merge")
    assert not later and "policy" in why, (why, later)

    (why, later), merges = _forcing(
        "pending",
        refuses="Head branch is out of date",
        blocker="BEHIND",
        options=["In review", "Done"],
    )
    assert not later and len(merges) == 1, "without the column, nothing changes"


@case
def the_checks_gh_lists_are_read_into_names_and_runs_to_start_again():
    """`gh pr checks --json` and `gh run rerun`, as the runner asks them."""

    listed = [
        {
            "name": "frontend",
            "bucket": "fail",
            "link": "https://github.com/x/y/actions/runs/36840080436/job/110296847197",
        },
        {
            "name": "core (3.11)",
            "bucket": "pass",
            "link": "https://github.com/x/y/actions/runs/36840080436/job/110296847663",
        },
        {"name": "GitGuardian", "bucket": "fail", "link": "https://dashboard.gitguardian.com"},
    ]
    asked: list[list[str]] = []

    def run(args, *rest, **kept):
        asked.append(args)
        if args[:3] == ["gh", "pr", "checks"]:
            # Exit 1, as gh answers with a check red — and the list printed all the same.
            return git_module.Result(1, json.dumps(listed), "")
        if args[:2] == ["gh", "api"]:
            return git_module.Result(0, "frontend\nfrontend\n", "")
        return git_module.Result(0, "", "")

    original_which, original_sleep = shutil.which, git_module.time.sleep
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    git_module.time.sleep = lambda seconds: None
    try:
        with _git_answering(run=run, token_for=lambda reference, accounts=None: ""):
            url = "https://github.com/x/y/pull/1"
            assert git_module.failing_checks(url) == ["GitGuardian", "frontend"]
            assert git_module.rerun_failed_checks(url)
            assert [
                "gh",
                "run",
                "rerun",
                "36840080436",
                "--failed",
                "-R",
                "github.com/x/y",
            ] in asked
            assert len([one for one in asked if one[:3] == ["gh", "run", "rerun"]]) == 1
            assert git_module.failing_on(url, "main") == ["frontend"]
            assert any("repos/x/y/commits/main/check-runs" in part for one in asked for part in one)
        with _git_answering(
            run=lambda *args, **kept: git_module.Result(1, "unknown flag: --json", "")
        ):
            assert git_module.failing_checks("https://github.com/x/y/pull/1") == []
    finally:
        git_module.shutil.which = original_which
        git_module.time.sleep = original_sleep


_REPAIR_RUN = "https://github.com/x/y/actions/runs/7"


def _red_base(*, names=("frontend",)):
    """`gh`, answering that the newest commit of the base fails these checks."""
    return _git_answering(
        base_failures=lambda url, base, accounts=None: [(name, _REPAIR_RUN) for name in names],
        failing_on=lambda url, base, accounts=None: list(names),
    )


def _forced_on_red_base(runner, page, url):
    from types import SimpleNamespace

    runner._checked = lambda ticket, url, workdir, base: ("base-red", "")
    job = SimpleNamespace(
        ticket=ticket_module.Ticket(page),
        project=projects.Project("Site", Path("/repo")),
        workdir=Path("/work"),
        base="main",
    )
    merges: list[str] = []
    with _github({}, merge=lambda url, method="squash", accounts=None: merges.append(url)):
        return runner._force_merge(job, url), merges


@case
def a_red_base_sets_the_pull_request_aside_and_opens_one_repair_for_all_of_them(state_home):
    """Base red: no merge, no question, the card says so — and one ticket to repair it."""
    first, second = "https://github.com/x/y/pull/1", "https://github.com/x/y/pull/2"
    pages = [_reviewed("p1", "In progress", first), _reviewed("p2", "In progress", second)]
    with _red_base():
        runner = _board_runner(pages, {})
        (why, later), merges = _forced_on_red_base(runner, pages[0], first)
        assert later and merges == [] and "base is red" in why, (why, later, merges)
        assert state.waiting_for_base("p1") == ("main", first, ["frontend"])

        (why, later), merges = _forced_on_red_base(runner, pages[1], second)
        assert later and merges == [], (later, merges)
        assert state.waiting_for_base("p2")

    assert len(runner.client.created) == 1, runner.client.created
    title, values = runner.client.created[0]
    assert title == "Repair main of Site", title
    assert values["Status"] == "Ready" and values["Priority"] == 75, values
    assert "`frontend`" in runner.client.bodies[0] and _REPAIR_RUN in runner.client.bodies[0]


@case
def the_repair_of_a_base_is_a_high_priority_code_bug(state_home):
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    with _red_base():
        runner = _board_runner([page], {})
        _forced_on_red_base(runner, page, url)
    _, values = runner.client.created[0]
    assert values["Type"] == "Code" and values["Sous-type"] == "Bug", values
    assert values["Priority"] == 75, values


@case
def the_pull_request_of_a_repair_is_validated_without_waiting_for_a_review(state_home):
    """A repair opened by the runner is merged once green; any other code ticket still waits."""
    project = projects.Project("Site", Path("/repo"))
    runner = _board_runner([], {})
    other = ticket_module.Ticket(_reviewed("p-other", "In progress", ""))
    repair = ticket_module.Ticket(_reviewed("t-1", "In progress", ""))
    state.repairing("x/y", "main", "t-1")  # the board spells ids with dashes
    assert runner._forced("code", project, other) == ""
    assert runner._forced("code", project, repair)
    assert runner._forced("writing", project, repair) == ""


@case
def a_repair_that_is_done_is_followed_by_a_new_one_if_the_base_is_red_again(state_home):
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    with _red_base():
        runner = _board_runner([page], {})
        _forced_on_red_base(runner, page, url)
        runner.client._pages[-1].properties["Status"] = {
            "type": "status",
            "status": {"name": "Done"},
        }
        _forced_on_red_base(runner, page, url)
    assert len(runner.client.created) == 2, runner.client.created


@case
def a_green_base_with_a_red_pull_request_keeps_the_pull_request_blocked():
    """Base green, the red is the pull request's: today's behaviour, nothing set aside."""
    checks, said, _ = _reading_checks(["failed", "failed"], [["frontend"], ["frontend"]], [])
    assert checks == "failed", "red here and not on the base is still the pull request's"


def _repairing(heads: list[str], ok: bool = True, then: str = "passed", pushed: list | None = None):
    """`_mend` of a pull request red by its own fault: what it answered, and the sessions sent.

    `heads` is what the branch is on in turn — before the session, after it —
    and `then` what the CI says once the fix is pushed.
    """
    from types import SimpleNamespace

    from ponos import session as session_module

    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    runner = _board_runner([page], {})
    runner._body = lambda ticket: "Le titre est faux."
    runner._add_cost = lambda *args: None
    sessions: list[tuple] = []
    heads = list(heads)

    def work(job, template, phase="session", detail=""):
        sessions.append((job.body, template))
        return session_module.Outcome(
            ok=ok,
            blocked=not ok,
            session_id="s",
            summary="done" if ok else "unsure",
            log=Path("/log"),
            answer="- `settings.spec.ts` : locator exact\n\nRESULT: ok — x",
        )

    runner._run_session = work
    runner._checked = lambda ticket, url, workdir, base: (then, "CI: " + then)
    job = SimpleNamespace(
        ticket=ticket_module.Ticket(page),
        workdir=Path("/work"),
        base="main",
        branch="ticket/x",
    )
    job_copy = ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project("Site", Path("/repo")),
        branch="ticket/x",
        base="main",
        workdir=Path("/work"),
    )
    with (
        _state_home(),
        _git_answering(
            head=lambda workdir: heads.pop(0) if len(heads) > 1 else heads[0],
            failing_checks=lambda url, accounts=None: ["frontend"],
            failed_log=lambda url, accounts=None, most=6000: (
                "Error: locator resolved to 2 elements"
            ),
            pull_request_body=lambda url, accounts=None: "La PR.",
            rebasing=lambda workdir: False,
            is_dirty=lambda workdir: False,
            push_leased=lambda workdir, branch, was, accounts=None: (
                pushed.append((branch, was)) or ""
            ),
            comment_pull_request=lambda *args, **kwargs: None,
        ),
    ):
        pushed = [] if pushed is None else pushed
        first = runner._mend(job_copy, url, "CI: red.")
        second = runner._mend(job_copy, url, "CI: red.") if len(heads) else None
    del job
    return first, second, sessions, pushed


@case
def a_pull_request_red_by_its_own_fault_is_repaired_by_a_session_and_goes_on():
    """The log reaches the session; its fix is pushed on the branch; a green CI lets the merge go on."""
    from ponos import prompt as prompt_module

    (checks, said, outcome), _, sessions, pushed = _repairing(
        ["aaa", "bbb"], then="passed", pushed=[]
    )
    assert checks == "passed" and outcome is not None, (checks, said)
    assert pushed == [("ticket/x", "aaa")], pushed
    assert len(sessions) == 1 and sessions[0][1] is prompt_module.REPAIR, sessions
    brief = sessions[0][0]
    assert "`frontend`" in brief and "locator resolved to 2 elements" in brief, brief
    assert "locator exact" in said and "réparé" in said or "repaired" in said, said


@case
def a_pull_request_still_red_after_its_repair_is_blocked_once_without_a_second_session():
    """Red again after the fix: `failed` is returned, and the same red never costs two sessions."""
    pushed: list = []
    (checks, said, _), _, sessions, _ = _repairing(["aaa", "bbb"], then="failed", pushed=pushed)
    assert checks == "failed" and "still red" in said, (checks, said)
    assert len(sessions) == 1

    # The head the repair pushed, and the one it started from, are both spent.
    runner_heads = ["aaa", "bbb"]
    (_, _, _), second, sessions, _ = _repairing(["aaa", "bbb", "bbb"], then="failed", pushed=[])
    assert second is not None and second[0] == "failed" and second[2] is None, second
    assert len(sessions) == 1, "a second session was sent after the same red"
    del runner_heads


@case
def a_repair_that_answers_blocked_or_commits_nothing_pushes_nothing():
    (checks, said, outcome), _, sessions, pushed = _repairing(["aaa"], ok=False, pushed=[])
    assert checks == "failed" and outcome is not None and not pushed, (checks, pushed)
    assert "unsure" in said and "locator exact" in said, said

    (checks, said, _), _, sessions, pushed = _repairing(["aaa"], ok=True, pushed=[])
    assert checks == "failed" and not pushed and "committed nothing" in said, (said, pushed)


@case
def a_merge_that_took_a_repair_carries_its_cost_into_the_history(state_home):
    """The repair is paid on top of the merge: the line written for it says so."""
    from ponos import session as session_module

    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    runner = _board_runner([page], {})
    repair = session_module.Outcome(
        ok=True,
        blocked=False,
        session_id="s-repair",
        summary="",
        log=Path("/log"),
        seconds=30.0,
        cost_usd=0.4,
    )
    runner._checked = lambda ticket, url, workdir, base: ("failed", "CI: red.")
    runner._mend = lambda job, url, checked: ("passed", "CI: passed.", repair)
    job = ticket_module.Job(
        ticket_module.Ticket(page),
        projects.Project("Site", Path("/repo")),
        branch="ticket/x",
        base="main",
        workdir=Path("/work"),
    )
    with _git_answering(
        begin_replay=lambda repo, branch, base, workdir, settle=None: git_module.Replay(
            workdir, was="aaa", onto="bbb", conflicts=[]
        ),
        push_leased=lambda workdir, branch, was, accounts=None: "",
        comment_pull_request=lambda *args, **kwargs: None,
        merge_pull_request=lambda url, method="squash", accounts=None: "merged",
    ):
        done = runner._resolved(job, url)
    assert done is not None and done["status"] == "done", done
    assert done["cost_usd"] == 0.4, done


@case
def the_repair_attempts_of_a_ticket_are_kept_by_head_commit(state_home):
    assert not state.mended("p1", "aaa")
    state.mending("p1", "aaa")
    assert state.mended("p1", "aaa") and not state.mended("p1", "bbb")
    assert not state.mended("p2", "aaa")
    state.forget_mending("p1", "aaa")
    assert not state.mended("p1", "aaa")


@case
def a_pull_request_set_aside_waits_for_a_green_base_then_goes_on_its_own(state_home):
    """Still red: left alone, no merge asked. Green again: merged, and the card says so."""
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "Validated", url)
    merges: list[str] = []

    def merge(url, method="squash", accounts=None):
        merges.append(url)
        return "merged"

    state.wait_for_base("p1", "main", url, ["frontend"])
    runner = _board_runner([page], {})
    with (
        _github({url: "OPEN"}, merge=merge),
        _git_answering(failing_on=lambda url, base, accounts=None: ["frontend", "lint"]),
    ):
        assert runner.deliver() == [] and merges == []
        assert runner.client.comments_written == [], "waiting is not said again at every pass"
    with (
        _github({url: "OPEN"}, merge=merge),
        _git_answering(failing_on=lambda url, base, accounts=None: []),
    ):
        done = runner.deliver()
    assert merges == [url] and done[0]["status"] == "done", (merges, done)
    assert state.waiting_for_base("p1") is None
    assert any("green again" in text for text in runner.client.comments_written)


@case
def a_resolved_pull_request_on_a_red_base_goes_back_to_validated_without_a_question(state_home):
    url = "https://github.com/x/y/pull/1"
    page = _reviewed("p1", "In progress", url)
    with _red_base():
        runner = _board_runner([page], {})
        done = runner._left_for_base(
            ticket_module.Ticket(page),
            projects.Project("Site", Path("/repo")),
            url,
            "main",
            "record",
        )
        assert state.waiting_for_base("p1")
    assert done["status"] == "waiting" and done["reason"] == "merge.base-red", done
    status = [values["Status"] for _, values in runner.client.written if "Status" in values]
    assert status == ["Validated"], status
    assert "the base is red, it is not this pull request" in runner.client.comments_written[-1]
    assert "Repair main of Site" in runner.client.comments_written[-1]


@case
def the_failures_of_a_base_and_its_ci_at_push_are_read_from_gh():

    def answering(out, ok=True):
        return lambda args, *rest, **kept: git_module.Result(0 if ok else 1, out, "")

    original_which = shutil.which
    git_module.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        url = "https://github.com/x/y/pull/1"
        with _git_answering(
            run=answering("frontend\thttps://github.com/x/y/runs/1\nlint\t"),
            token_for=lambda reference, accounts=None: "",
        ):
            assert git_module.base_failures(url, "main") == [
                ("frontend", "https://github.com/x/y/runs/1"),
                ("lint", ""),
            ]
        repo = Path("/repo")
        for out, wanted in (
            ("[]", "none"),
            ('[{"conclusion": "skipped"}, {"conclusion": "skipped"}]', "skipped"),
            ('[{"conclusion": "skipped"}, {"conclusion": "failure"}]', "ran"),
            ("not json", ""),
        ):
            with _git_answering(
                run=answering(out),
                remote_url=lambda repo: "git@github.com:x/y.git",
                token_for=lambda reference, accounts=None: "",
            ):
                assert git_module.ci_at_push(repo, "main") == wanted, (out, wanted)
        with _git_answering(
            run=answering("", ok=False),
            remote_url=lambda repo: "git@github.com:x/y.git",
            token_for=lambda reference, accounts=None: "",
        ):
            assert git_module.ci_at_push(repo, "main") == "", "a question GitHub did not answer"
    finally:
        git_module.shutil.which = original_which


@case
def doctor_says_when_a_base_has_no_ci_at_push():
    from ponos import health

    with _git_answering(
        default_branch=lambda repo: "dev", ci_at_push=lambda repo, base, accounts=None: "none"
    ):
        assert "dev has no CI run at push" in health.base_without_ci(Path("/repo"))
    with _git_answering(
        default_branch=lambda repo: "dev", ci_at_push=lambda repo, base, accounts=None: "skipped"
    ):
        assert "only skipped" in health.base_without_ci(Path("/repo"))
    for found in ("ran", ""):
        with _git_answering(
            default_branch=lambda repo: "dev",
            ci_at_push=lambda repo, base, accounts=None, found=found: found,
        ):
            assert health.base_without_ci(Path("/repo")) == ""


@case
def a_resolution_report_is_what_the_session_wrote_above_its_verdict():
    from ponos import delivery

    answer = "- `a.py` : les deux gardés\nTests : verts.\n\n**RESULT: ok — résolu**"
    assert delivery._report_of(answer) == "- `a.py` : les deux gardés\nTests : verts."
    assert delivery._report_of("RESULT: ok — rien à dire") == ""


@case
def conflicts_are_resolved_everywhere_but_where_the_file_says_not():
    config = _config('[runner]\nresolve_conflicts_except = ["Northwind", "Site vitrine"]\n')
    assert config.runner.resolve_conflicts_except == "Northwind, Site vitrine"
    assert not config.runner.resolves_conflicts("site vitrine")
    assert config.runner.resolves_conflicts("Trader IA")
    assert (
        _config('[runner]\nresolve_conflicts_except = "Site"\n').runner.resolve_conflicts_except
        == "Site"
    )
    off = _config("[runner]\nresolve_conflicts = false\n").runner
    assert not off.resolves_conflicts("Trader IA")
    assert _config("[runner]\nchecks_timeout_minutes = -3\n").runner.checks_timeout_minutes == 0


@case
def a_directory_holding_work_is_not_cleared_to_make_room():
    """Uncommitted changes under the ticket's path outrank the ticket."""

    made, _commands = _worktree_for(commits=0, dirty=True, path_exists=True)
    assert isinstance(made, git_module.GitError)
    assert "still holds work" in str(made) and "clean --force" in str(made)


@case
def a_residue_that_cannot_be_deleted_is_moved_aside_and_the_worktree_is_made():
    """Files a container made as root: no right to delete them, still a ticket to run."""

    original = (git_module.shutil.rmtree, git_module.shutil.which)
    with tempfile.TemporaryDirectory() as home:
        root = Path(home)
        os.environ["XDG_STATE_HOME"] = str(root / "state")
        path = root / "worktrees" / "leadz-9d2cb790"
        (path / "vendor" / "lib").mkdir(parents=True)
        (path / "vendor" / "lib" / "a.php").write_text("x")
        (path / "vendor").chmod(0o500)  # nothing in it can be unlinked, as non-root
        try:
            # The deletion refused whatever the user is, and no Docker to ask.
            git_module.shutil.rmtree = lambda *_args, **_kept: None
            git_module.shutil.which = lambda _name: None
            aside = git_module.discard(path)
            assert not path.exists() and Path(aside).is_dir()
            assert Path(aside).parent == root / "state" / "ponos" / "leftovers"
            # Nothing but a directory git cannot be asked about: a fresh one is made.
            path.mkdir()
            made, _commands = _worktree_for(commits=0, path_exists=True)
            assert not isinstance(made, git_module.GitError)
        finally:
            git_module.shutil.rmtree, git_module.shutil.which = original
            os.environ.pop("XDG_STATE_HOME", None)
            for directory, _names, _files in os.walk(root):
                os.chmod(directory, 0o700)


@case
def a_residue_is_emptied_by_a_container_when_docker_is_there():

    sent: list[list[str]] = []
    original = (git_module.shutil.rmtree, git_module.shutil.which, git_module.run)
    with tempfile.TemporaryDirectory() as home:
        path = Path(home) / "leadz-9d2cb790"
        path.mkdir()
        (path / "var").mkdir()

        def docker(args, *_rest, **_kept):
            sent.append(list(args))
            original[0](path / "var")
            return git_module.Result(0, "", "")

        try:
            git_module.shutil.rmtree = lambda *_args, **_kept: None
            git_module.shutil.which = lambda _name: "/usr/bin/docker"
            git_module.run = docker
            assert git_module.discard(path) == ""
        finally:
            git_module.shutil.rmtree, git_module.shutil.which, git_module.run = original
        assert not path.exists()
    assert sent and sent[0][:2] == ["docker", "run"] and "sh" not in sent[0] and "-c" not in sent[0]
    assert sent[0][-5:] == ["find", "/w", "-mindepth", "1", "-delete"]


@case
def a_directory_with_a_git_is_never_a_residue():

    with tempfile.TemporaryDirectory() as home:
        worktrees = Path(home) / "worktrees"
        (worktrees / "real-11111111").mkdir(parents=True)
        (worktrees / "real-11111111" / ".git").write_text("gitdir: /elsewhere")
        (worktrees / "left-22222222" / "vendor").mkdir(parents=True)
        assert git_module.residues(worktrees) == [worktrees / "left-22222222"]
        assert git_module.discard(worktrees / "real-11111111") == ""
        assert (worktrees / "real-11111111" / ".git").exists()


@case
def clean_removes_a_residue_and_leaves_a_real_worktree():
    from ponos import __main__ as cli

    with tempfile.TemporaryDirectory() as home:
        root = Path(home)
        repo, worktrees = root / "repo", root / "ponos" / "worktrees"
        repo.mkdir()
        for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                cwd=repo,
                check=True,
                capture_output=True,
            )
        real = worktrees / "real-11111111"
        worktrees.mkdir(parents=True)
        subprocess.run(
            ["git", "worktree", "add", "-q", str(real)], cwd=repo, check=True, capture_output=True
        )
        (worktrees / "left-22222222" / ".phpunit.cache").mkdir(parents=True)
        kept = cli._clear_residues(sorted(worktrees.iterdir()))
        assert not (worktrees / "left-22222222").exists()
        assert (real / ".git").exists() and kept == [real]


@case
def only_a_replayed_branch_is_ever_force_pushed():
    """A rebase rewrites what origin already has, so the push stops being a

    fast-forward — and a ticket that came back with “the push was refused” for
    doing exactly what it was told to do would be the same dead end one step
    later. `--force-with-lease`, never `--force`: origin moving under us is
    still a refusal.
    """

    sent: list[list[str]] = []

    def fake(args, cwd, timeout=300, token=""):
        sent.append(list(args))
        return git_module.Result(0, "", "")

    with _git_answering(git=fake):
        git_module.push(Path("/nowhere"), "ticket/le-header-9d2cb790")
        git_module.push(Path("/nowhere"), "ticket/le-header-9d2cb790", force=True)
    # Only the pushes: a push also asks the worktree which remote it is on, to
    # know which GitHub account it goes out under.
    pushes = [args for args in sent if args[0] == "push"]
    assert "--force-with-lease" not in pushes[0]
    assert "--force-with-lease" in pushes[1] and "--force" not in pushes[1]
