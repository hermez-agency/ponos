"""`web/setup.py`: the first connection, step by step."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, cast

from support import ROOT, _environment, _Fresh, _saved, case

from ponos import config as C
from ponos import notion
from ponos.web import answers
from ponos.web import api as web_api
from ponos.web import base as web_base

# -- what a message to the workspace carries ----------------------------------


def _api(path: Path) -> web_api.Api:
    """`_Fresh`, taken for the `Api` whose three first-connection gestures it does."""
    return cast(web_api.Api, _Fresh(path))


@case
def the_first_connection_writes_the_provider_only_once_it_answers() -> None:
    """A key that does not work, saved, is a ticket that fails on it in the night."""
    from ponos import provider
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _api(path)
    original = provider.api_key, provider.openrouter_key, provider.cli_login
    try:
        provider.api_key = lambda key: provider.Check(key == "sk-ant-good", "checked")
        provider.openrouter_key = lambda key, base_url="": provider.Check(
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
def the_cli_step_says_whether_claude_is_installed_then_signed_in() -> None:
    """Missing, the step gives both commands; installed, the sign-in; signed in, a green tick."""
    import json
    import subprocess

    from ponos import prerequisites, session
    from ponos.web import setup as web_setup

    signed: dict[str, object] = {}
    original = session.available, subprocess.run
    try:
        subprocess.run = lambda *_, **__: subprocess.CompletedProcess(  # type: ignore[assignment]
            [], 0, json.dumps(signed), ""
        )
        session.available = lambda: ""
        missing = web_setup.claude_login()
        assert missing["ok"] is False and missing["installed"] is False, missing
        assert missing["install"] == prerequisites.CLAUDE_INSTALL
        assert missing["command"] == "claude auth login"
        session.available = lambda: "/usr/bin/claude"
        unsigned = web_setup.claude_login()
        assert unsigned["ok"] is False and unsigned["installed"] is True, unsigned
        assert unsigned["said"] == "not signed in — claude auth login"
        signed.update(loggedIn=True, email="me@example.com", subscriptionType="max")
        ready = web_setup.claude_login()
        assert ready["ok"] and ready["installed"] and ready["said"] == "me@example.com (max)"
        answers.ClaudeLogin.model_validate(ready)
    finally:
        session.available, subprocess.run = original


@case
def the_test_button_tries_the_key_typed_or_the_one_saved_and_writes_nothing() -> None:
    """Trying a key is not saving it: the settings keep their own Save for that."""
    from ponos import provider
    from ponos.web import setup as web_setup

    path, _ = _saved()
    tried: list[str] = []
    original = provider.api_key
    try:

        def tried_key(key: str) -> provider.Check:
            tried.append(key)
            return provider.Check(key == "sk-ant-good", "checked")

        provider.api_key = tried_key
        with _environment(ANTHROPIC_API_KEY="sk-ant-good"):
            api = _api(path)
            before = path.read_text(encoding="utf-8")
            typed = {"provider": "api_key", "key": "sk-ant-other", "save": False}
            assert web_setup.save_provider(api, typed) == {"ok": False, "said": "checked"}
            said = web_setup.save_provider(api, {"provider": "api_key", "save": False})
            assert said["ok"] and tried == ["sk-ant-other", "sk-ant-good"]
            # Accepted, and still not written: neither the provider nor the key.
            assert path.read_text(encoding="utf-8") == before
            assert api.config.claude.provider != "api_key"
            secrets = C.secrets_path(path)
            assert not secrets.exists() or "sk-ant" not in secrets.read_text(encoding="utf-8")
    finally:
        provider.api_key = original


@case
def the_first_connection_finds_what_notion_shares_and_keeps_only_a_token_it_accepts() -> None:
    """No page link to copy: what the integration can see is what is offered.

    A token Notion refuses is said in words a newcomer can act on and is not
    written — the board would otherwise be a 401 every few seconds. One it
    accepts is written, and asked again with nothing typed: that is the poll the
    page runs while somebody is in Notion sharing a page.
    """
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _api(path)
    original = notion.Client.my_name, notion.Client.shared
    shared: dict[str, list[dict[str, Any]]] = {"pages": []}

    def refused(self: notion.Client) -> str:
        raise notion.NotionError("Notion 401: API token is invalid.")

    try:
        notion.Client.my_name = refused  # type: ignore[method-assign]  # a double: Notion says 401
        said = web_setup.notion_shared(api, {"token": "ntn_wrong"})
        assert said["ok"] is False and "notion.so/my-integrations" in said["said"], said
        answers.Shared.model_validate(said)
        assert C.read_secrets(C.secrets_path(path))["PONOS_NOTION_TOKEN"] == "ntn_real"

        notion.Client.my_name = lambda self: "Ponos"  # type: ignore[method-assign]  # a double
        notion.Client.shared = lambda self, directory: (  # type: ignore[method-assign]  # a double
            shared["pages"],
            [],
        )
        said = web_setup.notion_shared(api, {"token": "ntn_right"})
        assert said["ok"] and said["name"] == "Ponos" and said["pages"] == []
        assert api.config.notion.token == "ntn_right", "accepted, so written"
        shared["pages"] = [{"id": "a" * 32, "title": "Ponos", "url": ""}]
        said = web_setup.notion_shared(api, {})
        assert [page["title"] for page in said["pages"]] == ["Ponos"], (
            "the share is seen on the next ask"
        )
    finally:
        notion.Client.my_name, notion.Client.shared = original  # type: ignore[method-assign]


@case
def the_board_step_needs_no_token_to_work_without_notion() -> None:
    """No token is an installation whose board is `ponos.db`: nothing is missing, nothing is asked."""
    from ponos.web import setup as web_setup

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[notion]\n", encoding="utf-8")
    api = _api(path)
    with _environment(PONOS_NOTION_TOKEN=None):
        drawn = web_setup._board(api)
        # _Fresh has no board to count tickets on; what matters is that none asks for a token.
        assert drawn["notion"] is False and "token" not in drawn["said"], drawn


@case
def what_is_shared_with_the_integration_is_pages_to_build_under_and_boards_already_built() -> None:
    """A row of somebody's table is not a place for a board; a `ponos` database is one."""
    client = notion.Client("ntn_x")
    asked: list[dict[str, Any]] = []

    def answer(
        method: str, path: str, body: dict[str, Any] | None = None, **_: Any
    ) -> dict[str, Any]:
        asked.append(body or {})
        assert body is not None
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

    client._request = answer  # type: ignore[method-assign]  # a double: Notion's search, answered
    pages, boards = client.shared("ponos")
    assert [page["title"] for page in pages] == ["Home"]
    assert [board["id"] for board in boards] == ["3" * 32]
    assert asked[1]["query"] == "ponos"


