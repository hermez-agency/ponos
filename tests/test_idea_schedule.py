"""`idea_schedule.py` and `web/planned.py`: ideas found on their own."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from support import _board, _ideas_api, _saved, case

from ponos import config as C
from ponos import db, idea_schedule, ideas, project_settings, schedules, session
from ponos.web import api as web_api

NOW = datetime.fromisoformat("2026-10-21T10:30:00")  # a Wednesday


def _plan(**keys) -> idea_schedule.Plan:
    return idea_schedule.plan(C.Runner(**{f"ideas_{key}": value for key, value in keys.items()}))


@case
def a_cron_line_and_an_interval_fall_where_they_say_and_an_unreadable_line_never():
    """The two shapes the recurrences' four cadences did not have."""
    assert schedules.every(4, after=NOW) == datetime.fromisoformat("2026-10-21T14:30:00")
    assert schedules.every(0, after=NOW) == datetime.fromisoformat("2026-10-21T11:30:00"), (
        "an hour at least"
    )
    nine = "0 9 * * 1-5"  # weekdays at nine
    assert schedules.cron(nine, after=NOW) == datetime.fromisoformat("2026-10-22T09:00:00")
    friday = datetime.fromisoformat("2026-10-23T10:00:00")
    assert schedules.cron(nine, after=friday) == datetime.fromisoformat("2026-10-26T09:00:00"), (
        "not the weekend"
    )
    assert schedules.cron("*/15 * * * *", after=NOW) == datetime.fromisoformat(
        "2026-10-21T10:45:00"
    )
    assert schedules.cron("0 0,12 * * *", after=NOW) == datetime.fromisoformat(
        "2026-10-21T12:00:00"
    )
    # Both a day of the month and of the week: either, as cron has it.
    assert schedules.cron("0 8 1 * 1", after=NOW) == datetime.fromisoformat("2026-10-26T08:00:00")
    assert schedules.cron("0 8 31 2 *", after=NOW) is None, "February has no 31st"
    for broken in ("", "0 9 * *", "61 9 * * *", "0 9 * * mon", "*/0 * * * *", "5-1 * * * *"):
        assert schedules.cron(broken, after=NOW) is None, broken
        assert schedules.cron_problem(broken), broken
    assert schedules.cron_problem(nine) == ""
    aware = NOW.astimezone()
    assert schedules.cron(nine, after=aware).tzinfo is not None, "aware in, aware out"


@case
def every_preset_asks_the_recurrences_engine_for_its_next_moment():
    assert idea_schedule.next_after(_plan(), NOW) is None, "off is no moment at all"
    assert idea_schedule.next_after(_plan(schedule="every_4h"), NOW) == NOW + timedelta(hours=4)
    assert idea_schedule.next_after(_plan(schedule="hours", every_hours=7), NOW) == NOW + timedelta(
        hours=7
    )
    daily = idea_schedule.next_after(_plan(schedule="daily", at="09:00"), NOW)
    assert daily == datetime.fromisoformat("2026-10-22T09:00:00")
    weekly = idea_schedule.next_after(_plan(schedule="weekly", at="08:15", day="Monday"), NOW)
    assert weekly == datetime.fromisoformat("2026-10-26T08:15:00")
    assert idea_schedule.next_after(_plan(schedule="cron", cron="30 18 * * *"), NOW) == (
        datetime.fromisoformat("2026-10-21T18:30:00")
    )
    coming = idea_schedule.upcoming(_plan(schedule="every_4h"), NOW, NOW + timedelta(hours=13))
    assert coming == [NOW + timedelta(hours=4 * step) for step in range(4)]


@case
def a_schedule_that_cannot_fire_is_named_for_doctor():
    assert idea_schedule.problem(_plan()) == "", "off has nothing to be wrong"
    assert idea_schedule.problem(_plan(schedule="daily", at="9 o'clock")) != ""
    assert "cron line" in idea_schedule.problem(_plan(schedule="cron", cron="every day"))
    assert idea_schedule.problem(_plan(schedule="weekly", at="09:00")) == ""


@case
def a_project_follows_the_file_unless_it_says_its_own_word():
    everyone = _plan(scope="all")
    chosen = _plan(scope="selected", projects="aaa, Beta")
    assert idea_schedule.covers(everyone, "zzz", "Zeta", None), "all includes the ones added later"
    assert not idea_schedule.covers(everyone, "zzz", "Zeta", False)
    assert idea_schedule.covers(chosen, "aaa", "Alpha", None), "by its id"
    assert idea_schedule.covers(chosen, "bbb", "beta", None), "or by its name"
    assert not idea_schedule.covers(chosen, "ccc", "Gamma", None)
    assert idea_schedule.covers(chosen, "ccc", "Gamma", True), "its own word wins"


