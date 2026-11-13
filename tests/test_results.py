"""`results.py`: a ticket's result, apart from the account of its session."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from support import case

from ponos import db, results, ticket_page, tickets, voice

_POST = "Trois choses que j'ai apprises en livrant Ponos.\n\n1. Petit.\n2. Souvent.\n3. Seul."


@case
def a_code_session_s_result_is_its_block_and_the_rest_is_its_report() -> None:
    answer = (
        "<result>\nLe bouton Copier copie le texte brut.\n\n- page ticket\n</result>\n\n"
        "**What changed** — le bouton.\n\nRESULT: ok — bouton ajouté"
    )
    result, rest = results.extract(answer)
    assert result == "Le bouton Copier copie le texte brut.\n\n- page ticket"
    assert rest == "**What changed** — le bouton.\n\nRESULT: ok — bouton ajouté"
    assert results.without(answer) == rest
    # None at all: the message is the report whole.
    assert results.extract("Fait.\n\nRESULT: ok — fait") == ("", "Fait.\n\nRESULT: ok — fait")
    # The format quoted inline is no block: the tags are lines of their own.
    assert results.extract("I write <result> then </result>.")[0] == ""


@case
def the_report_on_the_page_leaves_the_result_out() -> None:
    said = voice.Voice("fr")
    report = ticket_page.report(
        said,
        status="done",
        summary="post écrit",
        answer=f"<result>\n{_POST}\n</result>\n\nJ'ai relu deux fois.\n\nRESULT: ok — post écrit",
    )
    assert "J'ai relu deux fois." in report
    assert "Petit." not in report and "<result>" not in report


@case
def an_old_part_what_was_done_is_cut_into_its_result_and_its_journal() -> None:
    done = (
        "**Résultat** : ✅ post écrit\n\n"
        "**Pull request** : https://github.com/o/r/pull/3\n\n"
        f"{_POST}\n\n"
        "**Reste à vérifier**\n\n- le ton\n\n"
        "### Historique\n\n- 2026-10-01 10:00 · ✅ post écrit"
    )
    result, journal = results.legacy(done)
    assert result == _POST
    assert journal.startswith("**Résultat** : ✅ post écrit\n\n**Pull request**")
    assert "- le ton" in journal and journal.endswith("- 2026-10-01 10:00 · ✅ post écrit")
    assert "Petit." not in journal


@case
def an_old_part_that_lost_its_bold_and_its_blank_lines_is_cut_all_the_same() -> None:
    done = (
        "Résultat : ✅ Découpage rédigé dans ANSWER.md.\n"
        "Découpage du ticket en trois sous-tickets.\n"
        "## Pourquoi trois\n"
        "Le chemin suppose une seule PR.\n"
        "Pull request : https://github.com/o/r/pull/9\n"
        "Reste à vérifier\n"
        "- la longueur\n"
        "### Historique\n"
        "- 2026-11-05 20:53 · 1 minute"
    )
    result, journal = results.legacy(done)
    assert result == (
        "Découpage du ticket en trois sous-tickets.\n## Pourquoi trois\nLe chemin suppose une seule PR."
    )
    assert journal == (
        "Résultat : ✅ Découpage rédigé dans ANSWER.md.\n\n"
        "Pull request : https://github.com/o/r/pull/9\n\nReste à vérifier\n\n- la longueur\n\n"
        "### Historique\n- 2026-11-05 20:53 · 1 minute"
    )


@case
def an_old_part_that_cannot_be_told_apart_stays_journal_whole() -> None:
    for done in (
        # A ticket that stopped: what it wrote is no deliverable.
        "**Résultat** : 🙋 il a posé une question\n\nIl manque le compte.",
        # Written by hand, or before the result line.
        "J'ai fait ceci et cela.",
        # Nothing of the session's own.
        "**Result:** ✅ done\n\n### History\n\n- one",
    ):
        assert results.legacy(done) == ("", done)
    assert results.legacy("") == ("", "")


@case
def an_excerpt_is_the_first_lines_without_their_marks() -> None:
    text = "# Audit\n\n| Gravité | Constat |\n|---|---|\n| Haute | **XSS** |\n\n- [lien](http://x)"
    assert results.excerpt(text) == "Audit\nGravité · Constat\nHaute · XSS"
    assert results.excerpt(text, lines=5).endswith("• lien")
    assert results.excerpt("x" * 400).endswith("…") and len(results.excerpt("x" * 400)) == 280
    assert results.excerpt("") == ""


@case
def the_runner_adds_the_files_and_the_diff_under_a_code_result() -> None:
    said = results.code_appendix(
        " a.py | 2 +-\n 1 file changed",
        "https://github.com/o/r/pull/7",
        files="Fichiers touchés",
        diff="Voir le diff",
    )
    assert "**Fichiers touchés**\n\n```\n a.py | 2 +-" in said
    assert said.endswith("[Voir le diff](https://github.com/o/r/pull/7/files)")
    assert results.code_appendix("", "", files="F", diff="D") == ""


@case
def every_result_is_a_version_and_none_is_overwritten(state_home: Path) -> None:
    made = tickets.create("Post LinkedIn", mission="Écris un post.")
    first = tickets.set_result(made.id, _POST)
    assert first is not None and first.version == 1 and first.source == "session"
    assert tickets.set_result(made.id, _POST) is None, "the same text is not kept twice"
    second = tickets.set_result(made.id, "Autre version.", source="edit", author="Salva")
    assert second is not None and second.version == 2
    record = tickets.get(made.id)
    assert record is not None and record.result == "Autre version."
    kept = tickets.results(made.id)
    assert [one.version for one in kept] == [2, 1]
    assert kept[1].text == _POST and kept[0].author == "Salva"
    assert tickets.set_result("0" * 32, "x") is None
    tickets.delete(made.id)
    assert tickets.results(made.id) == []


@case
def the_migration_cuts_the_tickets_of_before_and_keeps_a_copy() -> None:
    location = Path(tempfile.mkdtemp()) / "ponos.db"
    before = db.open_at(location, db.MIGRATIONS[: db.MIGRATIONS.index(db._tickets_have_a_result)])
    done = f"**Résultat** : ✅ post écrit\n\n{_POST}\n\n### Historique\n\n- une"
    try:
        for ticket, report in (("a" * 32, done), ("b" * 32, "Rien de démêlable.")):
            before.execute(
                "INSERT INTO tickets (id, title, report, created_at, edited_at) "
                "VALUES (?, 'T', ?, '2026-10-01', '2026-10-02')",
                (ticket, report),
            )
        before.commit()
    finally:
        before.close()
    after = db.open_at(location)
    try:
        after.row_factory = sqlite3.Row
        rows = {
            row["id"]: dict(row)
            for row in after.execute("SELECT id, result, journal FROM tickets ORDER BY id")
        }
        assert rows["a" * 32]["result"] == _POST
        assert (
            rows["a" * 32]["journal"] == "**Résultat** : ✅ post écrit\n\n### Historique\n\n- une"
        )
        assert rows["b" * 32] == {"id": "b" * 32, "result": "", "journal": "Rien de démêlable."}
        versions = after.execute(
            "SELECT ticket, version, source, at FROM ticket_results"
        ).fetchall()
        assert [tuple(row) for row in versions] == [("a" * 32, 1, "migration", "2026-10-02")]
    finally:
        after.close()
    assert db.backups(location), "a copy of the file is taken before"


@case
def ponos_show_prints_the_result_alone_or_the_three_parts(state_home: Path) -> None:
    import argparse
    import contextlib
    import io

    from ponos.__main__ import command_show

    made = tickets.create("Post LinkedIn", mission="Écris un post.", journal="Relu deux fois.")
    tickets.set_result(made.id, _POST)

    def shown(reference: str, result: bool) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = command_show(argparse.Namespace(ticket=reference, result=result))
        return code, out.getvalue(), err.getvalue()

    assert shown(made.id[-8:], True) == (0, f"{_POST}\n", "")
    code, out, _ = shown(f"http://console/tickets/{made.id}", False)
    assert code == 0
    assert out.index("Mission") < out.index(_POST) < out.index("Journal")
    assert "Relu deux fois." in out
    empty = tickets.create("Rien encore")
    assert shown(empty.id, True)[0] == 1
    assert shown("ffffffff", False) == (1, "", "No ticket for ffffffff\n")


@case
def a_session_asked_for_a_change_starts_from_the_result_it_had() -> None:
    from ponos import prompt

    said = prompt.current_result(_POST, 2)
    assert "version 2" in said and f"<current-result>\n{_POST}\n</current-result>" in said
    assert prompt.current_result("  ", 1) == ""