@case
def the_language_chosen_before_the_account_is_written_with_it() -> None:
    """The first step needs nobody signed in, and is written once somebody is."""
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _api(path)
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
def the_first_project_step_makes_the_workspace_folder_and_offers_its_repositories() -> None:
    """A fresh machine has no workspace folder: the step makes it, rather than `doctor` failing on it."""
    from ponos.web import setup as web_setup

    root = Path(tempfile.mkdtemp()) / "workspace"
    path, _ = _saved(f'[runner]\nworkspace_root = "{root}"\n')

    class Projects(_Fresh):
        def all_projects(self) -> dict[str, Any]:
            return {
                "projects": [{"id": "p1", "name": "Site"}, {"id": "", "name": "only in the file"}]
            }

    api = cast(web_api.Api, Projects(path))  # what the step asks of an Api, and nothing else
    said = web_setup.project_choices(api)
    assert root.is_dir() and said["repositories"] == [] and said["said"] == ""
    (root / "app" / ".git").mkdir(parents=True)
    said = web_setup.project_choices(api)
    assert [repository["name"] for repository in said["repositories"]] == ["app"]
    assert said["projects"] == [{"id": "p1", "name": "Site"}], "a project the board has"
    answers.ProjectChoices.model_validate(said)


@case
def a_token_written_alone_is_read_by_the_console_without_a_restart() -> None:
    """The first connection writes a Notion token to `secrets.env` and nothing else.

    A console that only watched `config.toml` kept the token it started with,
    and the page that had just been told “Notion knows this token” went on
    asking Notion with none.
    """

    path, _ = _saved()
    console = web_api.Api.__new__(web_api.Api)
    console._config = C.load(path)
    console._stamp = web_base._stamp(path)

    class Chat:
        config = None

    console.chat = Chat()  # type: ignore[assignment]  # a double: no conversation
    secrets = C.secrets_path(path)
    C.write_secrets(secrets, {"PONOS_NOTION_TOKEN": "ntn_pasted"})
    later = secrets.stat().st_mtime + 2
    os.utime(secrets, (later, later))
    assert console.config.notion.token == "ntn_pasted"


@case
def the_installer_gives_the_same_install_commands_as_doctor() -> None:
    """Said in two languages — sh before Python is there, Python after — and kept the same."""
    from ponos import prerequisites

    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert prerequisites.CLAUDE_INSTALL in script
    for manager, command in prerequisites.INSTALL.items():
        assert command.replace("{package}", "") in script, manager
        for tool, package in prerequisites.PACKAGES[manager].items():
            if package != tool:
                assert f"{manager}:{tool}) echo {package} ;;" in script, (manager, tool)
    assert "All the tools at once" in script
    # A systemctl with no user bus behind it is a container's or WSL's: asked
    # before it is relied on, or `set -e` ends the script on its first call.
    assert "systemctl --user show-environment" in script


