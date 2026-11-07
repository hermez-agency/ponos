"""`config.py`: what the file says, what it falls back on, and the secrets kept beside it."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from support import _board, _config, _environment, _local_api, _saved, _state, _state_home, case

from ponos import config as C
from ponos import db, github_checks, project_settings, state, update, vault, voice
from ponos.__main__ import build_parser
from ponos.web import settings as web_settings

# -- configuration -----------------------------------------------------------


@case
def the_names_of_the_board_are_fixed() -> None:
    names = _config("").board
    assert names.prop("status") == "statut" and names.prop("agent") == "Agent"
    assert names.state("ready") == "ready" and names.state("blocked") == "blocked"
    assert names.kind("writing") == "Rédaction"
    assert "failed" not in C.STATUS, "one status for a ticket that stopped"
    assert names.state("draft") == "draft"
    assert names.prop("role") == "Rôle", "the role is not the machine's « Agent »"


@case
def a_file_that_still_holds_the_old_board_table_is_refused_with_its_line() -> None:
    """Written for the board Ponos used to be told about: say to take it out, read nothing."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('# mine\n[notion]\ntoken = "x"\n[notion.pages]\ncontext = "Soul"\n')
    try:
        C.load(path)
    except C.ConfigError as error:
        said = str(error)
        assert f"{path}, line 2: [notion]" in said and "Remove this table" in said, said
    else:
        raise AssertionError("the file must not be read")


@case
def a_merge_method_gh_would_refuse_never_reaches_it() -> None:
    """The typo is caught here, not by GitHub refusing the merge you watched."""
    assert _config("").runner.merge_method == "squash"
    assert _config('[runner]\nmerge_method = "rebase"\n').runner.merge_method == "rebase"
    assert _config('[runner]\nmerge_method = "MERGE"\n').runner.merge_method == "merge"
    assert _config('[runner]\nmerge_method = "fast-forward"\n').runner.merge_method == "squash"

    assert set(github_checks.MERGE_FLAGS) == set(C.MERGE_METHODS)


@case
def force_validated_is_off_for_every_type_until_the_file_says_otherwise() -> None:
    """Nothing is merged or published unread by a file that never mentioned it.

    One switch per type, each read on its own, and an empty type — a ticket the
    runner ran by what its project holds — is never one of them.
    """
    quiet = _config("").runner
    assert not any(
        quiet.forces_validation(kind) for kind in ("code", "writing", "external", "publication", "")
    )
    runner = _config('[runner]\nforce_validated = ["code", "publication"]\n').runner
    assert runner.forces_validation("code") and runner.forces_validation("publication")
    assert not runner.forces_validation("writing")
    assert not runner.forces_validation("external")
    assert not runner.forces_validation("")

    # And the console can tick them, one box per type, where it saves them.
    path, config = _saved()
    for kind in ("code", "writing", "external", "publication"):
        field = web_settings.FIELDS[f"runner.force_validated_{kind}"]
        assert field.kind == "bool", field
    web_settings.save(config, {"settings": {"runner.force_validated_code": True}})
    assert C.load(path).runner.forces_validation("code")
    web_settings.save(config, {"settings": {"runner.force_validated_code": None}})
    assert not C.load(path).runner.forces_validation("code")


