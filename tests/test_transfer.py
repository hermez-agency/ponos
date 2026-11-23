"""`transfer.py`: a Ponos exported in one archive, and read back into another."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from support import case

from ponos import config as config_module
from ponos import db, memory, skills, tickets, transfer, transitions, vault, vault_store

TICKET = "a" * 32
OTHER = "b" * 32
PROJECT = "c" * 32
GOAL = "d" * 32
SCHEDULE = "e" * 32
TELEGRAM = "tg-SECRET-0123456789"
OPENROUTER = "sk-or-v1-SECRETSECRETSECRET"
ENTRY = "entry-SECRET-value-42"
STAMP = "2026-11-01T09:00:00+00:00"


@contextlib.contextmanager
def another_ponos() -> Iterator[Path]:
    """An empty Ponos of its own — state and configuration — for as long as the block lasts."""
    names = ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "PONOS_CONFIG")
    previous = {name: os.environ.get(name) for name in names}
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    os.environ.pop("PONOS_CONFIG", None)
    try:
        yield Path(os.environ["XDG_STATE_HOME"]) / "ponos"
    finally:
        db.close()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _fill() -> None:
    """A Ponos with something of every category, secrets included."""
    path = config_module.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'[runner]\ninterval_seconds = 42\n\n[openrouter]\nkey = "{OPENROUTER}"\n',
        encoding="utf-8",
    )
    vault_store.keep_own({"PONOS_TELEGRAM_TOKEN": TELEGRAM})
    vault_store.create("DEPLOY_KEY", "token", {"value": ENTRY}, [PROJECT])
    vault.forget()
    connection = db.connect()
    page = (
        "INSERT INTO board_pages (id, collection, title, properties, body, created, edited)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    connection.execute(page, (PROJECT, "projects", "Site", '{"Path": "/w/site"}', "", STAMP, STAMP))
    connection.execute(page, (GOAL, "goals", "Launch", "{}", "the launch", STAMP, STAMP))
    connection.execute(
        page,
        (
            SCHEDULE,
            "schedules",
            "Weekly",
            json.dumps({"Active": True, "Cadence": "Weekly", "Project": [PROJECT]}),
            "check the site",
            STAMP,
            STAMP,
        ),
    )
    connection.execute(page, ("context", "context", "Context", "{}", "I sell bikes.", STAMP, STAMP))
    connection.execute(
        "INSERT INTO project_settings (project, name, settings) VALUES (?, 'Site', ?)",
        (
            PROJECT,
            json.dumps({"validation": {"code": True}, "vault": {"entries": {"DEPLOY_KEY": ""}}}),
        ),
    )
    ticket = (
        "INSERT INTO tickets (id, title, project, status, mission, result, goal, on_change,"
        " created_at, edited_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    connection.execute(
        ticket,
        (TICKET, "Ready one", PROJECT, "ready", "do it", "", GOAL, "say hi", STAMP, STAMP),
    )
    connection.execute(
        ticket,
        (OTHER, "Done one", PROJECT, "done", f"token {TELEGRAM}", "made", "", "", STAMP, STAMP),
    )
    connection.execute("INSERT INTO ticket_after (ticket, after) VALUES (?, ?)", (TICKET, OTHER))
    connection.execute(
        "INSERT INTO ticket_comments (ticket, author, text, at) VALUES (?, 'me', 'well done', ?)",
        (OTHER, STAMP),
    )
    connection.execute(
        "INSERT INTO ticket_results (ticket, version, text, at) VALUES (?, 1, 'made', ?)",
        (OTHER, STAMP),
    )
    connection.execute(
        "INSERT INTO chats (id, title, messages) VALUES ('chat1', 'Talk', '[{\"role\": \"user\"}]')"
    )
    batch = connection.execute(
        "INSERT INTO idea_batches (scope, created_at) VALUES ('global', ?)", (STAMP,)
    ).lastrowid
    connection.execute(
        "INSERT INTO ideas (batch, scope, kind, title, created_at) VALUES (?, 'global', 'x', 'An idea', ?)",
        (batch, STAMP),
    )
    memory.add("The client reads French only.", "preference", PROJECT)
    skills.create("deploy", "how to deploy", "# Deploy\n")


def _archive_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())


def _one(sql: str, *args: Any) -> Any:
    return db.connect().execute(sql, args).fetchone()


@case
def an_export_imported_into_an_empty_ponos_gives_back_the_same_data(vault_home: Path) -> None:
    _fill()
    name, blob, manifest = transfer.export(transfer.KEYS)
    assert name.startswith("ponos-export-") and name.endswith(".zip")
    assert manifest["format"] == transfer.FORMAT
    assert manifest["counts"]["tickets"] == 2 and manifest["counts"]["conversations"] == 1
    skill_file = _one("SELECT content FROM skill_files")[0]

    with another_ponos():
        said = transfer.run(transfer.read(blob), apply=True)
        assert said["applied"] and said["mode"] == transfer.MERGE
        outcome = {category["key"]: category for category in said["categories"]}
        assert outcome["tickets"]["imported"] == 2 and not outcome["tickets"]["conflicts"]

        assert _one("SELECT title, mission, project, goal FROM tickets WHERE id = ?", OTHER)[
            :1
        ] == ("Done one",)
        assert _one("SELECT project, goal FROM tickets WHERE id = ?", TICKET) == (PROJECT, GOAL)
        assert _one("SELECT after FROM ticket_after WHERE ticket = ?", TICKET) == (OTHER,)
        assert _one("SELECT text FROM ticket_comments WHERE ticket = ?", OTHER) == ("well done",)
        assert _one("SELECT text FROM ticket_results WHERE ticket = ?", OTHER) == ("made",)
        assert _one("SELECT title FROM board_pages WHERE id = ?", PROJECT) == ("Site",)
        assert _one("SELECT body FROM board_pages WHERE id = ?", GOAL) == ("the launch",)
        assert _one("SELECT body FROM board_pages WHERE id = 'context'") == ("I sell bikes.",)
        assert json.loads(
            _one("SELECT settings FROM project_settings WHERE project = ?", PROJECT)[0]
        )["validation"] == {"code": True}
        assert _one("SELECT text, scope FROM memories") == (
            "The client reads French only.",
            PROJECT,
        )
        assert _one("SELECT content FROM skill_files")[0] == skill_file
        assert _one("SELECT title FROM chats WHERE id = 'chat1'") == ("Talk",)
        idea, batch = _one("SELECT title, batch FROM ideas")
        assert idea == "An idea" and _one("SELECT 1 FROM idea_batches WHERE id = ?", batch)
        raw = config_module.read_raw(config_module.config_path())
        assert raw["runner"]["interval_seconds"] == 42
        assert "openrouter" not in raw

        again = transfer.run(transfer.read(blob), apply=True)
        for category in again["categories"]:
            assert category["imported"] == 0 and not category["conflicts"], category


@case
def imported_tickets_are_numbered_by_the_board_they_arrive_on(vault_home: Path) -> None:
    """`PON-1` of the archive may be `PON-1` here already: the number is given again."""
    _fill()
    _, blob, _ = transfer.export(transfer.KEYS)
    with another_ponos():
        mine = tickets.create("already here", project=PROJECT)
        transfer.run(transfer.read(blob), apply=True)
        numbers = [record.public_id for record in tickets.listing() if record.id in (TICKET, OTHER)]
        assert len(numbers) == 2 and mine.public_id not in numbers
        assert len({*numbers, mine.public_id}) == 3


@case
def no_value_of_the_vault_nor_any_secret_is_in_the_archive(vault_home: Path) -> None:
    _fill()
    _, blob, manifest = transfer.export(transfer.KEYS)
    text = _archive_text(blob)
    for secret in (TELEGRAM, OPENROUTER, ENTRY):
        assert secret not in text, f"{secret} leaked into the archive"
    assert "DEPLOY_KEY" in [entry["name"] for entry in manifest["secrets"]["vault"]]
    assert "PONOS_TELEGRAM_TOKEN" in manifest["secrets"]["own"]
    assert {"setting": "notify.telegram.token", "name": "PONOS_TELEGRAM_TOKEN"} in manifest[
        "secrets"
    ]["config"]


@case
def an_import_starts_no_ticket_and_no_recurrence(vault_home: Path) -> None:
    _fill()
    _, blob, _ = transfer.export(transfer.KEYS)
    with another_ponos():
        transfer.run(transfer.read(blob), apply=True)
        assert _one("SELECT status FROM tickets WHERE id = ?", TICKET) == ("draft",)
        assert _one("SELECT status FROM tickets WHERE id = ?", OTHER) == ("done",)
        assert _one("SELECT COUNT(*) FROM tickets WHERE status IN ('ready', 'progress')") == (0,)
        properties = json.loads(
            _one("SELECT properties FROM board_pages WHERE id = ?", SCHEDULE)[0]
        )
        assert properties["Active"] is False and properties["Cadence"] == "Weekly"
        # The « On » sees the ticket as it arrived: no change, nothing run.
        assert transitions.observe(TICKET, "draft", title="Ready one", depth_limit=3) == (0, "")


@case
def the_conversations_are_left_out_unless_asked(vault_home: Path) -> None:
    _fill()
    _, blob, manifest = transfer.export(None)
    assert "conversations" not in manifest["categories"]
    assert "tickets" in manifest["categories"]
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert "conversations.json" not in archive.namelist()
    _, without, manifest = transfer.export([key for key in transfer.DEFAULTS if key != "tickets"])
    assert "tickets" not in manifest["categories"]


@case
def a_merge_lists_conflicts_and_replaces_nothing(vault_home: Path) -> None:
    _fill()
    _, blob, _ = transfer.export(["tickets"])
    db.connect().execute("UPDATE tickets SET title = 'Renamed here' WHERE id = ?", (OTHER,))
    preview = transfer.run(transfer.read(blob))
    tickets = next(item for item in preview["categories"] if item["key"] == "tickets")
    assert not preview["applied"] and tickets["conflicts"] == ["Done one"]
    transfer.run(transfer.read(blob), apply=True)
    assert _one("SELECT title FROM tickets WHERE id = ?", OTHER) == ("Renamed here",)


@case
def replacing_asks_for_a_confirmation_and_copies_the_database_first(vault_home: Path) -> None:
    _fill()
    _, blob, _ = transfer.export(["tickets"])
    db.connect().execute("UPDATE tickets SET title = 'Renamed here' WHERE id = ?", (OTHER,))
    try:
        transfer.run(transfer.read(blob), mode=transfer.REPLACE, apply=True)
    except transfer.TransferError:
        pass
    else:
        raise AssertionError("replacing without a confirmation was accepted")
    said = transfer.run(transfer.read(blob), mode=transfer.REPLACE, apply=True, confirmed=True)
    assert said["backup"] and Path(said["backup"]).exists()
    assert _one("SELECT title FROM tickets WHERE id = ?", OTHER) == ("Done one",)


@case
def an_archive_of_a_newer_format_is_refused_with_a_clear_message(vault_home: Path) -> None:
    for broken, said in (
        (b"not a zip", "not a zip"),
        (_zipped({"other.json": "{}"}), "no manifest"),
        (
            _zipped(
                {
                    "manifest.json": json.dumps(
                        {"kind": transfer.KIND, "format": 99, "ponos": "9.0.0", "categories": []}
                    )
                }
            ),
            "format 99",
        ),
    ):
        try:
            transfer.read(broken)
        except transfer.TransferError as error:
            assert said in str(error), str(error)
        else:
            raise AssertionError(f"{broken[:20]!r} was read")


def _zipped(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


@case
def the_command_line_exports_and_previews_an_import(vault_home: Path) -> None:
    from ponos.__main__ import main as cli_main

    _fill()
    folder = Path(tempfile.mkdtemp())
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert cli_main(["export", "--no-tickets", "-o", str(folder)]) == 0
    written = list(folder.glob("ponos-export-*.zip"))
    assert len(written) == 1, printed.getvalue()
    assert "DEPLOY_KEY" in printed.getvalue(), "the names to type again are said"
    with zipfile.ZipFile(written[0]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert "tickets" not in manifest["categories"]
    assert "conversations" not in manifest["categories"]

    with another_ponos():
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            assert cli_main(["import", str(written[0]), "--dry-run"]) == 0
        assert "would import" in printed.getvalue()
        assert _one("SELECT COUNT(*) FROM memories") == (0,), "a dry run writes nothing"
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli_main(["import", str(written[0]), "--only", "memories"]) == 0
        assert _one("SELECT COUNT(*) FROM memories") == (1,)
        assert _one("SELECT COUNT(*) FROM board_pages WHERE id = ?", GOAL) == (0,)


@case
def the_console_exports_and_previews_an_import_for_an_administrator(vault_home: Path) -> None:
    import threading
    import urllib.error
    import urllib.request

    from support import _bare_api, _TalkClient

    from ponos.web import app as web_app

    _fill()
    console = web_app.Console(("127.0.0.1", 0), _bare_api(_TalkClient([])), "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{console.server_address[1]}"

    def post(path: str, body: bytes, kind: str) -> tuple[int, bytes, Any]:
        request = urllib.request.Request(
            base + path,
            data=body,
            headers={"Content-Type": kind, "Authorization": "Bearer tok", "X-Ponos": "1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    try:
        code, blob, headers = post(
            "/api/export",
            json.dumps({"categories": ["tickets", "goals"]}).encode(),
            "application/json",
        )
        assert code == 200 and headers["Content-Type"] == "application/zip", blob[:200]
        assert "ponos-export-" in headers["Content-Disposition"]
        assert TELEGRAM.encode() not in blob

        code, said, _ = post(
            "/api/export", json.dumps({"categories": ["vault"]}).encode(), "application/json"
        )
        assert code == 400 and b"no such category" in said

        code, said, _ = post("/api/import?categories=tickets", blob, "application/zip")
        assert code == 200, said
        preview = json.loads(said)
        assert preview["applied"] is False and preview["available"] == ["goals", "tickets"]
        assert preview["chosen"] == ["tickets"]
        tickets = next(item for item in preview["categories"] if item["key"] == "tickets")
        assert tickets["count"] == 2 and tickets["ignored"] == 2

        code, said, _ = post("/api/import?mode=replace&apply=true", blob, "application/zip")
        assert code == 400 and b"confirmation" in said

        code, said, _ = post("/api/import", b"not a zip", "application/zip")
        assert code == 400 and b"not a zip" in said
    finally:
        console.shutdown()
        console.server_close()


@case
def only_an_administrator_exports_or_imports() -> None:
    from ponos.web import accounts
    from ponos.web import app as web_app

    for route in ("/api/export", "/api/import"):
        assert web_app.needed("POST", route) == accounts.ADMIN
