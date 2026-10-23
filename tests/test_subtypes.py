"""`subtypes.py`: the sub-type of a code ticket."""

from __future__ import annotations

import contextlib
import io
from datetime import UTC, date

from support import FRONTEND, _nameless, _naming_session, _saved, _state_home, _TypedClient, case

from ponos import config as C
from ponos import files, models, notion, prompt, provision, state, subtypes
from ponos.web import statistics as web_statistics
from ponos.web import tickets as web_tickets

# -- the sub-type of a code ticket --------------------------------------------


class _SubtypedClient(_TypedClient):
    """A board with a Type column and a Sous-type one."""

    def schema(self, database_id: str) -> dict[str, str]:
        return {**super().schema(database_id), "Sous-type": "select"}


def _subtyped(
    title: str, *, kind: str = "Code", subtype: str = "", body: str = "Le bouton ne répond plus."
):
    runner, ticket = _nameless(title, body)
    runner.client = _SubtypedClient(body)
    if kind:
        ticket.page.properties["Type"] = {"type": "select", "select": {"name": kind}}
    if subtype:
        ticket.page.properties["Sous-type"] = {"type": "select", "select": {"name": subtype}}
    return runner, ticket


def _subtype_written(runner) -> list[str]:
    return [values["Sous-type"] for values in runner.client.written if "Sous-type" in values]


