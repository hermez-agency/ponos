"""`vault_store.py`: Ponos's own vault — sealed entry by entry, given by name, masked everywhere."""

from __future__ import annotations

import http.client
import io
import json
import os
import socket
import sqlite3
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from support import _bare_runner, _board, _config, _http_answering, _ideas_api, _tools, case

from ponos import config as C
from ponos import health, ledger, notion, pages, prompt, push, session, tickets, vault, vault_store
from ponos.channels import request as channel_request

if TYPE_CHECKING:
    from ponos.web import api as web_api
    from ponos.web import app as web_app

SECRET = "sk_live_0123456789abcdef"


def _job(project: str, ticket: str = "t-1") -> Any:
    return type(
        "J",
        (),
        {"project": type("P", (), {"name": project})(), "ticket": type("T", (), {"id": ticket})()},
    )()


def _refused(call: Any, *args: Any, **kwargs: Any) -> str:
    try:
        call(*args, **kwargs)
    except (vault.VaultError, ValueError, LookupError) as error:
        return str(error)
    raise AssertionError(f"{call.__name__}{args} should have been refused")


# -- the file ------------------------------------------------------------------


@case
def the_vault_keeps_no_value_in_clear_and_refuses_a_value_moved_or_edited(
    vault_home: Path,
) -> None:
    made = vault_store.create("MA_CLE", "token", {"value": SECRET}, ["Leadz"], by="Salva")
    vault_store.create(
        "LEADZ", "login", {"user": "salva@hermez.dev", "password": "hunter2-hunter2"}, ["Leadz"]
    )
    vault_store.create("CERT", "note", {"value": "-----BEGIN-----\nabcdef\n-----END-----\n"}, [])
    assert made["print"] == "…cdef" and made["variables"] == ["MA_CLE"]
    assert "value" not in json.dumps(vault_store.listing()), "nothing lists a value"
    assert SECRET not in json.dumps(vault_store.listing())
    held = vault_store.path().read_bytes()
    for value in (SECRET, "hunter2-hunter2", "salva@hermez.dev", "BEGIN"):
        assert value.encode() not in held, value
    assert vault_store.mode_of(vault_store.path()) == 0o600
    key = vault_store.key_path()
    assert vault_store.mode_of(key) == 0o600
    assert not key.is_relative_to(vault_store.path().parent), "never beside the data"
    assert vault_store.whereabouts() == {"source": "file", "where": str(key)}
    assert vault_store.fingerprint("short-value") == "", "nothing under twelve characters"
    assert vault_store.read("MA_CLE") == SECRET
    assert vault_store.read("LEADZ_USER") == "salva@hermez.dev"
    assert vault_store.read("LEADZ_PASSWORD") == "hunter2-hunter2"

    connection = sqlite3.connect(vault_store.path())
    # A sealed value moved onto another entry: its associated data is not this one's.
    connection.execute(
        "UPDATE entries SET nonce = (SELECT nonce FROM entries WHERE name = 'MA_CLE'), "
        "sealed = (SELECT sealed FROM entries WHERE name = 'MA_CLE') WHERE name = 'CERT'"
    )
    # A project added by hand: who may read it is sealed with it.
    connection.execute(
        "UPDATE entries SET projects = '[\"Leadz\", \"Ponos\"]' WHERE name = 'LEADZ'"
    )
    connection.commit()
    assert "changed, or moved" in _refused(vault_store.read, "CERT")
    assert "changed, or moved" in _refused(vault_store.read, "LEADZ_USER")
    # And a byte of a sealed value changed: GCM's tag.
    sealed = bytearray(
        connection.execute("SELECT sealed FROM entries WHERE name = 'MA_CLE'").fetchone()[0]
    )
    sealed[0] ^= 1
    connection.execute("UPDATE entries SET sealed = ? WHERE name = 'MA_CLE'", (bytes(sealed),))
    connection.commit()
    connection.close()
    assert "changed, or moved" in _refused(vault_store.read, "MA_CLE")
    found = vault.read({"MA_CLE": "ponos:MA_CLE"}, "env")
    assert found.values == {} and "MA_CLE (ponos:" in found.missing[0], found.missing


