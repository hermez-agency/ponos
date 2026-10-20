"""`web/server.py`: who may reach the console, and what every answer carries."""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from support import _environment, _Fresh, _saved, _state_home, _time_passes, case

from ponos import config as C
from ponos import git as git_module
from ponos.__main__ import main as cli_main

# -- what a message to the workspace carries ----------------------------------


@case
def the_console_only_listens_beyond_localhost_when_told_to():
    """Behind the port sits bypassPermissions: a generated token is not consent."""
    from ponos.web import server as web_server

    configuration = C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(host="0.0.0.0"),
    )
    explained = io.StringIO()
    with contextlib.redirect_stdout(explained):
        assert web_server.serve(configuration, announce=False) == 2, "must refuse, not serve"
    said = explained.getvalue()
    assert "bypassPermissions" in said, "and say why, not just refuse"
    assert "web.email" in said, "and name both ways of saying it on purpose"


def _web_config(**web) -> C.Config:
    """A configuration that is nothing but its [web] table."""
    return C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(**web),
    )


@case
def an_email_and_a_password_are_a_way_into_the_console():
    """A token is right for a script and tiring for a person.

    What a session is signed from is derived from the two rather than drawn:
    the console's unit restarts with the machine, and a browser that had to
    sign in again every morning would be the token all over again.
    """
    from ponos import passwords
    from ponos.web import server as web_server

    assert web_server.sign_in(_web_config(), "tok") is None
    assert web_server.sign_in(_web_config(email="me@example.com"), "tok") is None, (
        "half a sign-in is somebody configuring one, not a way in"
    )
    assert web_server.sign_in(_web_config(password="hunter2"), "tok") is None

    entry = web_server.sign_in(_web_config(email="Me@Example.com", password="hunter2"), "tok")
    assert entry is not None and entry.email == "Me@Example.com"
    assert passwords.is_digest(entry.digest), (
        "a password from the environment is digested in memory"
    )
    assert entry.opens(" me@example.COM", "hunter2") and not entry.opens(
        "me@example.com", "hunter3"
    )
    again = web_server.sign_in(_web_config(email="me@example.com", password="hunter2"), "tok")
    assert entry.proof == again.proof, "a restart, or a capital, must not sign anybody out"
    assert "hunter2" not in entry.proof and entry.proof != "tok"
    changed = web_server.sign_in(_web_config(email="me@example.com", password="hunter3"), "tok")
    assert changed.proof != entry.proof, "a new password signs every browser out"
    elsewhere = web_server.sign_in(_web_config(email="me@example.com", password="hunter2"), "other")
    assert elsewhere.proof != entry.proof, "a session belongs to this console's token"
    kept = passwords.digest("hunter2")
    digested = web_server.sign_in(_web_config(email="me@example.com", password=kept), "tok")
    assert digested.digest == kept and digested.opens("me@example.com", "hunter2")


@case
def a_token_in_the_address_is_taken_out_and_the_destination_left_in():
    """`?token=…&view=…` is one secret and one destination, and only one goes.

    The token is moved into a cookie and out of the address, because it would
    otherwise sit in the history and in every screenshot. What sits beside it is
    not a secret: `serve` prints `/?token=…`, and a link to a pane is shared as
    `/?token=…&view=console/projects/list`. Redirecting both to a bare `/` put
    the second one on the board.
    """
    from urllib.parse import parse_qs

    from ponos.web import server as web_server

    assert web_server.landing("token=abc") == "/", "nothing else to say: the console opens"
    assert web_server.landing("") == "/"
    kept = web_server.landing("token=abc&view=console/projects/list")
    assert "token" not in kept, "the secret stays in the cookie"
    assert parse_qs(kept.lstrip("/?"))["view"] == ["console/projects/list"], kept
    # Whatever the address carried, in the order it carried it.
    both = web_server.landing("view=console/projects/list&token=abc&variant=table")
    assert parse_qs(both.lstrip("/?")) == {
        "view": ["console/projects/list"],
        "variant": ["table"],
    }, both


@case
def the_sign_in_page_asks_the_way_the_console_does():
    """It posts rather than navigates, and carries the header every write does.

    A form that navigated could not set `X-Ponos`, which is what tells a
    request from the console apart from one a page you had open made — so the
    page written here has to agree with the constant the server checks.
    """
    from ponos.web import server as web_server

    assert web_server.GUARD_HEADER in web_server.SIGN_IN, "the login would be refused as CSRF"
    assert "/api/login" in web_server.SIGN_IN
    assert 'type="password"' in web_server.SIGN_IN
    for page in (web_server.GATE, web_server.SIGN_IN):
        assert 'src="http' not in page and 'href="http' not in page, "it reaches off the machine"


