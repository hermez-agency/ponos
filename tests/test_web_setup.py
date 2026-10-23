"""`web/setup.py`: the first connection, step by step."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from support import ROOT, _environment, _Fresh, _saved, case

from ponos import config as C
from ponos import notion
from ponos.web import answers
from ponos.web import api as web_api

# -- what a message to the workspace carries ----------------------------------


@case
def the_first_connection_writes_the_provider_only_once_it_answers():
    """A key that does not work, saved, is a ticket that fails on it in the night."""
    from ponos import provider
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _Fresh(path)
    original = provider.api_key, provider.openrouter_key, provider.cli_login
    try:
        provider.api_key = lambda key: provider.Check(key == "sk-ant-good", "checked")
        provider.openrouter_key = lambda key, base="": provider.Check(
            key == "sk-or-good", "checked"
        )
        provider.cli_login = lambda: provider.Check(False, "not signed in — claude auth login")
        with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
            said = web_setup.save_provider(api, {"provider": "api_key", "key": "sk-ant-bad"})
            assert said["ok"] is False and "api_key" not in path.read_text(encoding="utf-8")
            said = web_setup.save_provider(api, {"provider": "api_key", "key": "sk-ant-good"})
            assert said["ok"] and api.config.claude.provider == "api_key"
            assert api.config.claude.api_key == "sk-ant-good"
            said = web_setup.save_provider(
                api, {"provider": "openrouter", "key": "sk-or-good", "route_sessions": True}
            )
            assert said["ok"] and provider.chosen(api.config) == "openrouter"
            assert api.config.openrouter.route_sessions is True
            # The CLI is written at once: what it needs is typed in a terminal.
            said = web_setup.save_provider(api, {"provider": "cli"})
            assert said["ok"] is False and said["command"] == "claude auth login"
            assert api.config.claude.provider == "cli"
            try:
                web_setup.save_provider(api, {"provider": "bedrock"})
            except ValueError:
                pass
            else:
                raise AssertionError("an unknown provider is refused")
    finally:
        provider.api_key, provider.openrouter_key, provider.cli_login = original


@case
def the_first_connection_finds_what_notion_shares_and_keeps_only_a_token_it_accepts():
    """No page link to copy: what the integration can see is what is offered.

    A token Notion refuses is said in words a newcomer can act on and is not
    written — the board would otherwise be a 401 every few seconds. One it
    accepts is written, and asked again with nothing typed: that is the poll the
    page runs while somebody is in Notion sharing a page.
    """
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _Fresh(path)
    original = notion.Client.my_name, notion.Client.shared
    shared = {"pages": []}

    def refused(self):
        raise notion.NotionError("Notion 401: API token is invalid.")

    try:
        notion.Client.my_name = refused
        said = web_setup.notion_shared(api, {"token": "ntn_wrong"})
        assert said["ok"] is False and "notion.so/my-integrations" in said["said"], said
        answers.Shared.model_validate(said)
        assert C.read_secrets(C.secrets_path(path))["PONOS_NOTION_TOKEN"] == "ntn_real"

        notion.Client.my_name = lambda self: "Ponos"
        notion.Client.shared = lambda self, directory: (shared["pages"], [])
        said = web_setup.notion_shared(api, {"token": "ntn_right"})
        assert said["ok"] and said["name"] == "Ponos" and said["pages"] == []
        assert api.config.notion.token == "ntn_right", "accepted, so written"
        shared["pages"] = [{"id": "a" * 32, "title": "Ponos", "url": ""}]
        said = web_setup.notion_shared(api, {})
        assert [page["title"] for page in said["pages"]] == ["Ponos"], (
            "the share is seen on the next ask"
        )
    finally:
        notion.Client.my_name, notion.Client.shared = original


@case
def what_is_shared_with_the_integration_is_pages_to_build_under_and_boards_already_built():
    """A row of somebody's table is not a place for a board; a `ponos` database is one."""
    client = notion.Client("ntn_x")
    asked: list[dict] = []

    def answer(method, path, body=None, **_):
        asked.append(body or {})
        if body["filter"]["value"] == "page":
            return {
                "results": [
                    {
                        "id": "1" * 32,
                        "url": "u1",
                        "parent": {"type": "workspace"},
                        "properties": {
                            "title": {"type": "title", "title": [{"plain_text": "Home"}]}
                        },
                    },
                    {
                        "id": "2" * 32,
                        "url": "u2",
                        "parent": {"type": "database_id"},
                        "properties": {
                            "Name": {"type": "title", "title": [{"plain_text": "A ticket"}]}
                        },
                    },
                ]
            }
        return {
            "results": [
                {"id": "3" * 32, "url": "u3", "title": [{"plain_text": "ponos"}]},
                {"id": "4" * 32, "url": "u4", "title": [{"plain_text": "ponos archive"}]},
            ]
        }

    client._request = answer
    pages, boards = client.shared("ponos")
    assert [page["title"] for page in pages] == ["Home"]
    assert [board["id"] for board in boards] == ["3" * 32]
    assert asked[1]["query"] == "ponos"


