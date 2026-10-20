"""The little bit of git and gh the runner needs.

One rule, and it is not negotiable: **a ticket is never worked on in the main
repository**. Every ticket gets a `git worktree` on its own branch, which lets
two tickets of the same project move at once and leaves your working copy
exactly as you left it.

A second rule follows from the first: **a ticket that has run before is picked
up, not refused**. Its branch is named after its ID, so the branch a failed
session left behind is the same one the next attempt asks for — that branch is
checked out again and replayed on top of the newest base, rather than standing
in the way of the ticket for good.

A third holds for the `gh` half: **a repository is worked under the account it
belongs to**. One machine may answer to two GitHubs — your own and a client's —
and `gh` only ever has one of them active at a time, so a pull request on the
other one is refused for reasons that read like a bug. `[github]` in the
configuration says which owner is whose account, and every command that leaves
the machine is run with that account's token. A machine with one account
configures nothing and nothing changes: `gh` answers as whoever it is signed in
as, exactly as before. A GitHub App connected from the console comes before
both, for the owners it is installed on — see github_app.py. A personal access
token (github_token.py) takes the same door: after the App, or before it when
`[github_access] mode` says so.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import github_app, github_token
from .config import state_dir


class GitError(Exception):
    pass


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run(
    args: list[str],
    cwd: Path | str | None = None,
    timeout: int = 300,
    token: str = "",
    environment: dict[str, str] | None = None,
) -> Result:
    """One command, and the GitHub account it runs as when there is a choice.

    `token` is what makes a second account possible: `gh` reads `GH_TOKEN`
    before anything it has on disk, and so does the credential helper it
    installs — which is how a `git push` goes out under the same account as the
    pull request that follows it. Empty leaves the environment alone, and the
    command answers as whoever `gh` is signed in as.
    """
    extra = dict(environment or {})
    environment = {**os.environ, **extra} if extra else None
    if token:
        # Both names: `gh` prefers GH_TOKEN, and setting only that one would
        # leave a GITHUB_TOKEN inherited from elsewhere to answer for the tools
        # that read it instead.
        environment = {**(environment or os.environ), "GH_TOKEN": token, "GITHUB_TOKEN": token}
        # An app's token, or the machine's own, opens github.com over HTTPS,
        # and git asks for it there: told how by the environment, never by
        # `.git/config`.
        if github_app.issued(token) or github_token.holds(token):
            environment.update(github_app.git_environment(base=environment))
    try:
        process = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        # An answer like any other, and the one `timeout` itself gives: every
        # caller already knows what to do with a command that failed, and none
        # of them was written to catch this — a fetch that hung on a dead remote
        # used to take the whole pass down with it.
        said = _decoded(error.stderr) or _decoded(error.stdout)
        why = f"{' '.join(args[:3])}: timed out after {timeout}s"
        return Result(TIMED_OUT, _decoded(error.stdout), f"{why}\n{said}" if said else why)
    return Result(process.returncode, process.stdout.strip(), process.stderr.strip())


# What `timeout(1)` answers for a command it had to stop, and what `run` answers
# for one that outlived its own.
TIMED_OUT = 124


def _decoded(output: str | bytes | None) -> str:
    """What a stopped command had said, whichever type `subprocess` kept it as."""
    if isinstance(output, bytes):
        return output.decode(errors="replace").strip()
    return (output or "").strip()


def git(
    args: list[str],
    cwd: Path | str,
    timeout: int = 300,
    token: str = "",
    environment: dict[str, str] | None = None,
) -> Result:
    return run(["git", *args], cwd=cwd, timeout=timeout, token=token, environment=environment)


# Which GitHub account a repository is worked under, by the owner it belongs to:
# `[github]` in the configuration, read as `owner = "the gh account"`. An empty
# mapping is one account and the whole of the old behaviour.
Accounts = dict[str, str]

# Asked of `gh` once per account and kept: a token is not something that changes
# under a run, and a board with forty tickets would otherwise spawn forty `gh
# auth token` on the way to the same answer. A refusal is kept too, but only for
# a minute: the console lives for weeks, and a `gh auth login` typed after one
# failed lookup has to be heard without anybody restarting it.
_TOKENS: dict[str, tuple[str, float]] = {}
FAILED_TOKEN_SECONDS = 60


def reference_parts(reference: str) -> list[str]:
    """A repository reference cut into its path, the host first when it has one.

    The one reading of the shapes the runner holds — the `origin` of a clone
    (`git@github.com:owner/name.git`), the URL of a pull request, and what a
    project page declares (`owner/name`) — shared by `owner` and by the project
    index, so that the two can never disagree about where a name starts.
    """
    text = str(reference).strip().removesuffix(".git")
    text = re.sub(r"^[a-z]+://", "", text)  # https://github.com/owner/name
    text = re.sub(r"^[^@/]+@", "", text)  # git@github.com:owner/name
    return [part for part in text.replace(":", "/", 1).split("/") if part]


def owner(reference: str) -> str:
    """Who a repository belongs to, from a URL, a remote or `owner/name`.

    The three shapes the runner actually holds: the `origin` of a clone, the
    URL of a pull request, and what a project page declares.
    """
    parts = reference_parts(reference)
    if len(parts) < 2:
        return ""
    # A host is the part with a dot in it; `owner/name` has none.
    return parts[1].lower() if "." in parts[0] else parts[0].lower()


def account_token(account: str) -> str:
    """The token `gh` holds for that account, or nothing — see `token_for`."""
    held = _TOKENS.get(account)
    if held and (held[0] or time.monotonic() < held[1]):
        return held[0]
    result = (
        run(["gh", "auth", "token", "--user", account], timeout=60)
        if shutil.which("gh")
        else Result(1, "", "gh not found")
    )
    token = result.out if result.ok else ""
    _TOKENS[account] = (token, time.monotonic() + FAILED_TOKEN_SECONDS)
    return token


def token_for(reference: str, accounts: Accounts | None) -> str:
    """Which account that repository is worked under, as a token to run with.

    Nothing means "whoever `gh` is signed in as", and it means it for three
    different reasons on purpose: no account is configured at all, none is
    configured for that owner, or `gh` is not signed in as the one that is
    named. The first two are the ordinary machine, and the third is `doctor`'s
    to report — a ticket has no business failing over a line of configuration
    that names an account nobody logged in.

    Before any of it, a GitHub App installed on that owner or a personal access
    token, as `[github_access] mode` orders them (the App first when it does
    not): either wins over every `gh` account, since connecting it was the later
    decision.
    """
    if granted := github_token.for_owner(owner(reference)):
        return granted
    if not accounts:
        return ""
    account = accounts.get(owner(reference))
    return account_token(account) if account else ""


# What a repository named on a Notion page may look like before it reaches a
# command line: GitHub's own shape, `owner/name`, and nothing `gh` or `git`
# could read as an option, a path or a URL of somebody else's. A project page
# is anybody's to edit who can edit the board.
REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")


def is_repository(name: str) -> bool:
    """`name` is an `owner/name` that can be handed to `gh` and `git` as it is."""
    return bool(REPOSITORY.fullmatch(name)) and name.rsplit("/", 1)[-1] not in (".", "..")


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def remote_url(repo: Path) -> str:
    result = git(["remote", "get-url", "origin"], repo)
    return result.out if result.ok else ""


def clone(repository: str, into: Path, accounts: Accounts | None = None) -> None:
    """Fetch `owner/name` into a folder this machine does not have yet.

    Through `gh` when it is there, because that is already what knows how to
    reach a private repository — the same authentication the pull requests go
    out under. Plain HTTPS otherwise, which covers a public repository on a
    machine with no `gh` at all.

    Ten minutes, rather than the five a git command usually gets: this is the
    one that may be pulling down a repository's whole history over a domestic
    line, and a ticket refused because the clone was big is not a better
    outcome than a ticket that started late.
    """
    if not is_repository(repository):
        raise GitError(f"{repository!r} is not a GitHub repository name, owner/name — not cloned")
    into.parent.mkdir(parents=True, exist_ok=True)
    token = token_for(repository, accounts)
    # `--` before the name, whatever it was checked against: past it, nothing
    # is read as an option.
    if shutil.which("gh"):
        result = run(["gh", "repo", "clone", "--", repository, str(into)], timeout=600, token=token)
    else:
        result = run(
            ["git", "clone", "--", f"https://github.com/{repository}.git", str(into)],
            timeout=600,
            token=token,
        )
    if not result.ok:
        lines = [
            line.strip() for line in (result.err + "\n" + result.out).splitlines() if line.strip()
        ]
        why = lines[-1] if lines else "no reason given"
        raise GitError(f"{repository} could not be cloned into {into} — {why}")


def default_branch(repo: Path) -> str:
    """The branch the origin declares as default, else main/master."""
    result = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], repo)
    if result.ok and "/" in result.out:
        return result.out.rsplit("/", 1)[-1]
    for candidate in ("main", "master"):
        if git(["rev-parse", "--verify", "--quiet", candidate], repo).ok:
            return candidate
    result = git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    return result.out or "main"


def fetch(repo: Path) -> None:
    git(["fetch", "--quiet", "origin"], repo, timeout=180)


@dataclass
class Worktree:
    """What making the ticket's worktree took, when it took anything.

    `reused` says the branch was already there: whatever is under it now is a
    history the last attempt left, replayed, so the push that follows is no
    longer a fast-forward of what origin holds. Unset when the branch was drawn
    fresh — which is the ordinary case, and says nothing worth reading.

    The rest is what the ticket's comment says about it, as facts rather than
    as a sentence: `voice.Voice.branch_note` writes the sentence, in the
    language the run speaks. `why` is `held` (its worktree was still there),
    `left` (an earlier attempt left the branch) or `pushed` (on origin, never
    merged); `failure` is why it could not be replayed onto `start`, if it
    could not.
    """

    reused: bool = False
    branch: str = ""
    why: str = ""
    carried: int = 0
    start: str = ""
    failure: str = ""
    # The local branch an interrupted worktree was saved to before it was given
    # up — see `rescue`. Independent of `reused`: the ticket may have had no
    # branch of its own worth keeping, and the backup is still there to read.
    backup: str = ""


def _held_at(repo: Path, branch: str) -> str:
    """The worktree that has this branch checked out, as git spells the path."""
    result = git(["worktree", "list", "--porcelain"], repo)
    if not result.ok:
        return ""
    path = ""
    for line in result.out.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
        elif line == f"branch refs/heads/{branch}":
            return path
    return ""


def _same(one: str, other: Path) -> bool:
    try:
        return Path(one).resolve() == other.resolve()
    except OSError:  # a path nobody can resolve is not the one we are after
        return False


def identity(worktree: Path | str) -> dict[str, str]:
    """An identity for git on a machine that has none, nothing on one that has.

    A rebase writes commits, and git refuses to write one where it cannot tell
    who is writing — a CI runner, a container, a server nobody ever configured.
    The replay then fails on an identity, that failure reads as the branch
    refusing to move, and the ticket lands in Blocked saying the pull request
    would not merge. Which is true, and not the reason.

    Carried in the environment rather than as `-c` so the command stays the
    command, and a fallback rather than a rule: a machine with an identity of
    its own keeps committing under it, so the replay of your branch stays yours.
    The author of a replayed commit is git's to restore either way.
    """
    resolved = git(["config", "--get", "user.email"], worktree)
    if resolved.ok and resolved.out:
        return {}
    return {
        "GIT_AUTHOR_NAME": "ponos",
        "GIT_AUTHOR_EMAIL": "ponos@localhost",
        "GIT_COMMITTER_NAME": "ponos",
        "GIT_COMMITTER_EMAIL": "ponos@localhost",
    }


# What carries a stopped rebase as far as it can: given the worktree and the ref
# it is replayed onto, it says why it failed, or nothing. See generated.py.
Settle = Callable[[Path, str], str]


def rebase(worktree: Path, onto: str, settle: Settle | None = None) -> str:
    """Replay the branch on top of `onto`. Says why it could not, or nothing.

    `--autostash` because a worktree kept from a failed session usually holds
    changes that were never committed, and those are exactly what the next
    session is meant to carry on from — refusing to rebase over them would put
    us back where we started.

    A rebase that stops is aborted rather than left half-applied: an agent that
    opens on a conflicted index reads it as the state of the world and starts
    resolving somebody else's merge instead of doing the ticket. The branch goes
    back to what it was, the session runs on it, and the conflict is a line in
    the ticket's comment.

    `settle` is offered the rebase where it stops on a conflict, before it is
    given up on: what it settles by itself (see generated.py) is not a conflict
    worth abandoning the replay for. If it carries the rebase to its end, that
    is a replay like any other.
    """
    result = git(["rebase", "--autostash", onto], worktree, environment=identity(worktree))
    if result.ok:
        return ""
    if settle and conflicted(worktree):
        failure = settle(worktree, onto)
        if not rebasing(worktree):
            return failure
    # Read off the index rather than off what git printed: git speaks the
    # machine's language, and a `CONFLIT` is as much a conflict as a `CONFLICT`.
    unmerged = conflicted(worktree)
    git(["rebase", "--abort"], worktree)
    if unmerged:
        return f"CONFLICT in {', '.join(unmerged)}"
    lines = [line.strip() for line in (result.out + "\n" + result.err).splitlines() if line.strip()]
    conflict = next((line for line in lines if line.startswith("CONFLICT")), "")
    return conflict or (lines[0] if lines else f"git rebase {onto} failed")


def exclusions(setting: str) -> list[str]:
    """`runner.worktree_exclude` as the directories it names, slashes dropped."""
    names = (name.strip().strip("/") for name in setting.split(","))
    return [name for name in names if name]


def _leave_out(path: Path, exclude: list[str]) -> None:
    """Fill a worktree made with `--no-checkout`, minus the paths in `exclude`.

    Before the first file is written rather than after: the disk filled on a
    video being checked out, and checking it out to delete it would fail the
    same way. `sparse-checkout` is per worktree (git turns on
    `extensions.worktreeConfig` for it), so the main checkout keeps every file.
    """
    patterns = ["/*", *(f"!/{name}" for name in exclude)]
    for step in (
        ["sparse-checkout", "set", "--no-cone", *patterns],
        ["reset", "--hard", "-q", "HEAD"],
    ):
        result = git(step, path)
        if not result.ok:
            raise GitError(f"git {step[0]}: {result.err or result.out}")


def add_worktree(
    repo: Path, path: Path, branch: str, base: str, exclude: list[str] | None = None
) -> Worktree:
    """The ticket's worktree, on its own branch, off the latest state of `base`.

    A branch is named after the ticket's ID, so every attempt at one ticket asks
    for the same branch — and one left behind by a session that failed, or by a
    pull request nobody merged, used to refuse that ticket for good. Refusing is
    the wrong answer to "this ticket has run before": the branch is picked up
    instead, replayed on top of the newest base, and the session carries on from
    where the last one stopped. Nothing is thrown away to make room, and nothing
    that another worktree is holding is touched.

    `exclude` names directories the worktree is made without — see `_leave_out`.
    """
    start = base
    deferred = ["--no-checkout"] if exclude else []
    if git(["rev-parse", "--verify", "--quiet", f"origin/{base}"], repo).ok:
        start = f"origin/{base}"
    # Registrations for directories somebody deleted by hand: git still counts
    # those as holding their branch, and would refuse to check it out again.
    git(["worktree", "prune"], repo)
    backup = rescue(repo, path, branch)

    local = git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], repo).ok
    remote = git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], repo).ok
    path.parent.mkdir(parents=True, exist_ok=True)

    if not local and not remote:
        _make_room(repo, path, base)
        result = git(["worktree", "add", *deferred, "-b", branch, str(path), start], repo)
        if not result.ok:
            raise GitError(f"git worktree add: {result.err or result.out}")
        if exclude:
            _leave_out(path, exclude)
        return Worktree(backup=backup)

    held = _held_at(repo, branch)
    if held and not _same(held, path):
        raise GitError(
            f"branch {branch} is checked out in {held} — another attempt at this "
            f"ticket is either running or was kept for a post-mortem.\n"
            f"  git -C {repo} worktree remove {held}   once you are done with it"
        )
    if held:
        why = "held"
    else:
        _make_room(repo, path, base)
        add = (
            ["worktree", "add", *deferred, str(path), branch]
            if local
            else [
                "worktree",
                "add",
                *deferred,
                "--track",
                "-b",
                branch,
                str(path),
                f"origin/{branch}",
            ]
        )
        result = git(add, repo)
        if not result.ok:
            raise GitError(f"git worktree add: {result.err or result.out}")
        if exclude:
            _leave_out(path, exclude)
        why = "left" if local else "pushed"

    return Worktree(
        reused=True,
        branch=branch,
        why=why,
        carried=commits_ahead(path, base),
        start=start,
        failure=rebase(path, start),
        backup=backup,
    )


# What a worktree can be in the middle of, by the file git leaves in its git
# directory while it is: a rebase is a directory, the others a single file.
_OPERATIONS = (
    ("rebase", "rebase-merge"),
    ("rebase", "rebase-apply"),
    ("merge", "MERGE_HEAD"),
    ("cherry-pick", "CHERRY_PICK_HEAD"),
    ("revert", "REVERT_HEAD"),
)


def interrupted(worktree: Path) -> str:
    """What a worktree was left in the middle of — '' when it is in no such state.

    A rebase, a merge, a cherry-pick or a revert still under way, or a HEAD
    that is on no branch while files have changed: what a session killed while
    it resolved conflicts leaves. Any of those makes the worktree refuse the
    ticket for good — `_make_room` reads the changes as somebody's work — and
    `rebase` on top of a rebase only fails again.
    """
    found = git(["rev-parse", "--absolute-git-dir"], worktree)
    if found.ok and found.out:
        for name, marker in _OPERATIONS:
            if (Path(found.out) / marker).exists():
                return name
    if not git(["symbolic-ref", "--quiet", "HEAD"], worktree).ok and is_dirty(worktree):
        return "detached"
    return ""


def rescue(repo: Path, path: Path, branch: str) -> str:
    """Save an interrupted worktree to a branch, give it up, and say where it went.

    `ponos/backup/<id>-<date>`, made of everything the worktree holds — `git
    add -A` and a commit with no hook: a hook that fails on half-resolved
    conflicts is exactly the reason not to run one. Then the operation is
    abandoned and the worktree removed, so that the ticket's own branch — which
    git leaves untouched until a rebase ends — is checked out again as it was.

    Nothing is given up before the backup exists: a commit that cannot be made
    stops the ticket, and the worktree with it, rather than lose the work.
    Returns the branch's name, or '' when there was nothing to save.
    """
    if not (path / ".git").exists():
        return ""
    operation = interrupted(path)
    if not operation:
        return ""
    name = f"ponos/backup/{branch.rsplit('-', 1)[-1]}-{datetime.now():%Y%m%d-%H%M%S}"
    git(["add", "-A"], path)
    git(
        [
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--allow-empty",
            "-m",
            f"ponos: sauvegarde d'un worktree interrompu ({operation})",
        ],
        path,
        environment=identity(path),
    )
    saved = git(["branch", name, "HEAD"], path)
    if not saved.ok:
        raise GitError(
            f"{path} was interrupted in a {operation} and could not be saved: {saved.err}"
        )
    if operation != "detached":
        git([operation, "--abort"], path)
    remove_worktree(repo, path)
    return name


def _make_room(repo: Path, path: Path, base: str) -> None:
    """Clear the ticket's directory, unless what is in it is somebody's work.

    Only ever the leavings of an earlier attempt at this same ticket: the path
    is made of the project and the ticket's ID, and nothing else writes there.
    A worktree with commits of its own or changes never committed is not ours to
    remove, and it is the one case where the ticket still has to stop.
    """
    if not path.exists():
        return
    if (path / ".git").exists() and (commits_ahead(path, base) or is_dirty(path)):
        raise GitError(
            f"{path} still holds work from an earlier attempt.\n"
            "  ponos clean --force   removes it, and says so when it would not"
        )
    remove_worktree(repo, path)
    if path.exists():
        discard(path)


def repository_of(worktree: Path) -> Path | None:
    """The repository `worktree` is a linked worktree of — or None.

    Asked by `clean`, of every directory the runner left under its state
    directory, and the answer decides which repository has a worktree removed
    and a branch deleted. So nothing outside that directory is ever allowed to
    answer: a scratch directory is no repository at all, and `git rev-parse`
    run inside it would climb to whatever encloses it — the home directory
    under dotfiles, a repository the state directory happens to sit in — and
    `clean` would then go and prune *that*.

    Three things have to hold. The directory carries a `.git` *file*, which is
    what a linked worktree has and a scratch directory (or a clone somebody
    made inside one) does not; git is not allowed past the directory's parent;
    and the repository it names lists this very directory among its worktrees.
    """
    if not (worktree / ".git").is_file():
        return None
    common = git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        worktree,
        environment={"GIT_CEILING_DIRECTORIES": str(worktree.parent)},
    )
    if not common.ok or not common.out:
        return None
    repo = Path(common.out).parent
    listed = git(["worktree", "list", "--porcelain"], repo)
    if not listed.ok:
        return None
    for line in listed.out.splitlines():
        if line.startswith("worktree ") and _same(line.split(" ", 1)[1], worktree):
            return repo
    return None


def remove_worktree(repo: Path, path: Path) -> None:
    git(["worktree", "remove", "--force", str(path)], repo)
    if path.exists():
        try:
            discard(path)
        except GitError:
            pass  # still there: the next worktree asked for here says so, loudly
    git(["worktree", "prune"], repo)


# Where a directory nobody could empty is put aside. Not `tidied`: that name is
# the file `cleanup` stamps the day of its last pass with.
LEFTOVERS = "leftovers"

# Small enough to pull in seconds, and it has `find`.
DOCKER_IMAGE = "alpine"


def is_residue(path: Path) -> bool:
    """A directory that was a worktree and is now only what its containers wrote.

    No `.git` at its top: a worktree, a clone and anything git tracks has one,
    and none of those is ever ours to empty. `git worktree remove` takes the
    `.git` file first, so what is left is `vendor/`, `var/` and caches that a
    Docker container created as root — files the runner's own user cannot delete.
    """
    return path.is_dir() and not path.is_symlink() and not (path / ".git").exists()


def discard(path: Path) -> str:
    """Get `path` out of the way: "" when it is gone, else where it was moved to.

    Deleted when we can; when the files belong to somebody else (root, through a
    container), by a container that can, `find -delete` run with no shell so
    nothing in the directory's name is ever interpreted; and when there is no
    Docker either, moved aside — renaming needs the right to write the parent
    directory, not the files inside it, so it works where deleting cannot, and
    the ticket gets a fresh directory instead of a refusal. Returns "" for a
    directory with a `.git`, too, and leaves it exactly where it is.
    """
    if not is_residue(path):
        return ""
    shutil.rmtree(path, ignore_errors=True)
    if not path.exists():
        return ""
    if shutil.which("docker"):
        run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{path}:/w",
                DOCKER_IMAGE,
                "find",
                "/w",
                "-mindepth",
                "1",
                "-delete",
            ],
            timeout=600,
        )
        try:
            path.rmdir()
        except OSError:
            pass
        if not path.exists():
            return ""
    aside = state_dir() / LEFTOVERS
    aside.mkdir(parents=True, exist_ok=True)
    target = aside / f"{path.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        path.rename(target)
    except OSError:
        # Another filesystem, or nowhere to write: nothing better than saying so.
        raise GitError(f"{path} cannot be emptied or moved aside — remove it by hand") from None
    return str(target)


def residues(root: Path) -> list[Path]:
    """The directories under `root` that are only residue — see `is_residue`."""
    if not root.is_dir():
        return []
    return [directory for directory in sorted(root.iterdir()) if is_residue(directory)]


def has_ref(repo: Path, reference: str) -> bool:
    return git(["rev-parse", "--verify", "--quiet", reference], repo).ok


def delete_branch(repo: Path, branch: str) -> Result:
    """Drop a branch whose worktree has just been removed.

    Forced, because the caller has already established that the branch carries
    nothing of its own — and `--delete` alone answers a different question than
    the one that was asked: it compares the branch with whatever the main
    checkout happens to be sitting on, which is nobody's base branch in
    particular.
    """
    return git(["branch", "--delete", "--force", branch], repo)


def commits_ahead(worktree: Path, base: str) -> int:
    for reference in (f"origin/{base}", base):
        result = git(["rev-list", "--count", f"{reference}..HEAD"], worktree)
        if result.ok and result.out.isdigit():
            return int(result.out)
    return 0


def unpushed(worktree: Path) -> int:
    """Commits of this worktree that no remote-tracking branch holds.

    The question a worktree is asked before it is thrown away: its commits are
    safe if some remote has them, whatever the branch is called there. -1 when
    git cannot say, which no caller reads as "nothing to lose".
    """
    result = git(["rev-list", "--count", "HEAD", "--not", "--remotes"], worktree)
    return int(result.out) if result.ok and result.out.isdigit() else -1


def current_branch(worktree: Path) -> str:
    """The branch checked out in `worktree`, '' when HEAD is detached."""
    return git(["symbolic-ref", "--quiet", "--short", "HEAD"], worktree).out


def head(worktree: Path) -> str:
    """The commit that branch is on, as a way of noticing it was replayed."""
    return git(["rev-parse", "HEAD"], worktree).out


def is_dirty(worktree: Path) -> bool:
    return bool(git(["status", "--porcelain"], worktree).out)


def push(
    worktree: Path, branch: str, force: bool = False, accounts: Accounts | None = None
) -> Result:
    """Push the ticket's branch, forcing only when its history was replayed.

    `force` comes from the branch having been picked up from an earlier attempt
    and rebased: origin holds the version from before the rebase, so an ordinary
    push is refused as not being a fast-forward. `--force-with-lease` is what
    makes that safe to answer automatically — it still refuses if origin has
    moved since the fetch this run started with, which is the only case where
    somebody else's commit could be under there.
    """
    force_flag = ["--force-with-lease"] if force else []
    return git(
        ["push", "--set-upstream", *force_flag, "origin", branch],
        worktree,
        timeout=300,
        token=token_for(remote_url(worktree), accounts),
    )


def open_pull_request(
    worktree: Path, title: str, body: str, base: str, accounts: Accounts | None = None
) -> str:
    """Open the PR through gh and return its URL. Opening it merges nothing."""
    if not shutil.which("gh"):
        raise GitError("gh not found — cannot open the pull request")
    token = token_for(remote_url(worktree), accounts)
    result = run(
        ["gh", "pr", "create", "--base", base, "--title", title, "--body", body],
        cwd=worktree,
        timeout=180,
        token=token,
    )
    if result.ok:
        for line in reversed(result.out.splitlines()):
            if line.startswith("http"):
                return line.strip()
        return result.out
    existing = run(["gh", "pr", "view", "--json", "url", "-q", ".url"], cwd=worktree, token=token)
    if existing.ok and existing.out.startswith("http"):
        return existing.out
    raise GitError(f"gh pr create: {result.err or result.out}")


MERGE_FLAGS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}


def merge_pull_request(url: str, method: str = "squash", accounts: Accounts | None = None) -> str:
    """Merge that pull request through `gh`. Returns what `gh` said of it.

    The one outward-facing gesture the runner makes on its own — and it makes it
    only because it was asked twice: once by the ticket having a pull request at
    all, once by somebody moving that ticket into the validated column. Anything
    GitHub refuses — a conflict, a check still red, a review still required — is
    raised as it came, because the wording is the answer.

    `--auto` is deliberately not used: a merge that lands quietly twenty minutes
    later, when a check goes green, is a merge nobody watched.
    """
    if not shutil.which("gh"):
        raise GitError("gh not found — cannot merge the pull request")
    result = run(
        ["gh", "pr", "merge", url, MERGE_FLAGS.get(method, "--squash")],
        timeout=300,
        token=token_for(url, accounts),
    )
    if result.ok:
        return (result.out or f"merged ({method})").strip()
    raise GitError(f"gh pr merge: {result.err or result.out}")


# What GitHub says when the merge is refused *because the branch is no longer on
# top of its base* — the one refusal a rebase answers. A check still red, a
# review still missing, a branch protected: those are refusals about the work or
# about the rules, and replaying the branch would only push a second time for
# nothing. "policy" is excluded for that reason: it is the wording of a base
# branch that forbids this merge, not of one that has moved.
_BEHIND = (
    "not mergeable",
    "merge conflict",
    "base branch was modified",
    "head branch is out of date",
    "not up to date",
)


def is_behind(error: object) -> bool:
    """Is this refusal one that replaying the branch could answer?"""
    said = str(error).lower()
    return any(wording in said for wording in _BEHIND) and "policy" not in said


def pull_request_branches(url: str, accounts: Accounts | None = None) -> tuple[str, str]:
    """The branch that pull request is made from, and the one it targets.

    Empty strings where the question could not be asked — `gh` missing, not
    authenticated, no network. The caller then has nothing to replay and says
    so, rather than guessing a branch name from a ticket.
    """
    if not shutil.which("gh"):
        return "", ""
    result = run(
        [
            "gh",
            "pr",
            "view",
            url,
            "--json",
            "headRefName,baseRefName",
            "-q",
            '.headRefName + " " + .baseRefName',
        ],
        timeout=60,
        token=token_for(url, accounts),
    )
    if not result.ok or len(result.out.split()) != 2:
        return "", ""
    made_from, into = result.out.split()
    return made_from, into


def replay_pushed(
    repo: Path,
    branch: str,
    onto: str,
    workdir: Path,
    accounts: Accounts | None = None,
    settle: Settle | None = None,
) -> str:
    """Replay a branch that is already on GitHub onto its base, and push it again.

    What a merge GitHub refuses for being behind asks for, and it is asked of
    the branch as origin holds it rather than of whatever this machine has: the
    ticket's own worktree is usually long gone by the time somebody validates.

    In a detached worktree of its own — the rule at the top of this module holds
    here too, and detached means the local branch is not moved either: another
    attempt at that same ticket may well have it checked out. The push is a
    lease on the very commit that was replayed, so a branch somebody pushed to
    in the meantime is left alone and the merge stays refused.

    Says why it could not, or nothing.
    """
    fetch(repo)
    was = git(["rev-parse", f"origin/{branch}"], repo).out
    if not was:
        return f"origin/{branch} is not here to replay"
    if not has_ref(repo, f"origin/{onto}"):
        return f"origin/{onto} is not here to replay onto"
    git(["worktree", "prune"], repo)
    workdir.parent.mkdir(parents=True, exist_ok=True)
    added = git(["worktree", "add", "--detach", str(workdir), was], repo)
    if not added.ok:
        return f"git worktree add: {added.err or added.out}"
    try:
        if failure := rebase(workdir, f"origin/{onto}", settle):
            return failure
        return push_leased(workdir, branch, was, accounts)
    finally:
        remove_worktree(repo, workdir)


def is_conflict(failure: str) -> bool:
    """Did that replay stop on a conflict, rather than on anything else?

    What `rebase` answers when it could not: the `CONFLICT` line git printed
    when there was one, the first line of whatever it said otherwise.
    """
    return failure.startswith("CONFLICT")


def push_leased(worktree: Path, branch: str, was: str, accounts: Accounts | None = None) -> str:
    """Push HEAD onto `branch`, on a lease on the very commit it was replayed from.

    `--force-with-lease=<branch>:<was>`, never `--force`: a branch somebody
    pushed to since `was` is refused, and their commits stay where they are.
    Says why it could not, or nothing — `pushed_over` tells that refusal apart.
    """
    pushed = git(
        ["push", f"--force-with-lease={branch}:{was}", "origin", f"HEAD:refs/heads/{branch}"],
        worktree,
        timeout=300,
        token=token_for(remote_url(worktree), accounts),
    )
    if pushed.ok:
        return ""
    lines = [line.strip() for line in (pushed.err + "\n" + pushed.out).splitlines() if line.strip()]
    return lines[-1] if lines else f"git push {branch} failed"


def pushed_over(failure: str) -> bool:
    """Was that push refused because somebody else pushed to the branch first?"""
    said = failure.lower()
    return "stale info" in said or "fetch first" in said or "non-fast-forward" in said


def merge_blocker(url: str, accounts: Accounts | None = None) -> str:
    """What GitHub already says stands between that pull request and a merge.

    `CONFLICTING` when the branch and its base touch the same lines, `BEHIND`
    when the base has moved and the repository wants branches up to date — the
    two a replay answers, asked *before* the merge rather than read in its
    refusal. Nothing for everything else, `UNKNOWN` included: GitHub works that
    out lazily, and a merge asked on it is the old road, which already reads a
    refusal for what it is.
    """
    if not shutil.which("gh"):
        return ""
    result = run(
        [
            "gh",
            "pr",
            "view",
            url,
            "--json",
            "mergeable,mergeStateStatus",
            "-q",
            '.mergeable + " " + .mergeStateStatus',
        ],
        timeout=60,
        token=token_for(url, accounts),
    )
    if not result.ok:
        return ""
    said = result.out.split()
    if "CONFLICTING" in said or "DIRTY" in said:
        return "CONFLICTING"
    return "BEHIND" if "BEHIND" in said else ""


@dataclass
class Replay:
    """A pull request's branch, being replayed onto its base in a worktree of its own.

    Left where git stopped: `conflicts` are the files it could not merge at its
    first stop, and the rebase is still in progress in `workdir` — for a
    session to carry to its end. `error` is a replay that could not even get
    that far, and nothing else is then worth reading.
    """

    workdir: Path
    was: str = ""
    onto: str = ""
    conflicts: list[str] | None = None
    arrived: str = ""
    diff: str = ""
    error: str = ""


# How much of a pull request's diff goes into the prompt of the session that
# resolves it. The rest is one `git diff` away, and the session is told which.
DIFF_LIMIT = 40_000


def begin_replay(
    repo: Path, branch: str, onto: str, workdir: Path, settle: Settle | None = None
) -> Replay:
    """Start replaying a pushed branch onto its base, and stop where git stops.

    `replay_pushed`, without the abort: the same detached worktree on the
    branch as origin holds it — the local branch is never moved — but a rebase
    that hits a conflict is left in progress, because resolving it is the whole
    point. What the resolution needs to know comes with it: which commits
    landed on the base since the branch left it, and what the branch changes.

    What `settle` can settle is settled first, so that the files it listed are
    off the list the session is given — and a replay it carries to its end has
    no conflict left, and no session to pay for.
    """
    fetch(repo)
    replay = Replay(workdir=workdir)
    replay.was = git(["rev-parse", f"origin/{branch}"], repo).out
    replay.onto = git(["rev-parse", f"origin/{onto}"], repo).out
    if not replay.was or not replay.onto:
        missing = branch if not replay.was else onto
        replay.error = f"origin/{missing} is not here to replay"
        return replay
    fork = git(["merge-base", replay.was, replay.onto], repo).out
    replay.arrived = git(["log", "--oneline", "--no-decorate", f"{fork}..{replay.onto}"], repo).out
    diff = git(["diff", f"{fork}..{replay.was}"], repo).out
    replay.diff = diff if len(diff) <= DIFF_LIMIT else diff[:DIFF_LIMIT] + "\n[… cut]"
    git(["worktree", "prune"], repo)
    workdir.parent.mkdir(parents=True, exist_ok=True)
    if workdir.exists():
        remove_worktree(repo, workdir)
    added = git(["worktree", "add", "--detach", str(workdir), replay.was], repo)
    if not added.ok:
        replay.error = f"git worktree add: {added.err or added.out}"
        return replay
    result = git(["rebase", f"origin/{onto}"], workdir, environment=identity(workdir))
    if not result.ok and settle and conflicted(workdir):
        failure = settle(workdir, f"origin/{onto}")
        if not rebasing(workdir):
            replay.error = failure
            return replay
    replay.conflicts = conflicted(workdir)
    if not result.ok and not replay.conflicts:
        git(["rebase", "--abort"], workdir)
        lines = [
            line.strip() for line in (result.out + "\n" + result.err).splitlines() if line.strip()
        ]
        replay.error = lines[0] if lines else f"git rebase origin/{onto} failed"
    return replay


def conflicted(worktree: Path) -> list[str]:
    """The files git stopped on, unmerged in the index."""
    result = git(["diff", "--name-only", "--diff-filter=U"], worktree)
    return [line.strip() for line in result.out.splitlines() if line.strip()] if result.ok else []


def rebasing(worktree: Path) -> bool:
    """Is a rebase still in progress there — stopped, and never carried to its end?"""
    for name in ("rebase-merge", "rebase-apply"):
        found = git(["rev-parse", "--git-path", name], worktree)
        if found.ok and found.out and (Path(worktree) / found.out).exists():
            return True
    return False


def contains(worktree: Path, ancestor: str) -> bool:
    """Does HEAD carry that commit — is the branch on top of it?"""
    return git(["merge-base", "--is-ancestor", ancestor, "HEAD"], worktree).ok


def with_markers(worktree: Path, files: list[str]) -> list[str]:
    """Those of the files that still carry a conflict marker.

    Read off the files themselves: a marker committed by a resolution that
    `git add`-ed a file without resolving it is exactly what git no longer sees.
    """
    marked = []
    for name in files:
        try:
            lines = (
                (Path(worktree) / name).read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except OSError:
            continue  # deleted on purpose, which is a resolution like any other
        if any(line.startswith(("<<<<<<< ", ">>>>>>> ")) or line == "<<<<<<<" for line in lines):
            marked.append(name)
    return marked


def push_aside(worktree: Path, name: str, accounts: Accounts | None = None) -> str:
    """Put HEAD on a branch of its own on origin, for somebody to look at.

    What a resolution that stopped halfway leaves behind: never the pull
    request's own branch. The name carries the commit, so pushing the same
    thing twice is the same branch and nothing is ever forced. Says why it
    could not, or nothing.
    """
    pushed = git(
        ["push", "origin", f"HEAD:refs/heads/{name}"],
        worktree,
        timeout=300,
        token=token_for(remote_url(worktree), accounts),
    )
    return "" if pushed.ok else (pushed.err or pushed.out or f"git push {name} failed")


def comment_pull_request(url: str, body: str, accounts: Accounts | None = None) -> bool:
    """Write that on the pull request. Whether it could, and never a failure."""
    if not shutil.which("gh"):
        return False
    result = run(
        ["gh", "pr", "comment", url, "--body", body[:60_000]],
        timeout=60,
        token=token_for(url, accounts),
    )
    return result.ok


def pull_request_body(url: str, accounts: Accounts | None = None) -> str:
    """The description a pull request was opened with, or nothing."""
    if not shutil.which("gh"):
        return ""
    result = run(
        ["gh", "pr", "view", url, "--json", "body", "-q", ".body"],
        timeout=60,
        token=token_for(url, accounts),
    )
    return result.out if result.ok else ""


# How long a pull request's checks are given to appear after a push: GitHub
# registers them a few seconds after the commit arrives, and asking at once
# would read a repository with CI as one without.
CHECKS_APPEAR_SECONDS = 60


def wait_for_checks(
    url: str, worktree: Path, minutes: int, accounts: Accounts | None = None
) -> str:
    """Wait for the pull request's checks: `passed`, `failed`, `pending` or `none`.

    `none` without asking anybody when the repository has no workflow of its
    own, which is most of the ones that have no CI — and when `minutes` is
    zero, which says not to wait. `pending` is the time it was given running
    out: the merge is asked all the same, and GitHub refuses it if a check it
    requires is not green.
    """
    if minutes <= 0 or not shutil.which("gh"):
        return "none"
    if not (Path(worktree) / ".github" / "workflows").is_dir():
        return "none"
    token = token_for(url, accounts)
    deadline = time.monotonic() + minutes * 60
    appear_by = time.monotonic() + CHECKS_APPEAR_SECONDS
    while True:
        left = int(deadline - time.monotonic())
        if left <= 0:
            return "pending"
        result = run(
            ["gh", "pr", "checks", url, "--watch", "--interval", "20"],
            timeout=left,
            token=token,
        )
        said = f"{result.out}\n{result.err}".lower()
        if result.ok:
            return "passed"
        if result.code == TIMED_OUT:
            return "pending"
        if "no checks reported" in said:
            if time.monotonic() >= appear_by:
                return "none"
            time.sleep(10)
            continue
        return "failed"


# What a red check is still given after it has been asked to run again, before
# its pull request's checks are read: GitHub puts the jobs back in the queue a
# moment after the call returns, and reading at once would read the old verdict.
RERUN_SETTLE_SECONDS = 20


def checks(url: str, accounts: Accounts | None = None, timeout: int = 60) -> list[dict]:
    """The pull request's checks, as `gh pr checks --json` lists them.

    Read whatever the exit code: `gh` answers 1 when a check failed, and the
    list it printed is the very thing asked for. Nothing when it cannot say —
    a `gh` too old for `--json`, no network — which the caller reads as not
    knowing, never as green.
    """
    if not shutil.which("gh"):
        return []
    result = run(
        ["gh", "pr", "checks", url, "--json", "name,bucket,link"],
        timeout=timeout,
        token=token_for(url, accounts),
    )
    if "unknown flag" in f"{result.err}\n{result.out}":
        return _rolled_up(url, accounts, timeout)
    try:
        listed = json.loads(result.out or "[]")
    except ValueError:
        return []
    if not isinstance(listed, list):
        return []
    return [one for one in listed if isinstance(one, dict)]


# How `gh pr checks` sorts what GitHub says of a check into its buckets, for the
# gh too old to be asked for them. Anything not named here is still running.
_BUCKETS = {
    "SUCCESS": "pass",
    "SKIPPED": "skipping",
    "NEUTRAL": "skipping",
    "FAILURE": "fail",
    "ERROR": "fail",
    "TIMED_OUT": "fail",
    "ACTION_REQUIRED": "fail",
    "STARTUP_FAILURE": "fail",
    "CANCELLED": "cancel",
}


def _rolled_up(url: str, accounts: Accounts | None = None, timeout: int = 60) -> list[dict]:
    """The checks of a pull request, for a `gh` that has no `pr checks --json`.

    `--json` came to `gh pr checks` in 2.48, and Ubuntu ships 2.46: on such a
    machine every check read as unknown — no names, nothing run again, no
    comparison with the base — and a forced merge stopped on a red it could not
    say anything about. `gh pr view --json statusCheckRollup` is far older, and
    says the same things in GitHub's own words, sorted here as `gh` sorts them.
    """
    result = run(
        ["gh", "pr", "view", url, "--json", "statusCheckRollup"],
        timeout=timeout,
        token=token_for(url, accounts),
    )
    try:
        rollup = json.loads(result.out or "{}").get("statusCheckRollup") if result.ok else None
    except (ValueError, AttributeError):
        return []
    listed = []
    for one in rollup if isinstance(rollup, list) else []:
        if not isinstance(one, dict):
            continue
        if one.get("__typename") == "StatusContext":
            name, link, verdict = one.get("context"), one.get("targetUrl"), one.get("state")
        else:
            name, link = one.get("name"), one.get("detailsUrl")
            verdict = one.get("conclusion") if one.get("status") == "COMPLETED" else ""
        listed.append(
            {
                "name": str(name or ""),
                "bucket": _BUCKETS.get(str(verdict or "").upper(), "pending"),
                "link": str(link or ""),
            }
        )
    return listed


def _failing(url: str, accounts: Accounts | None = None) -> list[dict]:
    """The pull request's checks that failed — see `checks`."""
    return [one for one in checks(url, accounts) if one.get("bucket") in ("fail", "cancel")]


