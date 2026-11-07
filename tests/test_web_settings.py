"""`web/settings.py`: the settings tab."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from support import _saved, case

from ponos import config as C
from ponos import schema
from ponos.web import settings as web_settings

# -- the settings tab ---------------------------------------------------------


@case
def a_value_is_written_as_toml_spells_it() -> None:
    """Four shapes, and a string that would otherwise end the line early."""
    assert C._literal(True) == "true" and C._literal(False) == "false"
    assert C._literal(1800) == "1800"
    assert C._literal(["blocked", "done"]) == '["blocked", "done"]'
    assert C._literal('a "quoted" \\ path') == '"a \\"quoted\\" \\\\ path"'

    path, _ = _saved()
    assert C.write_value(path, "runner", "unblock", True)
    assert C.write_value(path, "runner", "interval_seconds", 900)
    assert C.write_value(path, "notify", "events", ["blocked"])
    # An owner called "north wind" is not a bare key, and has to survive
    # being written and read back under the same name.
    assert C.write_value(path, "github", "north wind", "dev-northwind")
    config = C.load(path)
    assert config.runner.unblock is True
    assert config.runner.interval_seconds == 900
    assert config.notify.events == ("blocked",)
    assert "north wind" in config.github
    assert C.write_value(path, "github", "north wind", "dev-northwind") is False


@case
def clearing_a_field_removes_the_line_rather_than_emptying_it() -> None:
    """A key the file does not carry is a key the loader answers itself.

    Which is the whole grammar of the settings tab: blank means "say nothing",
    and the default comes back — comments and all, for the next time it is set.
    """
    path, _ = _saved('\n[runner]\n# how often it looks\nmodel = "opus"\ninterval_seconds = 60\n')
    assert C.write_value(path, "runner", "model", None) is True
    assert C.write_value(path, "runner", "model", None) is False, "already gone"
    text = path.read_text()
    assert "model" not in text
    assert "# how often it looks" in text, "the comments around it survive"
    assert C.load(path).runner.model == "", "and the default answers"


@case
def a_save_is_all_of_it_or_none_of_it() -> None:
    """Half a configuration is a runner that claims tickets it cannot finish."""
    path, config = _saved("\n[runner]\ninterval_seconds = 900\n")
    before = path.read_text()
    try:
        web_settings.save(
            config,
            {"settings": {"runner.max_concurrent": 4, "runner.merge_method": "fast-forward"}},
        )
    except ValueError as error:
        assert "squash" in str(error), error
    else:
        raise AssertionError("a merge method gh would refuse must not be saved")
    assert path.read_text() == before, "the good half must not have landed either"
    # The lock stays: it is the flock on it that counts, see `config._locked`.
    assert not [
        item
        for item in path.parent.iterdir()
        if item.name not in ("config.toml", "secrets.env", ".config.toml.lock")
    ]


@case
def two_saves_at_once_both_land() -> None:
    """Two tabs, or a tab and the CLI: the second used to replace the first's work.

    Each read the file, then put its copy in its place — and the copy of the
    second was made from the file as it was before the first. The barrier holds
    both between the read and the replace, where the race was; under the lock
    the second never gets there before the first is done, and the barrier gives
    up waiting for it.
    """
    path, _ = _saved()
    barrier = threading.Barrier(2, timeout=1)
    load = C.load

    def held(loaded: Path | None = None, *args: Any, **kwargs: Any) -> C.Config:
        if loaded == path:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return load(loaded, *args, **kwargs)

    failures: list[Exception] = []

    def save(key: str, value: object) -> None:
        try:
            C.edit(path, [("runner", key, value)])
        except Exception as error:  # noqa: BLE001 — reported by the assertion below
            failures.append(error)

    C.load = held  # type: ignore[assignment]  # a double: two saves meet at the barrier
    try:
        threads = [
            threading.Thread(target=save, args=("interval_seconds", 900)),
            threading.Thread(target=save, args=("max_concurrent", 3)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        C.load = load
    assert not failures, failures
    config = C.load(path)
    assert config.runner.interval_seconds == 900, path.read_text()
    assert config.runner.max_concurrent == 3, path.read_text()


@case
def a_value_written_by_the_cli_goes_through_the_same_save() -> None:
    """`ponos notify pair` wrote the real file in place.

    Killed between the truncation and the write, that left a configuration that
    no longer parsed. Through `edit`, the file is replaced whole, and the one it
    displaced is kept beside it.
    """
    path, _ = _saved()
    before = path.read_text()
    replaced = os.replace
    names: list[str] = []

    def watched(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        names.append(Path(target).name)
        return replaced(source, target)

    os.replace = watched  # type: ignore[assignment]  # a double: the name it replaces is kept
    try:
        assert C.write_value(path, "runner", "model", "opus")
    finally:
        os.replace = replaced
    assert "config.toml" in names, "the file is replaced, not written in place"
    assert C.load(path).runner.model == "opus"
    assert path.with_name("config.toml.bak").read_text() == before


@case
def a_floor_the_loader_would_repair_quietly_is_refused_here() -> None:
    """The loader raises a zero interval to one. A form that did so would lie."""
    path, config = _saved()
    for name, value in (
        ("runner.interval_seconds", 0),
        ("runner.max_concurrent", 0),
        ("runner.timeout_minutes", 0),
        ("web.port", -1),
    ):
        try:
            web_settings.save(config, {"settings": {name: value}})
        except ValueError as error:
            assert "at the least" in str(error), error
            continue
        raise AssertionError(f"{name} = {value} should have been refused")


@case
def a_save_that_would_leave_it_unusable_is_refused() -> None:
    """The copy is loaded before it is allowed to take the file's place."""
    path, config = _saved()
    before = path.read_text()
    try:
        original = C.load

        def refusing(path: Path, **named: object) -> C.Config:
            if ".saving" in path.name:
                raise C.ConfigError(f"{path}: the copy does not read")
            return original(path, **named)  # type: ignore[arg-type]

        C.load = refusing  # type: ignore[assignment]  # a double: the copy does not read
        try:
            web_settings.save(config, {"settings": {"runner.max_concurrent": 3}})
        finally:
            C.load = original
    except C.ConfigError as error:
        assert "unusable" in str(error)
        assert ".saving" not in str(error), "and names the file, not the copy"
    else:
        raise AssertionError("a configuration that does not read must not be saved")
    assert path.read_text() == before