@case
def a_project_with_its_own_validation_overrides_the_file_both_ways() -> None:
    """The project's switches when it has them, the file's otherwise.

    A project without its own is the board as it was; one with its own is
    taken at its word, even against the file — on where the file is off, off
    where the file is on. And a database that cannot be read validates nothing.
    """
    eager = _config('[runner]\nforce_validated = ["code"]\n')
    quiet = _config("")
    page = "1234abcd-0000-0000-0000-00000000beef"
    with _state():
        try:
            assert project_settings.validation(page) is None
            assert project_settings.forced_validation(eager, "code", page) == "global"
            assert project_settings.forced_validation(quiet, "code", page) == ""
            assert project_settings.forced_validation(eager, "", page) == ""

            # Off on the project, on in the file: the project wins.
            project_settings.set_validation(page, "Client", {"code": False, "publication": True})
            assert project_settings.forced_validation(eager, "code", page) == ""
            assert project_settings.forced_validation(eager, "publication", page) == "project"
            # On on the project, off in the file: the project wins again.
            project_settings.set_validation(page, "Client", {"code": True})
            assert project_settings.forced_validation(quiet, "code", page) == "project"
            assert project_settings.forced_validation(quiet, "publication", page) == ""
            # Another project, and a project without a page, still follow the file.
            assert project_settings.forced_validation(eager, "code", "f" * 32) == "global"
            assert project_settings.forced_validation(eager, "code", "") == "global"

            # Keyed by the page whichever way its id is spelled, and kept across
            # a restart: the connection closed, the file opened again.
            db.close()
            assert project_settings.validation(page.replace("-", "").upper()) == {
                "code": True,
                "writing": False,
                "external": False,
                "publication": False,
                "diagnostic": False,
            }
            assert project_settings.owning_validation() == [
                {"id": page.replace("-", ""), "name": "Client"}
            ]

            # Handed back to the file: the row goes, and the file decides again.
            project_settings.set_validation(page, "Client", None)
            assert project_settings.validation(page) is None
            assert project_settings.owning_validation() == []
            assert project_settings.forced_validation(eager, "code", page) == "global"

            # A database that cannot be read is never a merge nobody read.
            original = project_settings.validation

            def broken(project: str) -> None:
                raise db.DatabaseError("locked")

            project_settings.validation = broken
            try:
                assert project_settings.forced_validation(eager, "code", page) == ""
            finally:
                project_settings.validation = original
        finally:
            db.close()


@case
def the_validation_line_says_whose_decision_it_was() -> None:
    """A report that only said "validated" would not say which switch to turn off."""
    english, french = voice.Voice("en"), voice.Voice("fr")
    line = english.say("forced-validation", kind="Code", source=english.say("forced-by-project"))
    assert line == "Validated automatically (Force validated: Code) — the project's setting"
    assert french.say("forced-by-global") == "réglage global"
    assert french.say("forced-by-project") == "réglage du projet"


@case
def a_project_page_reads_and_saves_its_own_automatic_validation() -> None:
    """The tab's two calls: what applies, and the project's own switches saved.

    The switches are worded as the global card words them — the same fields —
    and turning them on starts from the file's values, which `values` already
    carries while the project has none of its own.
    """
    with _state(), _board() as board:
        try:
            page = board.create_row("projects", "Perso", {})
            api = _local_api(board)
            api._config.runner.force_validated_publication = True
            read = api.project_settings(page)
            validation = read["validation"]
            assert validation["own"] is False
            assert validation["global"]["publication"] is True
            assert validation["values"] == validation["global"]
            section = next(item for item in web_settings.SECTIONS if item.key == "validation")
            assert [field["label"] for field in validation["fields"]] == [
                field.label for field in section.fields
            ]
            assert [field["kind"] for field in validation["fields"]] == [
                "code",
                "publication",
                "writing",
                "external",
            ]

            saved = api.save_project_settings(
                page, {"validation": {"own": True, "values": {"code": True, "publication": False}}}
            )
            assert saved["validation"]["own"] is True
            assert saved["validation"]["values"]["code"] is True
            assert saved["validation"]["values"]["publication"] is False
            assert saved["validation"]["global"]["publication"] is True
            assert project_settings.owning_validation() == [
                {"id": project_settings.key(page), "name": "Perso"}
            ]

            for wrong in (
                {},
                {"validation": {"own": "yes"}},
                {"validation": {"own": True, "values": {"deploy": True}}},
                {"validation": {"own": True, "values": {"code": "on"}}},
            ):
                try:
                    api.save_project_settings(page, wrong)
                except ValueError:
                    continue
                raise AssertionError(f"{wrong} should have been refused")

            back = api.save_project_settings(page, {"validation": {"own": False}})
            assert back["validation"]["own"] is False
            assert back["validation"]["values"] == back["validation"]["global"]
            assert project_settings.owning_validation() == []
        finally:
            db.close()