@case
def the_settings_of_the_file_are_read_with_their_floors_and_defaults(state_home):
    _, config = _saved(
        '\n[runner]\nideas_schedule = "Weekly"\nideas_day = "friday"\nideas_every_hours = 0\n'
        'ideas_per_batch = 99\nideas_skip_above = -3\nideas_budget_usd = "1.5"\n'
        'ideas_scope = "nonsense"\nideas_projects = ["Alpha", "Beta"]\n'
    )
    runner = config.runner
    assert runner.ideas_schedule == "weekly" and runner.ideas_day == "Friday"
    assert runner.ideas_every_hours == 1 and runner.ideas_per_batch == 20
    assert runner.ideas_skip_above == 0 and runner.ideas_budget_usd == 1.5
    assert runner.ideas_scope == "all", "a typo is the default, never a narrower scope"
    assert runner.ideas_projects == "Alpha, Beta"
    assert _saved()[1].runner.ideas_schedule == "off", "nothing is scheduled unless asked"


# -- a pass -------------------------------------------------------------------


def _answering(cost: float = 0.02):
    """A `session.run` that proposes three ideas whose titles name the call."""
    asked: list[str] = []
    # Titles that do not look alike: two alike are the same idea, and dropped.
    words = (
        "mode sombre",
        "export csv",
        "recherche globale",
        "raccourcis clavier",
        "tableau de bord",
        "notifications push",
        "import depuis jira",
        "journal d'audit",
        "thème imprimable",
        "synchronisation hors ligne",
        "partage par lien",
        "historique des versions",
        "tutoriel guidé",
        "sauvegarde chiffrée",
        "traduction automatique",
        "graphiques de coût",
        "connexion par clé",
        "rapport hebdomadaire",
        "étiquettes colorées",
        "pièces jointes",
        "commentaires épinglés",
        "calendrier partagé",
        "modèles de tickets",
        "statistiques d'équipe",
        "aperçu des liens",
        "mode présentation",
        "filtres enregistrés",
        "corbeille restaurable",
        "assistant d'installation",
        "tests de charge",
    )

    def fake_run(text, **rest):
        asked.append(text)
        number = len(asked)
        answer = [
            {
                "title": words[(number * 3 + index) % len(words)],
                "description": "Parce que.",
                "kind": "ticket",
                "where": "src",
                "done": ["ok"],
                "out": [],
            }
            for index in range(3)
        ]
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s",
            summary="",
            log=Path("/dev/null"),
            cost_usd=cost,
            answer="```json\n" + json.dumps(answer) + "\n```",
        )

    return fake_run, asked


class _Pass:
    """A console with three projects, a fake session, and the schedule set as asked."""

    def __init__(self, board, **keys) -> None:
        self.board = board
        idea_schedule.plan_next(_plan(), None)  # a moment left by the run before
        self.ids = {
            name: board.create_row("projects", name, {}).replace("-", "")
            for name in ("Alpha", "Beta", "Gamma")
        }
        self.api = _ideas_api(board)
        for key, value in keys.items():
            setattr(self.api._config.runner, f"ideas_{key}", value)
        self.run, self.asked = _answering()
        self.told: list[tuple[str, str]] = []
        self.api._runner._announce = lambda title, body: self.told.append((title, body))

    def look(self, at: datetime):
        original, session.run = session.run, self.run
        try:
            return self.api.planned.look(at.astimezone())
        finally:
            session.run = original

    def count(self, name: str) -> int:
        return len(ideas.listed(self.ids[name]))


@case
def every_four_hours_with_two_projects_ticked_finds_ideas_for_those_two_at_every_pass(state_home):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="selected")
        run.api._config.runner.ideas_projects = f"{run.ids['Alpha']}, {run.ids['Gamma']}"
        assert run.look(NOW) is None, "a schedule just written waits for its first moment"
        assert run.asked == [] and idea_schedule.due() is not None
        assert run.look(NOW + timedelta(hours=3)) is None, "and is not early"

        first = run.look(NOW + timedelta(hours=4, minutes=1))
        assert first is not None and first.found == 6 and first.projects == 2
        assert (run.count("Alpha"), run.count("Beta"), run.count("Gamma")) == (3, 0, 3)
        assert len(run.asked) == 2

        assert run.look(NOW + timedelta(hours=4, minutes=2)) is None, "a moment is taken once"
        second = run.look(NOW + timedelta(hours=8, minutes=5))
        assert second is not None and second.found == 6
        assert (run.count("Alpha"), run.count("Beta"), run.count("Gamma")) == (6, 0, 6)
        last = idea_schedule.last()
        assert last is not None and last.found == 6 and abs(last.cost_usd - 0.04) < 1e-9


