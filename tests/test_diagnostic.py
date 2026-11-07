"""`diagnostic.py` and `diagnosis.py`: an investigation, and the tickets it writes."""

from __future__ import annotations

import json
from pathlib import Path

from support import case

from ponos import diagnostic, kinds, project_settings, prompt

# -- the fix tickets the session writes --------------------------------------


def _fix(**changes: object) -> dict[str, object]:
    return {
        "title": "Additionner",
        "context": "`calc.py:2` soustrait.",
        "expected": "Un `+`.",
        "done": "`total(2, 3)` vaut 5.",
        "out": "Le reste.",
        **changes,
    }


@case
def fix_tickets_are_read_with_their_four_parts_and_their_order() -> None:
    found, problem = diagnostic.fixes(
        [
            _fix(subtype="BUG", priority=180),
            _fix(title="Tester", type="code", after=[0, 0]),
            _fix(title="Prévenir", type="writing", subtype="bug", priority=True),
        ]
    )
    assert problem == "", problem
    assert [fix.title for fix in found] == ["Additionner", "Tester", "Prévenir"]
    assert (found[0].subtype, found[0].priority) == ("bug", 100), "clamped, and read lower case"
    assert found[1].after == [0], "a dependency said twice is one"
    assert (found[2].kind, found[2].subtype, found[2].priority) == ("writing", "", None)


@case
def a_fix_file_with_one_mistake_creates_nothing() -> None:
    """A series created up to its first mistake is a series nobody can trust the order of."""
    for raw, said in (
        ({"title": "un objet"}, "not an array"),
        ([_fix(), _fix(done="")], "has no done"),
        ([_fix(type="diagnostic")], "of type"),
        ([_fix(), _fix(after=[1])], "comes after"),
        ([_fix(after=[-1])], "comes after"),
        (["texte"], "not an object"),
    ):
        found, problem = diagnostic.fixes(raw)
        assert found == [] and said in problem, (raw, problem)
    found, problem = diagnostic.fixes({"tickets": [_fix()]})
    assert len(found) == 1 and not problem, "an array under `tickets` is read too"


@case
def no_fix_file_is_no_fix_and_a_broken_one_is_said() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        assert diagnostic.read_fixes(workdir) == ([], "")
        (workdir / diagnostic.FIXES).write_text("[{", encoding="utf-8")
        found, problem = diagnostic.read_fixes(workdir)
        assert found == [] and "not JSON" in problem, problem
        (workdir / diagnostic.FIXES).write_text(json.dumps([_fix()]), encoding="utf-8")
        assert len(diagnostic.read_fixes(workdir)[0]) == 1


@case
def a_fix_ticket_mission_holds_its_four_parts_and_where_it_comes_from() -> None:
    fix = diagnostic.fixes([_fix()])[0][0]
    headings = {
        "context": "Contexte",
        "expected": "Attendu",
        "done": "Fini quand",
        "out": "Hors périmètre",
        "from": "Écrit par le diagnostic",
    }
    body = diagnostic.body(fix, headings, "https://board.invalid/abc")
    for line in (
        "### Contexte\n\n`calc.py:2` soustrait.",
        "### Attendu",
        "### Fini quand",
        "### Hors périmètre\n\nLe reste.",
        "*Écrit par le diagnostic https://board.invalid/abc*",
    ):
        assert line in body, body


# -- what the project lets it reach -------------------------------------------