@case
def a_token_is_never_sent_to_the_browser() -> None:
    """A secret goes out as "set, ending in …abcd", and comes back only typed."""
    path, config = _saved('\n[notify.slack]\ntoken = "xoxb-1234567890wxyz"\nchannel = "C1"\n')
    drawn = json.dumps(web_settings.describe(config), ensure_ascii=False)
    assert "ntn_real" not in drawn and "xoxb-1234567890wxyz" not in drawn
    assert "…wxyz" in drawn, "enough to recognise it by"

    fields = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert fields["notify.slack.token"]["stated"] is True
    assert fields["notify.slack.token"]["fallback"] == "", "a secret has no default to show"
    assert fields["notify.telegram.token"]["stated"] is False
    assert fields["notify.telegram.token"]["preview"] == ""
    # Typing one sets it; the gesture that clears one is its own.
    web_settings.save(config, {"settings": {"notify.slack.token": "xoxb-new"}})
    assert C.load(path).notify.slack["token"] == "xoxb-new"
    web_settings.save(C.load(path), {"settings": {"notify.slack.token": None}})
    assert "token" not in C.load(path).notify.slack


@case
def what_the_file_says_is_told_apart_from_what_it_falls_back_on() -> None:
    """Otherwise a save would write every default into the file it read."""
    path, config = _saved("\n[runner]\ninterval_seconds = 900\n")
    fields = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    stated = fields["runner.interval_seconds"]
    assert stated["value"] == 900 and stated["stated"] is True
    silent = fields["runner.max_concurrent"]
    assert silent["value"] is None and silent["stated"] is False
    assert silent["fallback"] == C.Runner().max_concurrent, "the default, shown greyed"
    # The names of the board's columns are no setting at all.
    assert not [name for name in fields if name.startswith(("board.", "names."))]


