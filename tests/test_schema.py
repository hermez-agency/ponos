"""`schema.py`: what `config.toml` may say, and what is said when it does not read."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_origin

from support import _config, _environment, case

from ponos import config as C
from ponos import schema

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config.example.toml"

# A key line of the example, live or commented out: `# url = "https://…"` is a
# key the file documents and leaves to its default. The value has to look like
# one, so that prose with an equals sign in it is not taken for a key.
_KEY_LINE = re.compile(
    r"""^(?:#\s?)?("[^"]*"|[A-Za-z0-9_-]+)\s*=\s*(?:"|'|\[|true\b|false\b|-?\d)"""
)
_HEADER_LINE = re.compile(r"^(?:#\s?)?\[([A-Za-z0-9_.\-\" ]+)\]\s*$")


def _documented() -> set[tuple[str, ...]]:
    """Every key the example names, as a path — a free-form table counts as one key."""
    free = _free_tables()
    found: set[tuple[str, ...]] = set()
    table: tuple[str, ...] = ()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if header := _HEADER_LINE.match(line):
            table = tuple(part.strip('"') for part in header.group(1).split("."))
            path = table
        elif key := _KEY_LINE.match(line):
            path = (*table, key.group(1).strip('"'))
        else:
            continue
        for length in range(1, len(path) + 1):
            if path[:length] in free:
                path = path[:length]
                break
        if path not in _tables():
            found.add(path)
    return found


def _walk(
    model: type[schema.Table], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Any]]:
    for name, field in model.model_fields.items():
        kind = field.annotation
        if isinstance(kind, type) and issubclass(kind, schema.Table):
            yield (*prefix, name), kind
            yield from _walk(kind, (*prefix, name))
        else:
            yield (*prefix, name), field


def _tables() -> set[tuple[str, ...]]:
    return {path for path, kind in _walk(schema.File) if isinstance(kind, type)}


def _free_tables() -> set[tuple[str, ...]]:
    """The tables whose keys are the file's to choose: a project, an owner, a column."""
    return {
        path
        for path, field in _walk(schema.File)
        if not isinstance(field, type) and get_origin(field.annotation) is dict
    }


@case
def every_key_the_example_documents_is_one_the_model_reads_and_back() -> None:
    """config.example.toml and schema.py describe the same file.

    A key documented and not read is a setting that does nothing; a key read
    and not documented is one nobody finds. Secrets are neither: they are not
    keys of the file at all.
    """
    modelled = {path for path, _ in _walk(schema.File)} - _tables()
    documented = _documented()
    assert documented - modelled == set(), f"documented, never read: {documented - modelled}"
    assert modelled - documented == set(), f"read, never documented: {modelled - documented}"
    assert len(modelled) <= 60, f"the file was cut down to what is changed: {len(modelled)} keys"


def _written(table: str, key: str) -> str:
    return f"[{table}]\n{key} = 999\n"


