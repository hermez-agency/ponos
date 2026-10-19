"""The console's HTTP layer: `http.server`, and nothing else.

A tool whose whole claim is "no dependency to install" does not get to grow a
web framework the day it grows a web page. What is here is what the standard
library already offers — a threading HTTP server, a handler, and Server-Sent
Events, which are eight lines and exactly the shape of the problem.

**What is on the other side of this port matters more than the port.** The
runner starts Claude Code sessions with `bypassPermissions`; so does the chat.
Anything that can talk to this server can run code on this machine as you. That
is why:

- the default bind is `127.0.0.1`, and a non-loopback host without a configured
  token — or a configured sign-in — is refused rather than served;
- every request carries a token — as a header, as the cookie the first `?token=`
  sets, or as the cookie signing in with an email and a password sets;
- until somebody has said how this console is opened, there is nothing to carry:
  a console nobody claimed serves the first connection instead (see `setup`),
  and the password typed there is what closes that door — to this machine
  alone, or to whoever has the installation code `serve` printed when it
  started: a console behind a domain is a console the whole Internet reaches
  first;
- behind a proxy that says the browser came in over HTTPS (`X-Forwarded-Proto`),
  every cookie is `Secure`, so it never travels in clear on the way back;
- a request from a browser page that is not the console is rejected: writes
  demand a header a cross-origin form cannot set, and the `Host` header must
  name the address the console was reached on, which is what stops a hostile
  page from resolving its own domain to 127.0.0.1 and talking to you through it.
"""

from __future__ import annotations

import base64
import errno
import gzip
import hashlib
import hmac
import html
import json
import mimetypes
import queue
import re
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlparse

from .. import __version__
from .. import config as config_module
from .. import db, journal, legacy, notifications, openrouter, store, tailscale, vault, voice
from ..config import Config, state_dir
from . import attachments, creation, github, mcp, mcp_setup, oauth, setup
from .api import Api

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "ponos_token"
# Migration filet: the cookie a browser was given before the rename, still good
# for the year it was given for — a rename is not a reason to sign in again.
LEGACY_COOKIE = legacy.OLD.replace("-", "_") + "_token"

# The build names every file under `assets/` after a hash of what it holds, so
# a file there never changes under its name: a browser keeps it for a year and
# asks again only when `index.html` — never cached — points somewhere new.
IMMUTABLE = "public, max-age=31536000, immutable"

# The bundle is text, a megabyte and more of it, sent on every first load and
# over a tunnel as often as over loopback. Compressed once per file, on the first
# request that accepts it, and kept: the files only change when the code does,
# and the code changing is a restart.
COMPRESSIBLE = ("text/", "application/javascript", "application/json", "image/svg+xml")
_compressed: dict[tuple[Path, int, str], bytes] = {}

# A header no cross-origin form, image or script tag can set. Its presence is
# what tells "the console asked this" from "some page you had open asked this".
GUARD_HEADER = "X-Ponos"

# Bodies are small — a ticket, a message, a command. Anything larger is a
# mistake, and reading it would be the mistake becoming ours.
MAX_BODY = 256 * 1024
# A file refused for its size is still read — and dropped — before the refusal
# is sent: close on a client still writing and it sees a broken pipe, not the
# 413 that says why. Past this much, it gets the broken pipe.
MAX_DRAIN = 256 * 1024 * 1024

# Except a picture, which is a file and not a message: the console shrinks it
# before sending, and this is Notion's own ceiling for one piece.
MAX_PICTURE = 20 * 1024 * 1024

# What a picture is served under. It is drawn by an <img> and never run: an SVG
# opened on its own, at this origin, would otherwise be a page with a script.
PICTURE_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"

LOOPBACK = ("127.0.0.1", "::1", "localhost", "[::1]")


def accepts_gzip(header: str) -> bool:
    """`Accept-Encoding` names gzip, and not with `q=0` — which means "never"."""
    for part in header.split(","):
        coding, _, params = part.strip().partition(";")
        if coding.strip().lower() != "gzip":
            continue
        quality = params.strip().lower().replace(" ", "")
        return not (quality.startswith("q=") and quality[2:].strip("0.") == "")
    return False


def token_path() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path / "token"


def token(config: Config) -> str:
    """The console's token: the configured one, or one drawn once and kept.

    Kept on disk rather than drawn per start, because a token that changed on
    every restart would make the bookmark useless — and a console you reach by
    pasting a fresh secret every morning is a console you stop opening.
    """
    if config.web.token:
        return config.web.token
    path = token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    fresh = secrets.token_urlsafe(24)
    from ..disk import write_private  # 0600 from its first byte, not after a chmod

    write_private(path, fresh + "\n")
    return fresh


def landing(query: str) -> str:
    """Where a `?token=…` address goes once the token is in a cookie.

    Everything the address carried except the token, because the rest of it is
    not a secret, it is a destination: `serve` prints `/?token=…` and a deep
    link is shared as `/?token=…&view=console/projects/list`. Redirecting both
    to a bare `/` put the second one on the board.
    """
    rest = urlencode([pair for pair in parse_qsl(query) if pair[0] != "token"])
    return f"/?{rest}" if rest else "/"


@dataclass(frozen=True)
class SignIn:
    """An email, a password, and the cookie a browser that typed them carries.

    The cookie is *derived* from the two rather than drawn at random, and that
    is the whole of the session handling: a console that restarts — and its unit
    restarts with the machine — does not sign you out, while changing the
    password signs out every browser that ever held one, without anything to
    keep or to expire. It is an HMAC under the console's own token, so the value
    in the cookie says nothing about the password it came from.
    """

    email: str
    password: str
    cookie: str


def sign_in(config: Config, secret: str) -> SignIn | None:
    """How this console is opened, when it is not opened with its token.

    None unless both halves are set: an email without a password is somebody
    half-way through configuring one, and it must not be a way in.
    """
    email = config.web.email.strip()
    password = config.web.password
    if not email or not password:
        return None
    proof = hmac.new(
        secret.encode(), f"{email.lower()}\n{password}".encode(), hashlib.sha256
    ).hexdigest()
    return SignIn(email=email, password=password, cookie=proof)


# The installation code's letters: no 0 and O, no 1 and I, nothing a log line
# read off a phone gets wrong.
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# The headers a proxy adds. A request carrying one came through something — a
# Traefik, an nginx on the same machine — and is not "somebody at this machine",
# whatever address it arrived from.
FORWARDED = ("Forwarded", "X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Real-IP")


