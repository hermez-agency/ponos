"""`web/accounts.py`: the people a console is shared with, what each may do, and what each did."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from support import _board, _ideas_api, case

from ponos import config as C
from ponos import store

if TYPE_CHECKING:
    from ponos.web import api as web_api
    from ponos.web import app as web_app


@case
def an_invitation_makes_one_account_once_and_within_the_week(state_home: Path) -> None:
    """A link is a code drawn once, kept as its digest, and spent by the account it makes."""
    from ponos.web import accounts

    assert accounts.may("admin", "member") and accounts.may("member", "member")
    assert not accounts.may("reader", "member") and not accounts.may("guest", "reader")

    code, drawn = accounts.invite("member", by="Salva")
    assert drawn["role"] == "member" and drawn["by"] == "Salva"
    assert accounts.invited(code) == "member" and accounts.invited("not a code") == ""
    assert all("code" not in kept for kept in accounts.invitations()), "never given twice"

    for wrong in (
        {"email": "lea", "name": "Léa", "password": "long enough"},
        {"email": "lea@example.com", "name": " ", "password": "long enough"},
        {"email": "lea@example.com", "name": "Léa", "password": "short"},
    ):
        try:
            accounts.accept(code, **wrong)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{wrong} should have been refused")
    try:
        accounts.accept(code, "me@example.com", "Me", "long enough", reserved="Me@Example.com")
    except ValueError:
        pass
    else:
        raise AssertionError("the console's own email is nobody else's")
    assert accounts.invited(code) == "member", "a form got wrong keeps the link for a second try"

    lea = accounts.accept(code, " Lea@Example.com ", "  Léa   Martin ", "long enough")
    assert (lea.email, lea.name, lea.role) == ("Lea@Example.com", "Léa Martin", "member")
    assert accounts.invited(code) == "" and accounts.invitations() == []
    try:
        accounts.accept(code, "other@example.com", "Other", "long enough")
    except PermissionError:
        pass
    else:
        raise AssertionError("a link makes one account")

    again, _ = accounts.invite("reader")
    try:
        accounts.accept(again, "lea@example.com", "Léa", "long enough")
    except ValueError:
        pass
    else:
        raise AssertionError("one account an email")

    old, _ = accounts.invite("reader", now=datetime.now(UTC) - timedelta(days=8))
    assert accounts.invited(old) == "", "a week, and no more"
    assert [kept["role"] for kept in accounts.invitations()] == ["reader"], "the old one is gone"

    assert accounts.signing_in("LEA@example.com", "long enough") == lea
    assert accounts.signing_in("lea@example.com", "wrong one") is None
    assert accounts.signing_in("nobody@example.com", "long enough") is None
    assert accounts.set_role(lea.id, "reader").role == "reader"
    try:
        accounts.set_role(lea.id, "owner")
    except ValueError:
        pass
    else:
        raise AssertionError("three roles, and no fourth")
    assert accounts.owner("salva@example.com").name == "salva"
    assert accounts.owner("salva@example.com").may("admin")


@case
def a_deleted_accounts_sessions_are_refused_and_nobody_elses(state_home: Path) -> None:
    """A cookie names its account: the account gone, every one of its sessions is."""
    from ponos.web import accounts, sessions

    lea = accounts.create("lea@example.com", "Léa", "long enough", "member")
    tom = accounts.create("tom@example.com", "Tom", "long enough", "reader")

    def proof_of(identifier: int) -> str | None:
        found = accounts.find(identifier)
        return found.proof("tok") if found else None

    hers = sessions.issue(lea.proof("tok"), holder=lea.id)
    his = sessions.issue(tom.proof("tok"), holder=tom.id)
    assert hers.startswith(f"a{lea.id}.")
    assert (sessions.holder(hers, proof_of) or (0, 0))[0] == lea.id
    assert (sessions.holder(his, proof_of) or (0, 0))[0] == tom.id
    forged = f"a{tom.id}." + hers.split(".", 1)[1]
    assert sessions.holder(forged, proof_of) is None, "her session is not his"
    assert sessions.issued(lea.proof("tok"), hers) is None, "nor the console's own sign-in's"
    owners = sessions.issue("the owner's proof")
    assert sessions.holder(owners, proof_of) is None
    assert sessions.issued("the owner's proof", owners) is not None, "which keeps its cookie"

    accounts.remove(lea.id)
    assert sessions.holder(hers, proof_of) is None, "deleted: signed out everywhere"
    assert sessions.holder(his, proof_of) is not None, "and nobody else is"
    back = accounts.create("lea@example.com", "Léa", "long enough", "member")
    assert sessions.holder(hers, proof_of) is None, "invited again is another account"
    assert sessions.holder(sessions.issue(back.proof("tok"), holder=back.id), proof_of)


# -- through the door ----------------------------------------------------------


def _ask(
    console: web_app.Console,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    cookie: str = "",
    token: str = "",
) -> tuple[int, http.client.HTTPResponse, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", console.server_address[1], timeout=10)
    headers = {"Host": "127.0.0.1", "X-Ponos": "1", "Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = f"{console.cookie}={cookie}"
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


@contextmanager
def _serving(api: web_api.Api) -> Iterator[web_app.Console]:
    from ponos.web import app as web_app
    from ponos.web import server as web_server

    api._config = C.Config(
        board=api.config.board,
        runner=api.config.runner,
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


def _joined(console: web_app.Console, role: str, name: str, email: str) -> str:
    """An invitation drawn with the token and taken: the session cookie it gave."""
    status, _, drawn = _ask(console, "POST", "/api/invitations", {"role": role}, cookie="tok")
    assert status == 200, drawn
    link = urlparse(drawn["link"])
    assert link.path == "/invite", link
    code = parse_qs(link.query)["code"][0]
    status, page, _ = _ask(console, "GET", f"/invite?code={code}")
    assert status == 200
    status, answer, said = _ask(
        console,
        "POST",
        "/api/invite",
        {"code": code, "name": name, "email": email, "password": "long enough"},
    )
    assert status == 200, said
    cookie = answer.headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
    status, _, said = _ask(
        console,
        "POST",
        "/api/invite",
        {"code": code, "name": "x", "email": "x@y.z", "password": "long enough"},
    )
    assert status == 403, "a link makes one account"
    # Counted as a wrong password is: the next attempt would wait a second.
    console.attempts = type(console.attempts)()
    return cookie


@case
def a_reader_sees_and_is_refused_and_a_member_validates_under_their_name(
    state_home: Path,
) -> None:
    """The ticket's criterion, through the console's own door.

    A reader reads everything and writes nothing — 403, and a page that knows
    it before it draws a button; a member validates a ticket in review, and the
    comment on the ticket says who, as does the ticket's audit; neither changes
    the settings or the accounts; and an account deleted is signed out.
    """
    settings = C.BoardNames()
    with _board() as board:
        api = _ideas_api(board)
        said = api.runner.voice
        reviewed = board.create_row("tickets", "A button", {"statut": settings.state("review")})
        board.comment(reviewed, said.report(said.verdict("review", "PR #3"), "Adds a button."))
        drafted = board.create_row("tickets", "A draft", {"statut": settings.state("draft")})
        with _serving(api) as console:
            status, _, me = _ask(console, "GET", "/api/me", cookie="tok")
            assert me == {"email": "", "name": "", "role": "admin", "owner": True, "shared": False}
            reader = _joined(console, "reader", "Tom", "tom@example.com")
            member = _joined(console, "member", "Léa", "lea@example.com")

            status, _, me = _ask(console, "GET", "/api/me", cookie=reader)
            assert status == 200 and me["role"] == "reader" and me["name"] == "Tom", me
            assert me["shared"] is True
            status, _, _ = _ask(console, "GET", "/api/board", cookie=reader)
            assert status == 200, "a reader reads"
            status, page, html = _ask(console, "GET", "/?view=console/tickets/list", cookie=reader)
            assert status == 200 and 'data-role="reader"' in html, "the page knows before it draws"
            for path, body in (
                (f"/api/tickets/{drafted}/status", {"column": "ready"}),
                (f"/api/tickets/{reviewed}/decision", {"key": "validate"}),
                (f"/api/tickets/{reviewed}/talk", {"text": "hello"}),
                ("/api/tickets", {"title": "Mine"}),
                ("/api/settings", {}),
                ("/api/invitations", {"role": "admin"}),
            ):
                status, _, refused = _ask(console, "POST", path, body, cookie=reader)
                assert status == 403, (path, status, refused)
            status, _, _ = _ask(console, "GET", "/api/accounts", cookie=reader)
            assert status == 403
            status, _, _ = _ask(console, "POST", "/api/notifications/read", {}, cookie=reader)
            # Past the door, to a watch this test does not have: not a 403.
            assert status != 403, "what a reader has seen is theirs to mark"
            status, _, offered = _ask(console, "GET", "/api/push", cookie=reader)
            assert status == 200 and offered["available"] and offered["key"], offered
            phone = {
                "endpoint": "https://push.example.test/send/tom",
                "keys": {"p256dh": "B" + "A" * 86, "auth": "A" * 22},
                "label": "iPhone",
            }
            status, _, subscribed = _ask(
                console, "POST", "/api/push/subscribe", phone, cookie=reader
            )
            assert status == 200, ("the bell is a reader's too", subscribed)
            assert [(d["label"], d["who"]) for d in subscribed["devices"]] == [
                ("iPhone", "tom@example.com")
            ]
            phone["endpoint"] = "http://push.example.test/plain"
            status, _, _ = _ask(console, "POST", "/api/push/subscribe", phone, cookie=reader)
            assert status == 400, "not a push service"
            assert store.read(board.page(drafted), "statut") == settings.state("draft")

            for path, body in (("/api/settings", {}), ("/api/invitations", {"role": "admin"})):
                status, _, _ = _ask(console, "POST", path, body, cookie=member)
                assert status == 403, f"{path} is an admin's"
            status, _, panel = _ask(
                console, "GET", f"/api/tickets/{reviewed}/decision", cookie=member
            )
            assert status == 200, panel
            validate = panel["solutions"][0]["key"]
            status, _, decided = _ask(
                console,
                "POST",
                f"/api/tickets/{reviewed}/decision",
                {"key": validate},
                cookie=member,
            )
            assert status == 200, decided
            comment = board.comments(reviewed)[-1].text
            assert comment.splitlines()[0] == "Answered from the console by Léa.", comment
            status, _, audit = _ask(console, "GET", f"/api/tickets/{reviewed}/audit", cookie=reader)
            assert status == 200
            assert [(entry["who"], entry["action"]) for entry in audit["entries"]] == [
                ("Léa", "decided")
            ], audit
            status, _, moved = _ask(
                console,
                "POST",
                f"/api/tickets/{drafted}/status",
                {"column": "ready"},
                cookie=member,
            )
            assert status == 200, moved
            assert _audit_of(console, drafted, member) == [("Léa", "moved", "ready")]

            status, _, listed = _ask(console, "GET", "/api/accounts", cookie="tok")
            people = {account["name"]: account for account in listed["accounts"]}
            assert list(people) == ["salva", "Tom", "Léa"] and people["salva"]["owner"]
            status, _, _ = _ask(
                console, "POST", f"/api/accounts/{people['Léa']['id']}/delete", {}, cookie="tok"
            )
            assert status == 200
            status, _, _ = _ask(console, "GET", "/api/board", cookie=member)
            assert status == 401, "an account deleted is signed out"

            status, answer, _ = _ask(
                console,
                "POST",
                "/api/login",
                {"email": "tom@example.com", "password": "long enough"},
            )
            assert status == 200
            again = answer.headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
            status, _, me = _ask(console, "GET", "/api/me", cookie=again)
            assert me["name"] == "Tom" and me["role"] == "reader"
            status, answer, _ = _ask(
                console,
                "POST",
                "/api/login",
                {"email": "salva@example.com", "password": "the owner's own"},
            )
            assert status == 200, "the console's own sign-in is still the first admin"
            owner = answer.headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
            status, _, me = _ask(console, "GET", "/api/me", cookie=owner)
            assert me["role"] == "admin" and me["owner"] is True and me["name"] == "salva"


def _audit_of(console: web_app.Console, ticket: str, cookie: str) -> list[tuple[str, str, str]]:
    _, _, audit = _ask(console, "GET", f"/api/tickets/{ticket}/audit", cookie=cookie)
    return [(entry["who"], entry["action"], entry["detail"]) for entry in audit["entries"]]
