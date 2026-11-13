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

The temporary folders are the third thing a run fills. Each session has a
TMPDIR of its own under `leftovers.tmp_root()`, removed when it ends; the tidy
removes what is still there after `tmp_retention_hours`, and the `tmp*` folders
older sessions, tests, Chrome and Playwright dropped straight in `~/.cache` and
`~` (37 000 of them on 6 November 2026) once nothing in them was touched for
`LEGACY_HOURS`. Docker is the fourth: `docker_prune` hands it the unused images,
build cache and volumes once a day. A directory under `worktrees/` that no git
repository knows, with no `.git` and no ticket on the board — a `.vite`, a copy
whose repository was deleted — is as much an orphan as a scratch one.

A scratch directory whose ticket is no longer on the board at all is an orphan:
nobody can ask for it again, so it goes once it is old enough. A worktree in the
same case stays — it may still hold commits, and only `clean --force` asks git
whether they are anywhere else.

Once a day rather than every pass: reading the whole board costs a request per
hundred tickets, and at a ten-second cadence that is a rate limit for nothing.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import db, git, leftovers, rotation, state, store
from .base import Base
from .config import cache_dir, state_dir
from .ticket import short_id
from .web import oauth

logger = logging.getLogger(__name__)

DAY = 86400

# The three places a run fills, as `sizes` measures them and the console shows.
PLACES = ("worktrees", "logs", "scratch")

# The folders a session or a test of old made in `~/.cache` and `~`, which
# nothing ever removed. Only what nothing has touched for LEGACY_HOURS: a test
# run or a Chrome in progress is writing in its own.
LEGACY_HOURS = 2
LEGACY_NAMES = ("tmp*", "ponos-*tmp*", "ponos-tmp*", "pt")


def sizes(known: dict[str, int] | None = None) -> dict[str, int]:
    """Bytes held under each of `PLACES`, links not followed.

    `known` are places already measured, so as not to walk them twice.
    """
    known = known or {}
    return {
        place: known[place] if place in known else _size(state_dir() / place) for place in PLACES
    }


def tmp_size() -> int:
    """Bytes under the session TMPDIRs and the legacy folders `tidy_tmp` would take."""
    return _size(leftovers.tmp_root()) + sum(_size(path) for path in _legacy_tmp())


def _legacy_tmp() -> list[Path]:
    found: list[Path] = []
    cache = cache_dir().parent
    # The home is only the home when the cache is the usual `~/.cache`: a
    # cache moved elsewhere (a test, a container) says nothing about `~/tmp`.
    roots: list[tuple[Path, tuple[str, ...]]] = [(cache, LEGACY_NAMES)]
    if cache.name == ".cache":
        roots.append((cache.parent, ("tmp*",)))
    for parent, patterns in roots:
        try:
            entries = sorted(parent.iterdir())
        except OSError:
            continue
        for entry in entries:
            if (
                any(fnmatch.fnmatch(entry.name, pattern) for pattern in patterns)
                and entry.is_dir()
                and not entry.is_symlink()
            ):
                found.append(entry)
    return found


def _newest(directory: Path, since: float) -> bool:
    """Whether anything under `directory` was written after `since` — stops at the first."""
    try:
        if directory.stat().st_mtime >= since:
            return True
    except OSError:
        return True
    for parent, names, files in os.walk(directory):
        for name in (*names, *files):
            try:
                if os.lstat(os.path.join(parent, name)).st_mtime >= since:
                    return True
            except OSError:
                continue
    return False


def tidy_tmp(hours: int) -> tuple[int, int]:
    """Remove the stale temporary folders: (count, bytes). `hours` of 0 does nothing.

    The sessions' own, past `hours`; the legacy ones, past `LEGACY_HOURS`. Said
    by what is *inside*, not by the folder's own date: a directory's mtime moves
    only when an entry of it is added or removed.
    """
    if hours <= 0:
        return 0, 0
    now = time.time()
    targets = [
        (path, now - hours * 3600)
        for path in sorted(_children(leftovers.tmp_root()))
        if path.is_dir() and not path.is_symlink()
    ]
    targets += [(path, now - LEGACY_HOURS * 3600) for path in _legacy_tmp()]
    count = freed = 0
    for path, since in targets:
        if _newest(path, since):
            continue
        freed += _size(path)
        shutil.rmtree(path, ignore_errors=True)
        count += 1
    return count, freed