@case
def the_first_connection_is_offered_until_somebody_says_how_to_get_in():
    """A token protects an installation; a fresh one has nothing to protect yet.

    Two ways of deciding how the console is opened, and the page exists for the
    state where neither was taken. The token drawn on first start is not one of
    them: nobody chose it, and it is the very secret the first connection is
    there to stop somebody having to go and find.
    """
    from ponos.web import server as web_server

    bare = _web_config()
    assert web_server.claimable(bare, None), "a console nobody decided anything about"
    assert not web_server.claimable(_web_config(token="chosen"), None), (
        "a token in the file is a decision, and the gate is what it asks for"
    )
    entry = web_server.sign_in(_web_config(email="me@example.com", password="hunter22"), "tok")
    assert not web_server.claimable(bare, entry), "a sign-in closes it for good"


@case
def the_first_connection_writes_the_whole_installation_at_once():
    """One form, and the file it leaves is one somebody could have typed.

    Every value written is a key of `config.toml` — saved through the console's
    own writer, floors and all — and the pair that matters most is the one that
    closes the page behind it: once the email and the password are in, the
    console is claimed and this is not a way in any more.
    """
    from ponos import passwords
    from ponos.web import server as web_server
    from ponos.web import setup as web_setup

    path, _ = _saved()
    api = _Fresh(path)
    report = web_setup.apply(
        api,
        {
            "email": "me@example.com",
            "password": "one I remember",
            "confirm": "one I remember",
            "rules": "  I am Salva. Answer in French.  ",
            "telegram_token": "123:abc",
            "telegram_chat": "4242",
        },
    )
    assert report["problem"] == "", report
    assert report["steps"] and report["steps"][0][1].endswith("me@example.com from now on")

    written = path.read_text(encoding="utf-8")
    secrets = C.read_secrets(C.secrets_path(path))
    assert 'email = "me@example.com"' in written and "one I remember" not in written
    assert passwords.matches("one I remember", secrets["PONOS_WEB_PASSWORD"]), (
        "a secret goes beside the file"
    )
    assert passwords.is_digest(secrets["PONOS_WEB_PASSWORD"]), "and the password as its digest only"
    assert 'chat = "4242"' in written and "123:abc" not in written
    assert secrets["PONOS_TELEGRAM_TOKEN"] == "123:abc"
    assert secrets["PONOS_NOTION_TOKEN"] == "ntn_real", "the rest is left where it was"
    assert api.context == "I am Salva. Answer in French.", "the rules reach every ticket"

    entry = web_server.sign_in(api.config, "tok")
    assert entry is not None and entry.email == "me@example.com"
    assert not web_server.claimable(api.config, entry), "the door it just built stays shut"


@case
def a_first_connection_that_cannot_be_signed_into_later_is_refused():
    """What is refused here is refused before anything is written.

    A password is guessable in a way a token is not, and behind this port sits a
    runner that runs code on this machine — so the floor is said in the form
    rather than discovered by whoever grinds against it.
    """
    from ponos.web import setup as web_setup

    path, _ = _saved()
    before = path.read_text(encoding="utf-8")
    for payload, expected in (
        ({"email": "me", "password": "one I remember"}, "email address"),
        ({"email": "me@example.com", "password": "short"}, "at the least"),
        (
            {"email": "me@example.com", "password": "one I remember", "confirm": "another"},
            "not the same",
        ),
        (
            {
                "email": "me@example.com",
                "password": "one I remember",
                "notion_page": "my notion page",
            },
            "Notion page ID",
        ),
    ):
        api = _Fresh(path)
        try:
            web_setup.apply(api, payload)
        except ValueError as error:
            assert expected in str(error), error
            continue
        raise AssertionError(f"{payload} should have been refused")
    assert path.read_text(encoding="utf-8") == before, "a refusal writes nothing"