@case
def a_project_page_sets_its_path_and_its_vault_keys_without_the_toml() -> None:
    with _state(), _board() as board:
        try:
            page = board.create_row("projects", "Perso", {})
            api = _local_api(board)
            read = api.project_settings(page)
            assert read["path"] == {"value": ""}
            assert read["vault"]["entries"] == {} and "file" not in read["vault"]
            saved = api.save_project_settings(page, {"path": {"value": "~/workspace/perso"}})
            assert saved["path"]["value"] == "~/workspace/perso"
            saved = api.save_project_settings(
                page, {"vault": {"entries": {"NPM_TOKEN": "hermez/npm"}}}
            )
            assert saved["vault"]["entries"] == {"NPM_TOKEN": "hermez/npm"}
            assert saved["path"]["value"] == "~/workspace/perso", "one save leaves the other"
            wrongs: list[dict[str, Any]] = [
                {"path": {"value": 3}},
                {"vault": {"entries": {"ANTHROPIC_API_KEY": "x"}}},
                {"vault": {"entries": {"not a name": "x"}}},
                {"vault": {"entries": []}},
            ]
            for wrong in wrongs:
                try:
                    api.save_project_settings(page, wrong)
                except ValueError:
                    continue
                raise AssertionError(f"{wrong} should have been refused")
            cleared = api.save_project_settings(
                page, {"path": {"value": ""}, "vault": {"entries": {}}}
            )
            assert cleared["path"]["value"] == ""
        finally:
            db.close()


@case
def the_interval_never_reaches_systemd_as_zero() -> None:
    assert _config("[runner]\ninterval_seconds = 0\n").runner.interval_seconds == 1
    assert _config("[runner]\ninterval_seconds = 10\n").runner.interval_seconds == 10
    assert _config("").runner.interval_seconds == 1800


@case
def the_update_check_keeps_its_hourly_constant() -> None:
    """The interval of the check is no key any more: the file cannot ask for a fetch a second."""
    assert _config("").runner.update_interval_seconds == 3600
    assert _config("").runner.auto_update is True
    assert _config("[runner]\nauto_update = false\n").runner.auto_update is False


@case
def optional_properties_have_names_even_when_absent() -> None:
    config = _config("")
    for key in (
        "status",
        "project",
        "agent",
        "pull_request",
        "session",
        "model",
        "priority",
        "cost",
        "duration",
    ):
        assert config.board.prop(key), key


# -- what a message to the workspace carries ----------------------------------


@case
def in_a_container_a_new_version_is_a_new_image() -> None:
    """No link to move and no unit to restart: the image is the version."""
    from ponos.web import upgrade as web_upgrade

    with _environment(PONOS_CONTAINER="1"), _state_home():
        status = update.check()
        assert status.reason == update.CONTAINER and not status.stale
        assert update.apply(update.Status(current="a", latest="b"), 60) == update.CONTAINER
        said: list[str] = []
        update.between_runs(C.Runner(), say=said.append, notify=lambda *_: None)
        assert said == [], "nothing to say once an hour about something that cannot happen"
        upgrade = web_upgrade.Upgrade(lambda *a, **k: None, C.Runner)
        offer = upgrade.offer()
        assert offer["automatic"] is False and "new image" in offer["manual"]
        assert offer["command"] == update.PULL
        try:
            upgrade.start()
        except RuntimeError as error:
            assert "new image" in str(error)
        else:
            raise AssertionError("no update starts in a container")


@case
def a_run_beside_the_daemon_asks_it_to_look_rather_than_running_a_second_scheduler() -> None:
    """`ponos run` with a daemon holding the places wakes it (SIGUSR1) and starts nothing itself."""
    import signal

    root = Path(tempfile.mkdtemp())
    config = root / "config.toml"
    config.write_text("[runner]\n", encoding="utf-8")
    assert build_parser().parse_args(["daemon"]).function.__name__ == "command_daemon"
    try:
        build_parser().parse_args(["run", "--every", "1"])
    except SystemExit:
        pass
    else:
        raise AssertionError("`run --every` is gone: the daemon replaced it")
    woken = threading.Event()
    previous = signal.signal(signal.SIGUSR1, lambda *_: woken.set())
    try:
        with _environment(PONOS_CONFIG=str(config)), _state_home(), state.scheduling():
            answered = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; from ponos.__main__ import command_run, build_parser;"
                        "sys.exit(command_run(build_parser().parse_args(['run'])))"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    **os.environ,
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                },
            )
            assert woken.wait(10), "the daemon was not woken"
    finally:
        signal.signal(signal.SIGUSR1, previous)
    assert answered.returncode == 0, answered.stderr + answered.stdout
    assert "is looking at the board now" in answered.stdout, answered.stdout