@case
def any_entry_may_say_its_site_and_only_an_http_address_is_kept(vault_home: Path) -> None:
    token = vault_store.create(
        "OPENROUTER", "token", {"value": SECRET}, ["Leadz"], url="https://openrouter.ai/keys"
    )
    assert token["url"] == "https://openrouter.ai/keys"
    assert token["url_variable"] == "OPENROUTER_URL" and token["variables"] == ["OPENROUTER"]
    note = vault_store.create(
        "CERT", "note", {"value": "a" * 12}, [], url="notion.so/my-integrations"
    )
    assert note["url"] == "https://notion.so/my-integrations", "a bare host is https"
    assert vault_store.create("BARE", "token", {"value": "b" * 12}, [])["url_variable"] == ""
    assert vault_store.change("BARE", url="localhost:8080/x")["url"] == "https://localhost:8080/x"
    assert (
        vault_store.change("BARE", url="HTTP://Dokploy.example")["url"] == "HTTP://Dokploy.example"
    )
    for wrong in (
        "javascript:alert(1)",
        "ftp://files.example",
        "file:///etc/passwd",
        "https://",
        "https://exa mple.com",
        "https://example.com:port",
        "https://" + "a" * 500 + ".com",
    ):
        try:
            vault_store.change("BARE", url=wrong)
        except vault_store.Refused as error:
            assert error.field == "url" and "not the address of a site" in str(error), error
        else:
            raise AssertionError(f"{wrong!r} should have been refused")
    assert vault_store.listing()[0]["url"] == "HTTP://Dokploy.example", (
        "a refused one changes nothing"
    )
    # The address is no secret: in clear in the file, beside the name.
    assert b"https://openrouter.ai/keys" in vault_store.path().read_bytes()


@case
def an_entrys_address_is_no_other_entrys_variable(vault_home: Path) -> None:
    vault_store.create("DOKPLOY", "login", {"user": "u" * 8, "password": "p" * 8}, [])
    # DOKPLOY_URL is the login's address, even before it has one.
    assert "already gives DOKPLOY" in _refused(
        vault_store.create, "DOKPLOY_URL", "token", {"value": SECRET}, []
    )
    vault_store.create("SITE_URL", "token", {"value": SECRET}, [])
    assert "already gives SITE_URL" in _refused(
        vault_store.create, "SITE", "token", {"value": SECRET}, []
    )
    # A name whose address would be the runner's own.
    assert "ANTHROPIC_BASE_URL is the runner's own" in _refused(
        vault_store.create, "ANTHROPIC_BASE", "token", {"value": SECRET}, []
    )


@case
def an_address_changed_by_hand_opens_nothing_and_its_changes_are_in_the_journal(
    vault_home: Path,
) -> None:
    made = vault_store.create(
        "BREVO",
        "login",
        {"user": "ada@hermez.dev", "password": "hunter2-hunter2"},
        ["Brevo"],
        url="https://app.brevo.com/login",
        by="Salva",
    )
    vault_store.change("BREVO", url="https://app.brevo.com/account", by="Salva")
    vault_store.change("BREVO", url="https://app.brevo.com/account", description="Brevo")
    vault_store.change("BREVO", url="", by="Ada")
    moments = [
        (moment["action"], moment["detail"], moment["by"])
        for moment in vault_store.history(made["id"])
    ]
    assert moments == [
        ("url", "", "Ada"),
        ("described", "", ""),
        ("url", "https://app.brevo.com/account", "Salva"),
        ("created", "", "Salva"),
    ], moments
    vault_store.change("BREVO", url="https://app.brevo.com/login")
    assert vault_store.read("BREVO_PASSWORD") == "hunter2-hunter2"
    assert vault_store.addresses("Brevo") == {"BREVO_URL": "https://app.brevo.com/login"}
    # Somebody with the file alone sends the login to a site of their own.
    connection = sqlite3.connect(vault_store.path())
    connection.execute("UPDATE entries SET url = 'https://brevo.evil.io' WHERE name = 'BREVO'")
    connection.commit()
    connection.close()
    assert "changed, or moved" in _refused(vault_store.read, "BREVO_PASSWORD")
    assert vault_store.addresses("Brevo") == {}, "an address that does not open is not given"