def _talk_to(console, method: str, path: str, body: dict | None = None, **headers: str):
    """One request to a console started for the test: status, headers, JSON."""
    connection = http.client.HTTPConnection("127.0.0.1", console.server_address[1], timeout=10)
    sent = {"Host": "127.0.0.1", "X-Ponos": "1", "Content-Type": "application/json", **headers}
    connection.request(
        method, path, body=json.dumps(body).encode() if body is not None else None, headers=sent
    )
    answer = connection.getresponse()
    raw = answer.read()
    connection.close()
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        parsed = {"_raw": raw.decode("utf-8", "replace")}
    return answer.status, answer.headers, parsed


@contextmanager
def _console(api, code: str = "", entry=None):
    from ponos.web import app as web_app

    console = web_app.Console(("127.0.0.1", 0), api, "tok", entry, code)
    threading.Thread(target=console.serve_forever, daemon=True).start()
    try:
        yield console
    finally:
        console.shutdown()
        console.server_close()


@case
def from_outside_this_machine_nobody_claims_the_console_without_its_code():
    """A console behind a domain is a console the whole Internet reaches first.

    On loopback the first browser is somebody sitting at the machine. Anything
    else — another address, or this one through a proxy, which is what Traefik
    in front of a container is — has to give the code `serve` printed when it
    started. No code drawn, and the first connection is simply not offered.
    """
    from ponos.web import server as web_server

    claim = {"email": "me@example.com", "password": "one I remember", "confirm": "one I remember"}
    proxied = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}

    path, _ = _saved()
    before = path.read_text(encoding="utf-8")
    api = _Fresh(path)
    with _console(api) as console:
        status, _, said = _talk_to(console, "GET", "/api/setup", **proxied)
        assert status == 200 and said["claimed"] is False and said["code"] is True, said
        assert said["code_drawn"] is False
        status, _, said = _talk_to(console, "POST", "/api/setup", claim, **proxied)
        assert status == 403, (status, said)
        assert "installation code" in said["error"]
        status, _, said = _talk_to(console, "GET", "/", **proxied)
        assert status == 200 and 'data-setup="claim"' in said["_raw"], (
            "the steps, drawn by the bundle"
        )
        status, _, said = _talk_to(console, "GET", "/api/board", **proxied)
        assert status == 401, "and nothing else of the console"
    assert path.read_text(encoding="utf-8") == before, "a refusal writes nothing"
    assert web_server.claimable(api.config, None), "and the console is still nobody's"

    api = _Fresh(path)
    with _console(api, code="K7Q2-M9XD") as console:
        status, _, said = _talk_to(
            console, "POST", "/api/setup", {**claim, "code": "AAAA-BBBB"}, **proxied
        )
        assert status == 403 and said["error"] == "wrong installation code", said
        assert path.read_text(encoding="utf-8") == before
        status, headers, said = _talk_to(
            console, "POST", "/api/setup", {**claim, "code": "k7q2m9xd"}, **proxied
        )
        assert status == 429 and headers["Retry-After"] == "1", (
            "a wrong code is waited out, even before the right one"
        )
        _time_passes(console, 1)
        status, headers, said = _talk_to(
            console, "POST", "/api/setup", {**claim, "code": "k7q2m9xd"}, **proxied
        )
        assert status == 200, said
        assert "ponos_token=" in headers["Set-Cookie"]
        assert console.code == "", "a code opens the door once"
    assert not web_server.claimable(api.config, web_server.sign_in(api.config, "tok"))

    # At the machine itself, nothing to give: that is a laptop's first browser.
    path, _ = _saved()
    api = _Fresh(path)
    with _console(api) as console:
        status, _, said = _talk_to(console, "GET", "/api/setup")
        assert said["code"] is False, said
        status, _, said = _talk_to(console, "POST", "/api/setup", claim)
        assert status == 200, said


@case
def a_containers_healthcheck_is_answered_without_a_key():
    """`/healthz` says the console answers, to anybody — and says nothing else."""
    path, _ = _saved()
    api = _Fresh(path)
    with _console(api, code="K7Q2-M9XD") as console:
        status, _, said = _talk_to(console, "GET", "/healthz")
        assert status == 200 and said == {"ok": True}, (status, said)
        status, _, said = _talk_to(console, "GET", "/healthz", **{"X-Forwarded-For": "203.0.113.9"})
        assert status == 200 and said == {"ok": True}, "from outside as well, claimed or not"
        status, _, _ = _talk_to(console, "GET", "/api/board")
        assert status == 401, "and it opens nothing else"