@case
def the_language_chosen_before_the_account_is_written_with_it():
    """The first step needs nobody signed in, and is written once somebody is."""
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _Fresh(path)
    web_setup.apply(
        api,
        {
            "email": "me@example.com",
            "password": "one I remember",
            "confirm": "one I remember",
            "language": "fr",
        },
    )
    assert api.config.runner.language == "fr" and api.config.runner.app_language == "fr"


@case
def the_first_project_step_makes_the_workspace_folder_and_offers_its_repositories():
    """A fresh machine has no workspace folder: the step makes it, rather than `doctor` failing on it."""
    from ponos.web import setup as web_setup

    root = Path(tempfile.mkdtemp()) / "workspace"
    path, _ = _saved(f'[runner]\nworkspace_root = "{root}"\n')

    class Projects(_Fresh):
        def all_projects(self) -> dict:
            return {
                "projects": [{"id": "p1", "name": "Site"}, {"id": "", "name": "only in the file"}]
            }

    api = Projects(path)
    said = web_setup.project_choices(api)
    assert root.is_dir() and said["repositories"] == [] and said["said"] == ""
    (root / "app" / ".git").mkdir(parents=True)
    said = web_setup.project_choices(api)
    assert [repository["name"] for repository in said["repositories"]] == ["app"]
    assert said["projects"] == [{"id": "p1", "name": "Site"}], "a project the board has"
    answers.ProjectChoices.model_validate(said)


@case
def a_token_written_alone_is_read_by_the_console_without_a_restart():
    """The first connection writes a Notion token to `secrets.env` and nothing else.

    A console that only watched `config.toml` kept the token it started with,
    and the page that had just been told “Notion knows this token” went on
    asking Notion with none.
    """

    path, _ = _saved()
    console = web_api.Api.__new__(web_api.Api)
    console._config = C.load(path)
    console._stamp = web_api._stamp(path)

    class Chat:
        config = None

    console.chat = Chat()
    secrets = C.secrets_path(path)
    C.write_secrets(secrets, {"PONOS_NOTION_TOKEN": "ntn_pasted"})
    later = secrets.stat().st_mtime + 2
    os.utime(secrets, (later, later))
    assert console.config.notion.token == "ntn_pasted"


@case
def the_installer_gives_the_same_install_commands_as_doctor():
    """Said in two languages — sh before Python is there, Python after — and kept the same."""
    from ponos import prerequisites

    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert prerequisites.CLAUDE_INSTALL in script
    for manager, command in prerequisites.INSTALL.items():
        assert command.replace("{package}", "") in script, manager
        for tool, package in prerequisites.PACKAGES[manager].items():
            if package != tool:
                assert f"{manager}:{tool}) echo {package} ;;" in script, (manager, tool)
    # A systemctl with no user bus behind it is a container's or WSL's: asked
    # before it is relied on, or `set -e` ends the script on its first call.
    assert "systemctl --user show-environment" in script