@case
def a_schedule_that_is_off_runs_no_pass_and_forgets_its_moment(state_home):
    with _board() as board:
        run = _Pass(board, schedule="daily", at="09:00", scope="all")
        run.look(NOW)
        assert idea_schedule.due() is not None
        run.api._config.runner.ideas_schedule = "off"
        for step in range(0, 72, 6):
            assert run.look(NOW + timedelta(hours=step)) is None
        assert run.asked == [] and idea_schedule.due() is None and idea_schedule.last() is None


@case
def a_console_off_for_days_finds_one_pass_and_a_changed_frequency_draws_its_moment_again(
    state_home,
):
    with _board() as board:
        run = _Pass(board, schedule="daily", at="09:00", scope="all")
        run.look(NOW)
        back = NOW + timedelta(days=5)
        assert run.look(back) is not None
        assert len(run.asked) == 3, "one pass, one call per project — not five days of them"
        stored = idea_schedule.due()
        assert stored is not None and stored[1] > back.astimezone(), "the next one is from now"
        run.api._config.runner.ideas_schedule = "weekly"
        assert run.look(back + timedelta(days=6)) is None, "the old moment is nobody's"
        assert len(run.asked) == 3


@case
def all_projects_includes_one_added_after_the_schedule_was_set(state_home):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="all")
        run.look(NOW)
        run.look(NOW + timedelta(hours=5))
        assert len(run.asked) == 3
        late = board.create_row("projects", "Delta", {}).replace("-", "")
        run.api.forget_projects()
        run.look(NOW + timedelta(hours=10))
        assert len(run.asked) == 7, "four projects this time"
        assert len(ideas.listed(late)) == 3


@case
def a_project_with_too_many_new_ideas_is_skipped_and_the_journal_says_so(state_home):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="all", skip_above=3)
        run.look(NOW)
        records: list[str] = []

        class Hear(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Hear(logging.INFO)
        logger = logging.getLogger("ponos.web.planned")
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(logging.INFO)
        try:
            ideas.record(run.ids["Beta"], "haiku", None, [_idea(f"Déjà là {n}") for n in range(3)])
            done = run.look(NOW + timedelta(hours=5))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)
        assert done is not None and done.projects == 2
        assert run.count("Beta") == 3, "nothing was added over the threshold"
        assert list(done.skipped) == ["Beta"] and "3 new ideas" in done.skipped["Beta"]
        assert any("Beta skipped" in line and "3 new ideas" in line for line in records), records
        # The same threshold at nought means never skipped.
        run.api._config.runner.ideas_skip_above = 0
        run.look(NOW + timedelta(hours=10))
        assert run.count("Beta") == 6


def _idea(title: str) -> dict:
    return {"title": title, "kind": "ticket", "description": ""}


@case
def a_project_can_turn_itself_off_or_on_from_its_own_page(state_home):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="selected")
        api, alpha, beta = run.api, run.ids["Alpha"], run.ids["Beta"]
        api._config.runner.ideas_projects = alpha
        page = api.project_settings(alpha)["ideas"]
        assert page == {"enabled": True, "own": False, "schedule": "every_4h"}
        assert api.project_settings(beta)["ideas"]["enabled"] is False

        api.save_project_settings(alpha, {"ideas": {"enabled": False}})
        api.save_project_settings(beta, {"ideas": {"enabled": True}})
        assert api.project_settings(alpha)["ideas"] == {
            "enabled": False,
            "own": True,
            "schedule": "every_4h",
        }
        listed = {row["id"]: row for row in api.planned.describe()["projects"]}
        assert listed[alpha]["enabled"] is False and listed[beta]["enabled"] is True, (
            "reflected in the list"
        )
        assert project_settings.every_ideas() == {alpha: False, beta: True}

        run.look(NOW)
        done = run.look(NOW + timedelta(hours=5))
        assert done is not None and (run.count("Alpha"), run.count("Beta")) == (0, 3)

        # Said as the file says it, the word is handed back: no decision of its own.
        api.save_project_settings(alpha, {"ideas": {"enabled": True}})
        assert api.project_settings(alpha)["ideas"]["own"] is False
        assert (
            beta in project_settings.every_ideas() and alpha not in project_settings.every_ideas()
        )
        try:
            api.save_project_settings(alpha, {})
        except ValueError:
            pass
        else:
            raise AssertionError("a payload that says nothing is refused")