@case
def the_consoles_sign_in_may_live_in_the_environment_rather_than_the_file() -> None:
    """A server has somewhere better to put a password than a file you read out.

    The environment wins, which is what makes it worth setting — and what comes
    out of it is stripped, because a password read out of a file carries the
    newline that file ends with and would lock you out of your own console.
    """
    from ponos import passwords

    path, config = _saved('\n[web]\nemail = "file@example.com"\npassword = "written down"\n')
    assert config.web.email == "file@example.com"
    assert passwords.matches("written down", config.web.password), (
        "moved into the vault as its digest"
    )

    previous = {name: os.environ.get(name) for name in (C.WEB_EMAIL_ENV, C.WEB_PASSWORD_ENV)}
    os.environ[C.WEB_EMAIL_ENV] = "unit@example.com"
    os.environ[C.WEB_PASSWORD_ENV] = "from the unit\n"
    try:
        fresh = C.load(path)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert fresh.web.email == "unit@example.com"
    assert fresh.web.password == "from the unit"


@case
def the_consoles_trusted_proxies_come_from_the_file_or_else_the_environment() -> None:
    """Traefik's address is only known to the deployment: a container says it.

    Not a key of the file any more: the environment answers.
    """
    path, config = _saved()
    assert config.web.trusted_proxies == ("127.0.0.1", "::1"), "this machine, by default"
    with _environ(**{C.TRUSTED_PROXIES_ENV: " 10.0.1.5, ,10.0.2.0/24 "}):
        assert C.load(path).web.trusted_proxies == ("10.0.1.5", "10.0.2.0/24")


