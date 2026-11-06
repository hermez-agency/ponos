"""`cleanup.py`: clean, and the branch a failure leaves behind."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from support import _git_answering, _plain, _state_home, case

from ponos import git as git_module
from ponos import state
from ponos.__main__ import main as cli_main

# -- clean, and the branch a failure leaves behind ----------------------------


def _cleaning(worktrees: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    """Run `clean --force` over invented worktrees, and see which branches went.

    Each entry is a directory under `worktrees/`, and what git and gh would say
    of it: the branch it is on, whether that branch is pushed, the pull request
    `gh` finds on it, how many commits it has of its own, and whether anything
    in it was never committed.
    """

    deleted: list[str] = []
    with _state_home() as state_root, tempfile.TemporaryDirectory() as repository:
        repo = Path(repository)
        (repo / ".git").mkdir()
        root = state_root / "worktrees"
        root.mkdir(parents=True)
        for name in worktrees:
            (root / name).mkdir()
            # What a linked worktree carries, and what `clean` now asks for
            # before it lets any repository answer for a directory.
            (root / name / ".git").write_text(f"gitdir: {repo}/.git/worktrees/{name}\n")

        def facts(worktree: str | Path) -> dict[str, Any]:
            return worktrees[Path(worktree).name]

        def raw(args: list[str], cwd: Path, timeout: int = 300, **kept: Any) -> git_module.Result:
            if args[1:2] == ["--path-format=absolute"]:
                return git_module.Result(0, str(repo / ".git"), "")
            if args == ["worktree", "list", "--porcelain"]:
                listed = "\n".join(f"worktree {root / name}" for name in worktrees)
                return git_module.Result(0, f"worktree {repo}\n{listed}", "")
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return git_module.Result(0, facts(cwd)["branch"], "")
            raise AssertionError(f"clean asked git something unexpected: {args}")

        def delete(_repo: Path, branch: str) -> git_module.Result:
            deleted.append(branch)
            return git_module.Result(0, f"Deleted branch {branch}", "")

        pushed = {f"origin/{f['branch']}" for f in worktrees.values() if f.get("pushed")}
        requests = {f["branch"]: f.get("pull_request", "") for f in worktrees.values()}
        printed = io.StringIO()
        previous = os.environ.get("PONOS_CONFIG")
        os.environ["PONOS_CONFIG"] = str(repo / "nothing.toml")
        try:
            with (
                _git_answering(
                    git=raw,
                    default_branch=lambda _repo: "main",
                    has_ref=lambda _repo, reference: reference in {"main", "origin/main"} | pushed,
                    pull_request_on=lambda _repo, branch, accounts=None: requests.get(branch, ""),
                    commits_ahead=lambda worktree, _base: facts(worktree).get("commits", 0),
                    is_dirty=lambda worktree: facts(worktree).get("dirty", False),
                    remove_worktree=lambda _repo, worktree: shutil.rmtree(worktree),
                    delete_branch=delete,
                ),
                contextlib.redirect_stdout(printed),
            ):
                assert cli_main(["clean", "--force"]) == 0
        finally:
            if previous is None:
                os.environ.pop("PONOS_CONFIG", None)
            else:
                os.environ["PONOS_CONFIG"] = previous
    return _plain(printed.getvalue()), deleted


@case
def clean_leaves_the_worktree_of_a_session_in_flight_alone_while_the_daemon_runs(
    state_home: Path,
) -> None:
    """The daemon never lets go of its place, so `clean --force` cannot wait for it:
    what it spares is the worktree of a session written down for adoption."""
    going = state_home / "worktrees" / "app-1a2b3c4d"
    left = state_home / "worktrees" / "app-5e6f7a8b"
    going.mkdir(parents=True)
    left.mkdir(parents=True)
    state.track_session("s-1", "page-1a2b3c4d", {"pid": 1}, "")
    with state.scheduling(), contextlib.redirect_stdout(io.StringIO()):
        assert cli_main(["clean", "--force"]) == 0
    assert going.exists(), "a worktree was removed under a session in flight"
    assert not left.exists(), "and the daemon holding its place stops nothing else"


@case
def clean_force_does_not_list_the_worktree_of_a_ticket_in_progress(state_home: Path) -> None:
    """The trap of 6 November: `clean --force` stopped the processes of the
    session it was run beside, because it listed every worktree."""
    going = state_home / "worktrees" / "app-1a2b3c4d"
    left = state_home / "worktrees" / "app-5e6f7a8b"
    going.mkdir(parents=True)
    left.mkdir(parents=True)
    state.claim("page-1a2b3c4d", "progress")
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert cli_main(["clean", "--force"]) == 0
    assert going.exists(), "the claimed ticket's worktree was removed"
    assert not left.exists()


@case
def a_scratch_directory_never_speaks_for_the_repository_around_it() -> None:
    """`git rev-parse` in a directory that is no repository climbs to its
    parents — and the state directory may well sit inside one. `clean` would
    then prune that repository's worktrees and delete its branches."""

    with tempfile.TemporaryDirectory() as directory:
        outer = Path(directory) / "home"
        outer.mkdir()
        quiet: dict[str, Any] = {"capture_output": True, "check": True}
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(outer)], **quiet)
        identity = [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
        ]
        subprocess.run(
            ["git", *identity, "-C", str(outer), "commit", "--quiet", "--allow-empty", "-m", "one"],
            **quiet,
        )
        scratch = outer / ".local" / "state" / "ponos" / "scratch" / "deliver-1a2b3c4d"
        scratch.mkdir(parents=True)
        assert git_module.repository_of(scratch) is None, "a scratch directory is no worktree"

        cloned = scratch.parent / "cloned-1a2b3c4d"
        subprocess.run(["git", "init", "--quiet", str(cloned)], **quiet)
        assert git_module.repository_of(cloned) is None, "a clone made in one is not either"

        worktree = scratch.parent.parent / "worktrees" / "home-1a2b3c4d"
        subprocess.run(
            [
                "git",
                "-C",
                str(outer),
                "worktree",
                "add",
                "--quiet",
                "-b",
                "ticket/x",
                str(worktree),
            ],
            **quiet,
        )
        found = git_module.repository_of(worktree)
        assert found is not None and found.resolve() == outer.resolve(), found

        # A `.git` file that names a repository which does not list it back.
        (scratch / ".git").write_text(f"gitdir: {outer}/.git/worktrees/home-1a2b3c4d\n")
        assert git_module.repository_of(scratch) is None


