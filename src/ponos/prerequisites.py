"""What a machine needs before a ticket can run on it, and how to get each.

Said in three places, for three moments: `install.sh` before anything is copied,
`doctor` for whoever is helping, and the console's summary for whoever is
installing. The installer is a shell script and cannot import this, so it keeps
its own copy of the commands — the same ones, kept in step by a test.

A missing tool is never just *missing*. Somebody discovering Ponos does not know
that `git` comes from their package manager and Claude Code from a script of its
own, and an error that stops at the name sends them off to search for the rest:
so each need carries the one command that installs it on this machine — from
the package manager this machine actually has, when there is one to name.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import provider, resources

# Claude Code's own installer: no Node, no npm, and it keeps itself up to date.
CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"

# The package each tool comes in, where the name differs from the tool's.
PACKAGES = {
    "apt-get": {"python3": "python3", "git": "git", "gh": "gh"},
    "dnf": {"python3": "python3", "git": "git", "gh": "gh"},
    "pacman": {"python3": "python", "git": "git", "gh": "github-cli"},
    "brew": {"python3": "python@3.12", "git": "git", "gh": "gh"},
}

# The order the managers are looked for in: a Mac with Homebrew has no apt.
INSTALL = {
    "apt-get": "sudo apt-get install -y {package}",
    "dnf": "sudo dnf install -y {package}",
    "pacman": "sudo pacman -S --noconfirm {package}",
    "brew": "brew install {package}",
}


@dataclass(frozen=True)
class Need:
    """One thing the machine has, or has not, and what to type when it has not."""

    name: str
    ok: bool
    required: bool
    said: str
    fix: str = ""


def install_command(tool: str) -> str:
    """The command that installs `tool` here, or "" when no manager can be named."""
    if tool == "claude":
        return CLAUDE_INSTALL
    managers = ("brew",) if platform.system() == "Darwin" else tuple(INSTALL)
    for manager in managers:
        if shutil.which(manager) and tool in PACKAGES[manager]:
            return INSTALL[manager].format(package=PACKAGES[manager][tool])
    return ""


def check(state: Path, minimum_disk_mb: int) -> list[Need]:
    """git, Claude Code installed and signed in, room on the disk — and gh, optional."""
    needs: list[Need] = []
    for tool, required in (("git", True), ("gh", False)):
        found = shutil.which(tool)
        needs.append(
            Need(tool, bool(found), required, found or "not installed", "" if found else install_command(tool))
        )
    if not shutil.which("claude"):
        needs.append(Need("claude", False, True, "Claude Code is not installed", CLAUDE_INSTALL))
    else:
        login = provider.cli_login()
        needs.append(Need("claude", True, True, "installed"))
        needs.append(
            Need("claude login", login.ok, False, login.said, "" if login.ok else provider.LOGIN)
        )
    room = resources.disk_mb(state)
    if room is not None:
        enough = minimum_disk_mb <= 0 or room[0] >= minimum_disk_mb
        needs.append(
            Need(
                "disk", enough, True, f"{room[0]} MB free",
                "" if enough else f"free {minimum_disk_mb - room[0]} MB — a ticket starts above "
                f"{minimum_disk_mb} MB (runner.min_free_disk_mb)",
            )
        )
    return needs