@contextmanager
def _environ(**values: str) -> Iterator[None]:
    """Variables set for the length of a block, and put back as they were."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@case
def a_secret_left_in_config_toml_is_never_read() -> None:
    """The file is copied into images and pasted into tickets: no secret in it.

    Every key `SECRETS` names is ignored there, and said to be — `exposed` is
    what the launch and `doctor` read to tell somebody.
    """
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[web]\ntoken = "tok"\npassword = "pw"\n[claude]\napi_key = "sk-ant-x"\n'
        '[openrouter]\nkey = "sk-or-x"\n[github_access]\ntoken = "github_pat_x"\n'
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n[notify.slack]\ntoken = "xoxb-1"\n'
    )
    config = C.load(path)
    assert not config.web.token and not config.web.password
    assert (
        not config.claude.api_key and not config.openrouter.key and not config.github_access.token
    )
    assert "token" not in config.notify.telegram and config.notify.telegram["chat"] == "42"
    assert "token" not in config.notify.slack
    assert set(config.exposed) == {f"{table}.{key}" for table, key in C.SECRETS}

    # An empty value is where a token went, not one.
    path.write_text('[web]\ntoken = ""\n')
    assert C.load(path).exposed == ()


@case
def a_launch_moves_the_secrets_of_config_toml_and_secrets_env_into_the_vault(
    vault_home: Path,
) -> None:
    """An installation that updates itself must not wake up without its token.

    Moved, not copied: the file and its backup are left with no secret in them,
    the comments around stay, `secrets.env` is deleted, and nothing of it is
    left in clear in the vault. What the vault already holds was put there
    later: it is kept, and `secrets.env` wins over `config.toml` for the same
    reason. A password comes in as its digest.
    """
    from ponos import __main__ as cli
    from ponos import passwords, vault_store

    folder = Path(tempfile.mkdtemp())
    path = folder / "config.toml"
    text = (
        '[web]\n# the console\ntoken = "tok_real"\nport = 8787\n'
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
        '[openrouter]\nkey = "sk-or-old"\n'
    )
    path.write_text(text)
    path.chmod(0o640)
    (folder / "config.toml.bak").write_text(text)
    legacy = folder / "secrets.env"
    legacy.write_text(
        "# Ponos's secrets\nOPENROUTER_API_KEY=sk-or-new\n"
        'PONOS_WEB_PASSWORD="a typed password"\nBW_SESSION=bw-session-value\n'
    )
    C.keep_secrets({"PONOS_SLACK_TOKEN": "xoxb-already-in-the-vault"})

    said: list[str] = []
    with _environment(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert len(said) == 1 and "web.token" in said[0] and "Ponos's vault" in said[0], said

    kept = C.kept_secrets()
    password = kept.pop("PONOS_WEB_PASSWORD")
    assert passwords.is_digest(password) and passwords.matches("a typed password", password)
    assert kept == {
        "PONOS_WEB_TOKEN": "tok_real",
        "PONOS_TELEGRAM_TOKEN": "123:abc",
        "OPENROUTER_API_KEY": "sk-or-new",
        "BW_SESSION": "bw-session-value",
        "PONOS_SLACK_TOKEN": "xoxb-already-in-the-vault",
    }, kept
    assert not legacy.exists(), "secrets.env is gone once the vault holds it"
    sealed = vault_store.path().read_bytes()
    for value in ("tok_real", "123:abc", "sk-or-new", "a typed password", "bw-session-value"):
        assert value.encode() not in sealed, value
    assert (vault_store.path().stat().st_mode & 0o777) == 0o600
    for left in (path, folder / "config.toml.bak"):
        written = left.read_text()
        assert "tok_real" not in written and "123:abc" not in written and "sk-or" not in written
        assert "# the console" in written and 'chat = "42"' in written
    assert (path.stat().st_mode & 0o777) == 0o640, "the file keeps its own mode"

    config = C.load(path)
    assert config.web.token == "tok_real" and config.notify.telegram["token"] == "123:abc"
    assert config.openrouter.key == "sk-or-new" and config.exposed == ()

    said.clear()
    with _environment(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert said == [], "a second launch has nothing to say"

    # A line typed into the file again, after: refused — moved out, never read,
    # and the vault's own value kept.
    path.write_text(path.read_text().replace("port = 8787", 'port = 8787\ntoken = "tok_stale"'))
    assert C.load(path).web.token == "tok_real", "never read from the file"
    with _environment(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert "tok_stale" not in path.read_text() and C.kept_secrets()["PONOS_WEB_TOKEN"] == "tok_real"


@case
def the_console_writes_a_secret_into_the_vault_never_in_the_file(vault_home: Path) -> None:
    """The Settings tab and the first connection save through `config.edit`."""
    from ponos import vault_store

    path, config = _saved('\n[claude]\nprovider = "api_key"\n')
    C.keep_secrets({"PONOS_WEB_TOKEN": "tok_real"})
    saved = web_settings.save(
        config, {"settings": {"claude.api_key": "sk-ant-typed", "runner.max_concurrent": 3}}
    )
    assert set(saved["saved"]) == {"claude.api_key", "runner.max_concurrent"}, saved
    written = path.read_text()
    assert "sk-ant-typed" not in written and "max_concurrent = 3" in written
    assert C.exposed(C.read_raw(path)) == [], "no secret in the file after a save"
    assert C.kept_secrets()["ANTHROPIC_API_KEY"] == "sk-ant-typed"
    assert b"sk-ant-typed" not in vault_store.path().read_bytes(), "sealed, not in clear"
    assert not (path.parent / "secrets.env").exists()
    assert "sk-ant" not in (path.parent / "config.toml.bak").read_text()

    fresh = C.load(path)
    assert fresh.claude.api_key == "sk-ant-typed"
    field = next(
        item
        for section in web_settings.describe(fresh)["sections"]
        for item in section["fields"]
        if item["name"] == "claude.api_key"
    )
    assert field["stated"] and field["preview"] == "…yped" and field["value"] == ""

    web_settings.save(fresh, {"settings": {"claude.api_key": None}})
    assert "ANTHROPIC_API_KEY" not in C.kept_secrets()
    assert C.kept_secrets()["PONOS_WEB_TOKEN"] == "tok_real"


@case
def a_vault_that_does_not_open_leaves_the_environment_and_refuses_a_save(
    vault_home: Path,
) -> None:
    """Its key gone, the vault gives nothing — the runner still starts — and keeps nothing."""
    from ponos import vault_store

    path, config = _saved()
    C.keep_secrets({"PONOS_WEB_TOKEN": "tok_sealed"})
    vault_store.key_path().unlink()
    vault_store._own_kept = None
    with _environment(PONOS_TELEGRAM_TOKEN="123:from-the-env"):
        loaded = C.load(path)
    assert loaded.web.token == "" and loaded.notify.telegram["token"] == "123:from-the-env"
    try:
        C.edit(path, [("claude", "api_key", "sk-ant-typed")])
    except C.ConfigError as error:
        assert "vault" in str(error), error
    else:
        raise AssertionError("a secret the vault cannot keep is not saved")
    assert "sk-ant-typed" not in path.read_text()


@case
def a_typed_key_wins_over_the_environment_and_the_environment_over_a_password(
    vault_home: Path,
) -> None:
    """Who wrote it last: the console writes the vault, a compose file the
    environment — except for the sign-in, which the environment is there to claim."""
    path, _ = _saved()
    C.keep_secrets({"ANTHROPIC_API_KEY": "typed", "PONOS_WEB_PASSWORD": "typed too"})
    with _environment(
        ANTHROPIC_API_KEY="composed",
        PONOS_WEB_PASSWORD="from the unit",
        PONOS_SLACK_TOKEN="xoxb-env",
    ):
        config = C.load(path)
    assert config.claude.api_key == "typed"
    assert config.web.password == "from the unit"
    assert config.notify.slack == {"token": "xoxb-env"}, "the environment alone is enough"


@case
def every_secret_the_runner_reads_is_masked(vault_home: Path) -> None:
    """From the environment or from the vault, a value read is a value masked.

    Even the one that loses to the other: a session that prints it leaks it all
    the same. See vault.py.
    """
    path, _ = _saved()
    C.keep_secrets({"PONOS_WEB_TOKEN": "tok_written-in-the-vault"})
    vault.forget()
    try:
        with _environment(
            PONOS_WEB_TOKEN="tok_set-by-compose",
            PONOS_WEB_PASSWORD="password-set-by-compose",
            PONOS_TELEGRAM_TOKEN="123456:telegram-token",
        ):
            C.load(path)
        said = "tok_written-in-the-vault tok_set-by-compose password-set-by-compose 123456:telegram-token"
        assert vault.mask(said) == " ".join([vault.MASK] * 4), vault.mask(said)
    finally:
        vault.forget()


@case
def an_old_secrets_env_is_read_the_way_a_shell_read_it() -> None:
    """What `move_secrets` brings into the vault is what `source` and `env_file` read."""
    path = Path(tempfile.mkdtemp()) / "secrets.env"
    awkward = 'a "quoted" pass $HOME `x` \\ end'
    path.write_text(
        "# mine\nexport OTHER='kept'\n"
        'PONOS_WEB_PASSWORD="a \\"quoted\\" pass \\$HOME \\`x\\` \\\\ end"\nPONOS_WEB_TOKEN=t0k\n'
    )
    assert C.read_secrets(path) == {
        "OTHER": "kept",
        "PONOS_WEB_PASSWORD": awkward,
        "PONOS_WEB_TOKEN": "t0k",
    }, C.read_secrets(path)
    shell = subprocess.run(
        ["sh", "-c", f'. "{path}"; printf %s "$PONOS_WEB_PASSWORD"'],
        capture_output=True,
        text=True,
    )
    assert shell.stdout == awkward, shell.stdout


@case
def a_launch_closes_the_state_directory_and_the_folders_at_its_top(state_home: Path) -> None:
    """What sits under them stays as it was: the walk is `ponos doctor`'s."""
    (state_home / "captures").mkdir(mode=0o775, parents=True)
    (state_home / "captures").chmod(0o775)
    shot = state_home / "captures" / "shot.png"
    shot.write_bytes(b"png")
    shot.chmod(0o664)
    state_home.chmod(0o755)
    C.private_state()
    assert state_home.stat().st_mode & 0o777 == 0o700
    assert (state_home / "captures").stat().st_mode & 0o777 == 0o700
    assert shot.stat().st_mode & 0o777 == 0o664
