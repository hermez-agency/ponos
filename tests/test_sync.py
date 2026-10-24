"""`sync.py`: the two boards, kept in step."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import _mirror, _settings, case

from ponos import files, store, sync

# -- the two boards, kept in step --------------------------------------------


@case
def a_ticket_written_in_notion_appears_in_the_files():
    with _mirror("Je suis Camille Martin.") as (here, there, both, marks):
        page_id = here.create_row("tickets", "Corriger l'entête", {"Status": "Ready"})
        here.replace_markdown(page_id, "Relire la page d'accueil.")

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == [
            "created-in-markdown",
            "notion→markdown",
        ], [entry.what for entry in report.carried]
        mirrored = there.page(page_id)
        assert mirrored.title == "Corriger l'entête"
        assert store.read(mirrored, "Status") == "Ready"
        assert there.blocks_text(page_id) == "Relire la page d'accueil."
        assert there.context() == "Je suis Camille Martin."

        # A second pass on an unchanged board carries nothing: without that,
        # every fifteen minutes would rewrite every file on the disk.
        assert not both.synchronise(_settings(), stamps=marks).carried

        # And a change in Notion afterwards reaches the file.
        here.update("tickets", page_id, {"Status": "Done"})
        again = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in again.carried] == ["notion→markdown"]
        assert store.read(there.page(page_id), "Status") == "Done"


@case
def a_ticket_written_in_a_file_appears_in_notion():
    with _mirror() as (here, there, both, marks):
        local = there.create_row("tickets", "Écrire l'annonce", {"Status": "Ready"})
        there.replace_markdown(local, "Une annonce courte.")

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == ["created-in-notion"]
        created = report.carried[0].page
        assert here.pages[created].title == "Écrire l'annonce"
        assert store.read(here.pages[created], "Status") == "Ready"
        assert here.bodies[created] == "Une annonce courte."
        # The file now wears Notion's identifier: the URL, the relations and
        # every report from here on carry that one, and nothing carries its own.
        assert there.page(created).title == "Écrire l'annonce"

        # Changed in the file afterwards, and carried the other way.
        there.update("tickets", created, {"Status": "In review"})
        there.replace_markdown(created, "Une annonce, relue.")
        again = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in again.carried] == ["markdown→notion"]
        assert store.read(here.pages[created], "Status") == "In review"
        assert here.bodies[created] == "Une annonce, relue."


@case
def a_page_moved_on_both_sides_is_a_conflict_the_newest_wins():
    """The rule `storage.conflict` names, and the line it leaves behind.

    Losing an edit is not the failure mode to avoid here — one of the two is
    going to lose whatever the rule says. The failure mode is losing it
    *quietly*, so the conflict is journalled with both timestamps and the name
    of the side that won.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)

        # Both move, and Notion moves last.
        there.update("tickets", page_id, {"Status": "Blocked"})
        here.update("tickets", page_id, {"Status": "Done"})

        report = both.synchronise(_settings(), stamps=marks)
        assert len(report.conflicts) == 1
        said = report.conflicts[0].detail
        assert "Notion wins" in said and "newest" in said
        assert store.read(there.page(page_id), "Status") == "Done"

        # And the other way round: the file is the later one, by a minute —
        # within the same one, Notion would keep it.
        earlier = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        here.update("tickets", page_id, {"Status": "Failed"}, at=earlier)
        there.update("tickets", page_id, {"Status": "In review"})
        back = both.synchronise(_settings(), stamps=marks)
        assert len(back.conflicts) == 1
        assert "Markdown wins" in back.conflicts[0].detail
        assert store.read(here.pages[page_id], "Status") == "In review"


