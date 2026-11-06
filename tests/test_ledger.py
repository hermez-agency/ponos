"""`ledger.py` and `mirror.py`: `ponos.db` as the tickets, Notion as the mirror."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from support import case

from ponos import config as C
from ponos import ledger as ledger_module
from ponos import mirror, notion, store, ticket_page, tickets
from ponos.store import Comment, Page, read

SETTINGS = C.Notion(token="ntn_x", workspace="space")
DATABASE = "d" * 32


class _Notion:
    """Notion reduced to what the ledger asks of it, and able to go away."""

    def __init__(self) -> None:
        self.down = False
        self.pages: dict[str, Page] = {}
        self.bodies: dict[str, str] = {}
        self.talk: dict[str, list[Comment]] = {}
        self.calls: list[tuple[str, str]] = []
        self.projects = [Page("p" * 32, "", "Ponos", {})]

    def _up(self) -> None:
        if self.down:
            raise notion.Offline("no connection")

    def workspace(self, settings: C.Notion) -> Any:
        from ponos.workspace import Workspace

        self._up()
        return Workspace(tickets=DATABASE, projects="proj")

    def query(self, database_id: str, filter_: Any = None) -> list[Page]:
        self._up()
        if database_id == "proj":
            return self.projects
        return list(self.pages.values())

    def page(self, page_id: str) -> Page:
        self._up()
        return self.pages[page_id]

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        self._up()
        return self.bodies.get(block_id, "")

    def comments(self, page_id: str) -> list[Comment]:
        self._up()
        return self.talk.get(page_id, [])

    def create_row(self, database_id: str, title: str, values: Any = None) -> str:
        self._up()
        page_id = f"{len(self.pages) + 1:032x}"
        properties = {"Name": {"type": "title", "title": [{"plain_text": title}]}}
        self.pages[page_id] = Page(
            page_id, "", title, properties, {"last_edited_time": "2020-01-01"}
        )
        self.calls.append(("create", title))
        self.values = values
        return page_id

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        self._up()
        self.calls.append(("update", ",".join(sorted(values))))

    def append_markdown(self, page_id: str, markdown: str) -> int:
        self._up()
        self.bodies[page_id] = markdown
        return 1

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        self._up()
        self.bodies[page_id] = markdown
        self.calls.append(("replace", page_id))
        return 1

    def replace_section(self, page_id: str, titles: Any, markdown: str) -> int:
        self._up()
        self.calls.append(("section", markdown))
        return 1

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self._up()
        self.calls.append(("comment", text))

    def trash(self, page_id: str) -> str:
        self._up()
        self.calls.append(("trash", page_id))
        return ""

    def me(self) -> str:
        return "integration"

    def my_name(self) -> str:
        return "Ponos"

    def resolve_database(self, identifier: str) -> str:
        return identifier

    def schema(self, database_id: str) -> dict[str, str]:
        return {}

    def forget_database(self, database_id: str) -> None:
        pass


def _ledger(state: Path, remote: _Notion | None = None) -> tuple[ledger_module.Ledger, _Notion]:
    remote = remote or _Notion()
    return ledger_module.Ledger(remote, SETTINGS, state / "cache.json"), remote  # type: ignore[arg-type]


def _page(title: str, status: str, page_id: str, edited: str = "2020-01-01T00:00:00Z") -> Page:
    kinds = ledger_module.schema(SETTINGS)
    made = tickets.Record(id=page_id, title=title, status=status, notion=page_id)
    page = ledger_module.page_of(SETTINGS, made, kinds)
    page.raw["last_edited_time"] = edited
    return page


@case
def the_ledger_serves_the_tickets_as_pages_and_filters_them(state_home: Path) -> None:
    ledger, _ = _ledger(state_home)
    ledger.workspace(SETTINGS)
    first = tickets.create("Un", status="ready", priority=80, mission="Fais un.")
    tickets.create("Deux", status="done")
    ready = {"property": "statut", "select": {"equals": "ready"}}
    pages = ledger.query("tickets", ready)
    assert [page.id for page in pages] == [first.id]
    assert read(pages[0], "Priorité") == 80 and read(pages[0], "statut") == "ready"
    assert ledger.resolve_database(DATABASE) == "tickets"
    assert ledger.blocks_text(first.id) == "Fais un."


@case
def a_write_lands_in_the_row_and_in_the_queue(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    page = ledger.create_row("tickets", "Neuf", {"statut": "ready", "Priorité": 70})
    ledger.update(
        "tickets", page, {"statut": "progress", "Cost": 0.25, "Pull Request": "https://pr/1"}
    )
    ledger.comment(page, "Question ?")
    found = tickets.get(page)
    assert found is not None and found.status == "progress" and found.cost == 0.25
    assert found.pull_request == "https://pr/1"
    assert [remark.text for remark in tickets.comments(page)] == ["Question ?"]
    assert ledger.comments(page)[0].created_by == ledger.me()
    assert remote.calls == []  # nothing went to Notion: the mirror does that


@case
def the_page_is_cut_in_its_two_parts_and_put_back(state_home: Path) -> None:
    ledger, _ = _ledger(state_home)
    made = tickets.create("T", mission="Fais X.")
    done = ticket_page.DONE[0]
    ledger.replace_section(made.id, ticket_page.DONE, f"## {done}\n\n✅ Fait.")
    ledger.append_blocks(made.id, [{"type": "paragraph", "paragraph": {"rich_text": []}}])
    found = tickets.get(made.id)
    assert found is not None and found.mission == "Fais X." and found.report == "✅ Fait."
    assert ledger.blocks_text(made.id) == f"Fais X.\n\n## {done}\n\n✅ Fait."
    assert ticket_page.mission(ledger.blocks_text(made.id)) == "Fais X."
    ledger.replace_markdown(made.id, f"## Mission\n\nFais Y.\n\n## {done}\n\nRien.")
    again = tickets.get(made.id)
    assert again is not None and again.mission == "Fais Y." and again.report == "Rien."


@case
def the_mirror_creates_the_page_then_sends_one_write_per_ticket(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    page = ledger.create_row("tickets", "Neuf", {"statut": "ready"})
    ledger.update("tickets", page, {"statut": "progress"})
    ledger.update("tickets", page, {"Cost": 1.5})
    ledger.update("tickets", page, {"Cost": 2.5})
    report = mirror.push(ledger)
    assert not report.problems and tickets.pending() == []
    found = tickets.get(page)
    assert found is not None and found.notion in remote.pages
    # The page was made once, with everything: the later changes leave with it.
    assert [call[0] for call in remote.calls] == ["create"]
    ledger.update("tickets", page, {"statut": "review"})
    ledger.update("tickets", page, {"Cost": 3.0, "Progress": "fini"})
    mirror.push(ledger)
    assert remote.calls[1:] == [("update", "Cost,Progress,statut")]


@case
def notion_down_blocks_nothing_and_the_mirror_catches_up(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    remote.down = True
    page = ledger.create_row("tickets", "Pendant la panne", {"statut": "ready"})
    ledger.update("tickets", page, {"statut": "progress"})
    ledger.comment(page, "Dit hors ligne")
    assert ledger.query("tickets")[0].id == page
    report = mirror.run(ledger)
    assert report.offline and len(tickets.pending()) == 3
    assert tickets.pending()[0].tries == 1
    remote.down = False
    report = mirror.run(ledger)
    assert not report.offline and tickets.pending() == []
    assert ("comment", "Dit hors ligne") in remote.calls


@case
def the_workspace_and_the_projects_survive_notion_going_away(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    space = ledger.workspace(SETTINGS)
    assert space.tickets == "tickets" and space.projects == "proj"
    assert [page.title for page in ledger.query("proj")] == ["Ponos"]
    remote.down = True
    fresh, _ = _ledger(state_home, remote)  # a new process: only the file remembers
    again = fresh.workspace(SETTINGS)
    assert again.projects == "proj" and again.tickets == "tickets"
    assert [page.title for page in fresh.query("proj")] == ["Ponos"]
    try:
        fresh.query("never-read")
    except store.StoreError:
        pass
    else:
        raise AssertionError("what was never read cannot be answered from the cache")


@case
def a_page_created_in_notion_becomes_a_ticket_and_its_status_moves(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    new = "a" * 32
    remote.pages[new] = _page("Venu de Notion", "ready", new)
    remote.bodies[new] = "## Mission\n\nFais Z."
    report = mirror.pull(ledger)
    assert report.created == 1
    born = tickets.get(new)
    assert born is not None and born.mission == "Fais Z." and born.notion == new
    assert tickets.pending() == []  # it is there already: nothing to send back
    remote.pages[new] = _page("Venu de Notion", "blocked", new, edited="2020-01-02T00:00:00Z")
    mirror.pull(ledger)
    moved = tickets.get(new)
    assert moved is not None and moved.status == "blocked" and tickets.pending() == []


@case
def what_ponos_has_still_to_say_wins_over_what_notion_says(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    page = "b" * 32
    tickets.create("Local", id=page, notion=page, status="ready")
    ledger.update("tickets", page, {"statut": "progress"})
    remote.pages[page] = _page("Local", "ready", page, edited="2020-01-02T00:00:00Z")
    mirror.pull(ledger)
    kept = tickets.get(page)
    assert kept is not None and kept.status == "progress"


@case
def a_comment_written_in_notion_is_read_with_the_discussion(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    page = "c" * 32
    tickets.create("T", id=page, notion=page)
    remote.talk[page] = [
        Comment("Réponse", "t", id="1", discussion_id="x", created_by="human"),
        Comment("Notre voix", "t", id="2", discussion_id="x", created_by="integration"),
    ]
    first = ledger.comments(page)
    assert [(c.text, c.created_by) for c in first] == [("Réponse", "human")]
    assert len(ledger.comments(page)) == 1  # read twice, kept once
    assert all(change.what != "comment" for change in tickets.pending())


@case
def importing_fills_the_table_once(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    for number in "de":
        remote.pages[number * 32] = _page(f"Ticket {number}", "done", number * 32)
        remote.bodies[number * 32] = (
            f"## Mission\n\nFais {number}.\n\n## Ce qui a été fait\n\n✅ Oui."
        )
    assert mirror.imported(ledger) == (2, 0)
    assert mirror.imported(ledger) == (0, 2)
    found = tickets.get("d" * 32)
    assert found is not None and found.mission == "Fais d." and found.report == "✅ Oui."
    assert tickets.pending() == []


@case
def a_deleted_ticket_trashes_its_page(state_home: Path) -> None:
    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    page = ledger.create_row("tickets", "À supprimer", {})
    mirror.push(ledger)
    made = tickets.get(page)
    assert made is not None
    ledger.trash(page)
    mirror.push(ledger)
    assert ("trash", made.notion) in remote.calls


@case
def a_ready_ticket_is_in_the_runners_queue_with_notion_down(state_home: Path) -> None:
    from support import _board_runner

    from ponos import workspace as workspace_module

    ledger, remote = _ledger(state_home)
    ledger.workspace(SETTINGS)
    tickets.create("Prêt", status="ready", mission="Fais-le.", project="p" * 32, priority=60)
    tickets.create("Brouillon", status="draft")
    remote.down = True
    runner = _board_runner([], {})
    runner.client = ledger
    runner.config.notion = SETTINGS
    runner._workspace = workspace_module.Workspace(tickets="tickets")
    assert [ticket.title for ticket in runner.ready()] == ["Prêt"]
