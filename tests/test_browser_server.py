"""`browser_server.py`: the protocol, and the refusals that come before any browser starts.

What a sign-in does on a real page is `tests/functional.py`'s, on a local site
and a real Chromium; here, what needs neither.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from support import case

from ponos import browser_server, vault, vault_store

PASSWORD = "correct-horse-battery-staple-42"


@contextmanager
def _engine(**logins: str) -> Iterator[browser_server.Browser]:
    names = {
        "PONOS_BROWSER_PROJECT": "Brevo",
        "PONOS_BROWSER_TICKET": "t1",
        "PONOS_BROWSER_LOGINS": json.dumps(logins),
        "SITE_USER": "ada@hermez.test",
        "SITE_PASSWORD": PASSWORD,
        "LEADZ_PASSWORD": "another-password-of-leadz",
    }
    before = {name: os.environ.get(name) for name in names}
    os.environ.update(names)
    try:
        yield browser_server.Browser()
    finally:
        vault.forget()
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _call(engine: browser_server.Browser, tool: str, **arguments: Any) -> dict[str, Any]:
    reply = browser_server.handle(
        engine,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    assert reply is not None and reply["id"] == 7
    result: dict[str, Any] = reply["result"]
    return result


@case
def the_server_speaks_mcp_and_lists_its_tools() -> None:
    with _engine() as engine:
        opened = browser_server.handle(
            engine, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert opened is not None
        assert opened["result"]["serverInfo"]["name"] == "ponos-browser"
        assert "tools" in opened["result"]["capabilities"]
        assert browser_server.handle(engine, {"jsonrpc": "2.0", "method": "initialized"}) is None
        listed = browser_server.handle(engine, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {
            "browser_navigate",
            "browser_read",
            "browser_click",
            "browser_type",
            "browser_press",
            "browser_screenshot",
            "browser_download",
            "browser_upload",
            "browser_login",
        }
        unknown = browser_server.handle(engine, {"jsonrpc": "2.0", "id": 3, "method": "nope"})
        assert unknown is not None and unknown["error"]["code"] == -32601


@case
def a_login_not_granted_or_on_another_site_is_refused_and_written_down(vault_home: Path) -> None:
    vault_store.create(
        "SITE", "login", {"user": "ada@hermez.test", "password": PASSWORD}, ["Brevo"]
    )
    with _engine(SITE="https://app.brevo.com/login") as engine:
        other = _call(engine, "browser_login", entry="LEADZ")
        assert other["isError"] is False
        assert other["content"][0]["text"].startswith("refused: 'LEADZ' is not a login granted")
        elsewhere = _call(engine, "browser_login", entry="SITE", url="https://brevo.com.evil.io/")
        said = elsewhere["content"][0]["text"]
        assert said.startswith("refused: brevo.com.evil.io is not the site of SITE"), said
        assert engine._page is None, "no browser was started to refuse"
    (entry,) = vault_store.listing()
    assert [moment["action"] for moment in vault_store.history(entry["id"])][:1] == [
        "login-refused"
    ]


@case
def a_value_of_the_vault_is_never_typed_nor_said_back() -> None:
    with _engine(SITE="https://app.brevo.com/login") as engine:
        for value in (PASSWORD, f"  {PASSWORD} ", f"x{PASSWORD}x", "another-password-of-leadz"):
            refused = _call(engine, "browser_type", label="Mot de passe", value=value)
            assert refused["isError"] is True, value
            text = refused["content"][0]["text"]
            assert text.startswith("refused: that is a value of the vault"), text
            assert PASSWORD not in text
        assert engine._page is None
        assert engine.masked(f"Bonjour ada@hermez.test, {PASSWORD}") == "Bonjour ***, ***"
        assert PASSWORD not in engine.masked_safely(f"TimeoutError: {PASSWORD}")