def _children(root: Path) -> list[Path]:
    try:
        return list(root.iterdir())
    except OSError:
        return []


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
    records: int = 0
    freed: int = 0
    tmp: int = 0
    docker: bool = False


class Cleanup(Base):
    """The daily tidy of the state directory."""

    def rotate_logs(self) -> rotation.Rotation | None:
        """Keep `logs/` under `runner.log_max_mb` — see rotation.py. None when nothing was asked of it.

        The board is read only when the folder is over the ceiling, and a board
        that cannot be read stops the rotation: which logs are in use is
        something only the board says, and a log removed on a guess is gone.
        """
        cap = self.config.runner.log_max_mb * 1024 * 1024
        held = rotation.size()
        if held <= cap:
            found = rotation.Rotation(at=time.time(), cap=cap, size=held)
            rotation.keep(found)
            return found
        try:
            pages = self.client.query(self.database)
        except store.StoreError as error:
            self.say(f"  ! logs not rotated: the board could not be read — {error}")
            return None
        status = self.config.board.prop("status")
        keeping = {
            self.config.board.state(name) for name in ("running", "blocked", "review", "validated")
        }
        protected = {short_id(ticket) for ticket in state.going()}
        protected |= {short_id(page.id) for page in pages if store.read(page, status) in keeping}
        found = rotation.rotate(cap, protected)
        rotation.keep(found)
        if found.removed:
            logger.info(
                "logs rotated: %d file(s) removed, %s freed, %s left (ceiling %s)",
                found.removed,
                human(found.freed),
                human(found.size),
                human(cap),
            )
        if found.blocked:
            logger.warning(
                "logs/ holds %s, over its %s ceiling, and what is left belongs to tickets in"
                " use: nothing more is removed (runner.log_max_mb)",
                human(found.size),
                human(cap),
            )
        return found

    def tidy(self, *, now: bool = False) -> Tidied | None:
        """Apply the retention, once a day — or `now`, when the console asks.

        A worktree a session is standing in and one a finished ticket left
        behind look alike on disk: the tickets in flight here (`state.going`)
        and those in progress on the board are left alone.
        """
        if not now and time.time() - tidied_at() < DAY:
            return None
        stamp_path().parent.mkdir(parents=True, exist_ok=True)
        stamp_path().touch()
        days = self.config.runner.log_retention_days
        tidied = Tidied(logs=state.prune_logs(days))
        try:
            tidied.records = state.prune_records(days)
        except db.ERRORS as error:
            self.say(f"  ! ponos.db not pruned: {error}")
        try:
            tidied.records += oauth.purge()
        except db.ERRORS as error:
            self.say(f"  ! MCP keys not purged: {error}")
        tidied.tmp, gone = tidy_tmp(self.config.runner.tmp_retention_hours)
        tidied.freed += gone
        if self.config.runner.docker_prune:
            tidied.docker = leftovers.prune_docker()
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
        closed = {self.config.board.state("done"), self.config.board.state("cancelled")}
        running = self.config.board.state("running")
        status = self.config.board.prop("status")
        old = {
            short_id(page.id)
            for page in pages
            if done_too and store.read(page, status) in closed and _edited(page) < cutoff
        }
        busy = {short_id(page.id) for page in pages if store.read(page, status) == running}
        known = {short_id(page.id) for page in pages}
        claimed = {short_id(ticket) for ticket in state.going()}
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
                # No repository, no `.git`: nothing git could be asked about,
                # nothing for a ticket to come back to.
                bare = (
                    place == "worktrees"
                    and bool(known)
                    and owner not in known
                    and not (directory / ".git").exists()
                    and git.repository_of(directory) is None
                )
                forgotten = (
                    place == "worktrees"
                    and stale > 0
                    and bool(known)
                    and owner not in busy
                    and _touched(directory) < stale_cutoff
                )
                condemned = untouched and (owner in old or orphan or bare)
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
        if tidied.removed or tidied.logs or tidied.records or tidied.tmp:
            self.say(
                f"Tidied: {len(tidied.removed)} directory(ies), {tidied.tmp} temporary folder(s),"
                f" {tidied.logs} log file(s), {tidied.records} database row(s),"
                f" {tidied.freed // 1_000_000} MB freed."
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
