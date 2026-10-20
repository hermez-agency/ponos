"""`schema.py`: what `config.toml` may say, and what is said when it does not read."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import get_origin

from support import _config, _environment, case

from ponos import config as C
from ponos import schema, subtypes

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


def _walk(model: type[schema.Table], prefix: tuple[str, ...] = ()):
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
def every_key_the_example_documents_is_one_the_model_reads_and_back():
    """config.example.toml and schema.py describe the same file.

    A key documented and not read is a setting that does nothing; a key read
    and not documented is one nobody finds. Secrets are neither: they are not
    keys of the file at all.
    """
    modelled = {path for path, _ in _walk(schema.File)} - _tables()
    documented = _documented()
    assert documented - modelled == set(), f"documented, never read: {documented - modelled}"
    assert modelled - documented == set(), f"read, never documented: {modelled - documented}"
    assert {f"auto_model_subtype_{key}" for key in subtypes.KEYS} <= set(
        schema.RunnerTable.model_fields
    ), "a sub-type of subtypes.py the file cannot move"


@case
def the_example_reads_against_the_model_and_gives_the_defaults():
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
def the_tolerances_of_the_old_loader_are_kept():
    """A typo in a choice is the default, a value past a floor is the floor.

    What `config.load` always did, and what an installation's file may rely on
    without anybody knowing.
    """
    runner = _config(
        "[runner]\n"
        'update_channel = "mian"\n'
        "interval_seconds = 0\n"
        "credit_reserve_percent = 150\n"
        'classify_confidence = "HIGH"\n'
        'auto_model_code = "huge"\n'
        'auto_model_subtype_docs = "much lower"\n'
        "timeout_minutes = 12.9\n"
        'reply_interval_seconds = "30"\n'
        'worktree_exclude = ["media", " videos "]\n'
    ).runner
    assert runner.update_channel == "release", "never main by mistake"
    assert runner.interval_seconds == 1
    assert runner.credit_reserve_percent == C.MOST_RESERVED
    assert runner.classify_confidence == "high"
    assert runner.auto_model_code == "standard"
    assert runner.auto_model_subtypes == {}
    assert runner.timeout_minutes == 12, "cut, as int() cut it"
    assert runner.reply_interval_seconds == 30
    assert runner.worktree_exclude == "media, videos"

    config = _config(
        '[budget]\ndaily_usd = ""\nper_ticket_usd = -3\n'
        '[storage]\nmode = "markdwon"\n'
        '[claude]\nprovider = "anthropic"\n'
        '[notify]\nevents = ["Blocked", "never"]\n'
        "[notify.telegram]\nchat = -100123\nallowed_users = [1, 2]\n"
    )
    assert config.budget.daily_usd == config.budget.per_ticket_usd == 0.0
    assert config.storage.mode == "notion"
    assert config.claude.provider == ""
    assert config.notify.events == ("blocked",)
    assert config.notify.telegram == {"chat": "-100123", "allowed_users": "1,2"}


@case
def a_value_no_rule_reads_names_its_key_and_its_line():
    """A port that is not a number used to be a traceback naming nothing."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntickets_database = "abc"\n\n'
        '[runner]\n# how often\ninterval_seconds = 60\npush = "perhaps"\n\n'
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
    assert said[0].startswith(f"{path}, line 7: runner.push = 'perhaps' — "), said
    assert said[1].startswith(f"  {path}, line 10: web.port = 'eighty' — "), said
    assert said[2].startswith(f"  {path}, line 14: notify.events = 'blocked' — "), said
    assert len(said) == 3, "a key nobody reads is left alone, as it always was"


@case
def a_table_written_as_a_value_is_named_by_its_line():
    text = 'web = "loopback"\n[runner]\n'
    assert schema.line_of(text, ("web",)) == 1
    assert schema.line_of(text, ("runner", "interval_seconds")) == 2, "its table, then"
    assert schema.line_of('[notify.telegram]\n"chat" = 1\n', ("notify", "telegram", "chat")) == 2
    assert schema.line_of("[runner]\n", ("web", "port")) == 0


@case
def doctor_prints_what_does_not_read():
    from test_delivery import _doctor_said

    from ponos import __main__ as cli

    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntickets_database = "abc"\n[web]\nport = "eighty"\n')
    with _environment(PONOS_CONFIG=str(path)):
        code, said = _doctor_said(cli.command_doctor, None)
    assert code == 2
    assert f"{path}, line 4: web.port = 'eighty'" in said, said
    assert "Tools" not in said


@case
def a_python_without_pydantic_still_starts_and_says_so():
    """The machine's Python, before the version's environment is made.

    The modules import, `load` says what is missing rather than raising an
    ImportError, and a pass knows it cannot read the file — so that it makes
    the environment instead (`__main__._environment_first`).
    """
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntickets_database = "abc"\n')
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
def a_pass_that_cannot_read_the_file_makes_the_environment_and_stops(state_home):
    from ponos import __main__ as cli
    from ponos import update

    made: list[str] = []
    readable, heal, app_dir = C.readable, update.heal_environment, update.app_dir
    link = Path(tempfile.mkdtemp()) / "app"
    link.symlink_to(link.parent)
    C.readable = lambda: False
    update.heal_environment = lambda: made.append("made") or ""
    update.app_dir = lambda: link
    try:
        code = cli.command_run(cli.build_parser().parse_args(["run"]))
    finally:
        C.readable, update.heal_environment, update.app_dir = readable, heal, app_dir
    assert code == 0
    assert made == ["made"], "no configuration read, and no ticket"