@case
def a_fresh_container_is_sent_to_the_steps_until_they_have_been_gone_through() -> None:
    """A board without Notion is usable at once: nothing but a mark says the steps are still owed."""
    from support import _state_home

    from ponos.web import setup as web_setup

    with _state_home(), _environment(PONOS_CONTAINER="1"):
        assert web_setup.pending()
        assert web_setup.finish() == {"ok": True}
        assert not web_setup.pending()
    with _state_home(), _environment(PONOS_CONTAINER=None):
        assert not web_setup.pending(), "a machine installed with install.sh is not sent there"


@case
def the_summary_names_a_notion_board_by_its_title_and_links_to_it() -> None:
    """Thirty-two hexadecimal characters say nothing to whoever reads the summary."""
    from types import SimpleNamespace

    from ponos.web import setup as web_setup

    workspace = "3a8451680af480918afcf0eb9cf70e7b"

    class Answering(notion.Client):
        def __init__(self, answer: dict[str, Any] | Exception) -> None:
            super().__init__("ntn_setup")
            self.answer = answer

        def resolve_database(self, identifier: str) -> str:
            return identifier

        def database(self, database_id: str) -> dict[str, Any]:
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    def titled(client: object) -> dict[str, str]:
        api = SimpleNamespace(runner=SimpleNamespace(client=client))
        return web_setup._titled(api, workspace)  # type: ignore[arg-type]

    answered = {
        "title": [{"plain_text": "Master "}, {"plain_text": "workspace"}],
        "url": f"https://www.notion.so/{workspace}",
    }
    assert titled(Answering(answered)) == {
        "name": "Master workspace",
        "url": f"https://www.notion.so/{workspace}",
    }
    assert titled(Answering(notion.NotionError("object not found"))) == {}, "no name, no failure"
    assert titled(object()) == {}, "a board that is not Notion has no title to read"


@case
def the_summary_does_not_count_gh_among_what_this_machine_lacks() -> None:
    """gh is optional, and the GitHub line already says whether it answers."""
    from ponos import prerequisites
    from ponos.web import setup as web_setup

    def lacking(*missing: str) -> dict[str, Any]:
        needs = [
            prerequisites.Need(name, name not in missing, name != "gh", "")
            for name in ("git", "gh", "claude", "disk")
        ]
        original = prerequisites.check
        prerequisites.check = lambda state, minimum: needs  # type: ignore[assignment]
        try:
            return web_setup._machine(0)
        finally:
            prerequisites.check = original

    alone = lacking("gh")
    assert alone["state"] == "ok"
    assert "gh" not in [need["name"] for need in alone["needs"]]
    with_claude = lacking("gh", "claude")
    assert with_claude["state"] == "error"
    assert [need["name"] for need in with_claude["needs"] if not need["ok"]] == ["claude"]


@case
def the_summary_and_doctor_agree_on_a_workspace_folder_that_does_not_exist_yet() -> None:
    """The default folder is created, not reported: the summary's OK is what doctor sees next."""
    from ponos import health
    from ponos.web import setup as web_setup

    root = Path(tempfile.mkdtemp()) / "workspace"
    path, _ = _saved(f'[runner]\nworkspace_root = "{root}"\n')
    api = _api(path)
    said = web_setup._projects(api.config)
    assert said == {"state": "ok", "root": str(root), "repositories": 0, "configured": 0}
    assert root.is_dir()
    (check,) = health._workspace_root(api.config)
    assert check.state == health.OK, check


@case
def a_demonstration_ticket_that_failed_names_why_the_session_would_not_start(
    state_home: Path,
) -> None:
    """Without `claude`, the failure says it is not installed — and what installs it."""
    from ponos import prerequisites, provider, session
    from ponos.web import setup as web_setup

    path, _ = _saved()
    real = _Fresh(path)
    ticket = "0a1b2c3d" * 4

    class Api:
        config = real.config

        def board(self) -> dict[str, Any]:
            return {
                "tickets": [
                    {
                        "id": ticket,
                        "title": "Dire bonjour",
                        "url": "",
                        "column": "blocked",
                        "status": "blocked",
                        "progress": "",
                    }
                ]
            }

    log = C.state_dir() / "web" / f"demo-{ticket}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "  ! how much of the subscription is spent could not be read\n"
        "  ! context.md is empty — nothing about you reaches the agent\n"
        "    ✗ Dire bonjour — la session Claude n'a pas voulu démarrer\n",
        encoding="utf-8",
    )
    original = session.available, provider.cli_login
    try:
        with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
            session.available = lambda: ""
            said = web_setup.demo_state(Api(), ticket)  # type: ignore[arg-type]  # a double
            assert said["cause"] == "Claude Code is not installed on this machine"
            assert said["command"] == prerequisites.CLAUDE_INSTALL
            assert "pas voulu démarrer" in said["said"] and "subscription" not in said["said"]
            session.available = lambda: "/usr/bin/claude"
            provider.cli_login = lambda: provider.Check(False, "not signed in")
            said = web_setup.demo_state(Api(), ticket)  # type: ignore[arg-type]  # a double
            assert said["cause"] == "Claude Code is not signed in"
            assert said["command"] == provider.LOGIN
    finally:
        session.available, provider.cli_login = original