def failing_checks(url: str, accounts: Accounts | None = None) -> list[str]:
    """The names of the pull request's checks that failed, or nothing when unknown."""
    return sorted({str(one.get("name") or "") for one in _failing(url, accounts)} - {""})


def unstarted_checks(url: str, accounts: Accounts | None = None) -> str:
    """Why GitHub never started the pull request's red jobs — or "" when they ran.

    A job GitHub refuses to start — an account whose payment failed, a
    spending limit reached — is red in two seconds, exactly like a test that
    failed. It says nothing about the code, and nothing a session or a second
    run could change: what does is in the annotation GitHub leaves on it, which
    is returned as it is written. Only when *every* red check is such a job: one
    that did run and failed is the code's red, and is read as such.
    """
    failing = _failing(url, accounts)
    parts = reference_parts(url)
    if not failing or len(parts) < 3:
        return ""
    host, owner_name = parts[0], "/".join(parts[1:3])
    token = token_for(url, accounts)
    reasons = []
    for one in failing:
        job = re.search(r"/actions/runs/\d+/job/(\d+)", str(one.get("link") or ""))
        if not job:
            return ""
        result = run(
            [
                "gh",
                "api",
                "--hostname",
                host,
                f"repos/{owner_name}/check-runs/{job.group(1)}/annotations",
                "-q",
                ".[].message",
            ],
            timeout=60,
            token=token,
        )
        said = (
            next(
                (line.strip() for line in result.out.splitlines() if "was not started" in line),
                "",
            )
            if result.ok
            else ""
        )
        if not said:
            return ""
        reasons.append(said)
    return reasons[0]