@case
def a_vault_sealed_before_the_addresses_is_sealed_again_with_them_once(vault_home: Path) -> None:
    vault_store.create("MA_CLE", "token", {"value": SECRET}, ["Leadz"], url="https://a.example")
    vault_store.create("PLAIN", "token", {"value": SECRET + "-2"}, ["Leadz"])
    raw = vault_store.decoded(vault_store.key_path().read_text())
    # As the vault of the day before was sealed: without the address, and its check.
    connection = sqlite3.connect(vault_store.path())
    connection.row_factory = sqlite3.Row
    for row in connection.execute("SELECT * FROM entries").fetchall():
        plain = vault_store._open(raw, row["nonce"], row["sealed"], vault_store._bound(row))
        nonce, sealed = vault_store._seal(
            raw,
            plain,
            vault_store._associated_before(
                row["id"], row["name"], row["kind"], json.loads(row["projects"])
            ),
        )
        connection.execute(
            "UPDATE entries SET nonce = ?, sealed = ? WHERE id = ?", (nonce, sealed, row["id"])
        )
    nonce, sealed = vault_store._seal(raw, vault_store._CHECK, b"check")
    connection.execute("UPDATE meta SET nonce = ?, sealed = ? WHERE key = 'check'", (nonce, sealed))
    connection.commit()
    assert vault_store.read("MA_CLE") == SECRET and vault_store.read("PLAIN") == SECRET + "-2"
    for row in connection.execute("SELECT * FROM entries").fetchall():
        vault_store._open(raw, row["nonce"], row["sealed"], vault_store._bound(row))
    check = connection.execute("SELECT nonce, sealed FROM meta WHERE key = 'check'").fetchone()
    assert "changed, or moved" in _refused(
        vault_store._open, raw, check["nonce"], check["sealed"], b"check"
    ), "sealed again once, and never read the old way again"
    # From then on, an address changed by hand is refused.
    connection.execute("UPDATE entries SET url = 'https://b.example' WHERE name = 'MA_CLE'")
    connection.commit()
    connection.close()
    assert "changed, or moved" in _refused(vault_store.read, "MA_CLE")


@case
def a_rotation_seals_everything_again_and_the_old_key_opens_nothing(vault_home: Path) -> None:
    for index in range(3):
        vault_store.create(f"KEY_{index}", "token", {"value": f"{SECRET}-{index}"}, ["Leadz"])
    before = vault_store.key_path().read_text()
    old = vault_store.decoded(before)
    count, fresh = vault_store.rotate()
    assert count == 3 and fresh.source == "file" and fresh.raw != old
    assert vault_store.key_path().read_text() != before
    assert not vault_store.key_path().with_name("vault.key.pending").exists()
    connection = sqlite3.connect(vault_store.path())
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM entries").fetchall()
    for row in rows:
        associated = vault_store._associated(
            row["id"], row["name"], row["kind"], json.loads(row["projects"])
        )
        assert "changed, or moved" in _refused(
            vault_store._open, old, row["nonce"], row["sealed"], associated
        )
    assert [vault_store.read(f"KEY_{index}") for index in range(3)] == [
        f"{SECRET}-{index}" for index in range(3)
    ]
    # A rotation cut short after the vault was rewritten: the pending key opens it.
    kept = vault_store.key_path().read_text()
    vault_store._file_write(vault_store.key_path().with_name("vault.key.pending"), fresh.raw)
    vault_store._file_write(vault_store.key_path(), old)
    assert vault_store.read("KEY_0") == f"{SECRET}-0"
    assert vault_store.key_path().read_text() == kept, "and is kept in the old one's place"
    # A key that opens nothing is said, never replaced by a new one.
    vault_store._file_write(vault_store.key_path(), b"\x00" * 32)
    assert "does not open this vault" in vault_store.problem()
    vault_store.key_path().unlink()
    assert "key is missing" in vault_store.problem()


