"""`web/settings.py`: the settings tab."""

from __future__ import annotations

import json

from support import _saved, case

from ponos import config as C
from ponos import subtypes
from ponos.web import settings as web_settings

# -- the settings tab ---------------------------------------------------------


@case
def a_value_is_written_as_toml_spells_it():
    """Four shapes, and a string that would otherwise end the line early."""
    assert C._literal(True) == "true" and C._literal(False) == "false"
    assert C._literal(1800) == "1800"
    assert C._literal(["blocked", "done"]) == '["blocked", "done"]'
    assert C._literal('a "quoted" \\ path') == '"a \\"quoted\\" \\\\ path"'

    path, _ = _saved()
    assert C.write_value(path, "runner", "dry_run", True)
    assert C.write_value(path, "runner", "interval_seconds", 900)
    assert C.write_value(path, "notify", "events", ["blocked"])
    # A project called "Site vitrine" is not a bare key, and has to survive
    # being written and read back under the same name.
    assert C.write_value(path, "projects", "Site vitrine", "~/work/site")
    config = C.load(path)
    assert config.runner.dry_run is True
    assert config.runner.interval_seconds == 900
    assert config.notify.events == ("blocked",)
    assert "Site vitrine" in config.projects
    assert C.write_value(path, "projects", "Site vitrine", "~/work/site") is False


@case
def clearing_a_field_removes_the_line_rather_than_emptying_it():
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
def a_save_is_all_of_it_or_none_of_it():
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
    assert not [
        item for item in path.parent.iterdir() if item.name not in ("config.toml", "secrets.env")
    ]


@case
def a_floor_the_loader_would_repair_quietly_is_refused_here():
    """The loader raises a zero interval to one. A form that did so would lie."""
    path, config = _saved()
    for name, value in (
        ("runner.interval_seconds", 0),
        ("runner.progress_interval_seconds", 1),
        ("web.poll_seconds", 2),
        ("runner.update_interval_seconds", 30),
    ):
        try:
            web_settings.save(config, {"settings": {name: value}})
        except ValueError as error:
            assert "at the least" in str(error), error
            continue
        raise AssertionError(f"{name} = {value} should have been refused")


@case
def a_save_that_would_leave_it_unusable_is_refused():
    """The copy is loaded before it is allowed to take the file's place."""
    path, config = _saved()
    before = path.read_text()
    try:
        web_settings.save(config, {"settings": {"notion.token": None}})
    except C.ConfigError as error:
        assert "unusable" in str(error)
        assert ".saving" not in str(error), "and names the file, not the copy"
    else:
        raise AssertionError("a configuration with no token must not be saved")
    assert path.read_text() == before


@case
def a_token_is_never_sent_to_the_browser():
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
def what_the_file_says_is_told_apart_from_what_it_falls_back_on():
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
    # The three naming tables are drawn from the defaults, not listed twice.
    assert fields["notion.status.validated"]["fallback"] == "Validated"
    assert fields["notion.properties.progress"]["fallback"] == "Progress"


@case
def every_setting_the_file_holds_is_one_the_console_can_reach():
    """A key added to config.py and not described is a key nobody can set.

    The console draws itself from `settings.SECTIONS`; this is what keeps that
    description from falling behind the dataclasses it describes.
    """
    expected = set()
    for table, holder in (
        ("runner", C.Runner()),
        ("web", C.Web()),
        ("notify", C.Notify()),
        ("openrouter", C.OpenRouter()),
        ("claude", C.Claude()),
        ("storage", C.Storage()),
        ("permissions", C.Permissions()),
        ("github_access", C.GithubAccess()),
    ):
        for name in vars(holder):
            # The two channel tables are their own sections, and `projects` is a
            # mapping you add rows to rather than a list of known keys.
            if name in ("telegram", "slack"):
                continue
            expected.add(f"{table}.{name}")
    for name in vars(C.Notion()):
        if name in ("pages", "properties", "status", "types"):
            continue
        expected.add(f"notion.{name}")
    for table in ("pages", "properties", "status", "types"):
        expected |= {f"notion.{table}.{key}" for key in C.defaults(table)}
    # The one naming key with no default: a board names its drafts or has none.
    expected.add("notion.status.draft")
    expected |= {"notify.telegram.token", "notify.telegram.chat"}
    expected |= {"notify.slack.token", "notify.slack.channel"}

    # A mapping the file writes one key per sub-type: see `Runner.auto_model_subtypes`.
    expected.discard("runner.auto_model_subtypes")
    expected |= {f"runner.auto_model_subtype_{key}" for key in subtypes.KEYS}
    # A key the page draws under its newer name instead: see `LEGACY`.
    expected -= set(web_settings.LEGACY)
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
def a_choice_is_shown_in_words_and_saved_as_the_file_spells_it():
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
    assert drawn["runner.branch_prefix"]["advanced"] is True
    assert drawn["runner.max_concurrent"]["advanced"] is False
    web_settings.save(config, {"settings": {"runner.merge_method": "rebase"}})
    assert 'merge_method = "rebase"' in path.read_text()
    for section in web_settings.SECTIONS:
        if section.fields:
            assert not all(field.advanced for field in section.fields), section.key


@case
def the_tables_that_are_mappings_gain_and_lose_rows():
    """The two sections that are a mapping rather than a list of known keys.

    `[projects]` and `[github]` are saved by what the browser sends in full, so
    a row you removed there is a line that goes away here.
    """
    path, config = _saved(
        '\n[projects]\n"Site vitrine" = "~/work/site"\nold = "~/work/old"\n'
        '\n[github]\nnorthwind = "dev-northwind"\nold = "nobody"\n'
    )
    web_settings.save(
        config,
        {
            "projects": [
                {"name": "Site vitrine", "value": "~/work/site-v2"},
                {"name": "Trader IA", "value": "~/work/trader"},
            ],
            "github": [{"name": "Northwind", "value": "dev-northwind"}],
        },
    )
    saved = C.load(path)
    assert set(saved.projects) == {"Site vitrine", "Trader IA"}, "the row you removed is gone"
    assert saved.projects["Site vitrine"].endswith("site-v2")
    assert saved.github == {"northwind": "dev-northwind"}, "and an owner is read lowercased"

    drawn = web_settings.describe(C.load(path))
    assert {"name": "Northwind", "value": "dev-northwind"} in drawn["github"]
    assert any(section["pairs"] == "github" for section in drawn["sections"])


@case
def a_setting_that_needs_more_than_saving_says_so_and_only_when_it_moved():
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
