"""The Notion group: the token, the workspace, its databases found and shared.

What those databases hold — columns, statuses, types, schedules — is
`columns`, apart for its length only: one group of the dashboard, two modules.
`_project_rows` is here because `run` reads the board's projects once and hands
each one to `projects`.
"""

from __future__ import annotations

from .. import config as config_module
from .. import conversation, projects, store
from .. import workspace as workspace_module
from .check import ERROR, INFO, OK, WARN, Check, _check, _first_line
from .columns import _other_statuses, _schedules, _schema, _subtypes, _types

NOTION_INTEGRATIONS = "https://www.notion.so/profile/integrations"


def _board(
    config: config_module.Config, client: store.Store
) -> tuple[list[Check], workspace_module.Workspace | None]:
    """The board, Notion or files: reached, made of the pages it needs, shaped as the runner reads it."""
    found: list[Check] = []
    storage = config.storage
    if storage.markdown:
        found.append(
            _check(
                "notion.storage",
                OK,
                "Board",
                "A Markdown board at {{path}}.",
                params={"path": str(storage.path)},
            )
        )
        if not storage.path.is_dir():
            found.append(
                _check(
                    "notion.storage", INFO, "Board", "Not created yet: the first write makes it."
                )
            )
        if storage.mode == "both":
            found.append(
                _check(
                    "notion.storage",
                    INFO,
                    "Board",
                    "Mirrored with Notion, {{conflict}} wins a conflict, reconciled on every pass."
                    if storage.on_every_pass
                    else "Mirrored with Notion, {{conflict}} wins a conflict.",
                    params={"conflict": storage.conflict},
                )
            )
    if storage.notion:
        reached = _notion_token(config, client)
        found.extend(reached)
        if any(check.state == ERROR for check in reached):
            return found, None
    else:
        found.append(
            _check(
                "notion.storage",
                INFO,
                "Board",
                "storage.mode = “markdown”: Notion is never asked anything.",
            )
        )

    try:
        space = workspace_module.resolve(client, config.notion)
        schema = client.schema(space.tickets)
    except store.StoreError as error:
        found.append(
            _check(
                "notion.tickets",
                ERROR,
                "Tickets database",
                "The tickets database cannot be read.",
                cause="The database is not shared with the integration, or it was deleted or renamed."
                if storage.notion
                else "",
                steps=[
                    "Add the Ponos integration to your Notion page: ··· menu › Connections.",
                    "Check that the page or database named in the settings still exists.",
                ]
                if storage.notion
                else [],
                url=NOTION_INTEGRATIONS if storage.notion else "",
                evidence=str(error).strip(),
            )
        )
        return found, None
    if storage.notion and config.notion.workspace:
        found.extend(_workspace(config, space))
    found.append(
        _check(
            "notion.tickets",
            OK,
            "Tickets database",
            "Tickets database readable: {{count}} properties.",
            params={"count": str(len(schema))},
        )
    )
    reference = config.notion.tickets_database or config.notion.page("tickets")
    if storage.notion and space.tickets != reference:
        found.append(
            _check(
                "notion.tickets",
                WARN,
                "Tickets database",
                "Found by its name, “{{reference}}”.",
                params={"reference": reference},
                evidence=space.tickets,
            )
        )

    if storage.notion:
        found.append(_projects_database(client, space))
    found.extend(_schema(config, client, space))
    found.extend(_other_statuses(config, client, space))
    found.extend(_types(config, client, space))
    found.extend(_subtypes(config, client, space))
    found.extend(_schedules(config, client, space))
    found.extend(_comments(config, client, space))
    # Only a Notion board's projects are looked through one by one.
    return found, space if storage.notion else None


def _notion_token(config: config_module.Config, client: store.Store) -> list[Check]:
    try:
        config.require_usable()
    except config_module.ConfigError as error:
        return [
            _check(
                "notion.token",
                ERROR,
                "Notion token",
                "No Notion token or tickets database is set.",
                cause="The integration was never created, or its token never reached the settings.",
                steps=[
                    "Create an integration on Notion and copy its secret.",
                    "Paste it in Settings › Notion (notion.token).",
                ],
                url=NOTION_INTEGRATIONS,
                evidence=_first_line(error),
            )
        ]
    try:
        name = client.my_name() or "integration"
    except store.StoreError as error:
        return [
            _check(
                "notion.token",
                ERROR,
                "Notion token",
                "Notion refused the token.",
                cause="The token was revoked, mistyped, or belongs to another workspace.",
                steps=[
                    "Open the integration on Notion and copy its secret again.",
                    "Paste it in Settings › Notion (notion.token).",
                ],
                url=NOTION_INTEGRATIONS,
                evidence=_first_line(error),
            )
        ]
    return [
        _check(
            "notion.token", OK, "Notion token", "Connected as “{{name}}”.", params={"name": name}
        )
    ]