def rerun_failed_checks(url: str, accounts: Accounts | None = None) -> bool:
    """Run the failed jobs of the pull request's workflows again. Whether any was.

    Only GitHub Actions can be asked: a check another app posts has no run to
    start again, and is left as it is. Only the failed jobs, too — the green
    ones already said what they had to say, and running them again would only
    spend minutes.
    """
    parts = reference_parts(url)
    runs = sorted(
        {
            found.group(1)
            for one in _failing(url, accounts)
            if (found := re.search(r"/actions/runs/(\d+)", str(one.get("link") or "")))
        }
    )
    if not runs or len(parts) < 3:
        return False
    repository = "/".join(parts[:3])
    token = token_for(url, accounts)
    started = [
        run(["gh", "run", "rerun", one, "--failed", "-R", repository], timeout=60, token=token).ok
        for one in runs
    ]
    if any(started):
        time.sleep(RERUN_SETTLE_SECONDS)
    return any(started)


def failed_log(url: str, accounts: Accounts | None = None, most: int = 6000) -> str:
    """The end of the log of the pull request's failed jobs, or nothing when unknown.

    `gh run view --log-failed`, one run after the other, each cut to its tail:
    what went wrong is at the end of a log, and the beginning of one is a
    hundred lines of setup that would only crowd the prompt of the session
    reading it. `most` is for all the runs together.
    """
    parts = reference_parts(url)
    runs = sorted(
        {
            found.group(1)
            for one in _failing(url, accounts)
            if (found := re.search(r"/actions/runs/(\d+)", str(one.get("link") or "")))
        }
    )
    if not runs or len(parts) < 3:
        return ""
    token = token_for(url, accounts)
    logs = []
    for one in runs:
        result = run(
            ["gh", "run", "view", one, "--log-failed", "-R", "/".join(parts[:3])],
            timeout=120,
            token=token,
        )
        if result.ok and result.out.strip():
            logs.append(result.out.strip()[-(most // len(runs)) :])
    return "\n\n".join(logs)


def base_failures(url: str, base: str, accounts: Accounts | None = None) -> list[tuple[str, str]]:
    """The checks that failed on the newest commit of `base`, with the page of each run.

    What tells a pull request that broke something from one that merely
    inherited a red `main`: the same check red on both is not the pull
    request's doing. Nothing when it cannot be asked, which leaves the red to
    the pull request — the cautious reading. The link is the run to open
    first when the base has to be repaired.
    """
    parts = reference_parts(url)
    if not base or len(parts) < 3 or not shutil.which("gh"):
        return []
    host, owner_name = parts[0], "/".join(parts[1:3])
    result = run(
        [
            "gh",
            "api",
            "--hostname",
            host,
            f"repos/{owner_name}/commits/{base}/check-runs?per_page=100",
            "-q",
            '.check_runs[] | select(.conclusion == "failure" or .conclusion == '
            '"timed_out" or .conclusion == "cancelled") | [.name, .html_url] | @tsv',
        ],
        timeout=60,
        token=token_for(url, accounts),
    )
    if not result.ok:
        return []
    found: dict[str, str] = {}
    for line in result.out.splitlines():
        name, _, link = line.strip().partition("\t")
        if name:
            found.setdefault(name, link)
    return sorted(found.items())


def failing_on(url: str, base: str, accounts: Accounts | None = None) -> list[str]:
    """The names of the checks that failed on the newest commit of `base`."""
    return [name for name, _ in base_failures(url, base, accounts)]


def ci_at_push(repo: Path, base: str, accounts: Accounts | None = None) -> str:
    """Does the CI of that repository run when something is pushed to `base`?

    `ran` when at least one push run of the branch did something, `none` when
    it has no push run at all, `skipped` when every one it has was skipped — the
    two shapes of a base nobody watches, which is how a red one goes unseen.
    Nothing when it cannot be asked: no `gh`, no remote on GitHub, no network.
    """
    remote = remote_url(repo)
    parts = reference_parts(remote)
    if not base or len(parts) < 3 or not shutil.which("gh"):
        return ""
    result = run(
        [
            "gh",
            "run",
            "list",
            "--branch",
            base,
            "--event",
            "push",
            "--limit",
            "20",
            "--json",
            "conclusion",
            "-R",
            "/".join(parts[:3]),
        ],
        timeout=60,
        token=token_for(remote, accounts),
    )
    try:
        runs = json.loads(result.out or "[]") if result.ok else None
    except ValueError:
        runs = None
    if not isinstance(runs, list):
        return ""
    if not runs:
        return "none"
    worked = any(one.get("conclusion") != "skipped" for one in runs if isinstance(one, dict))
    return "ran" if worked else "skipped"


def pull_request_on(repo: Path, branch: str, accounts: Accounts | None = None) -> str:
    """The URL of an open pull request made from that branch, or nothing.

    Nothing also means the question could not be asked — `gh` missing, not
    authenticated, no network. That is deliberately not distinguished here: this
    is never the only thing a caller looks at before touching a branch.
    """
    if not shutil.which("gh"):
        return ""
    result = run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            "-q",
            ".[0].url",
        ],
        cwd=repo,
        timeout=60,
        token=token_for(remote_url(repo), accounts),
    )
    return result.out if result.ok else ""


def current_name(owner_and_name: str, accounts: Accounts | None = None) -> str:
    """What GitHub calls that repository today, as `owner/name` — or nothing.

    A repository renamed on GitHub keeps answering to its old name: GitHub
    redirects, and `gh repo view old/name` reports the new one. Nothing means
    the question could not be asked or had no answer — `gh` missing, not
    authenticated, no network, or a repository that never existed under any
    name. The caller treats every one of those the same way: no rename known.
    """
    if not shutil.which("gh") or not is_repository(owner_and_name):
        return ""
    result = run(
        [
            "gh",
            "repo",
            "view",
            "--json",
            "nameWithOwner",
            "-q",
            ".nameWithOwner",
            "--",
            owner_and_name,
        ],
        timeout=60,
        token=token_for(owner_and_name, accounts),
    )
    return result.out if result.ok else ""


def pull_request_state(url: str, accounts: Accounts | None = None) -> str:
    """What GitHub says of that pull request: MERGED, OPEN, CLOSED — or nothing.

    Nothing means the question could not be asked: `gh` missing, not
    authenticated, the pull request deleted. A ticket is never moved on an
    answer we did not get — the next run asks again.

    The URL carries its repository, so this needs no worktree: the ticket's own
    one is long gone by the time anyone merges.
    """
    if not shutil.which("gh"):
        return ""
    result = run(
        ["gh", "pr", "view", url, "--json", "state", "-q", ".state"],
        timeout=60,
        token=token_for(url, accounts),
    )
    return result.out if result.ok else ""


def pull_request_head(url: str, accounts: Accounts | None = None) -> str:
    """The commit the pull request's branch is at, or nothing when GitHub cannot say.

    What tells a push from a wait: the checks are those of this commit, so a
    head that is not the one last read means they are all to be read again.
    """
    if not shutil.which("gh"):
        return ""
    result = run(
        ["gh", "pr", "view", url, "--json", "headRefOid", "-q", ".headRefOid"],
        timeout=60,
        token=token_for(url, accounts),
    )
    return result.out.strip() if result.ok else ""