@case
def the_key_is_looked_for_in_the_keyring_then_the_environment_then_a_file(
    vault_home: Path,
) -> None:
    store = vault_home.parent / "keyring.json"
    fake = (
        "import json\n"
        f"store = {str(store)!r}\n"
        "held = json.load(open(store)) if os.path.exists(store) else {}\n"
        "words = sys.argv[1:]\n"
        "if words[0] == 'store':\n"
        "    held[' '.join(words[2:])] = sys.stdin.read()\n"
        "    json.dump(held, open(store, 'w'))\n"
        "elif words[0] == 'lookup':\n"
        "    if ' '.join(words[1:]) not in held: sys.exit(1)\n"
        "    print(held[' '.join(words[1:])], end='')\n"
        "elif words[0] == 'clear':\n"
        "    held.pop(' '.join(words[1:]), None); json.dump(held, open(store, 'w'))\n"
    )
    usable = vault_store.keyring_usable
    with _tools({"secret-tool": fake}):
        vault_store.keyring_usable = lambda: True
        try:
            vault_store.create("FROM_KEYRING", "token", {"value": SECRET}, ["Leadz"])
            assert vault_store.whereabouts()["source"] == "keyring"
            assert not vault_store.key_path().exists(), "no file when the keyring answers"
            assert SECRET.encode() not in store.read_bytes()
            count, _ = vault_store.rotate()
            assert count == 1 and vault_store.read("FROM_KEYRING") == SECRET
            assert list(json.loads(store.read_text())) == ["service ponos-vault key master"]
        finally:
            vault_store.keyring_usable = usable
    vault_store.path().unlink()
    # No keyring: the environment, then the file.
    os.environ[C.VAULT_KEY_ENV] = vault_store._encoded(os.urandom(32))
    vault_store.create("FROM_ENV", "token", {"value": SECRET}, ["Leadz"])
    assert vault_store.whereabouts() == {
        "source": "env",
        "where": f"the {C.VAULT_KEY_ENV} environment variable",
    }
    assert not vault_store.key_path().exists()
    count, given = vault_store.rotate()
    assert count == 1 and given.source == "env", "handed back, to be set again"
    os.environ[C.VAULT_KEY_ENV] = vault_store.encoded(given)
    assert vault_store.read("FROM_ENV") == SECRET
    os.environ[C.VAULT_KEY_ENV] = "not a key"
    assert "32 bytes" in vault_store.problem()
    del os.environ[C.VAULT_KEY_ENV]
    assert "key is missing" in vault_store.problem(), "never a new key for an old vault"
    assert C.VAULT_KEY_ENV not in session.inheritable({C.VAULT_KEY_ENV: "x", "HOME": "/h"})


@case
def an_entry_is_named_like_a_variable_and_never_like_the_runners_own(vault_home: Path) -> None:
    good = {"value": SECRET}
    for name, why in (
        ("not a name", "is not an environment variable name"),
        ("ANTHROPIC_API_KEY", "is the runner's own"),
        ("PONOS_NOTION_TOKEN", "is the runner's own"),
        ("PONOS_ANYTHING", "is the runner's own"),
        (C.VAULT_KEY_ENV, "is the runner's own"),
    ):
        assert why in _refused(vault_store.create, name, "token", good, ["Leadz"]), name
    assert "at least" in _refused(vault_store.create, "TINY", "token", {"value": "abc"}, [])
    assert "is not a date" in _refused(
        vault_store.create, "WHEN", "token", good, [], expires="soon"
    )
    assert "one of" in _refused(vault_store.create, "WHAT", "secret", good, [])
    vault_store.create("DOKPLOY", "login", {"user": "admin-user", "password": SECRET}, [])
    assert "already gives DOKPLOY" in _refused(
        vault_store.create, "DOKPLOY_USER", "token", good, []
    )
    assert "is the runner's own" in _refused(
        vault_store.create, "PONOS", "login", {"user": "x" * 8, "password": SECRET}, []
    )
    # A value replaced, its projects changed, each said in the journal, never with a value.
    entry = vault_store.listing()[0]
    vault_store.change(entry["id"], values={"user": "admin-user", "password": SECRET + "!"})
    vault_store.change(entry["id"], projects=["Ponos", "Leadz"], by="Salva")
    assert vault_store.read("DOKPLOY_PASSWORD") == SECRET + "!"
    assert vault_store.listing()[0]["projects"] == ["Leadz", "Ponos"]
    moments = vault_store.history(entry["id"])
    assert [moment["action"] for moment in moments] == ["projects", "replaced", "created"]
    assert SECRET not in json.dumps(moments)
    vault_store.revoke(entry["id"])
    assert vault_store.listing() == [] and "no such entry" in _refused(
        vault_store.history, entry["id"]
    )
    assert vault_store.read("DOKPLOY_PASSWORD") == "", "and nothing reads it any more"