@case
def every_setting_the_file_holds_is_one_the_console_can_reach() -> None:
    """A key added to config.py and not described is a key nobody can set.

    The console draws itself from `settings.SECTIONS`; this is what keeps that
    description from falling behind the dataclasses it describes.
    """
    # What the file keeps: the keys of schema.py, and the secrets that live elsewhere.
    expected = {f"runner.{name}" for name in schema.RunnerTable.model_fields}
    expected.discard("runner.force_validated")
    # The one list, drawn as a switch a type: see `settings._forced_changes`.
    expected |= {f"runner.force_validated_{kind}" for kind in C.VALIDATED}
    expected |= {f"web.{name}" for name in schema.WebTable.model_fields}
    expected |= {"web.token", "web.password"}
    expected |= {f"notify.{name}" for name in schema.NotifyTable.model_fields}
    expected -= {"notify.telegram", "notify.slack"}
    expected |= {"notify.telegram.token", "notify.telegram.chat"}
    expected |= {"notify.slack.token", "notify.slack.channel"}
    expected |= {f"claude.{name}" for name in schema.ClaudeTable.model_fields} | {"claude.api_key"}
    expected |= {"openrouter.key"}
    expected |= {f"permissions.{name}" for name in schema.PermissionsTable.model_fields}
    expected |= {f"github_access.{name}" for name in schema.GithubAccessTable.model_fields}
    expected |= {"github_access.token"}
    # Named in the file and not drawn: the two lists of people a channel listens to,
    # which are edited where they are read (see `notify.telegram`).
    missing = expected - set(web_settings.FIELDS)
    assert not missing, f"not reachable from the console: {sorted(missing)}"
    unknown = set(web_settings.FIELDS) - expected
    assert not unknown, f"described but not read by the loader: {sorted(unknown)}"

    for name, field in web_settings.FIELDS.items():
        assert field.label, name
        assert field.kind in (
            "text",
            "secret",
            "path",
            "bool",
            "int",
            "choice",
            "events",
            "lines",
        ), name
        if field.kind == "choice":
            assert field.choices, name


@case
def a_choice_is_shown_in_words_and_saved_as_the_file_spells_it() -> None:
    """The page says "One commit (squash)"; the file keeps saying `squash`.

    Every value a choice offers has its words, and no words name a value the
    loader would refuse. A section never folds all of itself away: the advanced
    fields sit under the ones somebody setting up a board needs first.
    """
    for name, field in web_settings.FIELDS.items():
        if field.options:
            assert [value for value, _ in field.options] == list(field.choices), name
    path, config = _saved()
    drawn = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert drawn["runner.merge_method"]["options"]["squash"] == "One commit (squash)"
    assert drawn["github_access.token_item"]["advanced"] is True
    assert drawn["runner.max_concurrent"]["advanced"] is False
    web_settings.save(config, {"settings": {"runner.merge_method": "rebase"}})
    assert 'merge_method = "rebase"' in path.read_text()
    for section in web_settings.SECTIONS:
        if section.fields:
            assert not all(field.advanced for field in section.fields), section.key


@case
def the_table_that_is_a_mapping_gains_and_loses_rows() -> None:
    """The section that is a mapping rather than a list of known keys.

    `[github]` is saved by what the browser sends in full, so a row you removed
    there is a line that goes away here.
    """
    path, config = _saved('\n[github]\nnorthwind = "dev-northwind"\nold = "nobody"\n')
    web_settings.save(config, {"github": [{"name": "Northwind", "value": "dev-northwind"}]})
    saved = C.load(path)
    assert saved.github == {"northwind": "dev-northwind"}, "and an owner is read lowercased"

    drawn = web_settings.describe(C.load(path))
    assert {"name": "Northwind", "value": "dev-northwind"} in drawn["github"]
    assert any(section["pairs"] == "github" for section in drawn["sections"])


@case
def a_setting_that_needs_more_than_saving_says_so_and_only_when_it_moved() -> None:
    """A notice about a restart you do not need is a notice you stop reading."""
    path, config = _saved()
    result = web_settings.save(config, {"settings": {"runner.interval_seconds": 600}})
    assert result["saved"] == ["runner.interval_seconds"]
    assert any("timer" in note for note in result["after"])

    result = web_settings.save(C.load(path), {"settings": {"runner.max_concurrent": 3}})
    assert result["after"] == [], "nothing to do but the next run"
    # Saving what the file already says changes nothing and claims nothing.
    assert (
        web_settings.save(C.load(path), {"settings": {"runner.max_concurrent": 3}})["saved"] == []
    )