@case
def the_workspace_is_a_switch_of_its_own_and_the_budget_stops_a_pass_between_two_projects(
    state_home,
):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="all", workspace=True, budget_usd=0.03)
        run.look(NOW)
        done = run.look(NOW + timedelta(hours=5))
        assert done is not None
        assert len(run.asked) == 2, "the workspace, one project: 0.04 is over the 0.03 ceiling"
        assert len(done.skipped) == 2 and all("budget" in why for why in done.skipped.values())
        assert len(ideas.listed("")) == 3, "the workspace's ideas have no project"

    with _board() as other:
        quiet = _Pass(other, schedule="every_4h", scope="all", workspace=False)
        quiet.look(NOW)
        quiet.look(NOW + timedelta(hours=5))
        assert len(ideas.listed("")) == 3, "all projects has never meant the workspace"


@case
def a_pass_tells_the_channels_only_when_asked_to_and_only_when_it_found_something(state_home):
    with _board() as board:
        quiet = _Pass(board, schedule="every_4h", scope="all")
        quiet.look(NOW)
        quiet.look(NOW + timedelta(hours=5))
        assert quiet.told == []
    with _board() as other:
        loud = _Pass(other, schedule="every_4h", scope="all", notify=True)
        loud.look(NOW)
        loud.look(NOW + timedelta(hours=5))
        assert len(loud.told) == 1
        title, body = loud.told[0]
        assert "9 new ideas" in title and "Alpha: 3" in body


@case
def one_project_that_fails_takes_only_itself_down(state_home):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="all")
        working = run.run

        def broken(text, **rest):
            if "Beta" in text:
                raise OSError("no claude")
            return working(text, **rest)

        run.run = broken
        run.look(NOW)
        done = run.look(NOW + timedelta(hours=5))
        assert done is not None and done.projects == 2 and done.found == 6
        assert "no claude" in done.skipped["Beta"]


@case
def the_dialog_saves_into_the_file_and_the_projects_ticked_replace_what_each_said(state_home):
    with _board() as board:
        path, config = _saved(f'\n[storage]\nmode = "markdown"\npath = "{board.root}"\n')
        run = _Pass(board)
        api = run.api
        api._config = config
        api._stamp = web_api._stamp(path)
        alpha, beta = run.ids["Alpha"], run.ids["Beta"]
        project_settings.set_ideas(beta, "Beta", True)

        saved = api.planned.save(
            {
                "schedule": "cron",
                "cron": "0 9 * * 1-5",
                "scope": "selected",
                "projects": [alpha],
                "per_batch": 5,
                "skip_above": 8,
                "budget_usd": 1.5,
                "notify": True,
                "workspace": True,
                "model": "sonnet",
            }
        )
        text = path.read_text(encoding="utf-8")
        for line in (
            'ideas_schedule = "cron"',
            'ideas_cron = "0 9 * * 1-5"',
            "ideas_per_batch = 5",
        ):
            assert line in text, line
        assert 'ideas_model = "sonnet"' in text and "ideas_notify = true" in text
        reloaded = C.load(path).runner
        assert reloaded.ideas_projects == alpha and reloaded.ideas_budget_usd == 1.5
        assert saved["settings"]["schedule"] == "cron" and saved["settings"]["per_batch"] == 5
        assert {row["id"]: row["enabled"] for row in saved["projects"]}[alpha] is True
        assert project_settings.every_ideas() == {}, (
            "the list is the whole truth for a selected scope"
        )
        assert saved["next"], "and the next pass is known"

        for refused in (
            {"cron": 3, "schedule": "sometimes"},
            {"per_batch": 99},
            {"budget_usd": "lots"},
        ):
            try:
                api.planned.save(refused)
            except ValueError:
                continue
            raise AssertionError(f"{refused} was accepted")


@case
def the_calendar_of_recurrences_is_given_the_passes_to_come_read_only(state_home):
    with _board() as board:
        run = _Pass(board, schedule="every_4h", scope="all")
        calendar = run.api.planned.calendar()
        assert calendar["active"] is True and len(calendar["upcoming"]) > 100
        assert calendar["upcoming"][0] == calendar["next"] and calendar["last"] == ""
        run.api._config.runner.ideas_schedule = "off"
        off = run.api.planned.calendar()
        assert off["active"] is False and off["upcoming"] == [] and off["next"] == ""
        shown = run.api.schedules()
        assert shown["ideas_pass"]["active"] is False


@case
def the_pass_leaves_its_tables_to_the_migration(state_home):
    with db.transaction(immediate=False) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert {"idea_plan", "idea_passes"} <= tables