def _refused(body: str) -> list[str]:
    """What `load` says of that file, one line each — it must not load."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(body, encoding="utf-8")
    try:
        C.load(path, secrets={})
    except C.ConfigError as error:
        return [line.strip().removeprefix(f"{path}, ") for line in str(error).splitlines()]
    raise AssertionError(f"loaded: {body!r}")


@case
def a_retired_key_still_in_a_file_is_refused_and_named() -> None:
    """Each key the file lost stops the load, by its line — `ponos config` takes it out.

    The whole of `conversion.RETIRED`, one line each: a file an update leaves
    behind is converted once, it is not read with its old lines on the side.
    """
    from ponos import conversion

    for table, keys in conversion.RETIRED.items():
        for key in keys:
            [said] = _refused(_written(table, key))
            assert said.startswith(f"line 2: {table}.{key} is not a key of config.toml"), said
            assert said.endswith("ponos config converts a file an older version wrote"), said
    for table in conversion.RETIRED_TABLES:
        if table == "notion":
            continue  # said in its own words: see the next case
        [said] = _refused(f"[{table}]\nanything = 1\n")
        assert said.startswith(f"line 1: [{table}] is not a table of config.toml"), said
    assert C.Runner().credit_reserve_percent == 5 and C.Runner().push is True


@case
def a_notion_table_is_refused_in_its_own_words() -> None:
    [said] = _refused('[runner]\n\n[notion]\nworkspace = "x"\n')
    assert said.startswith("line 3: [notion] — Ponos no longer works with Notion"), said
    assert "ponos config does" in said, said


@case
def the_four_force_validated_booleans_are_one_list() -> None:
    """`force_validated` names the types; the old booleans are a file to convert."""
    assert _config("").runner.forces_validation("code") is False
    assert _config(
        '[runner]\nforce_validated = ["code", "Publication", "nonsense"]\n'
    ).runner.forces_validation("publication")
    listed = _config('[runner]\nforce_validated = ["code"]\n').runner
    assert listed.forces_validation("code") and not listed.forces_validation("writing")
    said = _refused("[runner]\nforce_validated_code = true\n")
    assert said[0].startswith("line 2: runner.force_validated_code is not a key"), said


@case
def the_example_reads_against_the_model_and_gives_the_defaults() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    file = schema.read(tomllib.loads(text), text, EXAMPLE)
    assert file.runner.workspace_root == "~/workspace"
    assert file.runner.model_copy(update={"workspace_root": ""}) == schema.RunnerTable(
        workspace_root=""
    )
    assert file.web == schema.WebTable()
    assert file.budget == schema.BudgetTable(), "a blank amount is no limit, as the default"
    assert file.permissions == schema.PermissionsTable()


@case
def the_tolerances_of_the_old_loader_are_kept() -> None:
    """A typo in a choice is the default, a value past a floor is the floor.

    What `config.load` always did, and what an installation's file may rely on
    without anybody knowing.
    """
    runner = _config(
        "[runner]\n"
        'update_channel = "mian"\n'
        "interval_seconds = 0\n"
        'merge_method = "Squash "\n'
        "timeout_minutes = 12.9\n"
        'ideas_scope = "nonsense"\n'
    ).runner
    assert runner.update_channel == "release", "never main by mistake"
    assert runner.interval_seconds == 1
    assert runner.merge_method == "squash"
    assert runner.timeout_minutes == 12, "cut, as int() cut it"
    assert runner.ideas_scope == "all", "a typo is the default, never a narrower scope"

    config = _config(
        '[budget]\ndaily_usd = ""\nper_ticket_usd = -3\n'
        '[claude]\nprovider = "anthropic"\n'
        '[notify]\nevents = ["blocked", "never"]\n'
        "[notify.telegram]\nchat = -100123\nallowed_users = [1, 2]\n"
    )
    assert config.budget.daily_usd == config.budget.per_ticket_usd == 0.0
    assert config.claude.provider == ""
    assert config.notify.events == ("blocked",)
    assert config.notify.telegram == {"chat": "-100123", "allowed_users": "1,2"}


@case
def a_value_no_rule_reads_names_its_key_and_its_line() -> None:
    """A port that is not a number used to be a traceback naming nothing."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[runner]\n# how often\ninterval_seconds = 60\nunblock = "perhaps"\n\n'
        '[web]\nport = "eighty"\n\n'
        '[notify]\nreplies = true\nevents = "blocked"\n'
        'not_a_key = "yes"\n',
        encoding="utf-8",
    )
    try:
        C.load(path)
    except C.ConfigError as error:
        said = str(error).splitlines()
    else:
        raise AssertionError("loaded")
    assert said[0].startswith(f"{path}, line 4: runner.unblock = 'perhaps' — "), said
    assert said[1].startswith(f"  {path}, line 7: web.port = 'eighty' — "), said
    assert said[2].startswith(f"  {path}, line 10: notify.replies is not a key"), said
    assert said[3].startswith(f"  {path}, line 11: notify.events = 'blocked' — "), said
    assert said[4].startswith(f"  {path}, line 12: notify.not_a_key is not a key"), said
    assert len(said) == 5, "every value that does not read, and every key nobody reads"


