"""`config.py`: what the file says, what it falls back on, and the secrets kept beside it."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from support import _board, _config, _environment, _markdown_api, _saved, _state, _state_home, case

from ponos import config as C
from ponos import db, project_settings, state, update, vault, voice
from ponos import git as git_module
from ponos.__main__ import build_parser
from ponos.web import settings as web_settings

# -- configuration -----------------------------------------------------------


@case
def a_database_reference_is_normalised_but_a_name_is_not():
    assert (
        C._database_id(
            "https://www.notion.so/w/Master-Tickets-3c3451680af480f5b1aad0785c0322b4?v=1"
        )
        == "3c3451680af480f5b1aad0785c0322b4"
    )
    assert (
        C._database_id("3c345168-0af4-80f5-b1aa-d0785c0322b4") == "3c3451680af480f5b1aad0785c0322b4"
    )
    # Not an identifier: handed back untouched, to be looked up by name.
    assert C._database_id("Master Tickets") == "Master Tickets"
    assert C.is_identifier("3c3451680af480f5b1aad0785c0322b4")
    assert not C.is_identifier("Master Tickets")


@case
def blocked_falls_back_on_failed_but_only_when_unset():
    config = _config('[notion.status]\nfailed = "Blocked"\n')
    assert config.notion.state("blocked") == "Blocked"
    assert config.notion.state("ready") == "Ready", "defaults survive a partial block"

    config = _config('[notion.status]\nfailed = "Draft"\nblocked = "Blocked"\n')
    assert config.notion.state("failed") == "Draft"
    assert config.notion.state("blocked") == "Blocked"

    config = _config("")
    assert config.notion.state("review") == "In review"
    assert config.notion.state("done") == "Done"
    assert config.notion.state("blocked") == "Blocked", "its own column, not the failure one"
    assert config.notion.state("failed") == "Failed"


@case
def review_falls_back_on_done_but_only_when_done_is_named():
    """A file that names `done` and not `review` has one column for both.

    Which is also what turns the merge watch off: there is no column for a
    ticket to wait in, so there is nothing to watch. A file that names neither
    gets the defaults, which are two — an open pull request and a merged one
    are not the same day.
    """
    config = _config('[notion.status]\ndone = "Shipped"\n')
    assert config.notion.state("review") == config.notion.state("done") == "Shipped"

    config = _config("")
    assert config.notion.state("review") == "In review"
    assert config.notion.state("done") == "Done", "the defaults keep them apart"

    config = _config('[notion.status]\nreview = "Waiting on you"\ndone = "Shipped"\n')
    assert config.notion.state("review") == "Waiting on you"
    assert config.notion.state("done") == "Shipped"


@case
def a_merge_method_gh_would_refuse_never_reaches_it():
    """The typo is caught here, not by GitHub refusing the merge you watched."""
    assert _config("").runner.merge_method == "squash"
    assert _config('[runner]\nmerge_method = "rebase"\n').runner.merge_method == "rebase"
    assert _config('[runner]\nmerge_method = "MERGE"\n').runner.merge_method == "merge"
    assert _config('[runner]\nmerge_method = "fast-forward"\n').runner.merge_method == "squash"

    assert set(git_module.MERGE_FLAGS) == set(C.MERGE_METHODS)


@case
def force_validated_is_off_for_every_type_until_the_file_says_otherwise():
    """Nothing is merged or published unread by a file that never mentioned it.

    One switch per type, each read on its own, and an empty type — a ticket the
    runner ran by what its project holds — is never one of them.
    """
    quiet = _config("").runner
    assert not any(
        quiet.forces_validation(kind) for kind in ("code", "writing", "external", "publication", "")
    )
    runner = _config(
        "[runner]\nforce_validated_code = true\nforce_validated_publication = true\n"
    ).runner
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
def a_project_with_its_own_validation_overrides_the_file_both_ways():
    """The project's switches when it has them, the file's otherwise.

    A project without its own is the board as it was; one with its own is
    taken at its word, even against the file — on where the file is off, off
    where the file is on. And a database that cannot be read validates nothing.
    """
    eager = _config("[runner]\nforce_validated_code = true\n")
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
def the_validation_line_says_whose_decision_it_was():
    """A report that only said "validated" would not say which switch to turn off."""
    english, french = voice.Voice("en"), voice.Voice("fr")
    line = english.say("forced-validation", kind="Code", source=english.say("forced-by-project"))
    assert line == "Validated automatically (Force validated: Code) — the project's setting"
    assert french.say("forced-by-global") == "réglage global"
    assert french.say("forced-by-project") == "réglage du projet"


@case
def a_project_page_reads_and_saves_its_own_automatic_validation():
    """The tab's two calls: what applies, and the project's own switches saved.

    The switches are worded as the global card words them — the same fields —
    and turning them on starts from the file's values, which `values` already
    carries while the project has none of its own.
    """
    with _state(), _board() as board:
        try:
            page = board.create_row("projects", "Perso", {})
            api = _markdown_api(board)
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
def the_interval_never_reaches_systemd_as_zero():
    assert _config("[runner]\ninterval_seconds = 0\n").runner.interval_seconds == 1
    assert _config("[runner]\ninterval_seconds = 10\n").runner.interval_seconds == 10
    assert _config("").runner.interval_seconds == 1800


@case
def the_update_check_never_runs_more_than_once_a_minute():
    """At a ten-second cadence, an unbounded value would fetch six times a minute."""
    assert _config("").runner.update_interval_seconds == 3600
    assert _config("[runner]\nupdate_interval_seconds = 5\n").runner.update_interval_seconds == 60
    assert _config("").runner.auto_update is True
    assert _config("[runner]\nauto_update = false\n").runner.auto_update is False


@case
def optional_properties_have_names_even_when_absent():
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
        assert config.notion.prop(key), key


@case
def a_workspace_is_named_once_and_the_rest_is_found():
    config = _config("")
    assert config.notion.page("tickets") == "Tickets"
    assert config.notion.page("context") == "Context"
    renamed = _config('[notion.pages]\ncontext = "Qui je suis"\n')
    assert renamed.notion.page("context") == "Qui je suis"
    assert renamed.notion.page("tickets") == "Tickets", "defaults survive a partial block"


@case
def a_workspace_alone_is_enough_to_run():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntoken = "ntn_real"\n'
        'workspace = "https://www.notion.so/w/3a8451680af480918afcf0eb9cf70e7b?v=1"\n'
    )
    C.move_secrets(path)
    config = C.load(path)
    assert config.notion.workspace == "3a8451680af480918afcf0eb9cf70e7b", "URL reduced to an ID"
    assert not config.notion.tickets_database
    config.require_usable()  # neither raises nor needs a tickets database


@case
def neither_a_workspace_nor_a_database_is_refused():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\n')
    try:
        C.load(path).require_usable()
    except C.ConfigError as error:
        assert "notion.workspace" in str(error)
    else:
        raise AssertionError("a configuration naming no tickets database must be refused")


# -- what a message to the workspace carries ----------------------------------


@case
def in_a_container_a_new_version_is_a_new_image():
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
def a_loop_of_runs_takes_the_lock_like_the_timer_did():
    """`run --every` starts `ponos run` itself, and a run already going turns it away."""
    root = Path(tempfile.mkdtemp())
    config = root / "config.toml"
    config.write_text(
        f'[storage]\nmode = "markdown"\npath = "{root / "board"}"\n', encoding="utf-8"
    )
    arguments = build_parser().parse_args(["run", "--every", "1"])
    assert arguments.every == 1
    assert build_parser().parse_args(["run", "--every"]).every == 0, "the configuration's interval"
    with _environment(PONOS_CONFIG=str(config)), _state_home():
        with state.lock():
            answered = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; from ponos.__main__ import run_every, build_parser;"
                        "sys.exit(run_every(build_parser().parse_args(['run', '--every', '1']), passes=2))"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            )
        assert answered.returncode == 0, answered.stderr
        assert answered.stdout.count("a run is already in progress") == 2, answered.stdout


@case
def the_consoles_sign_in_may_live_in_the_environment_rather_than_the_file():
    """A server has somewhere better to put a password than a file you read out.

    The environment wins, which is what makes it worth setting — and what comes
    out of it is stripped, because a password read out of a file carries the
    newline that file ends with and would lock you out of your own console.
    """
    path, config = _saved('\n[web]\nemail = "file@example.com"\npassword = "written down"\n')
    assert config.web.email == "file@example.com" and config.web.password == "written down"

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
def the_consoles_trusted_proxies_come_from_the_file_or_else_the_environment():
    """Traefik's address is only known to the deployment: a container says it.

    The file wins once it carries the line — even empty, which trusts nobody.
    """
    path, config = _saved()
    assert config.web.trusted_proxies == ("127.0.0.1", "::1"), "this machine, by default"
    with _environ(**{C.TRUSTED_PROXIES_ENV: " 10.0.1.5, ,10.0.2.0/24 "}):
        assert C.load(path).web.trusted_proxies == ("10.0.1.5", "10.0.2.0/24")
        written, _ = _saved('\n[web]\ntrusted_proxies = ["192.0.2.1"]\n')
        assert C.load(written).web.trusted_proxies == ("192.0.2.1",)
        nobody, _ = _saved("\n[web]\ntrusted_proxies = []\n")
        assert C.load(nobody).web.trusted_proxies == ()


@contextmanager
def _environ(**values: str):
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
def a_secret_left_in_config_toml_is_never_read():
    """The file is copied into images and pasted into tickets: no secret in it.

    Every key `SECRETS` names is ignored there, and said to be — `exposed` is
    what the launch and `doctor` read to tell somebody.
    """
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntoken = "ntn_real"\nworkspace = "3a8451680af480918afcf0eb9cf70e7b"\n'
        '[web]\ntoken = "tok"\npassword = "pw"\n[claude]\napi_key = "sk-ant-x"\n'
        '[openrouter]\nkey = "sk-or-x"\n[github_access]\ntoken = "github_pat_x"\n'
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n[notify.slack]\ntoken = "xoxb-1"\n'
    )
    config = C.load(path)
    assert not config.notion.token and not config.web.token and not config.web.password
    assert (
        not config.claude.api_key and not config.openrouter.key and not config.github_access.token
    )
    assert "token" not in config.notify.telegram and config.notify.telegram["chat"] == "42"
    assert "token" not in config.notify.slack
    assert set(config.exposed) == {f"{table}.{key}" for table, key in C.SECRETS}
    try:
        config.require_usable()
    except C.ConfigError as error:
        assert "PONOS_NOTION_TOKEN" in str(error) and "secrets.env" in str(error), error
    else:
        raise AssertionError("a token only config.toml holds is no token")

    # The example's placeholder is where a token went, not one.
    path.write_text(f'[notion]\ntoken = "{C.PLACEHOLDER}"\n')
    assert C.load(path).exposed == ()


@case
def a_launch_moves_the_secrets_out_of_config_toml_and_says_so():
    """An installation that updates itself must not wake up without its token.

    Moved, not copied: the file and its backup are left with no secret in them,
    the comments around stay, and `secrets.env` is private from its first byte.
    A variable secrets.env already holds was put there later: it is kept.
    """
    from ponos import __main__ as cli

    folder = Path(tempfile.mkdtemp())
    path = folder / "config.toml"
    text = (
        '[notion]\n# the integration\ntoken = "ntn_real"\nworkspace = "w"\n'
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
        '[openrouter]\nkey = "sk-or-old"\n'
    )
    path.write_text(text)
    path.chmod(0o640)
    (folder / "config.toml.bak").write_text(text)
    C.write_secrets(C.secrets_path(path), {"OPENROUTER_API_KEY": "sk-or-new"})

    said: list[str] = []
    with _environ(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert len(said) == 1 and "notion.token" in said[0] and "secrets.env" in said[0], said

    stored = C.read_secrets(C.secrets_path(path))
    assert stored == {
        "PONOS_NOTION_TOKEN": "ntn_real",
        "PONOS_TELEGRAM_TOKEN": "123:abc",
        "OPENROUTER_API_KEY": "sk-or-new",
    }, stored
    assert (C.secrets_path(path).stat().st_mode & 0o777) == 0o600
    for left in (path, folder / "config.toml.bak"):
        written = left.read_text()
        assert "ntn_real" not in written and "123:abc" not in written and "sk-or" not in written
        assert "# the integration" in written and 'chat = "42"' in written
    assert (path.stat().st_mode & 0o777) == 0o640, "the file keeps its own mode"

    config = C.load(path)
    assert config.notion.token == "ntn_real" and config.notify.telegram["token"] == "123:abc"
    assert config.openrouter.key == "sk-or-new" and config.exposed == ()

    said.clear()
    with _environ(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert said == [], "a second launch has nothing to say"

    C.secrets_path(path).chmod(0o644)
    with _environ(PONOS_CONFIG=str(path)):
        cli.secrets_out_of_config(said.append)
    assert said and "chmod 600" in said[0], said


@case
def the_console_writes_a_secret_beside_the_file_never_in_it():
    """The Settings tab and the first connection save through `config.edit`."""
    path, config = _saved('\n[claude]\nprovider = "api_key"\n')
    saved = web_settings.save(
        config, {"settings": {"claude.api_key": "sk-ant-typed", "runner.max_concurrent": 3}}
    )
    assert set(saved["saved"]) == {"claude.api_key", "runner.max_concurrent"}, saved
    written = path.read_text()
    assert "sk-ant-typed" not in written and "max_concurrent = 3" in written
    assert C.read_secrets(C.secrets_path(path))["ANTHROPIC_API_KEY"] == "sk-ant-typed"
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
    assert "ANTHROPIC_API_KEY" not in C.read_secrets(C.secrets_path(path))
    assert C.read_secrets(C.secrets_path(path))["PONOS_NOTION_TOKEN"] == "ntn_real"


@case
def a_typed_key_wins_over_the_environment_and_the_environment_over_a_password():
    """Who wrote it last: the console writes secrets.env, a compose file the
    environment — except for the sign-in, which the environment is there to claim."""
    path, _ = _saved()
    C.write_secrets(
        C.secrets_path(path), {"ANTHROPIC_API_KEY": "typed", "PONOS_WEB_PASSWORD": "typed too"}
    )
    with _environ(
        ANTHROPIC_API_KEY="composed",
        PONOS_WEB_PASSWORD="from the unit",
        PONOS_SLACK_TOKEN="xoxb-env",
    ):
        config = C.load(path)
    assert config.claude.api_key == "typed"
    assert config.web.password == "from the unit"
    assert config.notify.slack == {"token": "xoxb-env"}, "the environment alone is enough"


@case
def every_secret_the_runner_reads_is_masked():
    """From the environment or from secrets.env, a value read is a value masked.

    Even the one that loses to the other: a session that prints it leaks it all
    the same. See vault.py.
    """
    path, _ = _saved()
    C.write_secrets(C.secrets_path(path), {"PONOS_NOTION_TOKEN": "ntn_written-in-the-file"})
    try:
        with _environ(
            PONOS_NOTION_TOKEN="ntn_set-by-compose",
            PONOS_WEB_PASSWORD="password-set-by-compose",
            PONOS_TELEGRAM_TOKEN="123456:telegram-token",
        ):
            C.load(path)
        said = "ntn_written-in-the-file ntn_set-by-compose password-set-by-compose 123456:telegram-token"
        assert vault.mask(said) == " ".join([vault.MASK] * 4), vault.mask(said)
    finally:
        vault.forget()


@case
def secrets_env_reads_what_a_shell_and_compose_read():
    """One file for `source`, `env_file` and `EnvironmentFile` — and for us."""
    path = Path(tempfile.mkdtemp()) / "secrets.env"
    awkward = 'a "quoted" pass $HOME `x` \\ end'
    assert C.write_secrets(path, {"PONOS_WEB_PASSWORD": awkward, "PONOS_WEB_TOKEN": "t0k"}) == [
        "PONOS_WEB_PASSWORD",
        "PONOS_WEB_TOKEN",
    ]
    assert C.read_secrets(path) == {"PONOS_WEB_PASSWORD": awkward, "PONOS_WEB_TOKEN": "t0k"}
    shell = subprocess.run(
        ["sh", "-c", f'. "{path}"; printf %s "$PONOS_WEB_PASSWORD"'],
        capture_output=True,
        text=True,
    )
    assert shell.stdout == awkward, shell.stdout

    path.write_text("# mine\nexport OTHER='kept'\nPONOS_WEB_TOKEN=old\n")
    assert C.write_secrets(path, {"PONOS_WEB_TOKEN": "new"}) == ["PONOS_WEB_TOKEN"]
    assert C.write_secrets(path, {"PONOS_WEB_TOKEN": "new"}) == [], "nothing moved, nothing written"
    assert path.read_text() == "# mine\nexport OTHER='kept'\nPONOS_WEB_TOKEN=new\n"
    assert C.read_secrets(path)["OTHER"] == "kept"
