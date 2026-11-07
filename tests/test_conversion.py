"""`conversion.py`: `ponos config` rewrites a file an older version wrote, once."""

from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from support import _board, _environment, case

from ponos import config as C
from ponos import conversion, project_settings, vault_store

# A file as the four steps found it: retired keys, the four booleans, a value
# over several lines, `[projects]` and `[vault.projects]`, a secret, Notion.
OLD = """\
# ponos — configuration

[runner]
language = "fr"
max_load_per_core = 2
worktree_exclude = [
  "node_modules",
  "dist",
]
force_validated_code = true
force_validated_writing = false
model = ""

# Projects whose repository cannot be guessed.
[projects]
"Site vitrine" = "~/workspace/site"
Ghost = "~/workspace/ghost"

# Slack, for the questions.
[notify.slack]
channel = "infra"
default_project = "Ponos"

[web]
token = "a-token-of-the-console"
poll_seconds = 5
port = 8787

[openrouter]
base_url = "https://openrouter.ai/api/v1"

[notion]
workspace = "x"

[notion.pages]
tickets = "y"

[vault]
provider = "env"

[vault.projects]
"Site vitrine" = ["NPM_TOKEN", "PONOS_STOLEN"]
"""

CONVERTED = """\
# ponos — configuration

[runner]
force_validated = ["code"]
language = "fr"
model = ""

# Slack, for the questions.
[notify.slack]
channel = "infra"

[web]
port = 8787

[vault]
provider = "env"
"""


def _written(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def _old_file() -> Path:
    return _written(OLD)


@case
def an_old_file_is_refused_until_it_is_converted_then_reads(vault_home: Path) -> None:
    path = _old_file()
    try:
        C.load(path, secrets={})
    except C.ConfigError as error:
        said = str(error)
    else:
        raise AssertionError("an old file loaded")
    assert "line 32: [notion]" in said and "(ponos config does)" in said, said
    without_notion = OLD.split("[notion]")[0]
    try:
        C.load(_written(without_notion), secrets={})
    except C.ConfigError as error:
        said = str(error)
    assert "line 5: runner.max_load_per_core is not a key of config.toml" in said, said
    assert "ponos config converts a file an older version wrote" in said, said

    with _board() as board:
        site = board.create_row("projects", "Site vitrine", {})
        project_settings.set_vault(site, "Site vitrine", {"NPM_TOKEN": "hermez/npm"})
        done = conversion.convert(path)

    assert path.read_text(encoding="utf-8") == CONVERTED, path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600, "the file keeps its mode"
    backup = conversion.backup_path(path)
    assert done.backup == backup and "max_load_per_core" in backup.read_text(encoding="utf-8")
    assert "a-token-of-the-console" not in backup.read_text(encoding="utf-8"), (
        "the copy kept beside it holds no secret either"
    )
    assert vault_store.own()["PONOS_WEB_TOKEN"] == "a-token-of-the-console"

    assert project_settings.path(site) == "~/workspace/site"
    assert project_settings.vault(site) == {"NPM_TOKEN": "hermez/npm"}, (
        "the project's own key wins over the file's, and the runner's own is never given"
    )
    assert "web.token → Ponos's vault" in done.moved, done.moved
    assert 'projects."Site vitrine" → the Settings tab of Site vitrine' in done.moved
    assert any(line.startswith("runner.force_validated_<type>") for line in done.moved)
    assert {"runner.max_load_per_core", "runner.worktree_exclude", "[notion]"} <= set(
        done.removed
    ), done.removed
    assert any(note.startswith('projects."Ghost": no project of that name') for note in done.notes)
    assert any("PONOS_STOLEN is the runner's own" in note for note in done.notes), done.notes

    config = C.load(path)
    assert config.runner.forces_validation("code") and not config.runner.forces_validation(
        "writing"
    )
    assert config.notify.slack["channel"] == "infra"


@case
def converting_twice_changes_nothing_the_second_time(vault_home: Path) -> None:
    path = _old_file()
    with _board() as board:
        board.create_row("projects", "Site vitrine", {})
        first = conversion.convert(path)
        converted = path.read_text(encoding="utf-8")
        backup = conversion.backup_path(path).read_text(encoding="utf-8")
        second = conversion.convert(path)
    assert first.changed and not second.changed
    assert second.moved == second.removed == [] and second.backup is None
    assert path.read_text(encoding="utf-8") == converted
    assert conversion.backup_path(path).read_text(encoding="utf-8") == backup, (
        "the copy of the old file is not overwritten by the converted one"
    )


@case
def a_file_already_in_todays_format_is_left_as_it_is(vault_home: Path) -> None:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(CONVERTED, encoding="utf-8")
    done = conversion.convert(path)
    assert not done.changed and done.backup is None
    assert not conversion.backup_path(path).exists()
    assert path.read_text(encoding="utf-8") == CONVERTED


@case
def an_empty_projects_table_goes_and_is_said_without_opening_the_board() -> None:
    """The example's `[projects]`, a comment and nothing else: no project to look up."""
    path = _written('[runner]\nmodel = ""\n\n# Projects, by name.\n[projects]\n# "A" = "~/a"\n')
    done = conversion.convert(path)
    assert done.changed and done.removed == ["[projects], empty"], done.removed
    assert path.read_text(encoding="utf-8") == '[runner]\nmodel = ""\n'


@case
def a_key_nobody_ever_read_is_left_for_the_person_to_correct(vault_home: Path) -> None:
    """A typo may be a real key misspelt: the conversion does not guess, the load names it."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[runner]\nmax_concurent = 4\nfetch = true\n", encoding="utf-8")
    done = conversion.convert(path)
    assert done.removed == ["runner.fetch"]
    assert path.read_text(encoding="utf-8") == "[runner]\nmax_concurent = 4\n"
    try:
        C.load(path, secrets={})
    except C.ConfigError as error:
        assert "line 2: runner.max_concurent is not a key" in str(error), str(error)
    else:
        raise AssertionError("a typo loaded")


@case
def ponos_config_converts_says_what_moved_and_opens_nothing(vault_home: Path) -> None:
    from ponos import __main__ as cli

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[runner]\nfetch = true\n\n[review]\nci_retries = 2\n", encoding="utf-8")
    out = io.StringIO()
    with _environment(PONOS_CONFIG=str(path), EDITOR="false"), redirect_stdout(out):
        code = cli.main(["config"])
        again = cli.main(["config", "--convert"])
    said = out.getvalue()
    assert code == 0 and again == 0, said
    assert "removed  runner.fetch" in said and "removed  [review]" in said, said
    assert f"kept as {conversion.backup_path(path)}" in said, said
    assert "already in today's format: nothing to convert" in said, said
    assert path.read_text(encoding="utf-8") == "[runner]\n"