@case
def the_openapi_schema_is_behind_the_same_door_as_the_api():
    """`/openapi.json` describes every route — so it opens with the token, like them.

    And a route answers as it did under `http.server`: with a slash at the
    end, to a HEAD without its body, and a path it does not serve is the 404
    the page reads — never FastAPI's `detail`, nor a 405 for another method.
    """
    path, _ = _saved()
    with _console(_Fresh(path)) as console:
        status, headers, said = _talk_to(console, "GET", "/openapi.json")
        assert status == 401 and said == {"error": "token missing or wrong"}, (status, said)
        key = {"Authorization": "Bearer tok"}
        status, headers, schema = _talk_to(console, "GET", "/openapi.json", **key)
        assert status == 200 and headers["X-Frame-Options"] == "DENY", status
        ticket = schema["paths"]["/api/tickets"]["post"]["requestBody"]
        assert ticket["content"]["application/json"]["schema"]["$ref"].endswith("/NewTicket")
        assert "/api/projects/{project_id}" in schema["paths"]
        assert not any(name.startswith(("/static", "/oauth")) for name in schema["paths"])
        assert _talk_to(console, "GET", "/docs", **key)[0] == 404, "no page that loads a CDN"
        status, _, said = _talk_to(console, "GET", "/api/setup/", **key)
        assert status == 200 and said["signed_in"] is True, said
        status, headers, said = _talk_to(console, "HEAD", "/api/setup", **key)
        assert status == 200 and int(headers["Content-Length"]) > 2 and said == {}, said
        assert _talk_to(console, "GET", "/api/nowhere", **key)[2] == {
            "error": "no such route: /api/nowhere"
        }
        status, _, said = _talk_to(console, "POST", "/api/setup/summary", {}, **key)
        assert (status, said) == (404, {"error": "no such route: /api/setup/summary"})
        status, _, said = _talk_to(console, "POST", "/api/tickets", {"ready": "maybe"}, **key)
        assert status == 400 and said["error"].startswith("ready: "), said
        status, _, said = _talk_to(console, "POST", "/api/chat", {"attachments": "x"}, **key)
        assert status == 400 and said["error"].startswith("attachments"), said


@case
def behind_https_the_consoles_cookies_are_secure():
    """The proxy says the browser came in over HTTPS: the cookie never goes back in clear.

    All three ways in — the token in the address, a sign-in, and the first
    connection — set the same cookie, and all three mark it `Secure` then.
    """
    from ponos.web import server as web_server

    path, _ = _saved('\n[web]\nemail = "me@example.com"\npassword = "one I remember"\n')
    api = _Fresh(path)
    entry = web_server.sign_in(api.config, "tok")
    https = {"X-Forwarded-Proto": "https"}
    with _console(api, entry=entry) as console:
        signing = {"email": "me@example.com", "password": "one I remember"}
        _, headers, _ = _talk_to(console, "POST", "/api/login", signing, **https)
        assert headers["Set-Cookie"].endswith("; Secure"), headers["Set-Cookie"]
        _, headers, _ = _talk_to(console, "POST", "/api/login", signing)
        assert "Secure" not in headers["Set-Cookie"], "plain HTTP on loopback has no use for it"
        status, headers, _ = _talk_to(console, "GET", "/?token=tok", **https)
        assert status == 303 and "; Secure" in headers["Set-Cookie"]

    path, _ = _saved()
    with _console(_Fresh(path)) as console:
        claim = {"email": "me@example.com", "password": "one I remember"}
        status, headers, said = _talk_to(console, "POST", "/api/setup", claim, **https)
    # Through a proxy, and so from outside: refused without a code — and with
    # one, below, the cookie it leaves is a secure one.
    assert status == 403, said
    path, _ = _saved()
    with _console(_Fresh(path), code="ABCD-EFGH") as console:
        status, headers, said = _talk_to(
            console, "POST", "/api/setup", {**claim, "code": "ABCD-EFGH"}, **https
        )
    assert status == 200 and "; Secure" in headers["Set-Cookie"], said