@case
def a_conflict_in_the_same_minute_goes_to_notion_and_says_so():
    """Notion's time is to the minute, a file's to the microsecond: compare minutes.

    A file changed at 10:05:30 and a page changed at 10:05:50 — which Notion
    gives back as 10:05:00 — would make the file look twenty-nine seconds newer
    than a page that is in fact the later of the two. Both sides are cut to the
    minute before they are compared, and a tie goes to Notion, in so many words.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)

        _, path = there._find(page_id)
        front, body = files.parse(path.read_text(encoding="utf-8"))
        front["Status"] = "Blocked"
        front["edited"] = "2030-01-01T10:05:30.123456+00:00"
        path.write_text(files.render(front, body), encoding="utf-8")
        here.update("tickets", page_id, {"Status": "Done"}, at="2030-01-01T10:05:00.000Z")

        report = both.synchronise(_settings(), stamps=marks)
        assert len(report.conflicts) == 1, report.entries
        said = report.conflicts[0].detail
        assert "same minute" in said and "Notion wins" in said, said
        assert store.read(there.page(page_id), "Status") == "Done"


@case
def a_file_edited_by_hand_without_touching_edited_reaches_notion():
    """`$EDITOR` does not bump `edited`, and the file is still the side that moved.

    The board in files is meant to be edited by hand — git, grep and an editor
    — and a person who opens a ticket and changes a word leaves the frontmatter's
    `edited` as it was. The change has to reach Notion all the same, and a page
    changed by hand *and* in Notion is a conflict written down, not a file
    quietly written over.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)

        _, path = there._find(page_id)
        text = path.read_text(encoding="utf-8")
        assert "Status: Ready" in text, text
        path.write_text(text.replace("Status: Ready", "Status: Blocked"), encoding="utf-8")

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == ["markdown→notion"], report.entries
        assert store.read(here.pages[page_id], "Status") == "Blocked"
        assert not both.synchronise(_settings(), stamps=marks).carried

        # A body changed by hand travels the same way.
        text = path.read_text(encoding="utf-8")
        path.write_text(text.rstrip() + "\n\nUne ligne écrite à la main.\n", encoding="utf-8")
        assert [entry.what for entry in both.synchronise(_settings(), stamps=marks).carried] == [
            "markdown→notion"
        ]
        assert "Une ligne écrite à la main." in here.bodies[page_id]

        # Both sides move: a conflict, journalled, whichever side wins.
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("Status: Blocked", "Status: Failed"), encoding="utf-8")
        here.update("tickets", page_id, {"Status": "Done"})
        both_moved = both.synchronise(_settings(), stamps=marks)
        assert len(both_moved.conflicts) == 1, both_moved.entries
        assert store.read(there.page(page_id), "Status") == "Done"


@case
def a_deletion_is_written_down_and_never_carried_across():
    """Nothing the sync does may remove a page. It says so instead.

    A file disappears for a hundred reasons — a bad merge, a stray `rm`, an
    editor writing to the wrong place — and none of them is a decision to delete
    a ticket. The same holds the other way: a Notion page somebody archived is
    not a reason to throw away the file they may have been editing.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)
        _, path = there._find(page_id)
        path.unlink()

        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.deletions] == ["deleted-in-markdown"]
        assert page_id in here.pages, "the Notion page must be left exactly as it was"
        assert not report.carried, "a gone file is not a page to create again"

        # And it stays said: the next pass repeats it rather than re-creating.
        assert both.synchronise(_settings(), stamps=marks).deletions

        # The other way: the Notion page goes, the file stays.
        local = there.create_row("tickets", "L'autre", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)
        created = [page for page in here.pages if here.pages[page].title == "L'autre"][0]
        del here.pages[created]
        gone = both.synchronise(_settings(), stamps=marks)
        assert "deleted-in-notion" in [entry.what for entry in gone.deletions]
        assert there.page(created).title == "L'autre"
        del local


@case
def the_journal_keeps_what_the_reconciliations_did():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ponos.db"
        report = sync.Report()
        report.note("conflict", "tickets", "abc", "Le ticket", "both moved")
        report.note("deleted-in-notion", "tickets", "def", "L'autre", "gone")
        sync.write_journal(report, path)
        sync.write_journal(report, path)
        entries = sync.journal(3, path)
        assert len(entries) == 3, "the journal appends rather than replaces"
        assert entries[-1]["what"] == "deleted-in-notion"
        assert entries[-1]["title"] == "L'autre"
        assert entries[-1]["at"]


@case
def the_standing_context_travels_both_ways():
    with _mirror("Écrit dans Notion.") as (here, there, both, marks):
        both.synchronise(_settings(), stamps=marks)
        assert there.context() == "Écrit dans Notion."

        there.set_context("Réécrit dans le fichier.")
        report = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in report.carried] == ["markdown→notion"]
        assert here.context == "Réécrit dans le fichier."

        here.context = "Réécrit dans Notion."
        back = both.synchronise(_settings(), stamps=marks)
        assert [entry.what for entry in back.carried] == ["notion→markdown"]
        assert there.context() == "Réécrit dans Notion."


@case
def a_mirrored_write_lands_on_both_boards_at_once():
    """Between two reconciliations, the run's own work must be on both sides.

    A ticket claimed at 14:02 and reconciled at 14:15 would otherwise spend
    thirteen minutes reading "Ready" in the files while a session works on it.
    """
    with _mirror() as (here, there, both, marks):
        page_id = here.create_row("tickets", "Le ticket", {"Status": "Ready"})
        both.synchronise(_settings(), stamps=marks)

        both.update("tickets", page_id, {"Status": "In progress"})
        assert store.read(there.page(page_id), "Status") == "In progress"
        both.append_markdown(page_id, "Un rapport.")
        assert "Un rapport." in there.blocks_text(page_id)
        both.comment(page_id, "Fini.")
        assert [comment.text for comment in there.comments(page_id)] == ["Fini."]
        # And what the mirror reads is still Notion's answer.
        assert both.page(page_id).title == "Le ticket"
