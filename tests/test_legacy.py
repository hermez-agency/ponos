"""`legacy.py`: an installation from before Ponos was called Ponos."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from support import ROOT, case

from ponos import legacy, session
from ponos.runner import Runner

# -- the rename: an installation from before Ponos was called Ponos -----------


# Every old name below is the migration filet under test: what an existing
# installation carries, and what it must not lose.


@case
def an_installation_from_before_the_rename_starts_with_everything_it_had():
    """Old directories, old variables, an old worktree: the first launch moves them all."""
    home = Path(tempfile.mkdtemp())
    old_config = home / ".config" / legacy.OLD
    # A state beside ~/.local/state: launched from this checkout, Ponos would
    # not migrate the database it finds there, the installation's own.
    old_state = home / "state" / legacy.OLD
    old_config.mkdir(parents=True)
    (old_config / "config.toml").write_text(
        f'[storage]\nmode = "markdown"\npath = "~/state/{legacy.OLD}/board"\n'
    )
    (old_state / "board").mkdir(parents=True)
    (old_state / "history.jsonl").write_text(
        json.dumps(
            {"at": "2026-09-30T10:00:00+00:00", "status": "done", "ticket": "Fix the footer"}
        )
        + "\n"
    )
    repository = home / "workspace" / "app"
    repository.mkdir(parents=True)

    def git(*argv: str, cwd: Path = repository) -> str:
        return subprocess.run(
            ["git", *argv],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        ).stdout

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "start")
    worktree = old_state / "worktrees" / "app-1234abcd"
    git("worktree", "add", "-q", "-b", "ticket/x", str(worktree))
    slug = session.project_key(worktree)
    (home / ".claude" / "projects" / slug).mkdir(parents=True)
    (home / ".claude" / "projects" / slug / "s1.jsonl").write_text("{}\n")

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("XDG_", "PONOS_", legacy.OLD_PREFIX))
    }
    # Said explicitly, where the installation finds it by itself: launched
    # from this checkout, Ponos would not write a state it was not given.
    environment.update(
        HOME=str(home),
        PYTHONPATH=str(ROOT / "src"),
        XDG_STATE_HOME=str(home / "state"),
        **{legacy.OLD_PREFIX + "WEB_EMAIL": "me@example.com"},
    )
    done = subprocess.run(
        [sys.executable, "-m", "ponos", "history"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert "Fix the footer" in done.stdout, "the history came along"
    assert "PONOS_WEB_EMAIL" in done.stderr, "the old variable is read, and said to be renamed"
    assert "moved" in done.stderr, "and the move is said in one line"
    state = home / "state" / "ponos"
    assert not old_config.exists() and not old_state.exists()
    assert (state / "board").is_dir()
    assert (state / "ponos.db").is_file() and (state / "history.jsonl.imported").is_file(), (
        "moved first, then read into the database"
    )
    assert "~/state/ponos/board" in (home / ".config" / "ponos" / "config.toml").read_text()
    moved = state / "worktrees" / "app-1234abcd"
    assert str(moved) in git("worktree", "list"), "the repository knows where its worktree went"
    assert (home / ".claude" / "projects" / session.project_key(moved) / "s1.jsonl").is_file()

    again = subprocess.run(
        [sys.executable, "-m", "ponos", "history"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert again.returncode == 0 and "moved" not in again.stderr, "and only once"


@case
def an_old_state_directory_holding_only_a_console_token_is_tidied_once_and_silently():
    """Recreated by an old checkout's test suite, with nothing but an empty
    `logs` and a `web/token` in it: the new state already has its own, and the
    line « was left in place » came back on every command, every ten seconds."""
    home = Path(tempfile.mkdtemp())
    old = home / "state" / legacy.OLD
    new = home / "state" / "ponos"
    (old / "logs").mkdir(parents=True)
    (old / "web").mkdir()
    (old / "web" / "token").write_text("stale\n")
    (new / "logs").mkdir(parents=True)
    (new / "web").mkdir()
    (new / "web" / "token").write_text("in use\n")
    said: list[str] = []
    previous = {key: os.environ.get(key) for key in ("XDG_STATE_HOME", "XDG_CONFIG_HOME")}
    os.environ.update(XDG_STATE_HOME=str(home / "state"), XDG_CONFIG_HOME=str(home / "config"))
    try:
        legacy.directories(said.append)
        assert said == [], said
        assert not old.exists(), "gone, so the next command has nothing to say"
        assert (new / "web" / "token").read_text() == "in use\n", "the token in use is kept"

        # Without a token of its own, the new state takes the old one, as quietly.
        (old / "web").mkdir(parents=True)
        (old / "web" / "token").write_text("stale\n")
        shutil.rmtree(new / "web")
        legacy.directories(said.append)
        assert said == [] and not old.exists()
        assert (new / "web" / "token").read_text() == "stale\n"

        # Something that matters is still moved and said, as before.
        (old / "board").mkdir(parents=True)
        (old / "board" / "fix-the-footer.md").write_text("# Fix the footer\n")
        legacy.directories(said.append)
        assert (new / "board").is_dir() and len(said) == 1 and "moved" in said[0]
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@case
def an_old_variable_is_read_under_its_new_name_unless_the_new_one_is_set():
    environment = {
        legacy.OLD_PREFIX + "CONFIG": "/old",
        legacy.OLD_PREFIX + "TERMINAL": "kitty",
        "PONOS_TERMINAL": "foot",
    }
    assert legacy.environment(environment) == [legacy.OLD_PREFIX + "CONFIG"]
    assert environment["PONOS_CONFIG"] == "/old"
    assert environment["PONOS_TERMINAL"] == "foot", "the new name wins"


@case
def an_old_session_link_opens_the_worktree_where_it_went():
    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = "/srv/state"
    try:
        assert (
            legacy.path(f"/srv/state/{legacy.OLD}/worktrees/app-1")
            == "/srv/state/ponos/worktrees/app-1"
        )
        assert legacy.path("/home/me/work/app") == "/home/me/work/app"
    finally:
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous


@case
def the_old_command_says_it_was_renamed_and_runs_ponos():
    directory = Path(tempfile.mkdtemp())
    target = directory / "ponos"
    target.write_text('#!/bin/sh\necho "ponos $*"\n')
    target.chmod(0o755)
    alias = directory / "old"
    alias.write_text((ROOT / "bin" / "former-name.in").read_text().replace("@BIN@", str(target)))
    alias.chmod(0o755)
    done = subprocess.run([str(alias), "list", "--all"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0
    assert "renamed ponos" in done.stderr
    assert done.stdout.strip() == "ponos list --all"


@case
def a_ticket_this_machine_took_before_the_rename_is_still_its_own():
    runner = object.__new__(Runner)
    runner._journals = {}
    runner.agent_label = "ponos@laptop"
    assert f"{legacy.OLD}@laptop" in runner.agent_labels
    assert f"{legacy.OLD}@desktop" not in runner.agent_labels
