"""`store.py`: the board a configuration chooses, and the screens that work without Notion."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from support import (
    _bare_api,
    _board,
    _ColumnsClient,
    _config,
    _markdown_api,
    _Nudged,
    _state_home,
    case,
)

from ponos import config as C
from ponos import files, ideas, markdown, notion, projects, state, store, sync
from ponos import ticket as ticket_module
from ponos.web import api as web_api
from ponos.web import board as web_board
from ponos.web import creation as web_creation
from ponos.web import live as web_live
from ponos.web import removal as web_removal

# -- the configuration that chooses a board -----------------------------------


@case
def the_storage_mode_decides_which_store_is_opened():
    configuration = _config("")
    assert configuration.storage.mode == "notion"
    assert isinstance(store.open(configuration), notion.Client)

    with tempfile.TemporaryDirectory() as directory:
        markdown_only = _config(f'[storage]\nmode = "markdown"\npath = "{directory}/board"\n')
        assert markdown_only.storage.path == Path(directory) / "board"
        assert isinstance(store.open(markdown_only), files.Board)
        both = _config(f'[storage]\nmode = "both"\npath = "{directory}/board"\n')
        assert isinstance(store.open(both), sync.Mirror)

    # A word nobody meant must not quietly decide where the board lives.
    assert _config('[storage]\nmode = "postgres"\n').storage.mode == "notion"
    assert _config('[storage]\nconflict = "mine"\n').storage.conflict == "newest"


@case
def a_markdown_installation_needs_neither_token_nor_workspace():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[storage]\nmode = "markdown"\n', encoding="utf-8")
    C.load(path).require_usable()  # must not raise

    # And a Notion one still says exactly what it is missing.
    empty = Path(tempfile.mkdtemp()) / "config.toml"
    empty.write_text("[notion]\n", encoding="utf-8")
    try:
        C.load(empty).require_usable()
    except C.ConfigError as error:
        assert "notion.token" in str(error)
        assert "markdown" in str(error), "the way out is worth naming here"
    else:
        raise AssertionError("a Notion installation with no token must not be usable")


# -- the three screens that must work without Notion --------------------------


@case
def the_console_lists_every_project_it_knows_of():
    """The board's own, and the ones only the configuration names.

    A name the file maps to a path and the board has never heard of is still a
    project of this installation — and the row says so, rather than sending
    somebody looking for a page that does not exist.
    """
    with _board() as board:
        code = board.create_row("projects", "ponos", {"Repository": "user/repo"})
        board.create_row("projects", "Site vitrine", {})
        ticket = board.create_row("tickets", "Un ticket", {"Status": "Ready"})
        board.update("tickets", ticket, {"Project": [code]})

        api = _markdown_api(board)
        api._config.projects["Jeu d'usine"] = "/home/salva/workspace/usine"
        asked: list[str] = []
        query = api.runner.client.query
        api.runner.client.query = lambda database, *rest, **named: (
            asked.append(database) or query(database, *rest, **named)
        )
        drawn = api.all_projects()
        assert api.runner.database not in asked, "the tickets are the console's to count"

    rows = {project["name"]: project for project in drawn["projects"]}
    assert set(rows) == {"ponos", "Site vitrine", "Jeu d'usine"}
    assert rows["ponos"]["kind"] == "code"
    assert rows["ponos"]["repository"] == "user/repo"
    # Counted by the console on the tickets it already holds: a count here was
    # the whole tickets database read again on every call.
    assert "tickets" not in rows["ponos"]
    # No repository declared anywhere: a document project, not a broken one.
    assert rows["Site vitrine"]["kind"] == "document"
    assert rows["Jeu d'usine"]["source"] == "config"
    assert rows["Jeu d'usine"]["path"] == "/home/salva/workspace/usine"
    assert drawn["storage"] == "markdown"


@case
def the_console_opens_a_project_and_writes_it_back():
    """A project is a page you can change, and the brief is why it is worth opening.

    What is written goes to the column the page already carries — a project
    database is written by hand, so "Repository" is sometimes "github" — and a
    save that invented a second column beside the one somebody filled in would
    be a save that changes nothing anybody can see.
    """
    with _board() as board:
        page = board.create_row("projects", "ponos", {"github": "user/repo"})
        board.replace_markdown(page, "Écris en français.")

        api = _markdown_api(board)
        opened = api.project(page)
        assert opened["name"] == "ponos"
        assert opened["repository"] == "user/repo"
        assert opened["content"] == "Écris en français."
        # No clone under the workspace root: the page says nowhere, not a guess.
        assert opened["located"] == ""

        written = api.save_project(
            page,
            {
                "name": "ponos",
                "repository": "user/autre-repo",
                "path": "~/workspace/ponos",
                "content": "Écris en français, et jamais de pyproject.",
            },
        )
        assert written["repository"] == "user/autre-repo"
        assert written["path"] == "~/workspace/ponos"
        assert written["content"] == "Écris en français, et jamais de pyproject."
        # The column somebody filled in, not a second one beside it.
        assert store.read(board.page(page), "github") == "user/autre-repo"
        assert "Repository" not in board.page(page).properties

        # Replacing, not appending: the brief is a value, like the context.
        api.save_project(page, {"content": "Écris en français, et jamais de pyproject."})
        assert board.blocks_text(page) == "Écris en français, et jamais de pyproject."

        # A payload with nothing in it says so rather than quietly doing nothing.
        try:
            api.save_project(page, {})
        except ValueError:
            pass
        else:
            raise AssertionError("a change with nothing to change must say so")

        # What the window asked for at the creation is corrected here too: the
        # description and the site in their columns, the type by its repository.
        written = api.save_project(
            page, {"description": "  Le  runner. ", "site": "https://ponos.dev"}
        )
        assert written["description"] == "Le runner."
        assert written["site"] == "https://ponos.dev"
        assert store.read(board.page(page), "URL") == "https://ponos.dev"
        for refused in ({"site": "ponos.dev"}, {"kind": "code", "repository": "", "path": ""}):
            try:
                api.save_project(page, refused)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{refused} must be refused")
        written = api.save_project(page, {"kind": "document", "repository": "user/autre-repo"})
        assert written["kind"] == "document"
        assert written["repository"] == "" and written["path"] == ""
        written = api.save_project(page, {"kind": "code", "repository": "user/repo"})
        assert written["kind"] == "code"

        # And a project the console has never heard of is a 404, not an empty page.
        try:
            api.project("f" * 32)
        except LookupError:
            pass
        else:
            raise AssertionError("an unknown project must not read as a blank one")


def _creatable(board: files.Board, language: str = "fr") -> web_api.Api:
    """A markdown Api that creates projects, speaking `language`."""
    api = _markdown_api(board)
    api._config.runner = C.Runner(language=language)
    api._runner.config = api._config
    api.creation = web_creation.Creation(api)
    api.watch = type("Watch", (), {"nudge": lambda self: None})()
    return api


def _refused(create, field: str) -> str:
    """The sentence a creation is refused with, which must be about `field`."""
    try:
        create()
    except web_creation.Refused as error:
        assert error.field == field, (error.field, str(error))
        return str(error)
    raise AssertionError(f"expected a refusal about {field}")


@case
def a_github_repository_is_written_as_its_whole_address():
    for given in (
        "hermez-agency/ponos",
        "https://github.com/hermez-agency/ponos",
        "https://github.com/hermez-agency/ponos.git",
        "github.com/hermez-agency/ponos/",
        "git@github.com:hermez-agency/ponos.git",
        "https://github.com/hermez-agency/ponos/tree/main/src",
    ):
        assert web_creation.github_url(given) == "https://github.com/hermez-agency/ponos", given
    for given in (
        "ponos",
        "https://gitlab.com/someone/ponos",
        "a/b/c",
        "-bad/ponos",
        "owner/..",
        "owner/a b",
    ):
        assert web_creation.github_url(given) == "", given


@case
def a_project_is_created_from_the_console_with_what_its_page_says():
    """A writing project, then a code one from GitHub: the page carries the
    columns the database already has, the brief is its body, and the answer is
    a row of the list — the one the list then holds."""
    with _board() as board:
        board.create_row("projects", "Existant", {"github": "someone/else"})
        api = _creatable(board)

        made = api.creation.create(
            {
                "name": "  Site   vitrine ",
                "description": "La page d'accueil.",
                "kind": "document",
                # Left over from the form before the type was changed.
                "repository": "owner/ignored",
                "site": "https://example.com",
                "content": "# Voix\n\nÉcris court.",
            }
        )
        assert made["name"] == "Site vitrine" and made["kind"] == "document"
        assert made["repository"] == "" and made["source"] == "board"
        page = board.page(made["id"])
        assert page.title == "Site vitrine"
        assert store.read(page, "Description") == "La page d'accueil."
        assert store.read(page, "URL") == "https://example.com"
        assert not store.read(page, "github")
        assert board.blocks_text(made["id"]) == "# Voix\n\nÉcris court."

        code = api.creation.create(
            {"name": "Ponos", "kind": "code", "repository": "hermez-agency/ponos"}
        )
        assert code["kind"] == "code"
        assert code["repository"] == "https://github.com/hermez-agency/ponos"
        # The column this database calls its repository, not a second one.
        assert store.read(board.page(code["id"]), "github") == code["repository"]
        assert "Repository" not in board.page(code["id"]).properties

        listed = {row["name"]: row for row in api.all_projects()["projects"]}
        assert listed["Ponos"]["id"] == code["id"] and listed["Ponos"]["kind"] == "code"
        assert listed["Site vitrine"]["kind"] == "document"

        # A ticket created on it right after is tied to it, and its runner finds
        # the clone of the repository it declares by its remote.
        root = Path(tempfile.mkdtemp())
        try:
            clone = root / "ponos"
            subprocess.run(["git", "init", "-q", str(clone)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(clone),
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:hermez-agency/ponos.git",
                ],
                check=True,
            )
            ticket = api.create_ticket("Un ticket", project=code["id"])["id"]
            relation = store.read(board.page(ticket), board.settings().prop("project"))
            assert relation == [code["id"]]
            found = projects.Resolver(root, {}).resolve(board, relation[0])
            assert found.path == clone and found.github == code["repository"]
        finally:
            shutil.rmtree(root, ignore_errors=True)


@case
def a_project_is_created_from_a_folder_and_names_its_remote():
    with _board() as board, tempfile.TemporaryDirectory() as directory:
        clone = Path(directory) / "jeu"
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(clone),
                "remote",
                "add",
                "origin",
                "git@github.com:SalvadorCardona/jeu.git",
            ],
            check=True,
        )
        api = _creatable(board)

        checked = api.creation.check(path=str(clone))
        assert checked["path"] == str(clone)
        assert checked["origin"] == "https://github.com/SalvadorCardona/jeu"

        made = api.creation.create({"name": "Jeu", "kind": "code", "path": f"{clone}/"})
        assert made["path"] == str(clone)
        assert made["repository"] == "https://github.com/SalvadorCardona/jeu"
        assert store.read(board.page(made["id"]), "Path") == str(clone)
        found = projects.Resolver(Path(directory), {}).resolve(board, made["id"])
        assert found.path == clone and found.is_code


@case
def a_project_the_console_cannot_create_is_refused_before_anything_is_written():
    """A name taken, a repository that is not GitHub's, a folder that is not
    there — each said under its field, in the runner's language, and the board
    left as it was."""
    with _board() as board, tempfile.TemporaryDirectory() as directory:
        board.create_row("projects", "Ponos", {})
        api = _creatable(board)
        create = api.creation.create

        said = _refused(lambda: create({"name": "PONOS", "kind": "document"}), "name")
        assert said == "Un projet s'appelle déjà « Ponos »."
        _refused(lambda: create({"name": "   ", "kind": "document"}), "name")
        said = _refused(
            lambda: create({"name": "Neuf", "kind": "code", "repository": "gitlab.com/a/b"}),
            "repository",
        )
        assert "gitlab.com/a/b" in said and "GitHub" in said
        _refused(lambda: create({"name": "Neuf", "kind": "code"}), "repository")
        missing = f"{directory}/nowhere"
        said = _refused(lambda: create({"name": "Neuf", "kind": "code", "path": missing}), "path")
        assert said == f"Il n'y a pas de dossier à {missing} sur cette machine."
        _refused(lambda: create({"name": "Neuf", "kind": "code", "path": directory}), "path")
        _refused(
            lambda: create({"name": "Neuf", "kind": "code", "path": "relative/folder"}), "path"
        )
        _refused(
            lambda: create({"name": "Neuf", "kind": "document", "site": "example.com"}), "site"
        )
        assert [page.title for page in board.query("projects")] == ["Ponos"]

        # In English for a runner that speaks it.
        said = _refused(lambda: _creatable(board, "en").creation.create({"name": "ponos"}), "name")
        assert said == "A project is already called “Ponos”."

        # What the form is told as it is filled in: a refusal said, not raised.
        checked = api.creation.check("not a repository", missing)
        assert "repository_error" in checked and "path_error" in checked
        checked = api.creation.check("owner/name")
        assert checked == {"repository": "https://github.com/owner/name", "cloned": ""}


@case
def the_console_server_creates_a_project_and_says_which_field_it_refuses():
    """The route, end to end: a project created is a row of the list; a refusal
    is a 400 whose violation names the field, which is what the form draws."""
    import urllib.error
    import urllib.parse
    import urllib.request

    from ponos.web import app as web_app

    with _board() as board:
        api = _creatable(board)
        console = web_app.Console(("127.0.0.1", 0), api, "tok")
        threading.Thread(target=console.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{console.server_address[1]}"
        headers = {
            "Authorization": "Bearer tok",
            "Content-Type": "application/json",
            "X-Ponos": "1",
        }

        def ask(path: str, body: dict | None = None) -> tuple[int, dict]:
            data = None if body is None else json.dumps(body).encode()
            request = urllib.request.Request(base + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read() or b"{}")

        try:
            status, made = ask("/api/projects", {"name": "Neuf", "kind": "document"})
            assert status == 200 and made["name"] == "Neuf" and made["kind"] == "document", made
            status, refused = ask("/api/projects", {"name": "neuf", "kind": "document"})
            assert status == 400
            assert refused["violations"] == [{"propertyPath": "name", "message": refused["error"]}]
            status, checked = ask(
                "/api/projects/check?" + urllib.parse.urlencode({"repository": "o/n"})
            )
            assert status == 200 and checked["repository"] == "https://github.com/o/n", checked
        finally:
            console.shutdown()
            console.server_close()


def _deletable(board: files.Board):
    """A markdown Api with a project of three tickets, and one elsewhere."""
    settings = board.settings()
    code = board.create_row("projects", "ponos", {"Repository": "user/repo"})
    elsewhere = board.create_row("projects", "Site vitrine", {})
    tickets = {}
    for title, status, project in (
        ("Prêt", settings.state("ready"), code),
        ("En cours", settings.state("running"), code),
        ("Fini", settings.state("done"), code),
        ("Ailleurs", settings.state("ready"), elsewhere),
    ):
        ticket = board.create_row("tickets", title, {settings.prop("status"): status})
        board.update("tickets", ticket, {settings.prop("project"): [project]})
        tickets[title] = ticket
    api = _markdown_api(board)
    api._config.notion = settings
    api._runner.config = api._config
    api._reader = web_board.Reader(journal=lambda report: None)
    api.removal = web_removal.Removal(api)
    api.watch = type("Watch", (), {"nudge": lambda self: None})()
    return api, code, tickets


@case
def deleting_a_project_needs_its_name_and_changes_nothing_without_it():
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        for confirm in ("", "Ponos", "ponosx"):
            try:
                api.removal.delete(code, {"confirm": confirm})
            except ValueError as error:
                assert "ponos" in str(error)
            else:
                raise AssertionError(f"“{confirm}” must not delete a project")
        assert board.page(code).title == "ponos", "refused, so still on the board"
        status = board.settings().prop("status")
        assert store.read(board.page(tickets["Prêt"]), status) == board.settings().state("ready")
        try:
            api.removal.delete("f" * 32, {"confirm": "ponos"})
        except LookupError:
            pass
        else:
            raise AssertionError("an unknown project must be a 404")


@case
def a_deleted_project_leaves_the_console_and_its_tickets_are_stopped_not_lost():
    """Gone from the list at once; tickets the runner could take are blocked and
    say why; the others, and the other project's, are left alone; nothing is
    removed for good — and what was spent on it stays in the history."""
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        settings = board.settings()
        status = settings.prop("status")
        ideas.record(code, "haiku", 0.5, [{"kind": "ticket", "title": "Une idée"}])
        state.record({"id": tickets["Fini"], "status": "done", "project": "ponos", "cost_usd": 2.0})

        done = api.removal.delete(code, {"confirm": "ponos"})

        assert (done["tickets"], done["blocked"], done["trashed"]) == (3, 2, 0)
        assert [one["name"] for one in api.all_projects()["projects"]] == ["Site vitrine"]
        for title, expected in (
            ("Prêt", settings.state("blocked")),
            ("En cours", settings.state("blocked")),
            ("Fini", settings.state("done")),
            ("Ailleurs", settings.state("ready")),
        ):
            assert store.read(board.page(tickets[title]), status) == expected, title
        assert (
            "supprimé" in board.comments(tickets["Prêt"])[-1].text
            or "deleted" in board.comments(tickets["Prêt"])[-1].text
        )
        assert not board.comments(tickets["Ailleurs"])
        # The page is put aside, not deleted: it is still on the disk.
        assert list((board.root / "trash" / "projects").glob("ponos-*.md"))
        assert done["ideas"] == 1 and not ideas.listed(code)
        assert sum(float(one.get("cost_usd") or 0) for one in state.history(100)) == 2.0

        # The ticket is still reachable, and the runner refuses its project.
        try:
            projects.Resolver(Path(tempfile.mkdtemp()), {}).resolve(board, code)
        except (LookupError, store.StoreError):
            pass
        else:
            raise AssertionError("a deleted project must not resolve")


@case
def deleting_a_project_may_trash_its_tickets_too():
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        done = api.removal.delete(code, {"confirm": "ponos", "trash_tickets": True})
        assert (done["trashed"], done["blocked"]) == (3, 0)
        titles = {page.title for page in board.query("tickets")}
        assert titles == {"Ailleurs"}
        assert len(list((board.root / "trash" / "tickets").glob("*.md"))) == 3
        assert api.reader.get(tickets["Prêt"]) is None, "dropped from what the console holds"


@case
def a_project_with_a_session_running_is_not_deleted():
    with _board() as board, _state_home():
        api, code, tickets = _deletable(board)
        running = web_live.active
        web_live.active = lambda *a, **k: [
            {"source": ticket_module.short_id(tickets["En cours"]), "log": "x"}
        ]
        try:
            api.removal.delete(code, {"confirm": "ponos"})
        except RuntimeError as error:
            assert "En cours" in str(error)
        else:
            raise AssertionError("a running session must stop the deletion")
        finally:
            web_live.active = running
        assert board.page(code).title == "ponos"
        status = board.settings().prop("status")
        assert store.read(board.page(tickets["Prêt"]), status) == board.settings().state("ready")


@case
def a_project_in_the_notion_trash_does_not_resolve():
    """The trash keeps a page readable by its ID; that is what must not be worked on."""

    class Backend:
        def page(self, page_id):
            return store.Page(id=page_id, url="", title="Site", raw={"archived": True})

    try:
        projects.Resolver(Path(tempfile.mkdtemp()), {}).resolve(Backend(), "p" * 32)
    except LookupError as error:
        assert "deleted" in str(error) and "Site" in str(error)
    else:
        raise AssertionError("an archived project must not resolve")


@case
def a_brief_is_saved_only_from_the_version_it_was_opened_at():
    """Edited in the console, the brief is never written over a newer one.

    The editor opens at a `version` and saves against it: a brief somebody
    wrote to meanwhile — in Notion, from another tab — is a conflict to read
    again, not a text to overwrite. And what is saved is what the runner reads
    at the next ticket, with nothing kept from the one it replaced.
    """
    with _board() as board:
        page = board.create_row("projects", "ponos", {"github": "user/repo"})
        board.replace_markdown(page, "# Voix\n\n- Écris en français.")
        api = _markdown_api(board)

        opened = api.project_brief(page)
        assert opened["content"] == "# Voix\n\n- Écris en français."
        assert opened["losses"] == {}, "a board of files loses nothing to Markdown"
        assert opened["version"] == api.project(page)["version"]

        # The text goes there and back unchanged, whatever the editor spells it.
        written = api.save_project(
            page, {"content": "# Voix\n\n* Écris en français.\n", "base": opened["version"]}
        )
        assert board.blocks_text(page) == "# Voix\n\n* Écris en français."
        assert written["version"] != opened["version"]
        assert (
            projects.Resolver(Path("/nowhere"), {}).brief(board, page)
            == "# Voix\n\n* Écris en français."
        )

        # Somebody else wrote while the editor was open: refused, and kept.
        board.replace_markdown(page, "Écrit ailleurs.")
        try:
            api.save_project(page, {"content": "Mon texte.", "base": opened["version"]})
        except RuntimeError:
            pass
        else:
            raise AssertionError("a brief that changed since it was opened was overwritten")
        assert board.blocks_text(page) == "Écrit ailleurs."

        # Read again, it saves.
        again = api.project_brief(page)
        api.save_project(page, {"content": "Mon texte.", "base": again["version"]})
        assert board.blocks_text(page) == "Mon texte."


@case
def a_brief_that_markdown_cannot_hold_is_not_rewritten_unannounced():
    """Notion holds more than a line of text does; the console says what that costs.

    `markdown.lost` names, block by block, what `plain` would flatten and
    `to_blocks` would not give back — and a save that knows about it refuses
    until the caller says it has been told.
    """

    def text(content, **notes):
        part = {
            "type": "text",
            "plain_text": content,
            "href": notes.pop("href", None),
            "annotations": notes,
        }
        return {"rich_text": [part]}

    assert markdown.lost({"type": "paragraph", "paragraph": text("Rien à perdre.")}) == []
    assert (
        markdown.lost(
            {"type": "heading_2", "heading_2": text("Titre", color="default", bold=False)}
        )
        == []
    )
    assert markdown.lost({"type": "paragraph", "paragraph": text("gras", bold=True)}) == [
        "formatting"
    ]
    assert markdown.lost({"type": "paragraph", "paragraph": text("lien", href="https://x.y")}) == [
        "link"
    ]
    assert markdown.lost(
        {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "mention", "plain_text": "@Salva"}]},
        }
    ) == ["mention"]
    assert markdown.lost({"type": "toggle", "toggle": text("Plié")}) == ["toggle"]
    assert markdown.lost({"type": "child_database", "child_database": {"title": "Notes"}}) == [
        "child_database"
    ]
    # A row is lost with its table, which is said once.
    assert markdown.lost({"type": "table_row"}) == []

    blocks = {
        "page": [
            {"id": "a", "type": "paragraph", "paragraph": text("Net.")},
            {"id": "b", "type": "toggle", "toggle": text("Plié"), "has_children": True},
            {"id": "c", "type": "child_database", "child_database": {"title": "Notes"}},
        ],
        "b": [
            {"id": "d", "type": "paragraph", "paragraph": text("gras", bold=True)},
            {"id": "e", "type": "callout", "callout": text("Attention"), "has_children": True},
        ],
        "e": [{"id": "f", "type": "toggle", "toggle": text("Encore"), "has_children": True}],
        "f": [
            {
                "id": "g",
                "type": "bookmark",
                "bookmark": {"url": "https://x.y"},
                "has_children": True,
            }
        ],
        "g": [{"id": "h", "type": "image", "image": {}}],
    }
    client = notion.Client("ntn_x")
    client._request = lambda method, path, body=None: {  # type: ignore[method-assign]
        "results": blocks.get(path.split("/")[2], []),
        "has_more": False,
    }
    found = client.losses("page")
    assert found == {
        "toggle": 2,
        "child_database": 1,
        "formatting": 1,
        "callout": 1,
        "bookmark": 1,
        "nested": 1,
    }, found

    with _board() as board:
        page = board.create_row("projects", "ponos", {})
        board.replace_markdown(page, "Texte.")
        api = _markdown_api(board)
        # The board of files has nothing to lose; make it say otherwise.
        board.losses = lambda *_: {"toggle": 1}  # type: ignore[method-assign]
        base = api.project_brief(page)["version"]
        try:
            api.save_project(page, {"content": "Autre.", "base": base})
        except ValueError:
            pass
        else:
            raise AssertionError("a page was rewritten without being told what it would lose")
        assert board.blocks_text(page) == "Texte."
        api.save_project(page, {"content": "Autre.", "base": base, "accept_losses": True})
        assert board.blocks_text(page) == "Autre."


@case
def the_console_reads_and_rewrites_the_standing_context():
    """Rewrites, never appends: the context is a value, not a history.

    Saving it twice has to leave one text. Everything else this console writes
    appends — a comment under a question, a report under a ticket — so this is
    the one place the distinction has to be made on purpose.
    """
    with _board() as board:
        board.set_context("Première version.")
        api = _markdown_api(board)
        assert api.context()["text"] == "Première version."
        assert api.context()["editable"]

        api.save_context("Deuxième version.")
        assert board.context() == "Deuxième version."
        api = _markdown_api(board)
        api.save_context("Deuxième version.")
        assert board.context() == "Deuxième version.", "a second save must not stack"

        # A workspace with nowhere to write says so rather than offering a save
        # that could only fail.
        blind = _markdown_api(board)
        blind._runner._workspace.context_page = ""
        assert not blind.context()["editable"]
        try:
            blind.save_context("x")
        except ValueError as error:
            assert "Context" in str(error)
        else:
            raise AssertionError("a context with no page must not pretend to save")


@case
def a_ticket_created_from_the_console_carries_its_priority_type_and_model():
    """A score and two selects in the form, written as the board takes them.

    They used to be set in Notion afterwards, by hand. Offered only for the
    columns the board has — a value for a missing one would be dropped on the
    way in — and a type left empty stays empty, for the runner to classify.
    The priority is a score from 0 to 100, 50 when none is said, refused
    outside that range.
    """
    with _board() as board:
        api = _markdown_api(board)
        api._schema_at = time.time()
        api._reader = web_board.Reader(journal=lambda report: None)
        api._outbox = web_board.Outbox(journal=lambda report: None)
        api.watch = _Nudged()
        read = api.board()
        choices = read["choices"]
        assert read["priority"] is True and "priority" not in choices
        assert [option["value"] for option in choices["model"]] == ["opus", "sonnet", "haiku"]
        assert {option["value"]: option["label"] for option in choices["type"]}[
            "writing"
        ] == "Writing"

        made = api.create_ticket(
            "Écrire l'annonce", ready=False, priority=80, kind="writing", model="haiku"
        )
        page = board.page(made["id"])
        settings = api.config.notion
        assert store.read(page, settings.prop("priority")) == 80
        assert store.read(page, settings.prop("type")) == "Writing"
        assert store.read(page, settings.prop("model")) == "haiku"
        assert not store.read(page, settings.prop("status")), "not ready is a draft"

        bare = board.page(api.create_ticket("Sans rien")["id"])
        assert not store.read(bare, settings.prop("type")), (
            "an empty type is the runner's to deduce"
        )
        assert store.read(bare, settings.prop("priority")) == 50, "none said is the middle"
        for wrong in (101, -1, "vite"):
            try:
                api.create_ticket("Hors bornes", priority=wrong)
            except ValueError:
                pass
            else:
                raise AssertionError(f"a priority of {wrong!r} must be refused")
        try:
            api.create_ticket("Mauvais type", kind="poem")
        except ValueError:
            pass
        else:
            raise AssertionError("a type that is none of the four must be refused")

    # A board without those columns is offered none of them.
    api = _bare_api(_ColumnsClient(["Ready"]))
    api._runner._workspace = type("W", (), {"goals": "", "projects": "", "tickets": "db"})()
    api._schema_at = time.time()
    assert api.board()["choices"] == {}