@case
def twenty_wrong_passwords_sent_at_once_are_held_back_not_all_checked(state_home):
    """A `time.sleep` per thread slowed nobody: twenty threads slept side by side.

    Counted before it is checked, an attempt leaves the address waiting while
    it is: of twenty sent together one is looked at, and the nineteen others are
    refused unseen. The right password waits too, then opens; ten failures in a
    row lock the address for a quarter of an hour, and another address is not
    concerned by any of it.
    """
    from concurrent.futures import ThreadPoolExecutor

    from ponos.web import attempts as web_attempts
    from ponos.web import server as web_server

    path, _ = _saved()
    api = _Fresh(path)
    entry = web_server.sign_in(
        _web_config(email="me@example.com", password="one I remember"), "tok"
    )
    wrong = {"email": "me@example.com", "password": "a guess"}
    right = {"email": "me@example.com", "password": "one I remember"}
    with _console(api, entry=entry) as console:
        # At once, as far as the count can tell: twenty connections opened
        # by a test do not all fit in a second on a loaded CI runner.
        frozen = console.attempts.clock()
        console.attempts.clock = lambda: frozen
        with ThreadPoolExecutor(max_workers=20) as pool:
            answers = list(
                pool.map(lambda _: _talk_to(console, "POST", "/api/login", wrong), range(20))
            )
        statuses = sorted(status for status, _, _ in answers)
        assert statuses == [401] + [429] * 19, statuses
        assert all(headers["Retry-After"] for status, headers, _ in answers if status == 429)
        status, _, _ = _talk_to(console, "POST", "/api/login", right)
        assert status == 429, "not even the right one, while the address waits"
        _time_passes(console, 1)
        status, headers, _ = _talk_to(console, "POST", "/api/login", right)
        assert status == 200 and "ponos_token=" in headers["Set-Cookie"]

        for failures in range(1, web_attempts.LOCK_AFTER + 1):
            status, _, _ = _talk_to(console, "POST", "/api/login", wrong)
            assert status == 401, (failures, status)
            _time_passes(console, web_attempts.wait_after(failures) - 0.5)
            if failures < web_attempts.LOCK_AFTER:
                status, _, _ = _talk_to(console, "POST", "/api/login", right)
                assert status == 429, "each wait is longer than the last"
                _time_passes(console, 0.5)
        _time_passes(console, -web_attempts.LOCK_SECONDS + 60)
        status, _, said = _talk_to(console, "POST", "/api/login", right)
        assert status == 429 and "try again" in said["error"], "ten in a row: the lock"
        elsewhere = {"X-Forwarded-For": "203.0.113.9"}
        status, _, _ = _talk_to(console, "POST", "/api/login", right, **elsewhere)
        assert status == 200, "the lock is this address's, not everybody's"

    assert web_attempts.address_of("127.0.0.1", "198.51.100.1, 203.0.113.9") == "203.0.113.9", (
        "a proxy on this side is believed about the hop it appended"
    )
    assert web_attempts.address_of("8.8.4.4", "198.51.100.1") == "8.8.4.4", (
        "anybody else saying who they relay is not"
    )
    assert web_attempts.address_of("2001:db8::1") == web_attempts.address_of("2001:db8::2"), (
        "one /64"
    )
    assert web_attempts.address_of("::ffff:192.0.2.7") == "192.0.2.7"


@case
def a_token_guessed_in_a_header_is_counted_and_the_consoles_cookie_is_not(state_home):
    """A wrong token in the address or a header is a guess; a stale cookie is not.

    The cookie is what a console gave — a neighbouring one, at the same address,
    overwrites it — and counting it would lock out the browser that holds it.
    """
    path, _ = _saved()
    api = _Fresh(path)
    api.config.web.token = "tok"
    with _console(api) as console:
        for _ in range(5):
            status, _, _ = _talk_to(console, "GET", "/api/board", Cookie="ponos_token=another")
            assert status == 401
        status, _, _ = _talk_to(console, "GET", "/api/board", Authorization="Bearer nope")
        assert status == 401
        status, headers, _ = _talk_to(console, "GET", "/api/board", Authorization="Bearer tok")
        assert status == 429 and headers["Retry-After"], "the right token waits as well, unseen"
        status, _, _ = _talk_to(console, "GET", "/setup", Cookie="ponos_token=tok")
        assert status == 200, "the cookie the console gave still opens it"


