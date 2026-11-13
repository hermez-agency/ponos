"""`agent_files.py`: ce que Claude Code dépose dans un worktree reste hors des commits."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from support import case

from ponos import agent_files, review

QUIET = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=QUIET,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _project(root: Path, files: dict[str, str]) -> tuple[Path, Path]:
    """Un dépôt avec `files` commités sur main, et le worktree d'un ticket."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    (repo / "README.md").write_text("projet\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "début")
    worktree = root / "ticket"
    _git(repo, "worktree", "add", "-q", "-b", "ticket/x", str(worktree), "main")
    return repo, worktree


def _staged(worktree: Path) -> list[str]:
    _git(worktree, "add", "-A")
    return _git(worktree, "diff", "--cached", "--name-only").splitlines()


@case
def what_claude_code_leaves_in_a_worktree_is_never_staged() -> None:
    with tempfile.TemporaryDirectory() as folder:
        repo, worktree = _project(Path(folder), {"AGENTS.md": "Un cas par module.\n"})
        agent_files.prepare(worktree)
        (worktree / ".claude" / "skills" / "lint").mkdir(parents=True)
        (worktree / ".claude" / "skills" / "lint" / "SKILL.md").write_text("x", encoding="utf-8")
        (worktree / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
        (worktree / "skills-lock.json").write_text("{}", encoding="utf-8")
        (worktree / "CLAUDE.local.md").write_text("x", encoding="utf-8")
        (worktree / "code.py").write_text("x = 1\n", encoding="utf-8")
        assert _staged(worktree) == ["code.py"], _staged(worktree)
        # Nothing of the project's own files was touched to get there.
        assert not (worktree / ".gitignore").exists()
        assert _git(repo, "status", "--porcelain") == ""


@case
def the_exclusions_are_written_once_beside_what_was_there() -> None:
    with tempfile.TemporaryDirectory() as folder:
        _, worktree = _project(Path(folder), {})
        path = agent_files.exclude_file(worktree)
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("*.log\n", encoding="utf-8")
        assert agent_files.exclude(worktree)
        once = path.read_text(encoding="utf-8")
        assert not agent_files.exclude(worktree), "written a second time"
        assert path.read_text(encoding="utf-8") == once
        assert once.startswith("*.log\n")
        assert once.count(agent_files.BEGIN) == 1
        assert "/.claude/" in once and "/skills-lock.json" in once


@case
def a_repository_with_only_agents_md_gets_a_claude_md_that_imports_it() -> None:
    with tempfile.TemporaryDirectory() as folder:
        _, worktree = _project(Path(folder), {"AGENTS.md": "Un cas par module.\n"})
        assert agent_files.prepare(worktree)
        assert (worktree / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
        assert _staged(worktree) == [], "the pointer would be committed"
        # AGENTS.md gone (a ticket removed it): the pointer goes with it.
        (worktree / "AGENTS.md").unlink()
        assert not agent_files.prepare(worktree)
        assert not (worktree / "CLAUDE.md").exists()


@case
def a_claude_md_the_repository_keeps_is_left_alone() -> None:
    with tempfile.TemporaryDirectory() as folder:
        _, worktree = _project(
            Path(folder), {"AGENTS.md": "Les règles.\n", "CLAUDE.md": "Les anciennes.\n"}
        )
        assert not agent_files.prepare(worktree)
        assert (worktree / "CLAUDE.md").read_text(encoding="utf-8") == "Les anciennes.\n"
        # And AGENTS.md is the one the self-review reads.
        assert review.INSTRUCTIONS[0] == "AGENTS.md"
        assert review.instructions(worktree).startswith("Les règles.")


@case
def a_repository_without_agents_md_gets_no_claude_md() -> None:
    with tempfile.TemporaryDirectory() as folder:
        _, worktree = _project(Path(folder), {})
        assert not agent_files.prepare(worktree)
        assert not (worktree / "CLAUDE.md").exists()


@case
def a_branch_that_forces_agent_files_into_a_commit_is_caught() -> None:
    with tempfile.TemporaryDirectory() as folder:
        _, worktree = _project(Path(folder), {"CLAUDE.md": "Les règles.\n"})
        agent_files.prepare(worktree)
        (worktree / "code.py").write_text("x = 1\n", encoding="utf-8")
        _git(worktree, "add", "-A")
        _git(worktree, "commit", "-q", "-m", "code")
        assert agent_files.committed(worktree, "main") == []
        # Changing or removing a CLAUDE.md the repository already had is its business.
        (worktree / "CLAUDE.md").write_text("Les règles, revues.\n", encoding="utf-8")
        _git(worktree, "commit", "-q", "-am", "règles")
        _git(worktree, "mv", "CLAUDE.md", "AGENTS.md")
        _git(worktree, "commit", "-q", "-m", "renommé")
        assert agent_files.committed(worktree, "main") == []
        # `git add -f` gets past an exclusion: a later commit taking it back out
        # leaves it in the history all the same.
        (worktree / ".claude").mkdir()
        (worktree / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
        (worktree / "skills-lock.json").write_text("{}", encoding="utf-8")
        _git(worktree, "add", "-f", ".claude/settings.local.json", "skills-lock.json")
        _git(worktree, "commit", "-q", "-m", "oups")
        _git(worktree, "rm", "-q", "--cached", "skills-lock.json")
        _git(worktree, "commit", "-q", "-m", "retiré")
        assert agent_files.committed(worktree, "main") == [
            ".claude/settings.local.json",
            "skills-lock.json",
        ]


@case
def agent_files_are_told_apart_from_the_project_s() -> None:
    for path in (".claude", ".claude/settings.json", "skills-lock.json", "CLAUDE.md"):
        assert agent_files.is_agent_file(path), path
    for path in ("AGENTS.md", "docs/CLAUDE.md", ".claudeignore", "src/.claude/x", "README.md"):
        assert not agent_files.is_agent_file(path), path