@case
def what_a_project_declares_is_read_leniently_and_saved_strictly() -> None:
    raw = {
        "mcp": "lead-finder, umami\nlead-finder",
        "hosts": [
            {"address": "deck@steamdeck.local:22", "entry": "DECK_KEY", "label": " la  console "},
            {"address": "pas une adresse", "entry": "X"},
            {"address": "prod.example", "entry": "pas-un-nom"},
        ],
        "urls": ["https://leadz.example", "ftp://ailleurs"],
        "ready": "yes",
    }
    access = diagnostic.parse(raw)
    assert access.mcp == ("lead-finder", "umami")
    assert access.hosts == (diagnostic.Host("deck@steamdeck.local:22", "DECK_KEY", "la console"),)
    assert access.urls == ("https://leadz.example",)
    assert access.ready is False, "only true is true"
    assert access.entries == ["DECK_KEY"]
    assert diagnostic.parse(access.as_dict()) == access, "what is saved reads back the same"
    assert not diagnostic.parse(None) and not diagnostic.Access()
    for wrong in (
        {"urls": ["ftp://ailleurs"]},
        {"hosts": [{"address": "pas une adresse"}]},
        {"hosts": [{"address": "deck@host", "entry": "pas-un-nom"}]},
        {"mcp": ["/etc/passwd"]},
    ):
        try:
            diagnostic.checked(wrong)
        except ValueError:
            continue
        raise AssertionError(f"{wrong} was saved")


@case
def a_project_keeps_its_diagnostic_accesses_and_drops_them_when_emptied(state_home: Path) -> None:
    project = "1234567890abcdef1234567890abcdef"
    assert project_settings.diagnostic(project) == diagnostic.Access()
    access = diagnostic.Access(mcp=("lead-finder",), ready=True)
    project_settings.set_diagnostic(project, "Leadz", access)
    assert project_settings.diagnostic(project) == access
    project_settings.set_diagnostic(project, "Leadz", diagnostic.Access())
    assert project_settings.diagnostic(project) == diagnostic.Access()


@case
def the_session_is_told_what_it_may_reach_and_never_a_value() -> None:
    access = diagnostic.Access(
        mcp=("lead-finder",),
        hosts=(
            diagnostic.Host("deck@steamdeck", "DECK", "la console"),
            diagnostic.Host("root@prod"),
        ),
        urls=("https://leadz.example",),
    )
    said = diagnostic.prompt(access, {"DECK": ["DECK_USER", "DECK_PASSWORD"]})
    assert "find the cause, fix nothing" in said and diagnostic.FIXES in said
    assert "`lead-finder`" in said and "only their tools that read" in said
    assert "`deck@steamdeck` (la console)" in said and "`$DECK_USER` and `$DECK_PASSWORD`" in said
    assert "`root@prod` — with the keys this machine already has" in said
    assert "https://leadz.example" in said and "GET requests only" in said
    bare = diagnostic.prompt(diagnostic.Access())
    assert "declares no access beyond its repository" in bare, bare
    granted = diagnostic.granted(
        access, [{"name": "DECK", "variables": ["DECK_USER", "DECK_PASSWORD"]}]
    )
    assert granted == {"DECK": ["DECK_USER", "DECK_PASSWORD"]}
    assert diagnostic.granted(access, []) == {}, "an entry the vault lacks is not promised"


@case
def a_diagnostic_reads_the_repository_and_is_never_asked_to_switch_to_code() -> None:
    section = prompt.kind("diagnostic", "/work/calcul")
    assert "/work/calcul" in section and "change nothing in it" in section
    assert "KIND: code" not in section, "a diagnostic writes a fix ticket, it is not made code"
    assert prompt.kind("diagnostic") == ""


@case
def a_diagnostic_is_a_type_worked_without_a_repository() -> None:
    assert "diagnostic" in kinds.KINDS and "diagnostic" in kinds.WITHOUT_REPOSITORY
    assert kinds.parse('{"type": "Diagnostic", "confidence": "high"}').kind == "diagnostic"
    settled = kinds.settle(kinds.Guess("code", "", "medium", "diagnostic"))
    assert settled.kind == "diagnostic", "between code and a diagnostic, not code"
    assert kinds.prudent("writing", "diagnostic") == "diagnostic"
    assert kinds.prudent("diagnostic", "code") == "code"
    assert "diagnostic" not in diagnostic.FIX_KINDS, "a diagnostic does not write diagnostics"