def _workspace(config: config_module.Config, space: workspace_module.Workspace) -> list[Check]:
    """The pages a workspace is made of: what was found, and what is missing or unreadable."""
    settings = config.notion
    found = [
        _check(
            "notion.workspace",
            OK,
            "Notion workspace",
            "{{count}} pages found: {{pages}}.",
            params={
                "count": str(len(space.rows)),
                "pages": ", ".join(f"“{name}”" for name in sorted(space.rows)) or "—",
            },
        )
    ]
    for message in space.warnings:
        found.append(
            _check(
                "notion.workspace",
                WARN,
                "Notion workspace",
                "A page of the workspace is missing or cannot be read.",
                steps=["Every page must be shared with the integration: ··· menu › Connections."],
                evidence=message,
            )
        )
    if space.context:
        found.append(
            _check(
                "notion.workspace",
                OK,
                "Notion workspace",
                "“{{page}}”: {{count}} characters in every prompt.",
                params={"page": settings.page("context"), "count": str(len(space.context))},
                evidence=space.context.strip().splitlines()[0][:60],
            )
        )
    for key in ("projects", "agents", "schedules", "goals"):
        if resolved := getattr(space, key):
            found.append(
                _check(
                    "notion.workspace",
                    OK,
                    "Notion workspace",
                    "“{{page}}” found.",
                    params={"page": settings.page(key)},
                    evidence=resolved,
                )
            )
    return found


def _projects_database(client: store.Store, space: workspace_module.Workspace) -> Check:
    if not space.projects:
        return _check(
            "notion.projects",
            WARN,
            "Projects database",
            "No projects database was found.",
            cause="Without it no ticket is tied to a repository, so none can produce a pull request.",
            steps=["Create the Projects database under your Ponos page, or run `ponos init`."],
        )
    try:
        client.schema(space.projects)
    except store.StoreError as error:
        return _check(
            "notion.projects",
            ERROR,
            "Projects database",
            "The projects database cannot be read.",
            cause="The database is not shared with the integration.",
            steps=["Add the Ponos integration to the Projects page: ··· menu › Connections."],
            url=NOTION_INTEGRATIONS,
            evidence=_first_line(error),
        )
    return _check("notion.projects", OK, "Projects database", "Projects database found and shared.")


def _comments(
    config: config_module.Config, client: store.Store, space: workspace_module.Workspace
) -> list[Check]:
    """Whether a discussion can be read, and what the runner does with one.

    The one capability that is off by default, and the one whose absence is
    silent: a ticket runs perfectly well while its discussion is invisible.
    """
    found: list[Check] = []
    sample = client.query(space.tickets)[:1]
    if not sample:
        found.append(
            _check(
                "notion.comments",
                INFO,
                "Comments",
                "No ticket yet: nothing to read a discussion on.",
            )
        )
    else:
        try:
            client.comments(sample[0].id)
            found.append(
                _check(
                    "notion.comments",
                    OK,
                    "Comments",
                    "Comments are readable: answers wake a ticket, and can be answered back.",
                )
            )
        except store.StoreError as error:
            if "403" in str(error):
                found.append(
                    _check(
                        "notion.comments",
                        ERROR,
                        "Comments",
                        "Comments cannot be read: an answer in a comment reaches nothing.",
                        cause="The integration was created without the comment capabilities.",
                        steps=[
                            "Open your integration on Notion › Capabilities, and tick Read comments (and Insert comments)."
                        ],
                        url=NOTION_INTEGRATIONS,
                        evidence=_first_line(error),
                    )
                )
            else:
                found.append(
                    _check(
                        "notion.comments",
                        WARN,
                        "Comments",
                        "Comments could not be read this time.",
                        evidence=_first_line(error),
                    )
                )
    runner = config.runner
    if runner.reply:
        found.append(
            _check(
                "settings.reply",
                OK,
                "Replies",
                "It answers when you write to it: {{names}}.",
                params={
                    "names": ", ".join(conversation.names(config.notion.mention, client.my_name()))
                },
            )
        )
        found.append(
            _check(
                "settings.reply",
                INFO,
                "Replies",
                "Every {{every}}s, {{scan}} pages a pass, permission_mode = {{mode}}.",
                params={
                    "every": str(runner.reply_interval_seconds),
                    "scan": str(runner.reply_scan),
                    "mode": runner.reply_permission_mode,
                },
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