def installation_code() -> str:
    """Eight letters, drawn once per start of a console nobody has claimed."""
    letters = "".join(secrets.choice(CODE_LETTERS) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


def same_code(offered: str, expected: str) -> bool:
    """The code as somebody types it: any case, with or without its dash."""
    def bare(code: str) -> bytes:
        return re.sub(r"[^0-9A-Za-z]", "", code).upper().encode()

    return bool(expected) and hmac.compare_digest(bare(offered), bare(expected))


def claimable(config: Config, entry: SignIn | None) -> bool:
    """Has anybody decided how this console is opened? — see `setup`.

    Two ways of deciding it, and neither has been taken: a sign-in, which is
    `None` until an email *and* a password are set, in the file or in the
    environment; or a token written in the configuration on purpose. The token
    drawn on first start is not a decision — it is what the console does when
    nobody has said anything, and it is the state the first connection is for.
    """
    return entry is None and not config.web.token


class Console(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address,
        handler,
        api: Api,
        secret: str,
        entry: SignIn | None = None,
        code: str = "",
    ) -> None:
        super().__init__(address, handler)
        self.api = api
        self.secret = secret
        self.entry = entry
        # What a first connection from outside this machine has to say first.
        # Empty: none was drawn, and such a connection is refused outright.
        self.code = code

    def handle_error(self, request, client_address) -> None:
        # A tab closed or reloaded mid-request is how a browser says goodbye,
        # not an error: its traceback in the journal hid the real ones.
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server_version = "ponos"
    protocol_version = "HTTP/1.1"

    # -- plumbing -------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # a console is not a web server; its log is the terminal it runs in

    @property
    def api(self) -> Api:
        return self.server.api  # type: ignore[attr-defined]

    @property
    def entry(self) -> SignIn | None:
        return self.server.entry  # type: ignore[attr-defined]

    def _send(
        self, code: int, body: bytes, kind: str, extra: dict | None = None, cache: str = "no-store"
    ) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            # Nothing here is meant to be cached, framed, sniffed or embedded —
            # but a picture, whose address changes with it, and is kept a day,
            # and the build's own files, whose names change with them.
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except ConnectionError:
            # The client is gone — a tab closed or reloaded. Nobody is left to
            # answer, and a 500 written on the same socket would only fail
            # again, inside the `except` of the route that called this.
            self.close_connection = True

    def _json(self, payload: dict, code: int = 200) -> None:
        # Every answer of the API, masked on its way to the page: see vault.py.
        self._send(
            code, json.dumps(vault.masked(payload), ensure_ascii=False).encode(), "application/json"
        )

    def _fail(self, code: int, message: str) -> None:
        self._json({"error": message}, code)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length > MAX_BODY:
            self.close_connection = True
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- who is asking --------------------------------------------------------

    def _host_is_ours(self) -> bool:
        """The `Host` header names the address this console is served on.

        Without this, any web page could point a domain of its own at 127.0.0.1
        and have your browser talk to the console as if it were the console.
        """
        configured = self.api.config.web.host
        if configured not in LOOPBACK or str(self.server.server_address[0]) not in LOOPBACK:
            # A wider bind was asked for on purpose, and is reached under a name
            # or address this process cannot enumerate — a LAN IP, a tailnet
            # name, whatever the tunnel calls it. The token is the guard there;
            # this check exists for the loopback case, which is the one a page
            # in another tab can actually reach.
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        expected = {"127.0.0.1", "::1", "localhost", str(self.server.server_address[0]), configured}
        # `tailscale serve` or an ssh-free tunnel relays to loopback and keeps the
        # name it was reached under: the one `web.url` says, and that one only.
        if self.api.config.web.url:
            expected.add(urlparse(self.api.config.web.url).hostname or "")
        try:
            expected.add(socket.gethostname())
        except OSError:
            pass
        return host in expected

    def _funnel_allows(self, route: str) -> bool:
        """A request that came through Tailscale Funnel reaches the MCP doors only.

        Funnel is the public Internet: the MCP endpoint is meant to be there, the
        console is not. `ponos tailscale` publishes those paths and no others, and
        this is the second lock, for a handler somebody added by hand. The header
        is Funnel's to set — it overwrites whatever the caller sent.
        """
        if not self.headers.get(tailscale.FUNNEL_HEADER):
            return True
        return tailscale.funnel_allowed(route)

    def _local(self) -> bool:
        """The request comes from this machine — not only to an address of it."""
        address = str(self.client_address[0])
        return address in ("127.0.0.1", "::1") or address.startswith(("127.", "::ffff:127."))

    def _outside(self) -> bool:
        """Not somebody at this machine: another address, or through a proxy."""
        return not self._local() or any(self.headers.get(name) for name in FORWARDED)

    def _secure(self) -> bool:
        """The browser reached the proxy in front of this console over HTTPS.

        `http.server` itself only ever speaks plain HTTP; what is encrypted is the
        leg between the browser and Traefik, and the proxy says so in this header.
        A browser that came in over HTTPS must never send the cookie back over
        anything else.
        """
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0]
        return proto.strip().lower() == "https"

    def _cookie(self, value: str) -> str:
        """The `Set-Cookie` of a way in — the token's, or a sign-in's."""
        secure = "; Secure" if self._secure() else ""
        return f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000{secure}"

    def _same_origin(self) -> bool:
        """The page that sent this is the console, as far as the browser says.

        The guard header already needs a page of this origin to be set at all;
        this is the second lock on the one write that replaces the code the
        console runs. A browser names the page a POST comes from in `Origin`,
        and a script outside a browser — which carries the token anyway — sends
        none, which is allowed.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host") or ""
        return origin in (f"http://{host}", f"https://{host}")

    def _presented(self) -> str:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        if self.headers.get("X-Token"):
            return str(self.headers.get("X-Token")).strip()
        cookies = SimpleCookie(self.headers.get("Cookie") or "")
        for name in (COOKIE, LEGACY_COOKIE):
            if name in cookies:
                return cookies[name].value
        return ""

    def _authorised(self, query: dict) -> bool:
        """The token, or the cookie a sign-in left. Either is this console's.

        The token does not go away when an email and a password are set: it is
        what a script, the dev server's proxy and `--print-token` carry. What
        changes is that a person no longer has to.
        """
        offered = (query.get("token") or [""])[0] or self._presented()
        if not offered:
            return False
        known = [self.server.secret]  # type: ignore[attr-defined]
        if self.entry:
            known.append(self.entry.cookie)
        # Compared as bytes: `compare_digest` refuses two strings when either
        # holds a character outside ASCII, and what is offered here came from a
        # browser — a cookie somebody pasted an accent into would be a 500
        # rather than the "no" it is.
        return any(hmac.compare_digest(offered.encode(), value.encode()) for value in known)

    # -- routing --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        route = parsed.path.rstrip("/") or "/"

        if not self._host_is_ours():
            return self._fail(421, "this console is not served under that name")
        if not self._funnel_allows(route):
            return self._fail(404, "no such route")
        # What a container's healthcheck asks: the console answers. Nothing
        # behind the door — not even whether it was claimed — so no key.
        if route == "/healthz":
            return self._json({"ok": True})
        # The MCP server's doors, which carry keys of their own — see `oauth`.
        if route.startswith("/.well-known/"):
            return self._discovery(route)
        if route == "/mcp":
            # No stream to open: but a key first, as for a POST — the 401 is
            # what tells a client to connect, whatever it tried first.
            if self._grant() is None:
                return None
            return self._send(405, b"", "text/plain", {"Allow": "POST"})
        if route == "/oauth/authorize":
            return self._authorize({key: values[0] for key, values in query.items()})
        # GitHub's two ways back, which come without the cookie — see web/github.py.
        if route == "/api/github/manifest/callback":
            code, answer = github.callback(
                (query.get("code") or [""])[0], (query.get("state") or [""])[0]
            )
            if code == 303:
                return self._send(303, b"", "text/plain", {"Location": answer})
            return self._send(code, answer.encode(), "text/html; charset=utf-8")
        if route == "/api/github/installed":
            drawn = github.installed((query.get("setup_action") or [""])[0])
            return self._send(200, drawn.encode(), "text/html; charset=utf-8")
        # What makes the console installable: the browser fetches these for
        # itself, and a manifest request leaves without the cookie unless the
        # page asks otherwise — they are the same files for everybody, and hold
        # no secret, so no key is asked for them either.
        if route == "/sw.js":
            return self._static("sw.js")
        if route in ("/static/manifest.webmanifest", "/static/offline.html") or route.startswith(
            "/static/pwa/"
        ):
            return self._static(route[len("/static/") :])
        if not self._authorised(query):
            # An unclaimed console is drawn by the bundle, which is no secret:
            # it is the same files for everybody, and what it asks first is the
            # code, the email and the password.
            if claimable(self.api.config, self.entry):
                if route.startswith("/static/"):
                    return self._static(route[len("/static/") :])
                if route == "/api/setup":
                    return self._json(self._setup_state(False))
            return self._unauthorised(route)

        # The token arrived in the URL: put it in a cookie and get it out of the
        # address bar, where it would otherwise sit in the history and in every
        # screenshot of the console. The token, and nothing else: the rest of
        # the address says *where* — `?token=…&view=console/projects/list` is
        # how a deep link is shared — and a redirect to a bare `/` would strip
        # the destination along with the secret and land on the board.
        if query.get("token") and route == "/":
            return self._send(
                303,
                b"",
                "text/plain",
                {
                    "Location": landing(parsed.query),
                    "Set-Cookie": self._cookie(query["token"][0]),
                },
            )

        # The steps of the first connection, for somebody already in: a console
        # still unclaimed has a password waiting to be set, one claimed from the
        # environment has everything after it — and the bare address of a
        # console with no board yet leads there, rather than to an empty board.
        if route == "/setup":
            claim = claimable(self.api.config, self.entry)
            return self._static("index.html", setup="claim" if claim else "steps")
        if route == "/" and not parsed.query and not self._usable():
            return self._send(303, b"", "text/plain", {"Location": "/setup"})

        if route == "/":
            return self._static("index.html")
        if route.startswith("/static/"):
            return self._static(route[len("/static/") :])
        if route == "/api/events":
            return self._stream(
                (query.get("after") or [""])[0], bool((query.get("board") or [""])[0])
            )

        try:
            if route == "/api/state":
                return self._json(self.api.state(local=self._local()))
            if route == "/api/board":
                return self._json(self.api.board())
            if route == "/api/notifications":
                return self._json(notifications.recent())
            if route == "/api/projects":
                return self._json(self.api.all_projects())
            if route == "/api/projects/check":
                return self._json(
                    self.api.creation.check(
                        (query.get("repository") or [""])[0], (query.get("path") or [""])[0]
                    )
                )
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.project(match.group(1)))
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})/brief", route):
                return self._json(self.api.project_brief(match.group(1)))
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})/settings", route):
                return self._json(self.api.project_settings(match.group(1)))
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})/image/(\w+)", route):
                data, kind = self.api.picture(match.group(1), match.group(2))
                return self._send(
                    200, data, kind, {"Content-Security-Policy": PICTURE_POLICY},
                    cache="private, max-age=86400",
                )
            if match := re.fullmatch(r"/api/files/([0-9a-fA-F-]{32,36})", route):
                return self._send(302, b"", "text/plain", {"Location": self.api.attachment(match.group(1))})
            if route == "/api/context":
                return self._json(self.api.context())
            if route == "/api/schedules":
                return self._json(self.api.schedules())
            if match := re.fullmatch(r"/api/schedules/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.schedule(match.group(1)))
            if route == "/api/ideas":
                # No `project` is the workspace's ideas, the dashboard's.
                return self._json(self.api.ideas.proposed((query.get("project") or [""])[0]))
            if route == "/api/ideas/all":
                # `scope=all` is every project's ideas and the workspace's together.
                return self._json(
                    self.api.ideas.every(
                        None if query.get("scope") == ["all"] else (query.get("project") or [""])[0]
                    )
                )
            if route == "/api/ideas/unscored":
                # What scoring the ideas with none would take: said before it is started.
                return self._json(
                    self.api.ideas.unscored(
                        None if query.get("scope") == ["all"] else (query.get("project") or [""])[0]
                    )
                )
            if route == "/api/history":
                return self._json(self.api.history())
            if route == "/api/disk":
                return self._json(self.api.disk())
            if route == "/api/statistics":
                try:
                    figures = self.api.statistics(
                        (query.get("from") or [""])[0],
                        (query.get("to") or [""])[0],
                        # No `project` (or a blank one, which `parse_qs` drops) is the whole board.
                        query["project"][0] if "project" in query else None,
                    )
                except ValueError as error:
                    # A period that makes no sense, said as the page's mistake.
                    return self._fail(400, str(error))
                return self._json(figures)
            if route == "/api/chat":
                return self._json({"messages": self.api.chat.history(), **self.api.chat.state()})
            if route == "/api/chat/sessions":
                return self._json({"sessions": self.api.chat.sessions((query.get("q") or [""])[0])})
            if route == "/api/chat/models":
                return self._json(self.api.chat.models())
            if match := re.fullmatch(r"/api/chat/attachments/([0-9a-f]{12})", route):
                return self._attachment(match.group(1))
            if route == "/api/settings":
                return self._json(self.api.settings())
            if route == "/api/mcp":
                return self._json(mcp_setup.overview(self._loopback(), self.api.config.web.url))
            if route == "/api/mcp/servers":
                return self._json(mcp_setup.servers())
            if route == "/api/settings/folder":
                try:
                    return self._json(self.api.folder((query.get("path") or [""])[0]))
                except ValueError as error:
                    return self._fail(400, str(error))
            if route == "/api/setup":
                return self._json(self._setup_state(True))
            if route == "/api/setup/summary":
                return self._json(setup.summary(self.api))
            if route == "/api/setup/claude":
                return self._json(setup.claude_login())
            if route == "/api/setup/github":
                return self._json(setup.github())
            if route == "/api/github":
                return self._json(github.status())
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.ticket(match.group(1)))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/talk", route):
                return self._json(self.api.talk(match.group(1)))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/decision", route):
                try:
                    return self._json(self.api.decision(match.group(1)))
                except ValueError as error:
                    return self._fail(409, str(error))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/runs", route):
                return self._json(self.api.runs(match.group(1)))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/transitions", route):
                return self._json(self.api.transitions(match.group(1)))
            if match := re.fullmatch(r"/api/runs/(\d+)/steps", route):
                try:
                    pages = {
                        name: int((query.get(name) or ["0"])[0] or 0)
                        for name in ("before", "after", "limit")
                    }
                except ValueError:
                    return self._fail(400, "before, after and limit are numbers")
                return self._json(
                    self.api.run_steps(
                        int(match.group(1)),
                        before=pages["before"],
                        after=pages["after"],
                        limit=pages["limit"] or journal.PAGE,
                    )
                )
            if route == "/api/logs":
                return self._json(self.api.logs((query.get("ticket") or [""])[0]))
            if match := re.fullmatch(r"/api/logs/([\w.\-]+)", route):
                return self._json(self.api.log(match.group(1)))
        except store.StoreError as error:
            return self._fail(502, f"the board: {str(error).splitlines()[0]}")
        except LookupError as error:
            return self._fail(404, str(error))
        except Exception as error:  # noqa: BLE001
            return self._fail(500, str(error).splitlines()[0])

        return self._fail(404, f"no such route: {route}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if not self._host_is_ours():
            self.close_connection = True
            return self._fail(421, "this console is not served under that name")
        if not self._funnel_allows(route):
            self.close_connection = True
            return self._fail(404, "no such route")
        # The MCP server and its authorisation server: a client of theirs is no
        # browser on the console's page, and carries none of its credentials.
        if route == "/mcp":
            return self._mcp()
        if route == "/oauth/register":
            return self._register()
        if route == "/oauth/token":
            return self._token()
        if route == "/oauth/authorize":
            return self._consent()
        # Two writes cannot be authorised beforehand, because they are what
        # produces the authorisation: signing in, and — on a console nobody has
        # claimed — the first connection that gives it a password to sign in
        # with. Everything else about them holds: the name they are reached
        # under, and the header below.
        signing_in = route == "/api/login"
        opening = signing_in or route == "/api/setup"
        if not opening and not self._authorised(parse_qs(parsed.query)):
            # The body is left unread, so the connection cannot be reused: the
            # next request on it would begin with this one's `{}` — which is how
            # a signed-out browser reloading the page got a 501 for "{}GET".
            self.close_connection = True
            return self._fail(401, "token missing or wrong")
        # A cookie alone is not consent: a page you have open elsewhere can post
        # a form to this port with your cookie attached, but it cannot set a
        # header of its own without a preflight this server never answers.
        if self.headers.get(GUARD_HEADER) != "1":
            self.close_connection = True
            return self._fail(403, "this request did not come from the console")

        # The two writes whose body is not JSON, and not small: a file, and a
        # recording. Read here, before `_body` would refuse them for their size.
        if route == "/api/chat/attachments":
            return self._upload(parse_qs(parsed.query))
        if route == "/api/chat/transcribe":
            return self._transcribe(parse_qs(parsed.query))

        picture = re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})/image/(\w+)", route)
        if picture and (self.headers.get("Content-Type") or "").startswith("image/"):
            return self._picture(picture.group(1), picture.group(2))

        payload = self._body()
        if signing_in:
            return self._sign_in(payload)
        if route in ("/api/update", "/api/update/cancel"):
            return self._update(route)
        try:
            if picture:
                chosen = store.Picture(
                    url=str(payload.get("url") or "").strip(),
                    emoji=str(payload.get("emoji") or "").strip(),
                )
                if chosen.removed and not payload.get("remove"):
                    raise ValueError("say which picture: a url, an emoji, or remove")
                return self._json(self.api.set_picture(picture.group(1), picture.group(2), chosen))
            if route == "/api/setup":
                return self._setup(payload)
            if route == "/api/setup/provider":
                return self._json(setup.save_provider(self.api, payload))
            if route == "/api/setup/notion":
                return self._json(setup.save_notion(self.api, payload))
            if route == "/api/setup/channels":
                return self._json(setup.save_channels(self.api, payload))
            if route == "/api/github/connect":
                return self._json(
                    github.connect(self._base(), str(payload.get("organisation", "")))
                )
            if route == "/api/github/disconnect":
                return self._json(github.disconnect(str(payload.get("slug", ""))))
            if route == "/api/tickets":
                return self._json(
                    self.api.create_ticket(
                        str(payload.get("title", "")),
                        str(payload.get("body", "")),
                        str(payload.get("project", "")),
                        bool(payload.get("ready", True)),
                        str(payload.get("priority", "")),
                        str(payload.get("type", "")),
                        str(payload.get("model", "")),
                        str(payload.get("subtype", "")),
                        str(payload.get("on", "")),
                    )
                )
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/on", route):
                return self._json(self.api.set_on(match.group(1), str(payload.get("on", ""))))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/status", route):
                seen = payload.get("from")
                return self._json(
                    self.api.set_status(
                        match.group(1),
                        str(payload.get("column", "")),
                        None if seen is None else str(seen),
                    )
                )
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/talk", route):
                return self._json(self.api.tell(match.group(1), str(payload.get("text", ""))))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/decision", route):
                titles = payload.get("titles") or []
                if not isinstance(titles, list):
                    raise ValueError("titles is a list of strings")
                return self._json(
                    self.api.decide(
                        match.group(1),
                        str(payload.get("key", "")),
                        number=int(payload.get("number") or 0),
                        text=str(payload.get("text", "")),
                        model=str(payload.get("model", "")),
                        titles=[str(title) for title in titles],
                    )
                )
            if route == "/api/command":
                return self._json(self.api.commands.start(str(payload.get("line", ""))))
            if route == "/api/chat":
                attached = payload.get("attachments") or []
                if not isinstance(attached, list):
                    raise ValueError("attachments is a list of ids")
                return self._json(
                    self.api.chat.send(str(payload.get("text", "")), [str(item) for item in attached])
                )
            if match := re.fullmatch(r"/api/chat/attachments/([0-9a-f]{12})/remove", route):
                return self._json(self.api.chat.detach(match.group(1)))
            if route == "/api/chat/stop":
                return self._json(self.api.chat.stop())
            if route == "/api/chat/reset":
                return self._json(self.api.chat.reset())
            if route == "/api/chat/model":
                return self._json(self.api.chat.choose(str(payload.get("model", ""))))
            if match := re.fullmatch(r"/api/chat/sessions/([0-9a-f]{12})/(open|rename|delete|project)", route):
                identifier, verb = match.groups()
                if verb == "open":
                    return self._json(self.api.chat.open(identifier))
                if verb == "rename":
                    return self._json(self.api.chat.rename(identifier, str(payload.get("title", ""))))
                if verb == "project":
                    return self._json(self.api.chat.link(identifier, str(payload.get("project", ""))))
                return self._json(self.api.chat.delete(identifier))
            if route == "/api/projects":
                try:
                    return self._json(self.api.creation.create(payload))
                except creation.Refused as error:
                    # Under the field it is about, as the form draws a refusal.
                    said = str(error)
                    violation = {"propertyPath": error.field, "message": said}
                    return self._json({"error": said, "violations": [violation]}, 400)
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})/delete", route):
                return self._json(self.api.removal.delete(match.group(1), payload))
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})/settings", route):
                return self._json(self.api.save_project_settings(match.group(1), payload))
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.save_project(match.group(1), payload))
            if route == "/api/settings":
                return self._json(self.api.save_settings(payload))
            if route == "/api/context":
                return self._json(self.api.save_context(str(payload.get("text", ""))))
            if route == "/api/schedules":
                return self._json(
                    self.api.create_schedule(str(payload.get("name", "")), payload)
                )
            if match := re.fullmatch(r"/api/schedules/([0-9a-fA-F-]{32,36})/launch", route):
                return self._json(self.api.launch_schedule(match.group(1)))
            if match := re.fullmatch(r"/api/schedules/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.save_schedule(match.group(1), payload))
            if route == "/api/ideas/generate":
                return self._json(self.api.ideas.generate(str(payload.get("project") or "")))
            if route == "/api/ideas":
                return self._json(self.api.ideas.create(payload))
            if route == "/api/ideas/score":
                # No `project` at all is every scope's; "" the workspace's.
                scope = payload.get("project")
                return self._json(self.api.ideas.score_unscored(None if scope is None else str(scope)))
            if match := re.fullmatch(r"/api/ideas/(\d+)", route):
                return self._json(self.api.ideas.edit(int(match.group(1)), payload))
            if match := re.fullmatch(r"/api/ideas/(\d+)/(keep|discard|ticket|reopen)", route):
                return self._json(getattr(self.api.ideas, match.group(2))(int(match.group(1))))
            if route == "/api/ideas/undo":
                # A `project` (empty for the workspace's) takes back that scope's
                # last decision; none at all, the last decision of any.
                scope = payload.get("project")
                return self._json(self.api.ideas.undo(None if scope is None else str(scope)))
            if route == "/api/disk/clean":
                return self._json(self.api.clean())
            if route == "/api/mcp/test":
                # The address tried is one of the two the tab offers, never one the page typed.
                web = self.api.config.web
                address = f"{web.url.rstrip('/')}/mcp" if web.url else ""
                if payload.get("target") != "public":
                    address = f"{self._loopback()}/mcp"
                return self._json(mcp_setup.probe(address))
            if route == "/api/notifications/read":
                identifier = payload.get("id")
                if identifier is not None and not isinstance(identifier, int):
                    raise ValueError("id is a number, or absent for all of them")
                return self._json(self.api.read_notifications(identifier))
            if route == "/api/refresh":
                self.api.resynchronise()
                return self._json({"ok": True})
        except config_module.ConfigError as error:
            return self._fail(400, str(error).splitlines()[0])
        except ValueError as error:
            return self._fail(400, str(error))
        except LookupError as error:
            return self._fail(404, str(error))
        except RuntimeError as error:
            return self._fail(409, str(error))
        except FileNotFoundError as error:
            return self._fail(503, str(error))
        except store.StoreError as error:
            return self._fail(502, f"the board: {str(error).splitlines()[0]}")
        except Exception as error:  # noqa: BLE001
            return self._fail(500, str(error).splitlines()[0])

        return self._fail(404, f"no such route: {route}")

    def _update(self, route: str) -> None:
        """Start, or call off, the update the header offers. See `upgrade.py`.

        Answered only to this machine and to the console's own page: of every
        write, this is the one that replaces the code answering it. The body
        says nothing — which version, which command and which directory are
        the server's to know, never the page's.
        """
        if not self._local():
            return self._fail(403, "an update is started from the machine the runner is on")
        if not self._same_origin():
            return self._fail(403, "this request did not come from the console")
        try:
            if route == "/api/update/cancel":
                return self._json(self.api.upgrade.cancel())
            return self._json(self.api.upgrade.start())
        except RuntimeError as error:
            return self._fail(409, str(error))

    # -- what a message carries -----------------------------------------------

    def _length(self) -> int:
        try:
            return int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return 0

    def _drain(self, length: int) -> None:
        """Read and drop an announced body the request will not be granted."""
        if length > MAX_DRAIN:
            return
        left = length
        while left > 0:
            chunk = self.rfile.read(min(1 << 16, left))
            if not chunk:
                return
            left -= len(chunk)

    def _upload(self, query: dict) -> None:
        """One file for the message being written, as the raw body of the request.

        Raw rather than multipart: one file per request is what the page sends,
        and the standard library no longer parses multipart (`cgi` is gone). The
        name comes in the query, the bytes are streamed to disk — never held.
        """
        name = (query.get("name") or [""])[0]
        length = self._length()
        chat = self.api.chat
        try:
            said = chat.attach(name, self.rfile, length)
        except attachments.TooLarge as error:
            self._drain(length)
            self.close_connection = True
            return self._fail(413, str(error))
        except ValueError as error:
            # Refused before its body was read, or halfway: nothing after it on
            # this connection can be trusted to start where it should.
            self.close_connection = True
            return self._fail(400, str(error))
        except OSError as error:
            self.close_connection = True
            return self._fail(500, f"the file could not be kept: {error}")
        return self._json(said)

    def _transcribe(self, query: dict) -> None:
        length = self._length()
        chat = self.api.chat
        if length > chat.config.web.attachment_max_mb * 1024 * 1024:
            self._drain(length)
            self.close_connection = True
            return self._fail(413, "the recording is longer than a message can be")
        audio = self.rfile.read(length) if length > 0 else b""
        try:
            said = chat.transcribe(
                audio,
                self.headers.get("Content-Type") or "",
                (query.get("lang") or [""])[0],
            )
        except openrouter.Unavailable as error:
            return self._fail(503, str(error))
        except openrouter.TranscriptionError as error:
            return self._fail(502, str(error))
        except ValueError as error:
            return self._fail(400, str(error))
        return self._json(said)

    def _attachment(self, identifier: str) -> None:
        """A file of the conversation, served back for its thumbnail.

        Under the type of its extension, never the one it was uploaded with, and
        with a sandbox: even an accepted kind is not a page this origin runs.
        Read whole, like the static files: `web.attachment_max_mb` bounds it.
        """
        try:
            attachment = self.api.chat.attachment(identifier)
            body = attachment.path.read_bytes()
        except (LookupError, OSError) as error:
            return self._fail(404, str(error))
        extra = {"Content-Disposition": f"inline; filename*=UTF-8''{quote(attachment.name)}"}
        # Every kind but the PDF, which Chrome refuses to open in a sandbox at
        # all — and whose viewer is a sandbox of its own.
        if attachment.type != "application/pdf":
            extra["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; media-src 'self'"
        self._send(200, body, attachment.type, extra)

    def _picture(self, page_id: str, slot: str) -> None:
        """A picture sent as it is, the body being the file. See `Api.set_picture`."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_PICTURE:
            self.close_connection = True
            return self._fail(413, f"a picture is sent whole, and under {MAX_PICTURE // (1024 * 1024)} MB")
        data = self.rfile.read(length)
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        name = re.sub(r"[^\w.\-]+", "-", unquote(self.headers.get("X-Filename") or ""))[:80]
        try:
            return self._json(
                self.api.set_picture(
                    page_id, slot, store.Picture(data=data, type=kind, name=name)
                )
            )
        except ValueError as error:
            return self._fail(400, str(error))
        except store.StoreError as error:
            return self._fail(502, f"the board: {str(error).splitlines()[0]}")
        except Exception as error:  # noqa: BLE001
            return self._fail(500, str(error).splitlines()[0])

    # -- the MCP server --------------------------------------------------------

    def _base(self) -> str:
        """The address this console is reached at, as the client reached it.

        Read from the request: behind Traefik it is the domain and HTTPS the
        proxy says it served, on this machine it is the loopback address — and
        the metadata a client reads has to name the one it used. `web.url`
        when it is set and the request did not come by loopback: a proxy or a
        tunnel that says nothing of HTTPS is the case it is for, and Claude
        Code on this machine still reads the address it typed.
        """
        scheme = "https" if self._secure() else "http"
        forwarded = (self.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        host = forwarded or (self.headers.get("Host") or "").strip()
        configured = self.api.config.web.url
        if configured and host.rsplit(":", 1)[0].strip("[]") not in LOOPBACK:
            return configured
        if not host:
            address = self.server.server_address
            host = f"{address[0]}:{address[1]}"
        return f"{scheme}://{host}"

    def _loopback(self) -> str:
        """This console as a client on this machine reaches it: the port it listens on."""
        host, port = self.server.server_address[:2]
        if host in ("0.0.0.0", "::", "", "::1") or host.startswith("127."):
            host = "127.0.0.1"
        return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"

    def _raw(self) -> bytes | None:
        """The body as it came — None when it is larger than any of ours."""
        length = self._length()
        if length > MAX_BODY:
            self._drain(length)
            self.close_connection = True
            return None
        return self.rfile.read(length) if length > 0 else b""

    def _form(self) -> dict[str, str] | None:
        """A form, as OAuth posts one — or JSON, which some clients send instead."""
        raw = self._raw()
        if raw is None:
            return None
        text = raw.decode("utf-8", errors="replace")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() == "application/json":
            try:
                said = json.loads(text or "{}")
            except ValueError:
                return {}
            return {str(key): str(value) for key, value in said.items()} if isinstance(said, dict) else {}
        return {key: value for key, value in parse_qsl(text, keep_blank_values=True)}

    def _discovery(self, route: str) -> None:
        """Where a client learns how to get a key: RFC 9728, then RFC 8414."""
        base = self._base()
        if route.startswith("/.well-known/oauth-protected-resource"):
            return self._json(
                {
                    "resource": f"{base}/mcp",
                    "resource_name": "Ponos",
                    "authorization_servers": [base],
                    "scopes_supported": list(oauth.SCOPES),
                    "bearer_methods_supported": ["header"],
                }
            )
        if route.startswith(("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")):
            return self._json(
                {
                    "issuer": base,
                    "authorization_endpoint": f"{base}/oauth/authorize",
                    "token_endpoint": f"{base}/oauth/token",
                    "registration_endpoint": f"{base}/oauth/register",
                    "scopes_supported": list(oauth.SCOPES),
                    "response_types_supported": ["code"],
                    "response_modes_supported": ["query"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": list(oauth.AUTH_METHODS),
                    "authorization_response_iss_parameter_supported": True,
                }
            )
        return self._fail(404, f"no such route: {route}")

    def _grant(self) -> oauth.Grant | None:
        """The key the request carries — or None, with the 401 already sent.

        The 401 names where the metadata is (RFC 9728): it is what makes Claude
        offer "Connect", with no key as with one expired or taken back.
        """
        header = self.headers.get("Authorization") or ""
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        try:
            grant = oauth.check(presented)
        except db.ERRORS as error:
            self._fail(500, f"the keys cannot be read: {error}")
            return None
        if grant is None:
            metadata = f"{self._base()}/.well-known/oauth-protected-resource/mcp"
            said = f'Bearer resource_metadata="{metadata}"'
            if presented:
                said += ', error="invalid_token"'
            self._send(
                401,
                json.dumps({"error": "a token for this server is needed"}).encode(),
                "application/json",
                {"WWW-Authenticate": said},
            )
        return grant

    def _mcp(self) -> None:
        """One JSON-RPC message for the MCP server, with a key of its own.

        Never the console's token nor its cookie: those open everything, and
        a connector is given read, or read and write, and nothing else.
        `Origin` is not checked, as Leadz does not: what it guards against —
        a page resolving its own name to this machine — is refused by the
        `Host` check already, and a page anywhere holds no key to send.
        """
        raw = self._raw()
        if raw is None:
            return self._fail(413, "a message is smaller than that")
        grant = self._grant()
        if grant is None:
            return None
        try:
            message = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}}, 400)
        answer = mcp.handle(self.api, grant, message, self._base())
        if answer is None:
            return self._send(202, b"", "application/json")
        return self._json(answer) if isinstance(answer, dict) else self._send(
            200, json.dumps(answer, ensure_ascii=False).encode(), "application/json"
        )

    def _register(self) -> None:
        raw = self._raw()
        if raw is None:
            return self._fail(413, "a registration is smaller than that")
        try:
            metadata = json.loads(raw.decode("utf-8") or "{}")
            return self._json(oauth.register(metadata), 201)
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "invalid_client_metadata", "error_description": "not JSON"}, 400)
        except oauth.OAuthError as error:
            return self._json(error.body(), error.status)

    def _token(self) -> None:
        form = self._form()
        if form is None:
            return self._fail(413, "a token request is smaller than that")
        basic = None
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("basic "):
            try:
                pair = base64.b64decode(header[6:].strip()).decode("utf-8")
                identifier, _, secret = pair.partition(":")
                basic = (unquote(identifier), unquote(secret))
            except (ValueError, UnicodeDecodeError):
                return self._json({"error": "invalid_client"}, 401)
        try:
            return self._json(oauth.exchange(form, basic))
        except oauth.OAuthError as error:
            return self._json(error.body(), error.status)

    def _authorize(self, params: dict[str, str], said: str = "", status: int = 200) -> None:
        """The consent page: which client, asking for what — and, signed out, who you are."""
        language = self._language()
        if claimable(self.api.config, self.entry):
            return self._send(
                403, consent_refused(language, "This console has not been set up yet.").encode(),
                "text/html; charset=utf-8",
            )
        try:
            request = oauth.asked(params)
        except oauth.OAuthError as error:
            if error.redirect:
                location = oauth.back(
                    error.redirect, error=error.error, error_description=error.description,
                    state=error.state, iss=self._base(),
                )
                return self._send(302, b"", "text/plain", {"Location": location})
            return self._send(
                400, consent_refused(language, error.description).encode(), "text/html; charset=utf-8"
            )
        needs = "" if self._authorised({}) else ("password" if self.entry else "token")
        page = consent_page(language, request, params, needs, said)
        self._send(status, page.encode(), "text/html; charset=utf-8")

    def _consent(self) -> None:
        """The consent page, answered: a code back to the client, or a refusal.

        Posted by the page above and by nothing else — its `Origin` is checked,
        and the console's cookie is `SameSite=Strict`, so a page elsewhere
        posting this form for you arrives signed out, and has to know the
        password.
        """
        form = self._form()
        if form is None:
            return self._fail(413, "a consent is smaller than that")
        if not self._same_origin():
            return self._fail(403, "this request did not come from the console")
        if claimable(self.api.config, self.entry):
            return self._fail(403, "this console has not been set up yet")
        try:
            request = oauth.asked(form)
        except oauth.OAuthError:
            return self._authorize(form)
        base = self._base()
        if form.get("decision") != "allow":
            location = oauth.back(
                request.redirect_uri, error="access_denied", state=request.state, iss=base
            )
            return self._send(302, b"", "text/plain", {"Location": location})
        if not self._authorised({}) and not self._proven(form):
            time.sleep(1)  # as signing in does: a password is guessable, a wall to grind against
            wrong = "wrong email or password" if self.entry else "wrong token"
            return self._authorize(form, _words(self._language())(wrong), 401)
        scopes = (oauth.READ, oauth.WRITE) if form.get("write") and oauth.WRITE in request.scopes else (oauth.READ,)
        code = oauth.code(request, scopes)
        location = oauth.back(request.redirect_uri, code=code, state=request.state, iss=base)
        self._send(302, b"", "text/plain", {"Location": location})

    def _proven(self, form: dict[str, str]) -> bool:
        """The credentials typed on the consent page: the sign-in's, or the token."""
        entry = self.entry
        if entry is not None:
            email = form.get("email", "").strip().lower()
            known_email = hmac.compare_digest(email.encode(), entry.email.lower().encode())
            known_password = hmac.compare_digest(form.get("password", "").encode(), entry.password.encode())
            return known_email and known_password
        offered = form.get("token", "").strip()
        return bool(offered) and hmac.compare_digest(offered.encode(), self.server.secret.encode())  # type: ignore[attr-defined]

    # -- the three kinds of response ------------------------------------------

    def _static(self, name: str, setup: str = "") -> None:
        target = (STATIC / name).resolve()
        if not str(target).startswith(str(STATIC)) or not target.is_file():
            return self._fail(404, f"no such file: {name}")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        marked = ""
        if name == "index.html":
            marked = self._configured()
            body = configured(body, marked)
            if setup:
                # What the page draws instead of the console: see `main.tsx`.
                body = re.sub(rb"<html\b", f'<html data-setup="{setup}"'.encode(), body, count=1)
                marked = f"{marked}:{setup}"
        extra: dict[str, str] = {}
        if kind.startswith(COMPRESSIBLE):
            extra["Vary"] = "Accept-Encoding"
            if accepts_gzip(self.headers.get("Accept-Encoding") or ""):
                key = (target, target.stat().st_mtime_ns, marked)
                if key not in _compressed:
                    _compressed[key] = gzip.compress(body, compresslevel=9, mtime=0)
                body = _compressed[key]
                extra["Content-Encoding"] = "gzip"
        if target.suffix == ".webmanifest":
            kind = "application/manifest+json"
        if kind.startswith("text/") or kind == "application/javascript":
            kind = f"{kind}; charset=utf-8"
        cache = IMMUTABLE if name.startswith("assets/") else "no-store"
        self._send(200, body, kind, extra, cache=cache)

    def _sign_in(self, payload: dict) -> None:
        """An email and a password against the configured ones. Nothing else."""
        entry = self.entry
        if entry is None:
            return self._fail(404, "this console is opened with its token")
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        # Both compared before either is looked at: an early return here would
        # answer "that email does not exist" by taking less time to say so. And
        # as bytes, because a password with an accent in it is a password.
        known_email = hmac.compare_digest(email.encode(), entry.email.lower().encode())
        known_password = hmac.compare_digest(password.encode(), entry.password.encode())
        if not (known_email and known_password):
            # Behind this port sits `bypassPermissions`, and a password is
            # guessable in a way a 32-character token is not. A second per
            # attempt is nothing to type through and a wall to grind against.
            time.sleep(1)
            return self._fail(401, "wrong email or password")
        self._send(200, b'{"ok": true}', "application/json", {"Set-Cookie": self._cookie(entry.cookie)})

    def _setup(self, payload: dict) -> None:
        """The first connection: everything at once, and a way in at the end.

        Signing the browser in rather than sending it back to the door it has
        just built: the password was typed one second ago, and asking for it
        again would be the token all over again. The console keeps its new
        sign-in on the server object, because that is where the way in is read
        from — a restart would find the same one in the file.
        """
        if not claimable(self.api.config, self.entry):
            return self._fail(404, "this console has already been set up")
        if self._outside():
            # From outside this machine, the code `serve` printed — or nothing.
            # Compared before anything is written, and a second per wrong guess,
            # as a password is: eight letters out of thirty-two are a lot of
            # guesses, and this keeps them that way.
            if not self.server.code:  # type: ignore[attr-defined]
                return self._fail(
                    403,
                    "the first connection is only offered on this machine, or with the "
                    "installation code the console prints when it starts",
                )
            if not same_code(str(payload.get("code", "")), self.server.code):  # type: ignore[attr-defined]
                time.sleep(1)
                return self._fail(403, "wrong installation code")
        result = setup.apply(self.api, payload)
        entry = sign_in(self.api.config, self.server.secret)  # type: ignore[attr-defined]
        if entry is None:  # the write went through and said nothing: refuse to guess
            return self._fail(500, "the credentials were not written")
        self.server.entry = entry  # type: ignore[attr-defined]
        self.server.code = ""  # type: ignore[attr-defined]  # used once, and the door is shut anyway
        self._send(
            200,
            json.dumps(result, ensure_ascii=False).encode(),
            "application/json",
            {"Set-Cookie": self._cookie(entry.cookie)},
        )

    def _setup_state(self, signed_in: bool) -> dict:
        """What the first connection's page needs before it draws a step."""
        claim = claimable(self.api.config, self.entry)
        return {
            "claimed": not claim,
            "signed_in": signed_in,
            "code": claim and self._outside(),
            "code_drawn": bool(self.server.code),  # type: ignore[attr-defined]
            "container": config_module.in_container(),
            "version": __version__,
            "storage": self.api.config.storage.mode,
        }

    def _usable(self) -> bool:
        try:
            self.api.config.require_usable()
        except config_module.ConfigError:
            return False
        return True

    def _unauthorised(self, route: str) -> None:
        if route.startswith("/api/"):
            return self._fail(401, "token missing or wrong")
        language = self._language()
        if claimable(self.api.config, self.entry):
            return self._static("index.html", setup="claim")
        if self.entry:
            page = sign_in_page(language)
        else:
            page = gate_page(language, self._token_whereabouts(), self._refused(language))
        self._send(401, page.encode(), "text/html; charset=utf-8")

    def _refused(self, language: str) -> str:
        """Why the token that came with this request did not open the door, if one did.

        A cookie is scoped by host and not by port: a second console on this
        machine — a test one beside 8787 — overwrites the first one's, and the
        gate reappears with nothing to say why. Now it says.
        """
        say = _words(language)
        if parse_qs(urlparse(self.path).query).get("token"):
            return say("wrong token")
        if self._presented():
            return say(
                "The token this browser kept is not this console's: another console at this "
                "address may have replaced it."
            )
        return ""

    def _language(self) -> str:
        """The language these pages are written in: the file's, else the browser's."""
        return self._configured() or language_of(self.headers.get("Accept-Language") or "")

    def _configured(self) -> str:
        """The language the configuration opens the console in, or "" for none."""
        asked = self.api.config.runner.interface_language()
        return voice.understood(asked) if asked else ""

    def _token_whereabouts(self) -> str:
        """Where this console's token can be read, on this machine, as HTML."""
        configuration = self.api.config
        if configuration.web.token:
            say = _words(self._language())
            kept = config_module.secrets_path(configuration.path)
            if config_module.read_secrets(kept).get("PONOS_WEB_TOKEN", "").strip():
                return say("<code>PONOS_WEB_TOKEN</code> of <code>{path}</code>").format(
                    path=html.escape(str(kept))
                )
            return say("the <code>PONOS_WEB_TOKEN</code> environment variable")
        return f"<code>{html.escape(str(state_dir() / 'web' / 'token'))}</code>"

    def _stream(self, since: str = "", board: bool = False) -> None:
        """One Server-Sent Events connection, for as long as the tab is open.

        Where to resume from comes as the header a browser sends when it
        reconnects on its own, or as `?after=` from a console that had to open
        the stream again itself — a refused stream is never retried by the
        browser, and a new `EventSource` cannot set a header. `?board=1` is a
        console whose board no longer follows from the changes it was sent,
        asking for it whole.
        """
        try:
            after = int(self.headers.get("Last-Event-ID") or since or 0)
        except ValueError:
            after = 0
        channel = self.api.hub.subscribe(after, board)
        self.api.watch.ensure_running()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            # No length and no chunking: the stream ends when the socket does,
            # so the connection has to be announced as closing. EventSource
            # reconnects on its own — with the last id it saw, which is the
            # whole reason the events are numbered.
            self.send_header("Connection", "close")
            self.close_connection = True
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = channel.get(timeout=15)
                except queue.Empty:
                    # A comment, not an event: it keeps the connection from
                    # being reaped by anything in between, and tells the browser
                    # nothing happened.
                    self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(vault.mask(event.encode()).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the tab was closed, which is the normal way this ends
        finally:
            self.api.hub.unsubscribe(channel)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()


# -- the pages a browser sees before it is in ---------------------------

# The palette, the card, the field and the button are the console's own — Hermez's
# stone and orange, the values of `frontend/src/tokens.css` and the shapes of its
# shadcn `Card`, `Input` and `Button` — copied rather than linked, because the
# bundle is behind this door. Dark unless this browser chose light in the console:
# the same line of `localStorage` its `index.html` reads before the first paint,
# so the door and the room behind it are the same colour.
_STYLE = """<style>
 :root{--background:#fafaf9;--foreground:#1c1917;--card:#fff;--field:#f5f5f4;--border:#e7e5e4;
       --muted-foreground:#57534e;--primary:#bf4a02;--primary-foreground:#fff;--ring:#e46212;
       --destructive:#cc2020;--shadow:0 1px 2px 0 rgb(28 25 23/.064);color-scheme:light}
 .dark{--background:#0c0a09;--foreground:#fafaf9;--card:#1c1917;--field:#221f1d;--border:#fafaf91c;
       --muted-foreground:#a8a29e;--primary:#ff8b44;--primary-foreground:#1c1917;--ring:#e46212;
       --destructive:#f87171;--shadow:0 1px 2px 0 rgb(0 0 0/.32);color-scheme:dark}
 body{background:var(--background);color:var(--foreground);margin:0;display:grid;place-items:center;min-height:100vh;
      font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
      -webkit-font-smoothing:antialiased}
 form{box-sizing:border-box;width:min(26rem,92vw);background:var(--card);border:1px solid var(--border);
      border-radius:1.05rem;padding:1.5rem;box-shadow:var(--shadow)}
 h1{font:800 1.25rem/1.2 "Bricolage Grotesque Variable","Bricolage Grotesque",ui-sans-serif,system-ui,sans-serif;
    letter-spacing:-.025em;margin:0 0 .375rem}
 p{color:var(--muted-foreground);margin:0 0 1.25rem;font-size:.875rem}
 label{display:block;font-size:.875rem;font-weight:500;margin:1rem 0 .375rem}
 input{width:100%;box-sizing:border-box;height:2.25rem;background:var(--field);border:1px solid var(--border);
       color:inherit;border-radius:.6rem;padding:.25rem .75rem;font:inherit;outline:none}
 input:focus-visible{background:var(--background);border-color:var(--ring);box-shadow:0 0 0 3px rgb(228 98 18/.5)}
 button:focus-visible,a:focus-visible{outline:none;box-shadow:0 0 0 3px rgb(228 98 18/.5)}
 button{margin-top:1.25rem;width:100%;height:2.25rem;background:var(--primary);color:var(--primary-foreground);
        border:0;border-radius:.6rem;padding:0 1rem;font:inherit;font-weight:500;cursor:pointer}
 button:hover{opacity:.9}
 code{background:var(--field);padding:.1rem .35rem;border-radius:.45rem;color:var(--foreground);
      font:.8125rem ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
 .said{color:var(--destructive);margin:.9rem 0 0;min-height:1.2em}
</style>
"""

# Before the first paint, as the console's `index.html` does it: dark, unless the
# console was switched to light in this browser.
_THEME = (
    "<script>try{document.documentElement.classList.toggle('dark',"
    "localStorage.getItem('ponos-theme')!=='light')}catch(e){}</script>\n"
)

# What these pages say, in the two languages the console speaks. The key is
# the English, as it is in `frontend/src/lib/french.ts`: a sentence nobody
# translated is drawn as it was written rather than as a name.
_FRENCH = {
    "token": "jeton",
    "sign in": "connexion",
    "Token": "Jeton",
    "Email": "E-mail",
    "Password": "Mot de passe",
    "Open the console": "Ouvrir la console",
    "Sign in to open the console.": "Connectez-vous pour ouvrir la console.",
    "wrong email or password": "e-mail ou mot de passe incorrect",
    "This console needs its token. <code>ponos serve --print-token</code> prints it, "
    "and it is kept in {where}.":
        "Cette console demande son jeton. <code>ponos serve --print-token</code> "
        "l'affiche, et il est gardé dans {where}.",
    "<code>PONOS_WEB_TOKEN</code> of <code>{path}</code>":
        "le <code>PONOS_WEB_TOKEN</code> de <code>{path}</code>",
    "the <code>PONOS_WEB_TOKEN</code> environment variable":
        "la variable d'environnement <code>PONOS_WEB_TOKEN</code>",
    "The token this browser kept is not this console's: another console at this "
    "address may have replaced it.":
        "Le jeton gardé par ce navigateur n'est pas celui de cette console : une autre "
        "console à la même adresse l'a peut-être remplacé.",
    "connect": "connecter",
    "<strong>{client}</strong> asks to reach this Ponos.": "<strong>{client}</strong> demande l'accès à ce Ponos.",
    "Read the tasks, the projects, the ideas and what the runner is doing":
        "Lire les tâches, les projets, les idées et ce que fait le runner",
    "Write: create tasks, answer the blocked ones, sort the ideas":
        "Écrire : créer des tâches, répondre aux tâches bloquées, trier les idées",
    "No tool runs a command, starts a session on the spot, changes the settings or deletes anything.":
        "Aucun outil ne lance de commande, ne démarre de session sur-le-champ, ne modifie les "
        "réglages ni ne supprime quoi que ce soit.",
    "Allow": "Autoriser",
    "Refuse": "Refuser",
    "wrong token": "jeton incorrect",
    "This console has not been set up yet.": "Cette console n'est pas encore configurée.",
}


def language_of(header: str) -> str:
    """The language a browser reads, from its `Accept-Language`.

    The console decides the same way — the browser's own list, in its order —
    and these pages have to agree with it: a sign-in in English opening onto a
    board in French reads as two products. The first tag that is one of the two
    spoken here wins; `voice.understood` reads it, as it reads the file's.
    """
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip()
        if tag.split("-")[0].lower() in voice.LANGUAGES:
            return voice.understood(tag)
    return voice.DEFAULT


def configured(page: bytes, language: str) -> bytes:
    """The console's page, carrying the language the configuration opens it in.

    Written into the page rather than asked for over the API, because the
    console picks its language before it draws anything — a first paint in
    English, redrawn in French a request later, is the flash this avoids. An
    attribute on `<html>`, read by `frontend/src/lib/i18n.ts`, and only as a
    default: a language somebody picked in the select stays theirs.
    """
    if not language:
        return page
    return re.sub(rb"<html\b", f'<html data-language="{language}"'.encode(), page, count=1)


def _words(language: str):
    table = _FRENCH if language == "fr" else {}
    return lambda text: table.get(text, text)


def _page(title: str, body: str, style: str = "", language: str = "en") -> str:
    """The way in, drawn by this server rather than by the bundle.

    A browser that has not got in cannot load the console, so these two pages
    are the only HTML written in Python — the first connection is the
    exception, drawn by the bundle, which is served to a console nobody has
    claimed — and, like everything else served
    here, they reach for nothing that is not on this machine.
    """
    return (
        f'<!doctype html>\n<html lang="{language}" class="dark">\n<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{html.escape(title)} · Ponos</title>\n" + _THEME + _STYLE + style + body
    )


def gate_page(language: str = "en", where: str = "", said: str = "") -> str:
    """Asked for the token — and told where to find it, as this machine has it.

    `where` is the real place: the `PONOS_WEB_TOKEN` line of the `secrets.env`
    in use, or the environment, when the token was chosen; else the file it was
    drawn into — under `$XDG_STATE_HOME` when that is set, which a path printed
    as a constant got wrong on every machine that sets it. `said` is why a token
    that was offered did not open the door, already in the page's language.
    """
    say = _words(language)
    where = where or f"<code>{html.escape(str(state_dir() / 'web' / 'token'))}</code>"
    return _page(
        say("token"),
        f"""<form onsubmit="location='/?token='+encodeURIComponent(this.t.value.trim());return false">
  <h1>Ponos</h1>
  <p>{say("This console needs its token. <code>ponos serve --print-token</code> prints it, "
          "and it is kept in {where}.").format(where=where)}</p>
  <label for="t">{say("Token")}</label>
  <input id="t" name="t" autofocus autocomplete="off" spellcheck="false">
  <button type="submit">{say("Open the console")}</button>
  <p class="said" role="alert">{html.escape(said, quote=False)}</p>
</form>
""",
        language=language,
    )


def sign_in_page(language: str = "en") -> str:
    """The same door, with a lock somebody can remember.

    It posts rather than navigates — a form that navigated could not set the
    header that tells a request from the console apart from a request from a
    page you had open.
    """
    say = _words(language)
    return _page(
        say("sign in"),
        f"""<form onsubmit="enter(this);return false">
  <h1>Ponos</h1>
  <p>{say("Sign in to open the console.")}</p>
  <label for="email">{say("Email")}</label>
  <input id="email" name="email" type="email" autofocus autocomplete="username" spellcheck="false">
  <label for="password">{say("Password")}</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">{say("Open the console")}</button>
  <p class="said" id="said" role="alert"></p>
</form>
<script>
const WRONG = {json.dumps(say("wrong email or password"), ensure_ascii=False)};
async function enter(form){{
  const said = document.getElementById('said');
  said.textContent = '';
  try {{
    const answer = await fetch('/api/login', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json', '{GUARD_HEADER}': '1'}},
      body: JSON.stringify({{email: form.email.value, password: form.password.value}}),
    }});
    if (answer.ok) {{ location = '/'; return; }}
    const body = await answer.json().catch(() => ({{}}));
    said.textContent = answer.status === 401 ? WRONG : (body.error || WRONG);
  }} catch (error) {{
    said.textContent = String(error);
  }}
}}
</script>
""",
        language=language,
    )


def consent_page(language: str, request, params: dict[str, str], needs: str, said: str = "") -> str:
    """Which client asks for what, and the door to sign in by when the browser is out.

    The request travels in hidden fields rather than in a server-side session:
    it is checked again in full when the form comes back, so what a browser
    changes in it is only ever another request, checked like the first.
    `needs` is `password`, `token`, or empty for a browser already in.
    """
    say = _words(language)
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(params.get(name, ""))}">'
        for name in (
            "response_type", "client_id", "redirect_uri", "code_challenge",
            "code_challenge_method", "scope", "state", "resource",
        )
        if params.get(name)
    )
    write = (
        f'<label class="scope"><input type="checkbox" name="write" value="1" checked> '
        f'{say("Write: create tasks, answer the blocked ones, sort the ideas")}</label>'
        if oauth.WRITE in request.scopes
        else ""
    )
    if needs == "password":
        door = (
            f'<label for="email">{say("Email")}</label>'
            '<input id="email" name="email" type="email" autocomplete="username" spellcheck="false" required>'
            f'<label for="password">{say("Password")}</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password" required>'
        )
    elif needs == "token":
        door = (
            f'<label for="token">{say("Token")}</label>'
            '<input id="token" name="token" autocomplete="off" spellcheck="false" required>'
        )
    else:
        door = ""
    client = html.escape(request.client.name)
    return _page(
        say("connect"),
        f"""<form method="post" action="/oauth/authorize">
  <h1>Ponos</h1>
  <p>{say("<strong>{client}</strong> asks to reach this Ponos.").format(client=client)}</p>
  {hidden}
  <label class="scope"><input type="checkbox" checked disabled> {say("Read the tasks, the projects, the ideas and what the runner is doing")}</label>
  {write}
  <p>{say("No tool runs a command, starts a session on the spot, changes the settings or deletes anything.")}</p>
  {door}
  <p class="said" role="alert">{html.escape(said)}</p>
  <button type="submit" name="decision" value="allow">{say("Allow")}</button>
  <button type="submit" name="decision" value="deny" class="quiet" formnovalidate>{say("Refuse")}</button>
</form>
""",
        # Every page here is served `no-referrer`, and a form posted under that
        # policy says `Origin: null` — which `_consent` would refuse as a page
        # from elsewhere. This one says where it is from, to itself alone.
        style='<meta name="referrer" content="same-origin">\n'
        "<style>.scope{display:flex;gap:.5rem;align-items:baseline;font-weight:400}"
        ".scope input{width:auto;height:auto}.quiet{background:transparent;color:var(--muted-foreground);margin-top:.4rem}</style>\n",
        language=language,
    )