@case
def a_sign_in_lasts_thirty_days_from_its_last_use_and_all_of_them_end_at_once(state_home):
    """The cookie of a sign-in used to be good until the password changed: forever.

    It carries its date now, signed: refused past thirty days, renewed — a day
    at most after it was given — by any answer to a browser still using it,
    and every one of them refused at once by `serve --sign-out-everywhere`.
    """
    from ponos.web import server as web_server
    from ponos.web import sessions as web_sessions

    path, _ = _saved()
    api = _Fresh(path)
    entry = web_server.sign_in(
        _web_config(email="me@example.com", password="one I remember"), "tok"
    )
    now = time.time()
    with _console(api, entry=entry) as console:

        def opened(cookie: str):
            return _talk_to(console, "GET", "/setup", Cookie=f"ponos_token={cookie}")

        status, headers, _ = opened(web_sessions.issue(entry.proof, now - 31 * 24 * 3600))
        assert status == 401, "a session left a month without a word is over"
        status, headers, _ = opened(web_sessions.issue(entry.proof, now - 2 * 24 * 3600))
        assert status == 200
        renewed = headers["Set-Cookie"]
        assert f"Max-Age={web_sessions.LIFETIME}" in renewed, renewed
        given = renewed.split("=", 1)[1].split(";", 1)[0]
        assert web_sessions.issued(entry.proof, given) >= int(now), "renewed from today"
        status, headers, _ = opened(given)
        assert status == 200 and "Set-Cookie" not in headers, "and not again within the day"
        status, _, _ = opened(web_sessions.issue("another proof", now))
        assert status == 401, "a session of another password, or another console"

        status, _, _ = _talk_to(
            console,
            "POST",
            "/api/login",
            {"email": "me@example.com", "password": "one I remember"},
        )
        assert status == 200
        assert cli_main(["serve", "--sign-out-everywhere"]) == 0
        assert (state_home / "web" / "sessions").stat().st_mode & 0o077 == 0, "kept as the token is"
        status, _, _ = opened(given)
        assert status == 401, "signed out everywhere — the running console as well"
        status, _, _ = _talk_to(console, "GET", "/setup", Cookie="ponos_token=tok")
        assert status == 200, "the token is not a session, and still opens it"


@case
def a_password_kept_in_clear_becomes_its_digest_on_the_first_launch():
    """`secrets.env` held the password as it is typed; it keeps its digest now.

    The installation from before is not asked anything: the launch replaces the
    line by the digest of that very value, the same password signs in, and the
    next launch has nothing to do. The environment's is the unit's to keep.
    """
    from ponos import __main__ as ponos_main
    from ponos import passwords
    from ponos.web import server as web_server

    path, _ = _saved('\n[web]\nemail = "me@example.com"\n')
    secrets_file = C.secrets_path(path)
    C.write_secrets(secrets_file, {C.WEB_PASSWORD_ENV: "one I remember"})
    said: list[str] = []
    with _environment(PONOS_CONFIG=str(path), PONOS_WEB_PASSWORD=None):
        ponos_main.secrets_out_of_config(said.append)
        kept = C.read_secrets(secrets_file)[C.WEB_PASSWORD_ENV]
        assert passwords.is_digest(kept) and "one I remember" not in secrets_file.read_text(
            encoding="utf-8"
        )
        assert any("scrypt digest" in line for line in said), said
        entry = web_server.sign_in(C.load(path), "tok")
        assert entry is not None and entry.digest == kept
        assert entry.opens("me@example.com", "one I remember"), "the same password signs in"
        said.clear()
        ponos_main.secrets_out_of_config(said.append)
        assert C.read_secrets(secrets_file)[C.WEB_PASSWORD_ENV] == kept and not said, "once"
        C.edit(path, [("web", "password", "another I remember")])
        typed = C.read_secrets(secrets_file)[C.WEB_PASSWORD_ENV]
        assert passwords.is_digest(typed) and passwords.matches("another I remember", typed), (
            "and one typed in the Settings is written as its digest from the start"
        )
    assert not passwords.matches("anything", "scrypt:1:1:1:broken:digest"), (
        "a broken digest is no way in"
    )


