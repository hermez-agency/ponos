"""What an installation from before the rename still carries, carried over.

Ponos was installed for a year under another name: its configuration, its
history, its worktrees and the variables of a unit file were all written under
it. A new version that only knew the new name would start on an empty board
with a blank configuration — nothing deleted, everything out of sight, which is
indistinguishable from lost to whoever is looking. So the first launch moves
what is there, once, and says so in one line.

**This whole module is a migration filet, and only that.** The old name is
spelled here, in `OLD`, and nowhere else in the code; when the filet goes (the
CHANGELOG says in which version), this file goes with it.

Everything is idempotent and cheap when there is nothing to do: one `exists()`
per directory, one pass over the environment. Two processes starting together
— the timer and the console — race on a `rename`, which one of them wins and the
other finds already done.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Migration filet: the name Ponos was installed under, before the rename.
OLD = "ticket-runner"
# Migration filet: the prefix its environment variables carried.
OLD_PREFIX = "TICKET_RUNNER_"
PREFIX = "PONOS_"

_warned = False


def environment(environ: dict[str, str] | None = None) -> list[str]:
    """Read every old variable under its new name, unless that one is set.

    Returns the old names that were taken over, and says so once per process
    on stderr: a unit file that still sets the old variable keeps working, and
    the line tells whoever reads the journal what to rename.
    """
    global _warned
    environ = os.environ if environ is None else environ
    taken = []
    for name in sorted(environ):
        if not name.startswith(OLD_PREFIX):
            continue
        new = PREFIX + name[len(OLD_PREFIX) :]
        if new not in environ:
            environ[new] = environ[name]
            taken.append(name)
    if taken and not _warned:
        _warned = True
        renamed = ", ".join(f"{name} → {PREFIX}{name[len(OLD_PREFIX) :]}" for name in taken)
        print(
            f"ponos: rename these variables, the old names will stop working: {renamed}",
            file=sys.stderr,
        )
    return taken


def _bases() -> list[tuple[Path, Path]]:
    """The configuration and the state, each under its old and its new name."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return [(config / OLD, config / "ponos"), (state / OLD, state / "ponos")]


def path(value: str) -> str:
    """A path written under the old state directory, under the new one.

    A `ponos://` link pasted in a ticket before the rename names a worktree
    where it used to be; after the move, the same worktree is here.
    """
    for old, new in _bases():
        if value == str(old) or value.startswith(f"{old}/"):
            return str(new) + value[len(str(old)) :]
    return value


def directories(say=None) -> list[str]:
    """Move the old configuration and state directories under the new name.

    A new directory that already exists is not overwritten: what it lacks is
    moved into it, entry by entry, and an old entry it already has is left
    where it is, with a line saying so. Nothing is ever deleted but an old
    directory left empty.
    """
    say = say or (lambda line: print(line, file=sys.stderr))
    moved = []
    for old, new in _bases():
        if not old.is_dir() or old.is_symlink():
            continue
        try:
            if new.exists() and all(_residue(entry) for entry in old.iterdir()):
                # Nothing anybody would miss: tidied once, without a word.
                _tidy(old, new)
                continue
            if not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
            else:
                kept = []
                for entry in sorted(old.iterdir()):
                    target = new / entry.name
                    if target.exists() and _residue(entry):
                        _tidy(entry, target)
                    elif target.exists():
                        kept.append(entry.name)
                    else:
                        entry.rename(target)
                if kept:
                    say(f"ponos: {old} was left in place, {new} already has: {', '.join(kept)}")
                else:
                    old.rmdir()
        except FileNotFoundError:
            # The other process starting at the same moment got there first.
            continue
        except OSError as error:
            say(f"ponos: could not move {old} to {new}: {error}")
            continue
        moved.append(str(new))
        say(f"ponos: moved {old} to {new} (ticket-runner is now called Ponos)")
        if new.name == "ponos" and (new / "worktrees").is_dir():
            _worktrees(new / "worktrees")
            _sessions(old, new)
    _configuration()
    return moved


def _residue(entry: Path) -> bool:
    """An old entry nobody would miss: an empty directory, or the console's token.

    What a process still written under the old name leaves behind when it
    starts on a machine already moved — an old checkout's test suite, run
    without `XDG_STATE_HOME`, did exactly that: an empty `logs` and a
    `web/token` drawn for a console that never ran. Kept as it was, the old
    directory had the line « was left in place » said on every command, and
    every ten seconds in the journal, about nothing.
    """
    if entry.is_symlink():
        return False
    if entry.is_file():
        return entry.parent.name == "web" and entry.name == "token"
    if entry.is_dir():
        return all(_residue(child) for child in entry.iterdir())
    return False


def _tidy(old: Path, new: Path) -> None:
    """A residue, merged into the new directory: what it lacks is moved, the rest
    dropped — the new directory's own token is the one in use."""
    if old.is_dir():
        new.mkdir(parents=True, exist_ok=True)
        for child in old.iterdir():
            _tidy(child, new / child.name)
        old.rmdir()
    elif new.exists():
        old.unlink()
    else:
        old.rename(new)


def _worktrees(root: Path) -> None:
    """Tell each repository where its worktrees went.

    A worktree moved by hand is still a worktree to its own `.git` file, but
    its repository records the old path and would prune it as missing.
    `git worktree repair`, run from inside, writes the new one back.
    """
    for worktree in sorted(root.iterdir()):
        if (worktree / ".git").is_file():
            try:
                subprocess.run(
                    ["git", "worktree", "repair"], cwd=worktree, capture_output=True, timeout=30
                )
            except (OSError, subprocess.SubprocessError):
                pass


def _sessions(old: Path, new: Path) -> None:
    """Rename Claude Code's folders for the sessions started under the old path.

    Claude Code files a session under its working directory, slugified: a
    blocked ticket's session, resumed in the moved worktree, would be looked
    for under the new slug and not found.
    """
    projects = Path.home() / ".claude" / "projects"
    before, after = (re.sub(r"[/.]", "-", str(place)) for place in (old, new))
    try:
        folders = sorted(projects.glob(f"{before}-*"))
    except OSError:
        return
    for folder in folders:
        target = projects / (after + folder.name[len(before) :])
        if not target.exists():
            try:
                folder.rename(target)
            except OSError:
                pass


def _configuration() -> None:
    """Point the configuration's own paths at the moved directories.

    Only paths: the file is somebody's, and a project may well be called by
    the old name. A path into the old configuration or state directory is
    rewritten; nothing else in the file is touched.
    """
    config = _bases()[0][1] / "config.toml"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return
    rewritten = text
    for old, new in _bases():
        rewritten = rewritten.replace(str(old), str(new))
        home = Path.home()
        if old.is_relative_to(home):
            short = "~/" + str(old.relative_to(home))
            rewritten = rewritten.replace(short, "~/" + str(new.relative_to(home)))
    if rewritten != text:
        config.write_text(rewritten, encoding="utf-8")


def migrate() -> None:
    """Everything above, as the command line runs it before anything else."""
    environment()
    if os.environ.get(PREFIX + "CONFIG"):
        # An explicit configuration is somebody's test or second installation:
        # the directories of the one in use are not its to move.
        return
    directories()