# -- a session -----------------------------------------------------------------


@case
def a_key_granted_to_leadz_reaches_a_leadz_session_and_no_other(vault_home: Path) -> None:
    """The first criterion: a key made for Leadz is in a Leadz session's environment only."""
    made = vault_store.create("MA_CLE", "token", {"value": SECRET}, ["Leadz"])
    runner = _bare_runner(None)
    runner.dry_run = False
    assert runner._secrets(_job("Ponos")) == {}, "nobody else's keys"
    assert runner._secrets(_job("leadz", "ticket-42")) == {"MA_CLE": SECRET}
    assert vault.mask(f"echo {SECRET}") == "echo ***", "read is remembered, and masked"
    used = vault_store.listing()[0]
    assert (used["last_ticket"], used["last_project"]) == ("ticket-42", "leadz")
    assert vault_store.history(made["id"])[0]["action"] == "read"
    # `[vault]` may name it too, and wins over the page on the same variable.
    runner.config = _config('[vault]\n[vault.projects]\nPonos = { MA_CLE = "ponos:MA_CLE" }\n')
    assert runner._secrets(_job("Ponos")) == {"MA_CLE": SECRET}
    text = prompt.build(
        prompt.DEFAULT,
        project="Leadz",
        title="t",
        body="b",
        repo="r",
        branch="b",
        base="main",
        url="u",
        secrets=["MA_CLE"],
    )
    assert "`MA_CLE`" in text and SECRET not in text, "the name, never the value"
    # Its address, as <NAME>_URL beside it — unmasked, and named apart in the prompt.
    vault_store.change("MA_CLE", url="https://openrouter.ai/keys")
    job = _job("Leadz")
    assert runner._secrets(job) == {"MA_CLE": SECRET, "MA_CLE_URL": "https://openrouter.ai/keys"}
    assert job.addresses == ["MA_CLE_URL"]
    assert vault.mask("https://openrouter.ai/keys") == "https://openrouter.ai/keys"
    assert runner._secrets(_job("Ponos")) == {"MA_CLE": SECRET}, "no address it was not granted"
    text = prompt.build(
        prompt.DEFAULT,
        project="Leadz",
        title="t",
        body="b",
        repo="r",
        branch="b",
        base="main",
        url="u",
        secrets=["MA_CLE"],
        addresses=["MA_CLE_URL"],
    )
    assert "in your environment: `MA_CLE`." in text and "`MA_CLE_URL`: an address" in text, text
    alone = prompt.held_secrets([], ["MA_CLE_URL"])
    assert alone.startswith("# Secrets") and "slips out" not in alone
    # The console's chat is no ticket: it is given nothing of the vault.
    chat = (
        Path(__file__).resolve().parents[1] / "src" / "ponos" / "web" / "console.py"
    ).read_text()
    assert "vault_store" not in chat and "_secrets(" not in chat


