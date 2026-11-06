"""What a session starts and does not stop: its processes and its containers.

A ticket's session runs `docker compose up` or `pnpm dev` from its worktree and
ends without a word about them. Two things outlive it, and they are not found
the same way. A background process stays in the session's process group, which
`session.halt` already kills — now at the end of every session, not only on a
timeout or a Stop. Not every one, though: Claude Code's Bash tool runs each
command in a session of its own, so the Vitest, the Playwright or the `pnpm dev`
it started is in no group of ours. What still ties them to the ticket is their
working directory, under the worktree — `stop_processes` ends those. A container belongs to the Docker daemon, not to any group:
the only link back to the session is the label Compose puts on it,
`com.docker.compose.project.working_dir`, which is the worktree's path.

Volumes are the delicate part. A project named after the worktree
(`java-mcv-ab39bb37`) was created by this ticket alone, so `down -v` loses
nothing. A project carrying the repository's shared name (`opoil`) may be the
developer's own database seen from the worktree: its volumes are never removed.
That is also why a session is given `COMPOSE_PROJECT_NAME` — two tickets of one
repository then stop sharing containers, and the name is one `down -v` may
delete. A compose file that pins `container_name` defeats it (two projects
cannot both own `opoil-php-api`), so those are reported, never edited: the
repository is not ours.

Nothing here raises: tidying up after a session must not turn a finished ticket
into a failed one.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from . import git
from .config import cache_dir, state_dir

logger = logging.getLogger(__name__)

PROJECT_LABEL = "com.docker.compose.project"
DIRECTORY_LABEL = "com.docker.compose.project.working_dir"
DOWN_TIMEOUT = 180
COMPOSE_FILES = ("docker-compose*.y*ml", "compose*.y*ml")
PINNED = re.compile(r"^\s*container_name\s*:", re.MULTILINE)


@dataclass(frozen=True)
class Project:
    """A Compose project that has containers started from `directory`."""

    name: str
    directory: Path


def worktrees() -> Path:
    return state_dir() / "worktrees"


def is_worktree(path: Path) -> bool:
    """Whether `path` is a ticket's worktree itself or something inside one."""
    return _below(path, worktrees()) and path != worktrees()


def worktree_of(path: Path) -> Path | None:
    """The worktree holding `path`, or None when it is not under `worktrees/`."""
    root = worktrees()
    if not _below(path, root) or path == root:
        return None
    return root / path.relative_to(root).parts[0]


def project_name(worktree: Path) -> str:
    """The Compose project name a worktree's session is given: its directory's.

    Compose accepts lowercase letters, digits, dashes and underscores, and a
    name that starts with a letter or a digit. The directory is already
    `<project>-<short id>`, which is what makes the name this ticket's own.
    """
    name = re.sub(r"[^a-z0-9_-]", "-", worktree.name.lower()).lstrip("-_")
    return name or "ticket"


def environment(workdir: Path) -> dict[str, str]:
    """What a session in `workdir` is told so its containers are its own."""
    worktree = worktree_of(workdir)
    return {"COMPOSE_PROJECT_NAME": project_name(worktree)} if worktree else {}


def tmp_root() -> Path:
    """Where every session's TMPDIR lives: one place Ponos knows, and can purge."""
    return cache_dir() / "tmp"


def make_tmp(session_id: str) -> Path | None:
    """A TMPDIR of its own for a session, or None when it cannot be made.

    Sessions, their tests and the Chrome or Playwright they start dropped
    `tmp*` folders in `~/.cache` and never removed them — 37 000 of them, 29 GB,
    on 6 November 2026. Under one root, named after the session, the end of the
    session (`drop_tmp`) and the daily tidy know where to look.
    """
    directory = tmp_root() / (re.sub(r"[^A-Za-z0-9_-]", "-", session_id) or "session")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return directory


def drop_tmp(directory: Path | None) -> None:
    """Remove a session's TMPDIR, only ever one made by `make_tmp`."""
    if directory is not None and directory.parent == tmp_root():
        shutil.rmtree(directory, ignore_errors=True)


def prune_docker() -> bool:
    """What no container refers to any more: images, build cache, volumes.

    Images and build cache of more than a day only — an image pulled a minute
    ago for a ticket that is about to start is not yet "unused". `volume prune`
    leaves every volume that a container, running or stopped, mounts, and
    `image prune` every image a container was made from. False when Docker is
    absent or refused.
    """
    done = False
    for command in (
        ["image", "prune", "-a", "-f", "--filter", "until=24h"],
        ["builder", "prune", "-f", "--filter", "until=24h"],
        ["volume", "prune", "-f"],
    ):
        done = docker(command, timeout=DOWN_TIMEOUT) is not None or done
    return done


