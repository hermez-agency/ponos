"""What a run leaves on disk, and the day it stops being worth keeping.

Every ticket on a repository gets a worktree — a whole checkout, `node_modules`
and build output included — and every ticket without one a scratch directory.
`clean` removed them, but only when somebody thought of typing it: on
1 October 2026 the state directory held 44 worktrees and 25 GB, with nothing
anywhere to say it was growing. So a pass now does it itself, once a day.

What may go is decided by the board, never by the disk. A directory is named
after its ticket's short id, and the tickets whose directory is removed are the
ones the board says are **done** or **cancelled** — both terminal — and have
been for the retention: edited on neither side for that long. A validated
ticket is not one of them: its worktree is where its delivery happens, and
`delivery.py` removes it itself once it is done. A ticket in progress, blocked, failed or
in review keeps its directory whatever its age: a blocked ticket's worktree is
where its uncommitted work waits for your answer, and the pull request does not
hold it (see `execution.py`). A worktree with changes never committed is kept
even for a done ticket. Its branch goes with it only when a remote holds every
commit of it: a branch costs nothing on disk, and it is the one place a commit
nobody merged is still written down.

Whatever its ticket's status, a worktree nobody has touched for
`stale_worktree_days` goes as well — the cancelled and done tickets of a board
are not the only thing a state directory piles up (a failed ticket kept for a
post-mortem, a ticket deleted from the board). Never one whose ticket is in
progress, never one holding changes or commits that are nowhere else.

The same tidy is what the disk guard runs when the free space falls under
`min_free_disk_mb` (see `reports.py`), which is why `tidy(now=True)` is not
only the console's button.

A scratch directory whose ticket is no longer on the board at all is an orphan:
nobody can ask for it again, so it goes once it is old enough. A worktree in the
same case stays — it may still hold commits, and only `clean --force` asks git
whether they are anywhere else.

Once a day rather than every pass: reading the whole board costs a request per
hundred tickets, and at a ten-second cadence that is a rate limit for nothing.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import git, state, store
from .base import Base
from .config import state_dir
from .ticket import short_id

DAY = 86400

# The three places a run fills, as `sizes` measures them and the console shows.
PLACES = ("worktrees", "logs", "scratch")


def sizes(known: dict[str, int] | None = None) -> dict[str, int]:
    """Bytes held under each of `PLACES`, links not followed.

    `known` are places already measured, so as not to walk them twice.
    """
    known = known or {}
    return {
        place: known[place] if place in known else _size(state_dir() / place) for place in PLACES
    }


def worktree_sizes() -> list[tuple[str, int]]:
    """(directory name, bytes) of each worktree, the heaviest first."""
    root = state_dir() / "worktrees"
    if not root.is_dir():
        return []
    held = [(entry.name, _size(entry)) for entry in root.iterdir() if entry.is_dir()]
    return sorted(held, key=lambda item: item[1], reverse=True)


def human(size: float) -> str:
    """A size the way a person reads it: 25 GB, 764 MB, 12 kB."""
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" or size >= 10 else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.0f} TB"


def _size(root: Path) -> int:
    total = 0
    for directory, _, names in os.walk(root):
        for name in names:
            try:
                total += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                continue
    return total


def stamp_path() -> Path:
    return state_dir() / "tidied"


def tidied_at() -> float:
    """When the last tidy ran, as a timestamp — 0 when it never has."""
    try:
        return stamp_path().stat().st_mtime
    except OSError:
        return 0.0


def _owner(directory: Path) -> str:
    """The short id a directory under the state directory was named after.

    Every name ends with it — `<project>-<short>` for a ticket's own,
    `rebase-<short>` and its siblings for what a delivery borrows.
    """
    return directory.name.rsplit("-", 1)[-1]


def _touched(directory: Path) -> float:
    """When anything in a worktree last moved, as far as its top level can tell.

    A directory's own mtime changes only when an entry of it is added or
    removed, and a session edits files deeper down for hours without that
    happening — so the checkout's index and HEAD are asked too: any `git add`,
    commit or checkout of the worktree moves them.
    """
    moments = []
    for target in (directory, *_git_files(directory)):
        try:
            moments.append(target.stat().st_mtime)
        except OSError:
            continue
    return max(moments, default=time.time())


def _git_files(directory: Path) -> list[Path]:
    try:
        pointer = (directory / ".git").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not pointer.startswith("gitdir:"):
        return []
    inner = Path(pointer.split(":", 1)[1].strip())
    return [inner / "index", inner / "HEAD"]


def _edited(page: store.Page) -> float:
    """When a page was last written, or now when it cannot be read: a date
    nobody can tell is not old enough to throw anything away on."""
    stamp = str(page.raw.get("last_edited_time") or "")
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


@dataclass
class Tidied:
    removed: list[Path] = field(default_factory=list)
    logs: int = 0
    freed: int = 0


class Cleanup(Base):
    """The daily tidy of the state directory."""

    def tidy(self, *, now: bool = False) -> Tidied | None:
        """Apply the retention, once a day — or `now`, when the console asks.

        Under the run lock, as every caller already is: a worktree a session
        is standing in and one a finished ticket left behind look alike on
        disk, and the lock is what guarantees there is no session.
        """
        if not now and time.time() - tidied_at() < DAY:
            return None
        stamp_path().parent.mkdir(parents=True, exist_ok=True)
        stamp_path().touch()
        days = self.config.runner.log_retention_days
        tidied = Tidied(logs=state.prune_logs(days))
        stale = self.config.runner.stale_worktree_days
        done_too = days > 0 and self.config.runner.clean_done_worktrees
        if not done_too and stale <= 0:
            return tidied
        try:
            pages = self.client.query(self.database)
        except store.StoreError as error:
            self.say(f"  ! not tidied: the board could not be read — {error}")
            return tidied
        cutoff = time.time() - days * DAY
        stale_cutoff = time.time() - stale * DAY
        closed = {self.config.notion.state("done"), self.config.notion.state("cancelled")}
        running = self.config.notion.state("running")
        status = self.config.notion.prop("status")
        old = {
            short_id(page.id)
            for page in pages
            if done_too and store.read(page, status) in closed and _edited(page) < cutoff
        }
        busy = {short_id(page.id) for page in pages if store.read(page, status) == running}
        known = {short_id(page.id) for page in pages}
        claimed = {short_id(ticket) for ticket in state.claims()}
        for place in ("worktrees", "scratch"):
            root = state_dir() / place
            if not root.is_dir():
                continue
            for directory in sorted(root.iterdir()):
                owner = _owner(directory)
                if not directory.is_dir() or owner in claimed:
                    continue
                try:
                    untouched = directory.stat().st_mtime < cutoff
                except OSError:
                    continue
                # An empty board is a board that was not read, not a board
                # whose every ticket was deleted.
                orphan = place == "scratch" and bool(known) and owner not in known
                forgotten = (
                    place == "worktrees"
                    and stale > 0
                    and bool(known)
                    and owner not in busy
                    and _touched(directory) < stale_cutoff
                )
                condemned = untouched and (owner in old or orphan)
                if not condemned and not forgotten:
                    continue
                size = _size(directory)
                if place == "worktrees":
                    if not self._drop_worktree(directory, forgotten=not condemned):
                        continue
                else:
                    shutil.rmtree(directory, ignore_errors=True)
                tidied.removed.append(directory)
                tidied.freed += size
        if tidied.removed or tidied.logs:
            self.say(
                f"Tidied: {len(tidied.removed)} directory(ies),"
                f" {tidied.logs} log file(s), {tidied.freed // 1_000_000} MB freed."
            )
        return tidied

    def drop_for(self, shorts: set[str]) -> tuple[list[Path], list[Path]]:
        """Remove what these tickets left under the state directory: (removed, kept).

        For a project that was deleted, whose tickets will never be worked on
        again. Only the throwaway directories — the repository the worktrees were
        made from is not in the state directory and is never touched, nor are the
        branches. A worktree with changes nobody committed is kept, as `tidy`
        keeps it: the caller has checked that no session is running, but a
        blocked ticket's worktree is where its unfinished work waits.
        """
        removed: list[Path] = []
        kept: list[Path] = []
        for place in ("worktrees", "scratch"):
            root = state_dir() / place
            if not root.is_dir():
                continue
            for directory in sorted(root.iterdir()):
                if not directory.is_dir() or _owner(directory) not in shorts:
                    continue
                if place == "worktrees":
                    if not self._drop_worktree(directory):
                        kept.append(directory)
                        continue
                else:
                    shutil.rmtree(directory, ignore_errors=True)
                removed.append(directory)
        return removed, kept

    def _drop_worktree(self, directory: Path, *, forgotten: bool = False) -> bool:
        """Remove a worktree, unless it holds work that is nowhere else.

        A done ticket's: uncommitted changes keep it. `forgotten` is the other
        case, a worktree only its age condemns: it must also be a worktree git
        knows (a stray directory is not ours to guess about) and have every
        commit pushed.
        """
        repo = git.repository_of(directory)
        if forgotten and repo is None:
            return False
        if repo is None:
            # Not a worktree any repository knows: a directory, and nothing
            # in it git could be asked about.
            if (directory / ".git").exists():
                return False
            try:
                git.discard(directory)
            except git.GitError as error:
                self.say(f"  ! {directory.name} kept: {error}")
                return False
            return True
        if git.is_dirty(directory):
            self.say(f"  ! {directory.name} kept: it has uncommitted changes")
            return False
        unpushed = git.unpushed(directory)
        if forgotten and unpushed != 0:
            self.say(f"  ! {directory.name} kept: it holds commits no remote has")
            return False
        branch = git.current_branch(directory)
        git.remove_worktree(repo, directory)
        # Only a branch every commit of which is on a remote: this one is
        # recoverable from there, and ticket branches would pile up otherwise.
        if branch and unpushed == 0:
            git.delete_branch(repo, branch)
        return True
