"""The board group: `ponos.db` read, and what the runner does with a discussion.

The board's shape is the code's own (`store.shape`), so there is no column to
look for and no option to add: what can still go wrong is the file not
answering, and a schedule that cannot make its ticket or has stopped making
it. `_project_rows` is here because `fixing` reads the board's projects
to find the one a fix is about.
"""

from __future__ import annotations

from datetime import datetime

from .. import config as config_module
from .. import conversation, projects, store
from .. import schedules as schedules_module
from .. import workspace as workspace_module
from .check import ERROR, INFO, OK, WARN, Check, _check, _first_line


def _board(
    config: config_module.Config, client: store.Store
) -> tuple[list[Check], workspace_module.Workspace | None]:
    """The board: readable, and the discussions answered or not."""
    found: list[Check] = []
    try:
        space = workspace_module.resolve(client, config.board)
        count = len(client.query(space.tickets))
    except store.StoreError as error:
        found.append(
            _check(
                "board.tickets",
                ERROR,
                "Board",
                "The board cannot be read.",
                steps=["Run `ponos doctor` again; if it says the same, see ponos.log."],
                evidence=str(error).strip(),
            )
        )
        return found, None
    found.append(
        _check(
            "board.tickets",
            OK,
            "Board",
            "The board is ponos.db: {{count}} ticket(s).",
            params={"count": str(count)},
        )
    )
    found.extend(_schedules(config, client, space))
    found.extend(_discussions(config, client))
    return found, None


def _schedules(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """What would keep a schedule's ticket from being born, and a runner that stopped making them."""
    found: list[Check] = []
    try:
        rows = [schedules_module.read(page, config.board) for page in client.query(space.schedules)]
    except store.StoreError as error:
        found.append(
            _check(
                "board.schedules",
                WARN,
                "Schedules",
                "The schedules could not be read.",
                evidence=_first_line(error),
            )
        )
        return found
    if not rows:
        found.append(_check("board.schedules", INFO, "Schedules", "No schedule written yet."))
        return found
    now = datetime.now().astimezone()
    for schedule in rows:
        params = {"schedule": schedule.name}
        title = "Schedule “{{schedule}}”"
        if schedule.problem:
            found.append(
                _check(
                    "board.schedule",
                    ERROR,
                    title,
                    "This schedule cannot make a ticket.",
                    params=params,
                    evidence=schedule.problem,
                )
            )
        elif not schedule.active:
            found.append(_check("board.schedule", INFO, title, "Unticked.", params=params))
        # A `Next` a day behind is not a schedule running late: it is a runner
        # that has stopped, and this is the only place that would say so.
        elif schedule.next and (now - schedule.next).total_seconds() > 86400:
            found.append(
                _check(
                    "board.schedule",
                    ERROR,
                    title,
                    "Due since {{since}} and never born: the runner is not passing.",
                    params={**params, "since": schedule.next.strftime("%Y-%m-%d %H:%M")},
                    steps=["Check that the runner runs: `ponos status`."],
                )
            )
        elif schedule.next:
            found.append(
                _check(
                    "board.schedule",
                    OK,
                    title,
                    "{{cadence}}, next on {{when}}.",
                    params={
                        **params,
                        "cadence": schedule.cadence,
                        "when": schedule.next.strftime("%Y-%m-%d %H:%M"),
                    },
                )
            )
        else:
            found.append(
                _check(
                    "board.schedule",
                    OK,
                    title,
                    "{{cadence}}, next on the next pass.",
                    params={**params, "cadence": schedule.cadence},
                )
            )
    return found


def _discussions(config: config_module.Config, client: store.Store) -> list[Check]:
    """What the runner does with a discussion: answer it, and look at the blocked tickets again."""
    found: list[Check] = []
    runner = config.runner
    if runner.reply:
        found.append(
            _check(
                "settings.reply",
                OK,
                "Replies",
                "It answers when you write to it: {{names}}.",
                params={"names": ", ".join(conversation.names("", client.my_name()))},
            )
        )
    else:
        found.append(
            _check(
                "settings.reply",
                INFO,
                "Replies",
                "runner.reply = false: a comment can wake a ticket, not start a talk.",
            )
        )
    if runner.unblock:
        found.append(
            _check(
                "settings.unblock",
                OK,
                "Unblocking",
                "Blocked tickets are looked at again: the ones whose cause is gone go back to ready.",
            )
        )
        found.append(
            _check(
                "settings.unblock",
                INFO,
                "Unblocking",
                "Each ticket every {{every}}s, permission_mode = {{mode}}.",
                params={
                    "every": str(runner.unblock_interval_seconds),
                    "mode": runner.reply_permission_mode,
                },
            )
        )
    else:
        found.append(
            _check(
                "settings.unblock",
                INFO,
                "Unblocking",
                "runner.unblock = false: a blocked ticket stays blocked until you move it.",
            )
        )
    return found


def _project_rows(
    client: store.Store, space: workspace_module.Workspace | None
) -> list[dict[str, str]]:
    """The projects that have a repository or a path, as the board declares them."""
    if space is None or not space.projects:
        return []
    rows = []
    try:
        for page in client.query(space.projects):
            repository = str(
                projects._property(page, "Repository", "repository", "github", "repo") or ""
            )
            path = str(projects._property(page, "Path", "path") or "")
            if repository or path:
                rows.append(
                    {
                        "id": page.id.replace("-", ""),
                        "name": page.title or "(untitled project)",
                        "repository": repository,
                        "path": path,
                    }
                )
    except store.StoreError:
        pass
    return rows