def docker_reclaimable() -> str:
    """What Docker says it could give back, as `Images 23GB, Build Cache 15GB` — or empty."""
    found = docker(["system", "df", "--format", "{{.Type}} {{.Reclaimable}}"], timeout=30)
    pieces = []
    for line in (found or "").splitlines():
        type_, _, reclaimable = line.rpartition(" ")
        if type_ and not reclaimable.startswith("0B"):
            pieces.append(f"{type_} {reclaimable.split(' ')[0]}")
    return ", ".join(pieces)


def compose_projects(under: Path) -> list[Project]:
    """The Compose projects with a container whose working directory is in `under`."""
    found = docker(
        [
            "ps",
            "-a",
            "--filter",
            f"label={DIRECTORY_LABEL}",
            "--format",
            f'{{{{.Label "{PROJECT_LABEL}"}}}}\t{{{{.Label "{DIRECTORY_LABEL}"}}}}',
        ],
        timeout=30,
    )
    projects: dict[str, Project] = {}
    for line in (found or "").splitlines():
        name, _, directory = line.partition("\t")
        if name and directory and _below(Path(directory), under):
            projects.setdefault(name, Project(name, Path(directory)))
    return list(projects.values())


def processes(under: Path, *, spared: Collection[Path] = ()) -> list[tuple[int, str]]:
    """(pid, command) of every process other than this one whose cwd is in `under`.

    Those whose cwd is in one of the `spared` worktrees are left out.
    """
    held = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cwd = Path(os.readlink(entry / "cwd"))
            if _below(cwd, under) and worktree_of(cwd) not in spared:
                command = (
                    (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                )
                held.append((int(entry.name), command.strip() or entry.name))
        except OSError:
            continue  # gone, or not ours to look at
    return held


def stop_project(project: Project) -> bool:
    """`docker compose down` on a project, with its volumes only when they are its own."""
    worktree = worktree_of(project.directory)
    own = worktree is not None and project.name == project_name(worktree)
    command = ["compose", "-p", project.name, "down", "--remove-orphans"]
    if own:
        command.append("-v")
    stopped = docker(command, timeout=DOWN_TIMEOUT) is not None
    if not stopped:
        logger.warning("leftovers: compose project %s could not be brought down", project.name)
    return stopped


def stop_processes(workdir: Path) -> list[int]:
    """End every process still running in the worktree of `workdir`, its session over.

    The whole worktree, not `workdir` alone: a command run from `frontend/` is
    the ticket's as much as one run from the root.
    """
    worktree = worktree_of(workdir)
    if worktree is None:
        return []
    pids = [pid for pid, _ in processes(worktree)]
    if pids:
        kill(pids)
        logger.info("leftovers: stopped %d process(es) left running in %s", len(pids), worktree)
    return pids


def sweep(workdir: Path) -> list[Project]:
    """Bring down what was started from `workdir`; the processes are `stop_processes`'s."""
    if not is_worktree(workdir):
        return []
    stopped = [project for project in compose_projects(workdir) if stop_project(project)]
    for project in stopped:
        logger.info("leftovers: brought down compose project %s", project.name)
    return stopped


def kill(pids: list[int]) -> None:
    """End processes found by `processes`: asked, then made to."""
    for sign in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sign)
            except OSError:
                pass
        if sign == signal.SIGTERM:
            time.sleep(2)


def pinned(workdir: Path) -> list[str]:
    """The compose files of `workdir` that fix a `container_name`."""
    names = []
    for pattern in COMPOSE_FILES:
        for path in sorted(workdir.glob(pattern)):
            try:
                if PINNED.search(path.read_text(encoding="utf-8", errors="replace")):
                    names.append(path.name)
            except OSError:
                continue
    return names


def warn_pinned(workdir: Path) -> None:
    """Say, in the log, which compose files defeat the isolation between tickets."""
    if not is_worktree(workdir):
        return
    for name in pinned(workdir):
        logger.warning(
            "leftovers: %s pins container_name, so two tickets of this repository cannot "
            "each run their own containers (COMPOSE_PROJECT_NAME does not rename them)",
            name,
        )


def docker(args: list[str], timeout: int) -> str | None:
    """Docker's output, or None when it is absent, down or refused."""
    if not shutil.which("docker"):
        return None
    result = git.run(["docker", *args], timeout=timeout)
    return result.out if result.ok else None


def _below(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
