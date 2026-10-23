"""What a session leaves running: killed with its group, brought down by its label."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from support import case

from ponos import leftovers, session


def _alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


@case
def a_background_process_does_not_outlive_a_session_that_ended_normally(state_home):
    worktree = leftovers.worktrees() / "demo-0a1b2c3d"
    worktree.mkdir(parents=True)
    pidfile = worktree / "server.pid"
    claude = worktree / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text(
        "#!" + sys.executable + "\n"
        "import json, subprocess, sys\n"
        "sys.stdin.read()\n"
        # What `pnpm dev &` does: a child that keeps running after its parent.
        "child = subprocess.Popen(['sleep', '300'], stdout=subprocess.DEVNULL)\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "print(json.dumps({'type': 'result', 'result': 'RESULT: ok', 'session_id': 's'}))\n"
    )
    claude.chmod(0o755)
    previous = os.environ["PATH"]
    os.environ["PATH"] = f"{claude.parent}{os.pathsep}{previous}"
    try:
        outcome = session.run("go", cwd=worktree, log=worktree / "log.jsonl", timeout_minutes=1)
    finally:
        os.environ["PATH"] = previous
    assert outcome.ok, outcome.error
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid), "the background process survived its session"


@case
def containers_started_from_a_worktree_are_brought_down(state_home):
    worktree = leftovers.worktrees() / "java-mcv-ab39bb37"
    shared = leftovers.worktrees() / "opoil-724cd12d"
    elsewhere = Path("/srv/dev/opoil")
    labelled = "\n".join(
        [
            f"java-mcv-ab39bb37\t{worktree}",
            f"opoil\t{shared / 'docker'}",
            f"opoil\t{shared}",
            f"opoil-local\t{elsewhere}",
        ]
    )
    calls: list[list[str]] = []

    def fake(args: list[str], timeout: int) -> str | None:
        calls.append(args)
        return labelled if args[0] == "ps" else ""

    original = leftovers.docker
    leftovers.docker = fake
    try:
        assert leftovers.sweep(elsewhere) == []  # not a worktree: never touched
        assert not [c for c in calls if c[0] == "compose"]
        leftovers.sweep(worktree)
        leftovers.sweep(shared)
    finally:
        leftovers.docker = original
    downs = [c for c in calls if c[0] == "compose"]
    # The project named after its worktree owns its volumes; the shared name never does.
    assert ["compose", "-p", "java-mcv-ab39bb37", "down", "--remove-orphans", "-v"] in downs
    assert ["compose", "-p", "opoil", "down", "--remove-orphans"] in downs
    assert not any(c[3:] == ["down", "--remove-orphans", "-v"] and c[2] == "opoil" for c in downs)
    assert not any("opoil-local" in c for c in downs)


@case
def a_session_in_a_worktree_gets_its_own_compose_project(state_home):
    worktree = leftovers.worktrees() / "Opoil_724CD12D"
    assert leftovers.environment(worktree / "src") == {"COMPOSE_PROJECT_NAME": "opoil_724cd12d"}
    assert leftovers.environment(Path("/tmp")) == {}


@case
def a_compose_file_that_pins_container_names_is_reported(state_home):
    worktree = leftovers.worktrees() / "opoil-724cd12d"
    worktree.mkdir(parents=True)
    (worktree / "docker-compose.yml").write_text(
        "services:\n  api:\n    container_name: opoil-php-api-${APP_ENV}\n"
    )
    (worktree / "compose.override.yml").write_text("services:\n  api:\n    image: x\n")
    assert leftovers.pinned(worktree) == ["docker-compose.yml"]


@case
def processes_are_found_by_their_working_directory(state_home):
    import subprocess

    worktree = leftovers.worktrees() / "demo-0a1b2c3d"
    worktree.mkdir(parents=True)
    child = subprocess.Popen(["sleep", "300"], cwd=worktree)
    try:
        assert child.pid in [pid for pid, _ in leftovers.processes(leftovers.worktrees())]
        leftovers.kill([child.pid])
        child.wait(timeout=5)
    finally:
        child.kill()
        child.wait()