def consent_refused(language: str, why: str) -> str:
    """A request the consent page cannot even show: said, and sent nowhere."""
    say = _words(language)
    return _page(
        say("connect"),
        f"<form><h1>Ponos</h1><p class=\"said\">{html.escape(say(why))}</p></form>\n",
        language=language,
    )


# The English pages, as they stand: what a test reads, and what a browser that
# says nothing about its language is given.
GATE = gate_page()
SIGN_IN = sign_in_page()


def serve(
    config: Config,
    *,
    host: str = "",
    port: int = 0,
    announce: bool = True,
) -> int:
    """Run the console until interrupted. Returns a process exit code."""
    host = host or config.web.host
    port = port or config.web.port
    secret = token(config)
    entry = sign_in(config, secret)

    # In a container the console listens to a network by nature — Docker's, and
    # behind it Traefik's — and what guards a console nobody has claimed there is
    # the installation code drawn below. Everywhere else, as it always was.
    if host not in LOOPBACK and not config.web.token and entry is None and not config_module.in_container():
        print(
            f"refusing to listen on {host}: behind this port sits a runner that starts\n"
            "Claude Code sessions with bypassPermissions, and a generated token is not a\n"
            "decision you took. Either keep the default 127.0.0.1 and reach it over ssh\n"
            "  ssh -L 8787:127.0.0.1:8787 <this machine>\n"
            "or say so on purpose: web.token, or web.email and web.password."
        )
        return 2

    # What to print as the way in. A console with a sign-in is opened by typing
    # an address, which is the whole point of having one — putting the token
    # back in that line would be telling you to paste a secret anyway. And one
    # nobody has claimed is opened by the address alone: the first connection is
    # what it serves, and asking for a token to reach it would be the circle
    # that page exists to break.
    def opening(address: str) -> str:
        if entry:
            return f"{address}  —  sign in as {entry.email}"
        if claimable(config, entry):
            return f"{address}  —  not set up yet: the first browser to open it sets its password"
        return f"{address}/?token={secret}"

    # Drawn once per start, and only while nobody has claimed the console: it is
    # what a first connection from anywhere but this machine has to give.
    code = installation_code() if claimable(config, entry) else ""

    api = Api(config)
    try:
        server = Console((host, port), Handler, api, secret, entry, code)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            # The console's unit starts with the machine, so a taken port is the
            # ordinary answer to `serve` rather than a failure: somebody typing
            # it wants the console, and the one already listening is it.
            print(f"already listening on http://{host}:{port} — the console is running")
            print(f"  open  {opening(f'http://{host}:{port}')}")
            print("  stop  systemctl --user stop ponos-web")
            return 0
        print(f"cannot listen on {host}:{port} — {error}")
        return 1

    address = server.server_address
    shown = f"http://{address[0]}:{address[1]}"
    if announce:
        print(f"Ponos console on {shown}")
        print(f"  open  {opening(shown)}")
        if code:
            print(f"  code  {code}  —  asked by the first connection from anywhere but this machine")
        print(f"  stop  Ctrl-C\n", flush=True)

    thread = threading.Thread(target=server.serve_forever, name="tr-console", daemon=True)
    thread.start()
    api.upgrade.watch()
    try:
        while thread.is_alive():
            thread.join(1)
    except KeyboardInterrupt:
        if announce:
            print("\nstopping")
    finally:
        api.watch.stop()
        server.shutdown()
        server.server_close()
    return 0