@case
def what_a_session_prints_of_a_vault_key_is_masked_everywhere(vault_home: Path) -> None:
    """`echo $MA_CLE` leaves `***` in the transcript, Notion, the board, the console and the phone."""
    vault_store.create("MA_CLE", "token", {"value": SECRET}, ["Leadz"])
    runner = _bare_runner(None)
    runner.dry_run = False
    given = runner._secrets(_job("Leadz"))
    home = vault_home.parent / "session"
    home.mkdir()
    (home / "claude").write_text(
        "#!" + sys.executable + "\n"
        "import json, os, sys\n"
        "sys.stdin.read()\n"
        "said = 'echo: ' + os.environ['MA_CLE']\n"
        "sys.stderr.write(said + '\\n')\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': said}]}}))\n"
        "print(json.dumps({'type': 'result', 'result': said + '\\nRESULT: ok — done', 'session_id': 's'}))\n"
    )
    (home / "claude").chmod(0o755)
    previous = os.environ["PATH"]
    os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
    seen: list[dict[str, Any]] = []
    try:
        outcome = session.run(
            "go",
            cwd=home,
            log=home / "s.jsonl",
            timeout_minutes=1,
            environment=given,
            on_event=seen.append,
        )
    finally:
        os.environ["PATH"] = previous
    assert outcome.ok, outcome.error
    assert SECRET not in outcome.answer and "echo: ***" in outcome.answer
    assert SECRET not in (home / "s.jsonl").read_text() and SECRET not in json.dumps(seen)
    assert (home / "s.err").read_text() == "echo: ***\n"
    # The comment on the ticket, in Notion and in ponos.db.
    sent: list[bytes] = []

    def answered(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    with _http_answering(answered):
        notion.Client("ntn_test").comment("p", outcome.answer + " " + SECRET)
        # Telegram and Slack: one door, `channels.request`.
        channel_request("https://api.telegram.org/botX/sendMessage", {"text": SECRET})
        channel_request("https://slack.com/api/chat.postMessage", {"text": f"done: {SECRET}"})
        # A push: what is encrypted for the phone.
        sealed: list[bytes] = []
        encrypt = push.encrypt

        def sealing(payload: bytes, *rest: Any, **named: Any) -> bytes:
            sealed.append(payload)
            return b"x"

        push.encrypt = sealing
        try:
            push.send(push.Subscription("https://push.example.test/x", "p", "a"), {"body": SECRET})
        finally:
            push.encrypt = encrypt
    assert len(sent) == 4 and all(SECRET.encode() not in body for body in sent), sent
    assert sealed and SECRET.encode() not in sealed[0] and b"***" in sealed[0], sealed
    notion_settings = _config("").notion
    board = ledger.Ledger(pages.Pages(notion_settings), notion_settings)
    board.workspace(notion_settings)
    page = board.create_row(board.resolve_database("Tickets"), f"Deploy {SECRET}")
    board.comment(page, outcome.answer + SECRET)
    written = "".join(
        [record.title for record in tickets.listing()]
        + [remark.text for record in tickets.listing() for remark in tickets.comments(record.id)]
    )
    assert SECRET not in written and "***" in written
    # The console, its JSON and its stream.
    with _board() as markdown:
        api = _ideas_api(markdown)
        with _serving(api) as console:
            status, _, said = _ask(console, "GET", "/api/vault", token="tok")
            assert status == 200 and SECRET not in json.dumps(said)
            from ponos.web.routes import answer

            assert SECRET.encode() not in answer({"text": SECRET}).body
            # No board to watch here: the stream is what is looked at.
            api.watch = type("Still", (), {"ensure_running": lambda self: None})()
            api.hub.publish("notice", text="before")
            api.hub.publish("notice", text=f"the key is {SECRET}")
            streamed = _streamed(console, "/api/events?after=1", "the key is")
            assert "the key is ***" in streamed and SECRET not in streamed, streamed


# -- doctor ----------------------------------------------------------------------


@case
def doctor_says_where_the_key_is_and_what_expires_or_is_given_to_nobody(
    vault_home: Path,
) -> None:
    assert health.settings._vault_store() == [], "nothing to say of a vault never used"
    today = date.today()
    vault_store.create(
        "OLD", "token", {"value": SECRET}, ["Leadz"], expires=str(today - timedelta(days=1))
    )
    vault_store.create(
        "SOON", "token", {"value": SECRET}, ["Leadz"], expires=str(today + timedelta(days=3))
    )
    vault_store.create("ALONE", "token", {"value": SECRET}, [])
    checks = health.settings._vault_store()
    said = {(check.state, check.said): check for check in checks}
    key = said[
        (
            "warn",
            "The vault's key is a file, {{path}}: a backup that holds it and vault.db holds every key.",
        )
    ]
    assert key.params["path"] == str(vault_store.key_path())
    assert said[("error", "Past their expiry date in the vault: {{names}}.")].params == {
        "names": "OLD"
    }
    assert (
        said[("warn", "Expiring within {{days}} days in the vault: {{names}}.")].params["names"]
        == "SOON"
    )
    assert said[("warn", "Granted to no project, so given to no session: {{names}}.")].params == {
        "names": "ALONE"
    }
    vault_store.path().chmod(0o644)
    loose = [check for check in health.settings._vault_store() if "read by others" in check.said]
    assert loose and loose[0].params["path"] == str(vault_store.path())
    vault_store.path().chmod(0o600)
    assert SECRET not in json.dumps([check.asdict() for check in checks])


# -- the console -------------------------------------------------------------------


def _ask(
    console: web_app.Console,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    cookie: str = "",
    token: str = "",
    origin: str = "",
) -> tuple[int, http.client.HTTPResponse, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", console.server_address[1], timeout=10)
    headers = {"Host": "127.0.0.1", "X-Ponos": "1", "Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = f"{console.cookie}={cookie}"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    sent = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=sent, headers=headers)
    answer = connection.getresponse()
    raw = answer.read().decode("utf-8", "replace")
    connection.close()
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        parsed = raw
    return answer.status, answer, parsed


def _streamed(console: web_app.Console, path: str, until: str) -> str:
    connection = socket.create_connection(("127.0.0.1", console.server_address[1]), timeout=10)
    connection.sendall(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer tok\r\n\r\n".encode()
    )
    read = b""
    try:
        while until.encode() not in read:
            chunk = connection.recv(65536)
            if not chunk:
                break
            read += chunk
    finally:
        connection.close()
    return read.decode("utf-8", "replace")


@contextmanager
def _serving(api: web_api.Api) -> Iterator[web_app.Console]:
    from ponos.web import app as web_app
    from ponos.web import server as web_server

    api._config = C.Config(
        notion=api.config.notion,
        runner=api.config.runner,
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(email="salva@example.com", password="the owner's own"),
    )
    entry = web_server.sign_in(api.config, "tok")
    console = web_app.Console(("127.0.0.1", 0), api, "tok", entry)
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:
        yield console
    finally:
        console.shutdown()
        console.server_close()


def _signed_in(console: web_app.Console, email: str, password: str) -> str:
    status, answer, said = _ask(
        console, "POST", "/api/login", {"email": email, "password": password}
    )
    assert status == 200, said
    return answer.headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]


@case
def the_vault_api_is_an_admins_says_no_value_and_asks_for_the_password_again(
    vault_home: Path,
) -> None:
    from ponos.web import accounts, sessions

    accounts.create("lea@example.com", "Léa", "long enough", "member")
    with _board() as markdown:
        api = _ideas_api(markdown)
        with _serving(api) as console:
            member = _signed_in(console, "lea@example.com", "long enough")
            for method, path in (
                ("GET", "/api/vault"),
                ("POST", "/api/vault"),
                ("PUT", "/api/vault/x"),
                ("DELETE", "/api/vault/x"),
                ("GET", "/api/vault/x/history"),
            ):
                status, _, _ = _ask(console, method, path, {"confirm": "x"}, cookie=member)
                assert status == 403, (method, path, status)

            owner = _signed_in(console, "salva@example.com", "the owner's own")
            new = {
                "name": "MA_CLE",
                "kind": "token",
                "value": SECRET,
                "projects": ["Leadz"],
                "description": "Leadz's Dokploy",
            }
            # Signed in just now: the password was typed, the write goes on.
            status, _, made = _ask(console, "POST", "/api/vault", new, cookie=owner)
            assert status == 200, made
            assert SECRET not in json.dumps(made) and made["print"] == "…cdef"
            # Five minutes on, it is asked for again.
            sessions._proven.clear()
            status, _, refused = _ask(
                console, "PUT", f"/api/vault/{made['id']}", {"value": SECRET + "x"}, cookie=owner
            )
            assert status == 403 and refused["reauthenticate"] is True, refused
            status, _, refused = _ask(
                console,
                "PUT",
                f"/api/vault/{made['id']}",
                {"value": SECRET + "x", "confirm": "not it"},
                cookie=owner,
            )
            assert status == 403 and refused["error"] == "wrong password", refused
            console.attempts = type(console.attempts)()
            status, _, changed = _ask(
                console,
                "PUT",
                f"/api/vault/{made['id']}",
                {
                    "value": SECRET + "x",
                    "projects": ["Leadz", "Opoil"],
                    "confirm": "the owner's own",
                },
                cookie=owner,
            )
            assert status == 200 and changed["projects"] == ["Leadz", "Opoil"], changed
            assert vault_store.read("MA_CLE") == SECRET + "x"
            # Another page, posting with this browser's cookie: refused by its Origin.
            status, _, _ = _ask(
                console,
                "DELETE",
                f"/api/vault/{made['id']}",
                {},
                cookie=owner,
                origin="https://evil.example",
            )
            assert status == 403
            # A refusal quotes nothing it was sent.
            status, _, refused = _ask(
                console, "POST", "/api/vault", {**new, "name": "ANTHROPIC_API_KEY"}, cookie=owner
            )
            assert status == 400 and SECRET not in json.dumps(refused), refused
            status, _, refused = _ask(
                console, "POST", "/api/vault", {**new, "projects": {"x": SECRET}}, cookie=owner
            )
            assert status == 400 and SECRET not in json.dumps(refused), refused

            status, _, listed = _ask(console, "GET", "/api/vault", cookie=owner)
            assert status == 200 and listed["proven"] is True
            assert listed["key"]["source"] == "file", "the page says where the key is"
            assert listed["key"]["where"] == str(vault_store.key_path())
            assert [entry["name"] for entry in listed["entries"]] == ["MA_CLE"]
            status, _, moments = _ask(
                console, "GET", f"/api/vault/{made['id']}/history", cookie=owner
            )
            assert [moment["action"] for moment in moments["entries"]] == [
                "projects",
                "replaced",
                "created",
            ]
            assert moments["entries"][-1]["by"] == "salva"
            status, _, gone = _ask(console, "DELETE", f"/api/vault/{made['id']}", {}, cookie=owner)
            assert status == 200 and gone["name"] == "MA_CLE"
            assert vault_store.listing() == []


# -- the CLI -------------------------------------------------------------------------


@case
def ponos_vault_reads_a_value_from_stdin_and_never_prints_it(vault_home: Path) -> None:
    from ponos.__main__ import main

    printed = io.StringIO()
    stdin, stdout = sys.stdin, sys.stdout
    try:
        sys.stdin, sys.stdout = io.StringIO(SECRET + "\n"), printed
        assert main(["vault", "set", "MA_CLE", "--project", "Leadz", "--project", "Opoil"]) == 0
        sys.stdin = io.StringIO("salva@hermez.dev\nhunter2-hunter2\n")
        assert (
            main(
                ["vault", "set", "LEADZ", "--kind", "login", "--project", "Leadz"]
                + ["--url", "https://leadz.example/login"]
            )
            == 0
        )
        sys.stdin = io.StringIO(SECRET + "-again\n")
        assert main(["vault", "set", "MA_CLE"]) == 0, "set again replaces the value"
        assert main(["vault", "list"]) == 0
        assert main(["vault", "rotate"]) == 0
        sys.stdin = io.StringIO("")
        assert main(["vault", "rm", "LEADZ"]) == 1, "no terminal, no --yes: nothing removed"
        assert main(["vault", "rm", "LEADZ", "--yes"]) == 0
    finally:
        sys.stdin, sys.stdout = stdin, stdout
    said = printed.getvalue()
    assert "MA_CLE" in said and "Leadz, Opoil" in said and "…gain" in said, said
    assert "LEADZ_URL: https://leadz.example/login" in said, "list says the address"
    assert SECRET not in said and "hunter2" not in said, said
    assert vault_store.read("MA_CLE") == SECRET + "-again"
    assert [entry["name"] for entry in vault_store.listing()] == ["MA_CLE"]
    kept = vault_store.listing()[0]
    assert vault_store.history(kept["id"])[-1]["by"].startswith("cli:")