@case
def clean_removes_the_branch_that_would_block_the_ticket_for_ever() -> None:
    """A branch name comes from the ticket's ID, so it is the same one every time.

    A session that failed without committing leaves the worktree and the branch;
    `add_worktree` then refuses that ticket for good. Removing the directory and
    leaving the branch — which is what `clean` used to do — changed nothing.
    """
    printed, deleted = _cleaning(
        {"trader-ia-16e26e94": {"branch": "ticket/ameliorer-la-doc-16e26e94"}}
    )
    assert deleted == ["ticket/ameliorer-la-doc-16e26e94"]
    assert "removed branch ticket/ameliorer-la-doc-16e26e94" in printed


@case
def clean_never_removes_a_branch_that_carries_something_of_its_own() -> None:
    """The refusal `clean` lifts is also what protects the previous session's work.

    A commit that was never pushed — the push failed, and the branch is all
    that is left of it — an open pull request, or a worktree with uncommitted
    changes: each of those stays, and the output says which and why, because
    that ticket is going to stay blocked until somebody looks at it.
    """
    printed, deleted = _cleaning(
        {
            "unpushed": {"branch": "ticket/ameliorer-la-doc-16e26e94", "commits": 1},
            "reviewed": {
                "branch": "ticket/le-header-9d2cb790",
                "pushed": True,
                "pull_request": "https://github.com/x/y/pull/12",
                "commits": 2,
            },
            "unsaved": {"branch": "ticket/le-bandeau-3ca45168", "dirty": True},
        }
    )
    assert deleted == []
    assert "ticket/ameliorer-la-doc-16e26e94 kept — 1 commit(s)" in printed
    assert "ticket/le-header-9d2cb790 kept — it is pushed" in printed
    assert "https://github.com/x/y/pull/12" in printed
    assert "ticket/le-bandeau-3ca45168 kept — the worktree has changes" in printed
    assert printed.count("branch -D ") == 3, "each kept branch says what is left to do"