@case
def a_prefix_says_the_sub_type_without_asking_anybody(state_home):
    for title, key in (
        ("[Bug] Le bouton ne répond plus", "bug"),
        ("Ponos — [Feature] Un badge sur la carte", "feature"),
        ("[UX] [Amélioration] Des libellés plus clairs", "improvement"),
        ("[Ops] Monter la version de Node", "chore"),
        ("[Refactor] Découper runner.py", "refactor"),
        ("[Perf] Le board s'ouvre en 80 ms", "perf"),
        ("[Docs] Le README", "docs"),
        ("[Sécurité] Le token fuit dans les logs", "security"),
        ("[security] same, in English", "security"),
    ):
        assert subtypes.from_prefix(title) == key, title
    assert subtypes.from_prefix("[UX] Une carte plus lisible") == "", "a domain says nothing"
    assert subtypes.from_prefix("Le bouton ne répond plus") == ""

    runner, ticket = _subtyped("[Bug] Le bouton ne répond plus")
    with _naming_session('{"subtype": "feature", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [], "a prefix costs no session"
    assert job is not None and job.subtype == "bug"
    assert _subtype_written(runner) == ["Bug"]


@case
def the_sub_type_session_counts_against_the_daily_limit(state_home):
    runner, ticket = _subtyped("Le bouton Envoyer ne répond plus")
    answer = '{"subtype": "bug", "reason": "Il ne marche plus.", "confidence": "high"}'
    with _naming_session(answer, cost=0.25):
        runner.prepare(ticket)
    assert state.spent_today() == 0.25, state.spent_today()


@case
def a_sub_type_without_a_prefix_is_deduced_by_the_light_model():
    runner, ticket = _subtyped("Le bouton Envoyer ne répond plus")
    answer = '{"subtype": "bug", "reason": "Il ne marche plus.", "confidence": "high"}'
    with _state_home(), _naming_session(answer) as asked:
        job = runner.prepare(ticket)
    assert len(asked) == 1 and "what kind of change it is" in asked[0], asked
    assert job is not None and job.subtype == "bug"
    assert _subtype_written(runner) == ["Bug"]
    assert any("Il ne marche plus." in note for note in job.notes), job.notes

    # With no type either, the one session says both.
    runner, ticket = _subtyped("Le bouton Envoyer ne répond plus", kind="")
    answer = (
        '{"type": "code", "reason": "Un correctif.", "confidence": "high", '
        '"alternative": "", "subtype": "perf", "subtype_confidence": "medium"}'
    )
    with _state_home(), _naming_session(answer) as asked:
        job = runner.prepare(ticket)
    assert len(asked) == 1 and '"subtype"' in asked[0], "one session for the type and the sub-type"
    assert job is not None and job.kind == "code" and job.subtype == "perf"
    assert _subtype_written(runner) == ["Perf"]


@case
def a_sub_type_in_doubt_is_an_improvement_and_the_report_says_so():
    runner, ticket = _subtyped("Revoir le bouton Envoyer")
    with _state_home(), _naming_session('{"subtype": "bug", "confidence": "low"}'):
        job = runner.prepare(ticket)
    assert job is not None and job.subtype == "improvement", "a doubt never blocks"
    assert _subtype_written(runner) == ["Amélioration"]
    assert any("Sous-type" in note and "Amélioration" in note for note in job.notes), job.notes

    runner, ticket = _subtyped("Revoir le bouton Envoyer")
    with _state_home(), _naming_session("", missing=True):
        job = runner.prepare(ticket)
    assert job is not None and job.subtype == "improvement"
    assert _subtype_written(runner) == [], (
        "no answer at all: nothing written, asked again next time"
    )


@case
def a_sub_type_somebody_wrote_is_never_overwritten():
    runner, ticket = _subtyped("[Bug] Le README", subtype="Docs")
    with _state_home(), _naming_session('{"subtype": "bug", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and _subtype_written(runner) == []
    assert job is not None and job.subtype == "docs", "the column wins over the prefix"

    runner, ticket = _subtyped("[Bug] Annoncer la v2", kind="Rédaction")
    with _state_home(), _naming_session("{}") as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.subtype == "" and _subtype_written(runner) == [], (
        "ignored on the other types"
    )

    runner, ticket = _nameless("Le bouton ne répond plus", "x")
    with _state_home(), _naming_session('{"subtype": "bug", "confidence": "high"}') as asked:
        job = runner.prepare(ticket)
    assert asked == [] and job.subtype == "", "a board without the column asks nobody"


@case
def a_sub_type_is_the_developers_word_in_every_language():
    """« Feature » in French too, not « Fonctionnalité »: one label, no entry in french.ts.

    The French words it used to be shown as are still understood, in a title or
    an answer — only what the console shows changed, not what is read.
    """
    dictionary = (FRONTEND / "src/lib/french.ts").read_text(encoding="utf-8")
    assert [subtype.label for subtype in subtypes.SUBTYPES] == [
        "Bug",
        "Feature",
        "Improvement",
        "Chore",
        "Refactor",
        "Perf",
        "Docs",
        "Security",
    ]
    for subtype in subtypes.SUBTYPES:
        assert subtype.as_dict()["label"] == subtype.label, subtype.key
        assert f'"{subtype.label}":' not in dictionary, subtype.key
    for word, key in (
        ("Fonctionnalité", "feature"),
        ("Amélioration", "improvement"),
        ("Maintenance", "chore"),
        ("Performance", "perf"),
        ("Sécurité", "security"),
    ):
        assert subtypes.of(word) == key, word
    ideas = (FRONTEND / "src/components/console/idea-cards.tsx").read_text(encoding="utf-8")
    assert 'technical: "Tech"' in ideas and 't("Technical")' not in ideas


@case
def the_commit_the_pull_request_and_the_changelog_follow_the_sub_type():
    for key, commit, section in (
        ("bug", "fix", "Fixed"),
        ("feature", "feat", "Added"),
        ("improvement", "feat", "Changed"),
        ("chore", "chore", ""),
        ("refactor", "refactor", "Changed"),
        ("perf", "perf", "Changed"),
        ("docs", "docs", ""),
        ("security", "fix", "Security"),
    ):
        said = subtypes.section(key)
        assert f"starts with `{commit}: `" in said, key
        assert (f"under **{section}**" in said) if section else ("no entry" in said), key
    assert "reproduces the bug" in subtypes.section("bug")
    assert "reproduces" not in subtypes.section("feature")
    assert subtypes.section("") == ""

    assert subtypes.titled("feature", "Ponos — [Feature] Un badge") == "feat: Ponos — Un badge"
    assert subtypes.titled("bug", "[UX] [Bug] Le bouton") == "fix: [UX] Le bouton"
    assert subtypes.titled("docs", "Le README") == "docs: Le README"
    assert subtypes.titled("bug", "fix: déjà dit") == "fix: déjà dit"
    assert subtypes.titled("", "[Bug] x") == "[Bug] x"

    common = dict(project="p", title="T", body="b", repo="/r", branch="b", base="main", url="u")
    built = prompt.build(prompt.DEFAULT, **common, kind=subtypes.section("bug"))
    assert built.index("`fix: `") < built.index("# What is expected")
    assert "- Notion ticket: u\n\n# What is expected" in prompt.build(prompt.DEFAULT, **common)


@case
def the_sub_type_moves_the_level_a_code_ticket_starts_at():
    grid = C.Runner(use_fable=True).model_grid()
    body = "Une phrase."
    assert models.choose("Le README", body, kind="code", code=True, grid=grid).level == "standard"
    docs = models.choose("Le README", body, kind="code", code=True, grid=grid, subtype="docs")
    assert docs.level == "light" and ("model-subtype-lower", {"subtype": "docs"}) in docs.signals
    hole = models.choose("Le token", body, kind="code", code=True, grid=grid, subtype="security")
    assert hole.level == "heavy"
    writing = models.choose(
        "Le token", body, kind="writing", code=False, grid=grid, subtype="security"
    )
    assert writing.level == "light", "only a code ticket"
    path, _ = _saved()
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            '\n[runner]\nauto_model_subtype_docs = "same"\nauto_model_subtype_bug = "nope"\n'
        )
    loaded = C.load(path).runner
    assert loaded.subtype_shift("docs") == "same" and loaded.subtype_shift("bug") == "same"
    assert loaded.subtype_shift("security") == "higher"
    top = C.Runner(auto_model_code="heaviest").model_grid()
    assert (
        models.choose("x", body, kind="code", code=True, grid=top, subtype="security").level
        == "heaviest"
    )


@case
def init_offers_the_sub_type_column_and_doctor_names_it_when_it_is_missing():
    settings = C.Notion(properties=dict(C._DEFAULT_PROPERTIES))
    column = provision.tickets_schema(settings)["Sous-type"]
    options = [option["name"] for option in column["select"]["options"]]
    assert options == [
        "Bug",
        "Feature",
        "Amélioration",
        "Chore",
        "Refactor",
        "Perf",
        "Docs",
        "Sécurité",
    ]
    assert files.schemas(settings)["tickets"]["Sous-type"] == "select"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        from ponos.__main__ import _doctor_columns

        _doctor_columns({"Status": "status"}, settings)
    assert "“Sous-type” missing" in out.getvalue(), out.getvalue()


@case
def the_backfill_fills_the_code_tickets_from_their_prefix_alone(state_home):
    def page(identifier: str, title: str, kind: str, subtype: str = "") -> notion.Page:
        properties = {"Type": {"type": "select", "select": {"name": kind}}}
        if subtype:
            properties["Sous-type"] = {"type": "select", "select": {"name": subtype}}
        return notion.Page(id=identifier, url="", title=title, properties=properties)

    done = page("f", "[Bug] Fermé depuis un an", "Code")
    done.properties["Status"] = {"type": "status", "status": {"name": "Done"}}
    pages = [
        done,
        page("a", "[Bug] Le bouton", "Code"),
        page("b", "[Docs] Le README", "Code", "Feature"),
        page("c", "Sans préfixe", "Code"),
        page("d", "[Bug] Un texte", "Rédaction"),
        page("e", "Ponos — [Ops] Node 24", "Code"),
    ]

    class Board(_SubtypedClient):
        def query(self, database_id, filter_=None):
            return pages

        def update(self, database_id, page_id, values):
            self.written.append({"id": page_id, **values})

    runner, _ = _nameless("x", "")
    runner.client = Board("")
    with _naming_session("{}") as asked:
        dry = runner.backfill_subtypes(write=False)
        assert [(one.id, key) for one, key in dry] == [("a", "bug"), ("e", "chore")]
        assert runner.client.written == []
        runner.backfill_subtypes()
    assert asked == [], "never a session"
    assert runner.client.written == [
        {"id": "a", "Sous-type": "Bug"},
        {"id": "e", "Sous-type": "Chore"},
    ], runner.client.written
    assert [one.id for one, _ in runner.backfill_subtypes(write=False, closed=True)] == [
        "f",
        "a",
        "e",
    ], "a done ticket only when asked: an edit moves its closing date"
    settings = C.Notion()
    assert web_tickets._subtype(done, settings) == "bug", (
        "the console reads the prefix it was not given"
    )
    assert web_tickets._subtype(pages[2], settings) == "feature", "the column wins"
    assert web_tickets._subtype(pages[4], settings) == "", "never on another type"


@case
def the_statistics_count_the_closed_tickets_by_sub_type_and_by_week():

    def card(identifier, subtype, edited, duration=None):
        return {
            "id": identifier,
            "column": "done",
            "subtype": subtype,
            "created": "2026-10-01",
            "edited": edited,
            "duration": duration,
        }

    tickets = [
        card("a", "bug", "2026-10-06"),
        card("b", "bug", "2026-10-13", 30),
        card("c", "docs", "2026-10-13"),
        card("d", "", "2026-10-13"),
    ]
    history = [
        {"id": "a", "at": "2026-10-06T09:00:00+00:00", "cost_usd": 1.0, "seconds": 600},
        {"id": "b", "at": "2026-10-13T09:00:00+00:00", "cost_usd": 3.0},
    ]
    found = web_statistics.figures(tickets, history, date(2026, 10, 1), date(2026, 10, 20), UTC)[
        "subtypes"
    ]
    assert found["total"] == 3, found
    assert found["weeks"][1]["counts"] == {"bug": 1} and found["weeks"][2]["counts"] == {
        "bug": 1,
        "docs": 1,
    }
    bug = next(item for item in found["subtypes"] if item["key"] == "bug")
    assert (bug["count"], bug["cost"], bug["duration"]) == (2, 2.0, 20.0), bug
    docs = next(item for item in found["subtypes"] if item["key"] == "docs")
    assert docs["cost"] is None and docs["duration"] is None and docs["label"] == "Docs"
    # The console tells a sub-type by its colour alone: no emoji reaches it.
    assert "icon" not in docs, docs