@case
def a_key_or_a_table_nobody_reads_is_refused_with_its_line_and_what_it_was_meant_to_be() -> None:
    """A misspelt key is a setting that does nothing: the load stops on it, and says which."""
    said = _refused(
        "[runner]\n"
        "max_concurent = 4\n"
        "interval_seconds = 30\n"
        "\n"
        "[runer]\n"
        "interval_seconds = 60\n"
        "\n"
        "[notify.telegram]\n"
        "chatt = 42\n"
        "\n"
        "[projects]\n"
        'Anything = "~/anything"\n'
        "\n"
        "[web]\n"
        "nothing_like_it = 1\n"
    )
    assert said == [
        "line 2: runner.max_concurent is not a key of config.toml "
        "(did you mean runner.max_concurrent?) — ponos config converts a file an older version wrote",
        "line 5: [runer] is not a table of config.toml "
        "(did you mean runner?) — ponos config converts a file an older version wrote",
        "line 9: notify.telegram.chatt is not a key of config.toml "
        "(did you mean notify.telegram.chat?) — ponos config converts a file an older version wrote",
        "line 11: [projects] is not a table of config.toml "
        "— ponos config converts a file an older version wrote",
        "line 15: web.nothing_like_it is not a key of config.toml "
        "— ponos config converts a file an older version wrote",
    ], said
    # A secret an older version wrote is the launch's to move, not a typo: it
    # is left out of the reading, its table with it when it was its only key.
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[web]\npassword = "pw"\n[notify.telegram]\ntoken = "123:abc"\n[openrouter]\nkey = "k"\n'
    )
    loaded = C.load(path, secrets={})
    assert loaded.exposed == ("web.password", "notify.telegram.token", "openrouter.key")


@case
def doctor_says_which_key_nobody_reads() -> None:
    from test_health import _doctor_said

    from ponos import __main__ as cli

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[runner]\nmax_concurent = 4\n")
    with _environment(PONOS_CONFIG=str(path)):
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 2
    assert f"{path}, line 2: runner.max_concurent is not a key of config.toml" in said, said


@case
def a_table_written_as_a_value_is_named_by_its_line() -> None:
    text = 'web = "loopback"\n[runner]\n'
    assert schema.line_of(text, ("web",)) == 1
    assert schema.line_of(text, ("runner", "interval_seconds")) == 2, "its table, then"
    assert schema.line_of('[notify.telegram]\n"chat" = 1\n', ("notify", "telegram", "chat")) == 2
    assert schema.line_of("[runner]\n", ("web", "port")) == 0


@case
def doctor_prints_what_does_not_read() -> None:
    from test_health import _doctor_said

    from ponos import __main__ as cli

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[runner]\n\n[web]\nport = "eighty"\n')
    with _environment(PONOS_CONFIG=str(path)):
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 2
    assert f"{path}, line 4: web.port = 'eighty'" in said, said
    assert "Machine" not in said, "nothing after it is asked"


@case
def a_python_without_pydantic_still_starts_and_says_so() -> None:
    """The machine's Python, before the version's environment is made.

    The modules import, `load` says what is missing rather than raising an
    ImportError, and a pass knows it cannot read the file — so that it makes
    the environment instead (`__main__._environment_first`).
    """
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[runner]\n")
    probe = (
        "import sys\n"
        "sys.modules['pydantic'] = None\n"
        "from ponos import config\n"
        "assert not config.readable()\n"
        "try:\n"
        f"    config.load(config.Path({str(path)!r}))\n"
        "except config.MissingLibrary as error:\n"
        "    print(error)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "ponos update --environment" in done.stdout, done.stdout
    assert C.readable()


@case
def a_pass_that_cannot_read_the_file_makes_the_environment_and_stops(state_home: Path) -> None:
    from ponos import __main__ as cli
    from ponos import update

    made: list[str] = []
    readable, heal, app_dir = C.readable, update.heal_environment, update.app_dir
    link = Path(tempfile.mkdtemp()) / "app"
    link.symlink_to(link.parent)
    C.readable = lambda: False

    def healing() -> str:
        made.append("made")
        return ""

    update.heal_environment = healing
    update.app_dir = lambda: link
    try:
        code = cli.command_run(cli.build_parser().parse_args(["run"]))
    finally:
        C.readable, update.heal_environment, update.app_dir = readable, heal, app_dir
    assert code == 0
    assert made == ["made"], "no configuration read, and no ticket"
