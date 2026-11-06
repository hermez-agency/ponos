"""The machine group, continued: Ponos's own installation rather than the computer.

The channels it reports to, its version and environment, its database, and
the processes a worktree left behind.
"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path
from typing import Any

from .. import __version__, channels, cleanup, db, environment, leftovers, state
from .. import config as config_module
from .. import update as update_module
from ..ticket import short_id
from .check import ERROR, INFO, OK, WARN, Check, _check, _first_line, _fix, _installing
from .machine import _has_display

# The commands quoted under a worktree's leftover processes: enough to know the dev server.
STRAY_SHOWN = 5

# What a channel's error code means, for the codes Slack answers with — the code
# itself stays in the evidence, quoted.
NOTIFY_SAID = {
    "channel_not_found": "{{channel}} cannot find the channel, or the bot cannot see it.",
    "not_in_channel": "The bot is not in the {{channel}} channel.",
    "missing_scope": "The {{channel}} token lacks a permission.",
    "invalid_auth": "{{channel}} refused the bot token.",
}


def _notifications(config: config_module.Config) -> list[Check]:
    settings = config.notify
    found: list[Check] = []
    if not settings.desktop:
        found.append(
            _check(
                "machine.desktop",
                INFO,
                "Desktop notifications",
                "Desktop notifications are off.",
            )
        )
    elif config_module.in_container():
        found.append(
            _check(
                "machine.desktop",
                INFO,
                "Desktop notifications",
                "No desktop in a container: Telegram or Slack are the way to be told.",
            )
        )
    elif not _has_display():
        found.append(
            _check(
                "machine.desktop",
                INFO,
                "Desktop notifications",
                "Not applicable: this machine has no graphical session.",
            )
        )
    elif shutil.which("notify-send"):
        found.append(
            _check("machine.desktop", OK, "Desktop notifications", "Sent through notify-send.")
        )
    else:
        found.append(
            _check(
                "machine.desktop",
                WARN,
                "Desktop notifications",
                "Desktop notifications are asked for, but notify-send is missing.",
                **_installing("notify-send"),
            )
        )
    live = channels.open(settings)
    if not live:
        found.append(
            _check(
                "machine.notify",
                INFO,
                "Notifications",
                "No messaging channel: [notify.telegram] or [notify.slack] to be told, and to answer, from your phone.",
            )
        )
    for channel in live:
        params = {"channel": channel.name.capitalize()}
        try:
            found.append(
                _check(
                    "machine.notify",
                    OK,
                    "{{channel}} notifications",
                    "{{channel}}: {{said}}.",
                    params={**params, "said": channel.check()},
                )
            )
        except channels.ChannelError as error:
            code = _first_line(error).split(" ", 1)[0]
            found.append(
                _check(
                    "machine.notify",
                    ERROR,
                    "{{channel}} notifications",
                    NOTIFY_SAID.get(code, "{{channel}} does not answer."),
                    params=params,
                    evidence=_first_line(error),
                    cause="The token was revoked, or the chat or channel is wrong.",
                    steps=["Check the {{channel}} token and chat in Settings › Notifications."],
                )
            )
        found.extend(_answerers(channel, settings))
    if live:
        found.append(
            _check(
                "machine.notify",
                INFO,
                "Notifications",
                "Sent on: {{moments}}.",
                params={"moments": ", ".join(settings.events) or "nothing"},
            )
        )
        found.append(
            _check(
                "machine.notify",
                INFO,
                "Notifications",
                "Answers come back as comments on the ticket."
                if settings.replies
                else "Replies are not read (notify.replies = false).",
            )
        )
    return found


def _answerers(channel: channels.Channel, settings: config_module.Notify) -> list[Check]:
    """Who may answer on this channel — said, because an answer can run code.

    An answer becomes a comment, a comment wakes a ticket, and a ticket runs a
    session with `bypassPermissions`. Nobody named is anybody who can write
    there: fine in a private chat, a door left open in a group or a channel.
    """
    if not settings.replies:
        return []
    params = {"channel": channel.name.capitalize(), "table": f"notify.{channel.name}"}
    title = "{{channel}} answers"
    if channel.allowed:
        return [
            _check(
                "machine.answerers",
                OK,
                title,
                "Answers are read from {{count}} users only ({{table}}.allowed_users).",
                params={**params, "count": str(len(channel.allowed))},
            )
        ]
    chat = str(settings.telegram.get("chat", "")) if channel.name == "telegram" else ""
    if channel.name == "telegram" and chat and not chat.startswith("-"):
        return [
            _check(
                "machine.answerers",
                INFO,
                title,
                "A private chat: only you write in it.",
                params=params,
            )
        ]
    return [
        _check(
            "machine.answerers",
            WARN,
            title,
            "Anybody who can write on {{channel}} can answer, and an answer can wake a ticket.",
            params=params,
            steps=["Name the people allowed in {{table}}.allowed_users."],
        )
    ]


def _version(config: config_module.Config, remote: bool) -> list[Check]:
    """This version, the newest one, and how the one is followed by the other."""
    found = [
        _check(
            "machine.version",
            INFO,
            "Version",
            "Ponos {{version}}: what changed is in CHANGELOG.md.",
            params={"version": __version__},
        )
    ]
    # In a container there is nothing to follow: the image is the version.
    if config_module.in_container():
        found.append(
            _check(
                "machine.version",
                INFO,
                "Version",
                "A container is updated by pulling a new image.",
                evidence=update_module.CONTAINER,
            )
        )
        return found
    runner = config.runner
    channel = runner.update_channel
    status = update_module.check(channel=channel) if remote else update_module.remembered()
    if status.reason:
        found.append(
            _check(
                "machine.version",
                WARN,
                "Version",
                "The newest version could not be compared with this one.",
                evidence=status.reason,
            )
        )
    elif status.stale:
        found.append(
            _check(
                "machine.version",
                WARN,
                "Version",
                "{{current}} installed, {{available}} available.",
                params={
                    "current": status.current[:8],
                    "available": f"{status.tag} ({status.latest[:8]})"
                    if status.tag
                    else status.latest[:8],
                },
                steps=["Run `ponos update`, or Update in the console's header."],
            )
        )
    elif status.current:
        found.append(
            _check(
                "machine.version",
                OK,
                "Version",
                "The newest version is installed ({{newest}}).",
                params={
                    "newest": f"{status.tag}, {status.current[:8]}"
                    if status.tag
                    else status.current[:8]
                },
            )
        )
    else:
        found.append(
            _check("machine.version", INFO, "Version", "No version check has been made yet.")
        )
    found.append(
        _check(
            "machine.update",
            INFO,
            "Updates",
            "runner.update_channel = “main”: every commit of the branch it was installed from is followed."
            if channel == "main"
            else "runner.update_channel = “{{channel}}”: the newest release tag (vX.Y.Z) is followed, never a commit in between.",
            params={"channel": channel},
        )
    )
    if runner.auto_update:
        found.append(
            _check(
                "machine.update",
                INFO,
                "Updates",
                "Checked by the daemon every {{every}}s (runner.auto_update): it installs a newer version and restarts on it, its sessions taken back.",
                params={"every": str(runner.update_interval_seconds)},
            )
        )
    else:
        found.append(
            _check(
                "machine.update",
                INFO,
                "Updates",
                "runner.auto_update = false: `ponos update` updates by hand.",
            )
        )
    return found


def _environment() -> list[Check]:
    """The `.venv` of the version in use: there, runnable, and holding what it requires."""
    title = "Python environment"
    if config_module.in_container():
        return [
            _check(
                "machine.environment",
                INFO,
                title,
                "The image's Python: requirements.txt was installed when it was built.",
            )
        ]
    version = update_module.installed_version()
    if version is None:
        return [
            _check(
                "machine.environment",
                INFO,
                title,
                "Not installed by install.sh: {{where}} runs on whatever started it.",
                params={"where": str(update_module.app_dir())},
            )
        ]
    state, said = environment.diagnose(version)
    if state == "ok":
        return [
            _check(
                "machine.environment",
                OK,
                title,
                "The environment of this version is in place.",
                evidence=said,
            )
        ]
    if state == "warn":
        return [
            _check(
                "machine.environment",
                WARN,
                title,
                "This version has no environment of its own: the machine's Python runs it.",
                evidence=said,
            )
        ]
    return [
        _check(
            "machine.environment",
            ERROR,
            title,
            "The environment of this version cannot run it.",
            steps=["Run `{{repair}}` to make it again."],
            params={"repair": environment.REPAIR},
            evidence=said,
        )
    ]


def _database() -> list[Check]:
    """The local database opens, and is at the schema this code knows — or why not.

    Opening it is what brings it up to date, so this is also what migrates it
    on purpose. A file newer than the code is the case worth an error: every
    part of the runner that writes into it would stop on it. Migrations applied
    in another order than the code's are a warning: the file has every table,
    but was once written by another branch's code. The copy taken before the
    last migration is said with how to put it back, since a version gone back
    to refuses the file the newer one migrated.
    """
    title = "Local database"
    try:
        location, found, disorder = db.check()
    except db.DatabaseError as error:
        restore: dict[str, Any] = {}
        if isinstance(error, db.TooNew):
            known = [copy for copy in db.backups(db.path()) if copy[0] <= len(db.MIGRATIONS)]
            if known:
                restore = {
                    "steps": [
                        "Stop the runner and the console.",
                        "Put back the copy taken before the migration, at schema version "
                        "{{backup_version}}: `{{restore}}` — what was written since is lost.",
                    ],
                    "params": {
                        "backup_version": str(known[0][0]),
                        "restore": _restore(db.path(), known[0][1]),
                    },
                }
        return [
            _check(
                "machine.database",
                ERROR,
                title,
                "The local database cannot be used.",
                evidence=str(error),
                **restore,
            )
        ]
    held = db.sizes(location)
    checks = [
        _check(
            "machine.database",
            OK,
            title,
            "{{location}}: schema version {{version}} of {{count}}, {{size}} on disk"
            " and {{wal}} of write-ahead log.",
            params={
                "location": str(location),
                "version": str(found),
                "count": str(len(db.MIGRATIONS)),
                "size": cleanup.human(held[0]),
                "wal": cleanup.human(held[1]),
            },
        )
    ]
    copies = db.backups(location)
    if copies:
        checks.append(
            _check(
                "machine.database",
                INFO,
                title,
                "Copy taken before the last migration: {{backup}}, at schema version "
                "{{backup_version}}. To go back to the version before it, stop the runner "
                "and the console, then run `{{restore}}`.",
                params={
                    "backup": str(copies[0][1]),
                    "backup_version": str(copies[0][0]),
                    "restore": _restore(location, copies[0][1]),
                },
            )
        )
    if disorder:
        checks.append(
            _check(
                "machine.database",
                WARN,
                title,
                "Its migrations do not match this code's list.",
                evidence=disorder,
            )
        )
    return checks


def _restore(location: Path, copy: Path) -> str:
    """The command that puts `copy` back in place of `location`.

    Its `-wal` and `-shm` go first: left beside the copy, SQLite would replay
    the newer file's last writes onto it.
    """
    where, copied = shlex.quote(str(location)), shlex.quote(str(copy))
    return f"rm -f {where}-wal {where}-shm && cp {copied} {where}"


def _spared() -> set[Path]:
    """The worktrees of the tickets in progress here: what runs in them is theirs.

    A session going (`stopping.live`), but also a ticket this host claimed and
    is between two sessions of — its CI run here, its rebase, its retry: the
    Vitest or the dev server it started is not left behind yet, and stopping
    it would pull the floor from under the ticket.
    """
    root = leftovers.worktrees()
    going = {short_id(ticket) for ticket in state.going()}
    return {
        worktree
        for worktree in (root.iterdir() if root.is_dir() else ())
        if worktree.name.rsplit("-", 1)[-1] in going
    }


def _stray() -> list[Check]:
    """The containers and processes a session started in its worktree and left running.

    A worktree whose ticket is still in progress is not looked at: its `claude`,
    its MCP servers and its dev server are not left behind yet, and `ponos clean
    --force` would stop them under it. The processes are said a worktree at a
    time — a session leaves a dev server with its watchers and workers, and one
    line a pid made the band two screens long.
    """
    root = leftovers.worktrees()
    spared = _spared()
    composed = [
        project
        for project in leftovers.compose_projects(root)
        if leftovers.worktree_of(project.directory) not in spared
    ]
    held: dict[Path, list[tuple[int, str]]] = {}
    for pid, command in leftovers.processes(root, spared=spared):
        try:
            where = leftovers.worktree_of(Path(f"/proc/{pid}/cwd").readlink()) or root
        except OSError:
            where = root
        held.setdefault(where, []).append((pid, command))
    title = "Left running"
    if not composed and not held:
        return [
            _check(
                "machine.stray",
                OK,
                title,
                "No container or process left running from a worktree.",
            )
        ]
    steps = ["Run `ponos clean --force` to stop them, once no run is in progress."]
    found = [
        _check(
            "machine.stray",
            WARN,
            title,
            "The Compose project {{name}} still has containers.",
            params={"name": project.name},
            steps=steps,
            evidence=str(project.directory),
        )
        for project in composed
    ]
    found.extend(
        _check(
            "machine.stray",
            WARN,
            title,
            "{{count}} process(es) left running in the worktree {{name}}.",
            params={"name": worktree.name, "count": str(len(pids))},
            steps=steps,
            evidence="\n".join(f"{pid} {command[:100]}" for pid, command in pids[:STRAY_SHOWN])
            + ("\n…" if len(pids) > STRAY_SHOWN else ""),
            # Processes run from the root itself are no ticket's: `clean` decides.
            fix=_fix(
                "stray_processes",
                "Stop",
                "Stop the {{count}} process(es) left running in the worktree {{name}}?",
                [],
                target=worktree.name,
            )
            if worktree != root
            else None,
        )
        for worktree, pids in held.items()
    )
    return found