@case
def every_page_runs_only_its_own_scripts_and_every_answer_says_so(state_home):
    """A Content-Security-Policy on the pages, and the headers that go with it.

    A page's inline lines are allowed by their hash and by nothing else, so the
    pages drawn here carry no `onsubmit=`; the API is served as something that
    runs nothing at all. HSTS only once a proxy says the browser came in over
    HTTPS — on plain HTTP it would be a promise nobody keeps.
    """
    import base64
    import hashlib

    from ponos.web import server as web_server

    for page in (web_server.GATE, web_server.SIGN_IN):
        assert " onsubmit=" not in page and " onclick=" not in page, "an inline handler has no hash"
    path, _ = _saved()
    api = _Fresh(path)
    entry = web_server.sign_in(
        _web_config(email="me@example.com", password="one I remember"), "tok"
    )
    with _console(api, entry=entry) as console:
        status, headers, said = _talk_to(console, "GET", "/")
        assert status == 401
        policy = headers["Content-Security-Policy"]
        script = re.search(r"<script>(.*?)</script>", said["_raw"], re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in policy, policy
        assert "unsafe-inline" not in policy and "frame-ancestors 'none'" in policy
        assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert "microphone=(self)" in headers["Permissions-Policy"]
        assert "Strict-Transport-Security" not in headers

        status, headers, said = _talk_to(console, "GET", "/", Cookie="ponos_token=tok")
        assert status in (200, 303), status
        status, headers, said = _talk_to(console, "GET", "/setup", Cookie="ponos_token=tok")
        policy = headers["Content-Security-Policy"]
        scripts = policy.split("script-src ", 1)[1].split(";", 1)[0]
        assert "unsafe" not in scripts and "'sha256-" in scripts, (
            "the theme, before the first paint"
        )
        assert "style-src 'self' 'unsafe-inline'" in policy, "the bundle writes its own styles"

        status, headers, _ = _talk_to(
            console,
            "GET",
            "/api/board",
            Cookie="ponos_token=tok",
            **{"X-Forwarded-Proto": "https"},
        )
        assert headers["Content-Security-Policy"] == web_server.LOCKED_POLICY
        assert headers["Strict-Transport-Security"].startswith("max-age=")
        status, headers, _ = _talk_to(console, "GET", "/sw.js")
        assert headers["Content-Security-Policy"] == web_server.WORKER_POLICY, (
            "a worker that fetches"
        )


@case
def a_file_beside_the_static_folder_is_not_one_of_its_files():
    """`static-old/` begins with `static`: a prefix let it through, `is_relative_to` does not."""
    from ponos.web import server as web_server

    with tempfile.TemporaryDirectory() as directory, _state_home():
        root = Path(directory).resolve()
        (root / "static").mkdir()
        (root / "static" / "kept.txt").write_text("ours", encoding="utf-8")
        (root / "static-old").mkdir()
        (root / "static-old" / "secret.txt").write_text("not ours", encoding="utf-8")
        original = web_server.STATIC
        web_server.STATIC = root / "static"
        try:
            path, _ = _saved()
            with _console(_Fresh(path)) as console:
                status, _, _ = _talk_to(console, "GET", "/static/kept.txt")
                assert status == 200
                status, _, said = _talk_to(console, "GET", "/static/../static-old/secret.txt")
                assert status == 404 and "not ours" not in json.dumps(said), said
        finally:
            web_server.STATIC = original


@case
def a_repository_named_on_a_notion_page_is_checked_before_a_command_sees_it():
    """A project page is anybody's who edits the board, and its name reaches `gh`.

    `owner/name`, in GitHub's alphabet, or nothing is run at all; and `--`
    before it all the same, so that past it nothing is read as an option.
    """
    for name in ("SalvadorCardona/ponos", "hermez-agency/react-data-form", "a/b.c_d-e"):
        assert git_module.is_repository(name), name
    for name in (
        "--upload-pack=touch/x",
        "owner",
        "a/b/c",
        "owner/..",
        "-o/name",
        "owner/name; rm",
        "https://evil.example/owner/name",
        "owner/na me",
    ):
        assert not git_module.is_repository(name), name

    ran: list[list[str]] = []
    original_run, original_which = git_module.run, shutil.which
    git_module.run = lambda command, **_: (ran.append(command), git_module.Result(0, "", ""))[1]
    shutil.which = lambda name: "/usr/bin/" + name
    try:
        with tempfile.TemporaryDirectory() as directory:
            try:
                git_module.clone("--upload-pack=touch /tmp/x/y", Path(directory) / "y")
            except git_module.GitError as error:
                assert "not a GitHub repository name" in str(error)
            else:
                raise AssertionError("cloned a name that is an option")
            assert ran == [], "and nothing ran"
            git_module.clone("owner/name", Path(directory) / "name")
            assert ran[-1][:4] == ["gh", "repo", "clone", "--"], ran
            assert git_module.current_name("--json/x") == "" and len(ran) == 1
            git_module.current_name("owner/name")
            assert ran[-1][-2:] == ["--", "owner/name"], ran
    finally:
        git_module.run, shutil.which = original_run, original_which
