"""The console as an application: FastAPI, served by uvicorn, behind one guard.

Until October 2026 this was `http.server` and nothing else — the regular
expressions that routed, the stream, the guard and the headers written by hand
— because a tool whose claim was "no dependency to install" did not get to grow
a web framework the day it grew a web page. Each installed version has had an
environment of its own since (`environment.py`), and the console is what the
first packages came in for: FastAPI reads what a write carries and describes
every route in an OpenAPI schema (`/openapi.json`), which the page's types are
to come from; uvicorn serves it. The runner — the timer's passes — imports none
of it, and neither does `server.py`, which says why.

The door is `Guard`, one middleware in front of the whole application: a route
is behind it by being a route — the schema with the rest — and nothing has to
remember to ask. What it checks is what `server.py` describes. The API's routes
are in `routes.py`; the doors around them — the pages, the stream, the first
connection, the MCP server and its keys — are here.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hmac
import html
import json
import logging
import mimetypes
import queue
import re
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlparse

import uvicorn
from anyio import CapacityLimiter, from_thread, to_thread
from fastapi import APIRouter, Body, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .. import __version__, db, openrouter, tailscale, vault, voice
from .. import config as config_module
from ..config import state_dir
from . import answers, attachments, attempts, github, mcp, oauth, routes, server, sessions, setup
from .api import Api
from .routes import MAX_BODY, answer, fail
from .server import (
    COMPRESSIBLE,
    COOKIE,
    FORWARDED,
    GUARD_HEADER,
    HSTS,
    IMMUTABLE,
    LEGACY_COOKIE,
    LOCKED_POLICY,
    LOOPBACK,
    PERMISSIONS,
    TOKEN_COOKIE_AGE,
    WORKER_POLICY,
    SignIn,
    _compressed,
    _words,
    accepts_gzip,
    claimable,
    configured,
    consent_page,
    consent_refused,
    gate_page,
    landing,
    language_of,
    page_policy,
    same_code,
    sign_in,
    sign_in_page,
)

logger = logging.getLogger(__name__)


class Console:
    """One console: what its doors are checked against, and the server behind them.

    What the `http.server` object used to carry — the API, the token, the
    sign-in, the installation code, the count of attempts — is kept here, and
    the application reads it from `app.state.console`. The socket is bound
    here, before uvicorn is handed it, so that a port already taken is said by
    `serve` as it always was, and a test can ask for port 0 and read which one
    it got.
    """

    def __init__(
        self,
        address: tuple[str, int],
        api: Api,
        secret: str,
        entry: SignIn | None = None,
        code: str = "",
    ) -> None:
        self.api = api
        self.secret = secret
        self.entry = entry
        # What a first connection from outside this machine has to say first.
        # Empty: none was drawn, and such a connection is refused outright.
        self.code = code
        # Who got the door wrong lately — see `attempts`.
        self.attempts = attempts.Attempts()
        host, port = address
        self.socket = socket.create_server(
            (host.strip("[]"), port),
            family=socket.AF_INET6 if ":" in host else socket.AF_INET,
            # A burst — a browser opening its six connections while a script
            # guesses — is answered by the 429 that says to wait, not by a reset.
            backlog=64,
        )
        self.server_address: tuple[str, int] = self.socket.getsockname()[:2]
        self.app = application(self)
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                lifespan="off",
                http="h11",
                ws="none",
                # A console is not a web server; its log is the terminal it runs in.
                access_log=False,
                log_level="warning",
                server_header=False,
                # `X-Forwarded-For` is read by the guard, which decides what a
                # proxy is to be trusted with — uvicorn must not rewrite the
                # address first: a request through Traefik would look local.
                proxy_headers=False,
                # A stream stays open for as long as its tab: stopping does not
                # wait for every tab to close.
                timeout_graceful_shutdown=2,
            )
        )
        self.streams: CapacityLimiter | None = None
        self._stopped = threading.Event()
        self._serving = False

    def serve_forever(self) -> None:
        """Answer until `shutdown`, or a signal in the main thread."""

        async def serving() -> None:
            # A request is answered on a thread of its own while the `Api`
            # waits on Notion, git or a process — as `http.server` answered
            # every one: more of them than anyio's forty, so that a few slow
            # reads do not hold up a page opening.
            to_thread.current_default_thread_limiter().total_tokens = THREADS
            self.streams = CapacityLimiter(STREAMS)
            await self.server.serve(sockets=[self.socket])

        self._serving = True
        try:
            asyncio.run(serving())
        finally:
            self._stopped.set()

    def shutdown(self) -> None:
        self.server.should_exit = True
        if self._serving:
            self._stopped.wait(10)

    def server_close(self) -> None:
        self.socket.close()


# Threads for the routes, which wait on the board; and for the streams, which
# each wait on their channel in a thread of their own, never in the routes' pool.
THREADS = 100
STREAMS = 1000


def is_local(address: str) -> bool:
    """`address` is this machine's — loopback, as IPv4, IPv6 or IPv4 in IPv6."""
    return address in ("127.0.0.1", "::1") or address.startswith(("127.", "::ffff:127."))


class Asking:
    """Who sent one request, and with what: the questions the guard asks of it."""

    def __init__(self, request: Request, console: Console) -> None:
        self.request = request
        self.headers = request.headers
        self.console = console
        self.api = console.api
        # The session cookie given again with the answer, when it is a day old.
        self.renewed = ""
        # How long this address has to wait, when it got the door wrong too often.
        self.throttled = 0.0
        # The token or a sign-in came with it — what `/api/setup` tells the page.
        self.signed_in = False

    def host_is_ours(self) -> bool:
        """The `Host` header names the address this console is served on.

        Without this, any web page could point a domain of its own at 127.0.0.1
        and have your browser talk to the console as if it were the console.
        """
        configured = self.api.config.web.host
        bound = str(self.console.server_address[0])
        if configured not in LOOPBACK or bound not in LOOPBACK:
            # A wider bind was asked for on purpose, and is reached under a name
            # or address this process cannot enumerate — a LAN IP, a tailnet
            # name, whatever the tunnel calls it. The token is the guard there;
            # this check exists for the loopback case, which is the one a page
            # in another tab can actually reach.
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        expected = {"127.0.0.1", "::1", "localhost", bound, configured}
        # `tailscale serve` or an ssh-free tunnel relays to loopback and keeps the
        # name it was reached under: the one `web.url` says, and that one only.
        if self.api.config.web.url:
            expected.add(urlparse(self.api.config.web.url).hostname or "")
        try:
            expected.add(socket.gethostname())
        except OSError:
            pass
        return host in expected

    def funnel_allows(self, route: str) -> bool:
        """A request that came through Tailscale Funnel reaches the MCP doors only.

        Funnel is the public Internet: the MCP endpoint is meant to be there, the
        console is not. `ponos tailscale` publishes those paths and no others, and
        this is the second lock, for a route somebody added by hand. The header
        is Funnel's to set — it overwrites whatever the caller sent.
        """
        if not self.headers.get(tailscale.FUNNEL_HEADER):
            return True
        return tailscale.funnel_allowed(route)

    def local(self) -> bool:
        """The request comes from this machine — not only to an address of it."""
        client = self.request.client
        return is_local(str(client.host) if client else "")

    def outside(self) -> bool:
        """Not somebody at this machine: another address, or through a proxy."""
        return not self.local() or any(self.headers.get(name) for name in FORWARDED)

    def secure(self) -> bool:
        """The browser reached the proxy in front of this console over HTTPS.

        The console itself only ever speaks plain HTTP; what is encrypted is the
        leg between the browser and Traefik, and the proxy says so in this header.
        A browser that came in over HTTPS must never send the cookie back over
        anything else.
        """
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0]
        return proto.strip().lower() == "https"

    def cookie(self, value: str, age: int = TOKEN_COOKIE_AGE) -> str:
        """The `Set-Cookie` of a way in — the token's, or a sign-in's session."""
        secure = "; Secure" if self.secure() else ""
        return f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{secure}"

    def knocker(self) -> str:
        """Who the attempts are counted against — see `attempts.address_of`."""
        client = self.request.client
        return attempts.address_of(
            str(client.host) if client else "", self.headers.get("X-Forwarded-For") or ""
        )

    def same_origin(self) -> bool:
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

    def presented(self) -> str:
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

    def authorised(self, typed: str = "") -> bool:
        """The token, or the cookie a sign-in left. Either is this console's.

        `typed` is the token of the address (`?token=`). The token does not go
        away when an email and a password are set: it is what a script, the dev
        server's proxy and `--print-token` carry. What changes is that a person
        no longer has to.
        """
        self.renewed = ""
        offered = typed or self.presented()
        if not offered:
            return False
        # A token typed into the address or set in a header is an attempt, and
        # counted; the cookie is what this console gave, and a stale one — a
        # neighbouring console's — is no guess. While the address waits, an
        # attempt is not even looked at.
        attempt = bool(typed) or self.explicit()
        knocker = self.knocker()
        if attempt and (wait := self.console.attempts.waiting(knocker)):
            self.throttled = wait
            return False
        # Compared as bytes: `compare_digest` refuses two strings when either
        # holds a character outside ASCII, and what is offered here came from a
        # browser — a cookie somebody pasted an accent into would be a 500
        # rather than the "no" it is.
        if hmac.compare_digest(offered.encode(), self.console.secret.encode()):
            return True
        entry = self.console.entry
        if entry and (given := entry.holds(offered)) is not None:
            # Thirty days from the last time it was used: renewed, a day at most
            # after it was given, by whatever this request is answered with.
            if time.time() - given > sessions.RENEW_AFTER:
                self.renewed = entry.session()
            return True
        if attempt:
            self.console.attempts.failed(knocker)
        return False

    def explicit(self) -> bool:
        """The request carries a token of its own, rather than the console's cookie."""
        header = self.headers.get("Authorization") or ""
        return header.lower().startswith("bearer ") or bool(self.headers.get("X-Token"))

    def base(self) -> str:
        """The address this console is reached at, as the client reached it.

        Read from the request: behind Traefik it is the domain and HTTPS the
        proxy says it served, on this machine it is the loopback address — and
        the metadata a client reads has to name the one it used. `web.url`
        when it is set and the request did not come by loopback: a proxy or a
        tunnel that says nothing of HTTPS is the case it is for, and Claude
        Code on this machine still reads the address it typed.
        """
        scheme = "https" if self.secure() else "http"
        forwarded = (self.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        host = forwarded or (self.headers.get("Host") or "").strip()
        configured = self.api.config.web.url
        if configured and host.rsplit(":", 1)[0].strip("[]") not in LOOPBACK:
            return configured
        if not host:
            address = self.console.server_address
            host = f"{address[0]}:{address[1]}"
        return f"{scheme}://{host}"

    def loopback(self) -> str:
        """This console as a client on this machine reaches it: the port it listens on."""
        host, port = self.console.server_address[:2]
        if host in ("0.0.0.0", "::", "", "::1") or host.startswith("127."):
            host = "127.0.0.1"
        return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"

    def language(self) -> str:
        """The language these pages are written in: the file's, else the browser's."""
        return self.configured() or language_of(self.headers.get("Accept-Language") or "")

    def configured(self) -> str:
        """The language the configuration opens the console in, or "" for none."""
        asked = self.api.config.runner.interface_language()
        return voice.understood(asked) if asked else ""


def _asking(request: Request) -> Asking:
    asking: Asking = request.state.asking
    return asking


def _console(request: Request) -> Console:
    console: Console = request.app.state.console
    return console


def _send(
    code: int, body: bytes, kind: str, extra: dict[str, str] | None = None, cache: str = "no-store"
) -> Response:
    """An answer that is not the API's JSON — a page, a file, a redirect.

    What every answer carries besides — `nosniff`, no framing, the browser's
    powers it never needs — is added by the guard on the way out; a page's
    Content-Security-Policy is hashed here, from the page.
    """
    headers = {"Cache-Control": cache}
    if kind.startswith("text/html") and "Content-Security-Policy" not in (extra or {}):
        headers["Content-Security-Policy"] = page_policy(body)
    headers.update(extra or {})
    return Response(body, status_code=code, headers=headers, media_type=kind)


def _too_many(wait: float) -> Response:
    """Refused unseen: this address got the door wrong too often, too recently."""
    seconds = max(1, int(wait + 0.999))
    return Response(
        json.dumps({"error": f"too many attempts — try again in {seconds} s"}).encode(),
        status_code=429,
        media_type="application/json",
        headers={"Retry-After": str(seconds)},
    )


# The doors that carry keys of their own, or none: the MCP server and its
# authorisation server, GitHub's two ways back — which come without the cookie,
# see web/github.py — and what makes the console installable, which the browser
# fetches for itself: the same files for everybody, holding no secret.
OPEN_READS = (
    "/healthz",
    "/mcp",
    "/oauth/authorize",
    "/api/github/manifest/callback",
    "/api/github/installed",
    "/sw.js",
    "/static/manifest.webmanifest",
    "/static/offline.html",
)
OPEN_WRITES = ("/mcp", "/oauth/register", "/oauth/token", "/oauth/authorize")

# What every answer carries, unless it says otherwise. Nothing here is meant to
# be cached, framed, sniffed or embedded — but a picture, whose address changes
# with it, and is kept a day, and the build's own files, whose names change with
# them. No window of another site keeps a hand on one of the console's, and no
# page elsewhere embeds what it answers.
DRESS = (
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "no-referrer"),
    ("permissions-policy", PERMISSIONS),
    ("cross-origin-opener-policy", "same-origin"),
    ("cross-origin-resource-policy", "same-origin"),
    ("content-security-policy", LOCKED_POLICY),
)


class Guard:
    """The door every request goes through before it reaches a route.

    In front of the whole application, OpenAPI's schema included: a route is
    behind it by being a route, and nothing has to remember to ask. What it
    lets through carries an `Asking` (`request.state.asking`) — who sent it,
    and with what — and whatever the route answers leaves dressed in the
    headers `DRESS` lists, the HSTS a proxy over HTTPS earns, and the renewed
    session cookie when one is due.

    Written for ASGI directly rather than as `BaseHTTPMiddleware`, which would
    hold up the stream of `/api/events` behind it.
    """

    def __init__(self, app: ASGIApp, console: Console) -> None:
        self.app = app
        self.console = console

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # A HEAD is the GET without its body, as it always was; and a route is
        # the same route with a slash at the end.
        head = scope["method"] == "HEAD"
        scope = {
            **scope,
            "method": "GET" if head else scope["method"],
            "path": scope["path"].rstrip("/") or "/",
        }
        asking = Asking(Request(scope), self.console)
        scope["state"] = {**scope.get("state", {}), "asking": asking}
        dressed = self._dressed(send, asking, head)
        refused = self._refused(scope, asking)
        if refused is not None:
            if scope["method"] != "GET":
                # Its body left unread: the connection is not one to read the
                # next request from — a signed-out page reloading itself got a
                # 501 for "{}GET" once.
                refused.headers["Connection"] = "close"
            await refused(scope, receive, dressed)
            return
        await self.app(scope, receive, dressed)

    def _refused(self, scope: Scope, asking: Asking) -> Response | None:
        """What answers in the route's place — or None, and the route answers."""
        route = scope["path"]
        reading = scope["method"] == "GET"
        if not asking.host_is_ours():
            return fail(421, "this console is not served under that name")
        if not asking.funnel_allows(route):
            return fail(404, "no such route")
        if reading and (route in OPEN_READS or route.startswith(("/.well-known/", "/static/pwa/"))):
            return None
        if not reading and route in OPEN_WRITES:
            return None
        # Two writes cannot be authorised beforehand, because they are what
        # produces the authorisation: signing in, and — on a console nobody has
        # claimed — the first connection that gives it a password to sign in
        # with. Everything else about them holds: the name they are reached
        # under, and the header below.
        opening = not reading and route in ("/api/login", "/api/setup")
        typed = asking.request.query_params.get("token", "")
        if not opening:
            asking.signed_in = asking.authorised(typed)
            if not asking.signed_in:
                if asking.throttled:
                    return _too_many(asking.throttled)
                if not reading:
                    return fail(401, "token missing or wrong")
                return self._unauthorised(route, asking)
        if not reading:
            # A cookie alone is not consent: a page you have open elsewhere can
            # post a form to this port with your cookie attached, but it cannot
            # set a header of its own without a preflight this server never
            # answers.
            if asking.headers.get(GUARD_HEADER) != "1":
                return fail(403, "this request did not come from the console")
            return None
        # The token arrived in the URL: put it in a cookie and get it out of the
        # address bar, where it would otherwise sit in the history and in every
        # screenshot of the console. The token, and nothing else: the rest of
        # the address says *where* — `?token=…&view=console/projects/list` is
        # how a deep link is shared — and a redirect to a bare `/` would strip
        # the destination along with the secret and land on the board.
        if typed and route == "/":
            return _send(
                303,
                b"",
                "text/plain",
                {
                    "Location": landing(scope["query_string"].decode("latin-1")),
                    "Set-Cookie": asking.cookie(typed),
                },
            )
        return None

    def _unauthorised(self, route: str, asking: Asking) -> Response | None:
        # An unclaimed console is drawn by the bundle, which is no secret: it is
        # the same files for everybody, and what it asks first is the code, the
        # email and the password.
        claim = claimable(self.console.api.config, self.console.entry)
        if claim and (route.startswith("/static/") or route == "/api/setup"):
            return None
        if route.startswith("/api/") or route == "/openapi.json":
            return fail(401, "token missing or wrong")
        language = asking.language()
        if claim:
            return _static(asking, "index.html", setup="claim")
        if self.console.entry:
            page = sign_in_page(language)
        else:
            page = gate_page(language, _token_whereabouts(asking), _refused(asking, language))
        return _send(401, page.encode(), "text/html; charset=utf-8")

    @staticmethod
    def _dressed(send: Send, asking: Asking, head: bool) -> Send:
        async def dressed(message: Message) -> None:
            if message["type"] == "http.response.start":
                _journal(asking.request, message["status"])
                headers = MutableHeaders(scope=message)
                for name, value in DRESS:
                    if name not in headers:
                        headers[name] = value
                if asking.secure():
                    headers["strict-transport-security"] = HSTS
                if asking.renewed and "set-cookie" not in headers:
                    headers["set-cookie"] = asking.cookie(asking.renewed, sessions.LIFETIME)
            elif message["type"] == "http.response.body" and head:
                message = {**message, "body": b""}
            await send(message)

        return dressed


def _journal(request: Request, status: int) -> None:
    """A request that went wrong, into the journal: the 2xx and 3xx are no news.

    The path without its query: `?token=…` is how a console is opened.
    """
    if status < 400:
        return
    (logger.error if status >= 500 else logger.warning)(
        "console: %s %s → %d", request.method, request.url.path, status
    )


def _refused(asking: Asking, language: str) -> str:
    """Why the token that came with this request did not open the door, if one did.

    A cookie is scoped by host and not by port: a second console on this
    machine — a test one beside 8787 — overwrites the first one's, and the
    gate reappears with nothing to say why. Now it says.
    """
    say: Callable[[str], str] = _words(language)
    if asking.request.query_params.get("token"):
        return say("wrong token")
    if asking.presented():
        return say(
            "The token this browser kept is not this console's: another console at this "
            "address may have replaced it."
        )
    return ""


def _token_whereabouts(asking: Asking) -> str:
    """Where this console's token can be read, on this machine, as HTML."""
    configuration = asking.api.config
    if configuration.web.token:
        say: Callable[[str], str] = _words(asking.language())
        kept = config_module.secrets_path(configuration.path)
        if config_module.read_secrets(kept).get("PONOS_WEB_TOKEN", "").strip():
            return say("<code>PONOS_WEB_TOKEN</code> of <code>{path}</code>").format(
                path=html.escape(str(kept))
            )
        return say("the <code>PONOS_WEB_TOKEN</code> environment variable")
    return f"<code>{html.escape(str(state_dir() / 'web' / 'token'))}</code>"


def _static(asking: Asking, name: str, setup: str = "") -> Response:
    # Read from `server` at each request, where a test may point it elsewhere.
    folder = server.STATIC
    target = (folder / name).resolve()
    # `is_relative_to`, not a prefix: `static-old/` begins with `static` too.
    if not target.is_relative_to(folder) or not target.is_file():
        return fail(404, f"no such file: {name}")
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    body = target.read_bytes()
    marked = ""
    if name == "index.html":
        marked = asking.configured()
        body = configured(body, marked)
        if setup:
            # What the page draws instead of the console: see `main.tsx`.
            body = re.sub(rb"<html\b", f'<html data-setup="{setup}"'.encode(), body, count=1)
            marked = f"{marked}:{setup}"
    extra: dict[str, str] = {}
    # Hashed from the page as it is, before it is compressed: see `page_policy`.
    if kind == "text/html":
        extra["Content-Security-Policy"] = page_policy(body, bundle=name == "index.html")
    elif name == "sw.js":
        extra["Content-Security-Policy"] = WORKER_POLICY
    if kind.startswith(COMPRESSIBLE):
        extra["Vary"] = "Accept-Encoding"
        if accepts_gzip(asking.headers.get("Accept-Encoding") or ""):
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
    return _send(200, body, kind, extra, cache=cache)


def _read(request: Request) -> bytes | None:
    """The body as it came — None when it is larger than any of ours.

    For a route that runs on a thread of its own, as every route here does:
    the body is the event loop's to read, and the thread waits for it.
    """
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        return None
    return from_thread.run(request.body)


class _Body:
    """The body of a request as a file `attachments` copies from — streamed, never held."""

    def __init__(self, request: Request) -> None:
        self._chunks = request.stream()
        self._left = b""

    def read(self, size: int) -> bytes:
        while not self._left:
            try:
                self._left = from_thread.run(self._chunks.__anext__)
            except StopAsyncIteration:
                return b""
        piece, self._left = self._left[:size], self._left[size:]
        return piece


def _described() -> FastAPI:
    """The console's routes — the API's, and the doors around it — and no console yet."""
    app = FastAPI(
        title="Ponos",
        version=__version__,
        # The schema only: the pages that draw it load their scripts from a
        # CDN, which the console's Content-Security-Policy refuses — and the
        # console runs nothing it does not serve itself.
        docs_url=None,
        redoc_url=None,
    )
    app.include_router(routes.router)
    app.include_router(doors)
    return app


def schema() -> dict[str, Any]:
    """The OpenAPI schema, without a console to serve it: what `scripts/openapi.py` writes."""
    return _described().openapi()


def application(console: Console) -> FastAPI:
    """The console's routes, behind its guard."""
    app = _described()
    app.state.console = console
    app.add_middleware(Guard, console=console)

    @app.exception_handler(StarletteHTTPException)
    async def unrouted(request: Request, error: StarletteHTTPException) -> Response:
        # A path no route serves, or serves by another method: there is no such
        # route, as `http.server` said for both.
        if error.status_code in (404, 405):
            return fail(404, f"no such route: {request.url.path}")
        return fail(error.status_code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> Response:
        return routes.refusal(error)

    return app


doors = APIRouter(route_class=routes.Answered)


# -- the console's own doors ---------------------------------------------------


@doors.get("/healthz", include_in_schema=False)
def healthz() -> Response:
    # What a container's healthcheck asks: the console answers. Nothing behind
    # the door — not even whether it was claimed — so no key.
    return answer({"ok": True})


@doors.get("/", include_in_schema=False)
def index(request: Request) -> Response:
    # The bare address of a console with no board yet leads to its first
    # steps, rather than to an empty board.
    if not request.url.query and not _usable(_console(request)):
        return _send(303, b"", "text/plain", {"Location": "/setup"})
    return _static(_asking(request), "index.html")


@doors.get("/setup", include_in_schema=False)
def first_steps(request: Request) -> Response:
    # The steps of the first connection, for somebody already in: a console
    # still unclaimed has a password waiting to be set, one claimed from the
    # environment has everything after it.
    console = _console(request)
    claim = claimable(console.api.config, console.entry)
    return _static(_asking(request), "index.html", setup="claim" if claim else "steps")


@doors.get("/sw.js", include_in_schema=False)
def worker(request: Request) -> Response:
    return _static(_asking(request), "sw.js")


@doors.get("/static/{name:path}", include_in_schema=False)
def static(request: Request, name: str) -> Response:
    return _static(_asking(request), name)


@doors.get("/api/github/manifest/callback", include_in_schema=False)
def github_callback(code: str = "", state: str = "") -> Response:
    status, answered = github.callback(code, state)
    if status == 303:
        return _send(303, b"", "text/plain", {"Location": answered})
    return _send(status, answered.encode(), "text/html; charset=utf-8")


@doors.get("/api/github/installed", include_in_schema=False)
def github_installed(setup_action: str = "") -> Response:
    return _send(200, github.installed(setup_action).encode(), "text/html; charset=utf-8")


def _usable(console: Console) -> bool:
    try:
        console.api.config.require_usable()
    except config_module.ConfigError:
        return False
    return True


# -- signing in, and the first connection ------------------------------------


@doors.post("/api/login")
def login(request: Request, payload: routes.Fields = Body(default_factory=dict)) -> Response:
    """An email and a password against the configured ones. Nothing else."""
    console, asking = _console(request), _asking(request)
    entry = console.entry
    if entry is None:
        return fail(404, "this console is opened with its token")
    # Behind this port sits `bypassPermissions`, and a password is guessable
    # in a way a 32-character token is not: counted before it is checked,
    # and refused unseen while the address waits — see `attempts`.
    knocker = asking.knocker()
    if wait := console.attempts.admit(knocker):
        return _too_many(wait)
    if not entry.opens(str(payload.get("email", "")), str(payload.get("password", ""))):
        return fail(401, "wrong email or password")
    console.attempts.forgive(knocker)
    return _send(
        200,
        b'{"ok": true}',
        "application/json",
        {"Set-Cookie": asking.cookie(entry.session(), sessions.LIFETIME)},
    )


@doors.get("/api/setup")
def setup_state(request: Request) -> Response:
    """What the first connection's page needs before it draws a step."""
    console, asking = _console(request), _asking(request)
    claim = claimable(console.api.config, console.entry)
    return answer(
        {
            "claimed": not claim,
            "signed_in": asking.signed_in,
            "code": claim and asking.outside(),
            "code_drawn": bool(console.code),
            "container": config_module.in_container(),
            "version": __version__,
            "storage": console.api.config.storage.mode,
        }
    )


@doors.post("/api/setup")
def claim(request: Request, payload: routes.Fields = Body(default_factory=dict)) -> Response:
    """The first connection: everything at once, and a way in at the end.

    Signing the browser in rather than sending it back to the door it has
    just built: the password was typed one second ago, and asking for it
    again would be the token all over again. The console keeps its new
    sign-in on the console object, because that is where the way in is read
    from — a restart would find the same one in the file.
    """
    console, asking = _console(request), _asking(request)
    if not claimable(console.api.config, console.entry):
        return fail(404, "this console has already been set up")
    if asking.outside():
        # From outside this machine, the code `serve` printed — or nothing.
        # Compared before anything is written, and counted as a password is:
        # eight letters out of thirty-two are a lot of guesses, and this
        # keeps them that way.
        if not console.code:
            return fail(
                403,
                "the first connection is only offered on this machine, or with the "
                "installation code the console prints when it starts",
            )
        knocker = asking.knocker()
        if wait := console.attempts.admit(knocker):
            return _too_many(wait)
        if not same_code(str(payload.get("code", "")), console.code):
            return fail(403, "wrong installation code")
        console.attempts.forgive(knocker)
    result = setup.apply(console.api, payload)
    entry = sign_in(console.api.config, console.secret)
    if entry is None:  # the write went through and said nothing: refuse to guess
        return fail(500, "the credentials were not written")
    console.entry = entry
    console.code = ""  # used once, and the door is shut anyway
    return _send(
        200,
        json.dumps(result, ensure_ascii=False).encode(),
        "application/json",
        {"Set-Cookie": asking.cookie(entry.session(), sessions.LIFETIME)},
    )


# -- the update --------------------------------------------------------------


def _update(request: Request, cancel: bool) -> Response:
    """Start, or call off, the update the header offers. See `upgrade.py`.

    Answered only to this machine and to the console's own page: of every
    write, this is the one that replaces the code answering it. The body
    says nothing — which version, which command and which directory are
    the server's to know, never the page's.
    """
    asking = _asking(request)
    if not asking.local():
        return fail(403, "an update is started from the machine the runner is on")
    if not asking.same_origin():
        return fail(403, "this request did not come from the console")
    upgrade = _console(request).api.upgrade
    try:
        return answer(upgrade.cancel() if cancel else upgrade.start())
    except RuntimeError as error:
        return fail(409, str(error))


@doors.post("/api/update", response_model=answers.UpgradeProgress)
def update(request: Request) -> Response:
    return _update(request, cancel=False)


@doors.post("/api/update/cancel", response_model=answers.UpgradeProgress)
def cancel_update(request: Request) -> Response:
    return _update(request, cancel=True)


# -- the stream --------------------------------------------------------------


@doors.get("/api/events", response_model=answers.Stream)
async def events(request: Request, after: str = "", board: str = "") -> Response:
    """One Server-Sent Events connection, for as long as the tab is open.

    Where to resume from comes as the header a browser sends when it
    reconnects on its own, or as `?after=` from a console that had to open
    the stream again itself — a refused stream is never retried by the
    browser, and a new `EventSource` cannot set a header. `?board=1` is a
    console whose board no longer follows from the changes it was sent,
    asking for it whole.

    What the schema says it answers, `answers.Stream`, is no body: it is the
    data of each event, under the event's name — for the page's types.
    """
    console = _console(request)
    api = console.api
    try:
        since = int(request.headers.get("Last-Event-ID") or after or 0)
    except ValueError:
        since = 0
    channel = await run_in_threadpool(api.hub.subscribe, since, bool(board))
    await run_in_threadpool(api.watch.ensure_running)

    async def stream() -> AsyncIterator[bytes]:
        try:
            # EventSource reconnects on its own — with the last id it saw,
            # which is the whole reason the events are numbered.
            yield b"retry: 3000\n\n"
            while True:
                try:
                    event = await to_thread.run_sync(
                        channel.get, True, 15, abandon_on_cancel=True, limiter=console.streams
                    )
                except queue.Empty:
                    # A comment, not an event: it keeps the connection from
                    # being reaped by anything in between, and tells the
                    # browser nothing happened.
                    yield b": still here\n\n"
                    continue
                yield vault.mask(event.encode()).encode("utf-8")
        finally:
            # The tab was closed, which is the normal way this ends.
            api.hub.unsubscribe(channel)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# -- what a message carries --------------------------------------------------


@doors.post("/api/chat/attachments", response_model=answers.Attached)
def upload(request: Request, name: str = "") -> Response:
    """One file for the message being written, as the raw body of the request.

    Raw rather than multipart: one file per request is what the page sends,
    and a parser of forms would be a dependency for one field. The name comes
    in the query, the bytes are streamed to disk — never held.
    """
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    try:
        said = _console(request).api.chat.attach(name, _Body(request), length)
    except attachments.TooLarge as error:
        return fail(413, str(error))
    except ValueError as error:
        return fail(400, str(error))
    except OSError as error:
        return fail(500, f"the file could not be kept: {error}")
    except ClientDisconnect:
        return fail(400, "the file was not sent whole")
    return answer(said)


@doors.post("/api/chat/transcribe")
def transcribe(request: Request, lang: str = "") -> Response:
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    chat = _console(request).api.chat
    if length > chat.config.web.attachment_max_mb * 1024 * 1024:
        return fail(413, "the recording is longer than a message can be")
    audio = from_thread.run(request.body) if length > 0 else b""
    try:
        said = chat.transcribe(audio, request.headers.get("content-type") or "", lang)
    except openrouter.Unavailable as error:
        return fail(503, str(error))
    except openrouter.TranscriptionError as error:
        return fail(502, str(error))
    except ValueError as error:
        return fail(400, str(error))
    return answer(said)


@doors.get("/api/chat/attachments/{identifier:attachment}")
def attachment(request: Request, identifier: str) -> Response:
    """A file of the conversation, served back for its thumbnail.

    Under the type of its extension, never the one it was uploaded with, and
    with a sandbox: even an accepted kind is not a page this origin runs.
    Read whole, like the static files: `web.attachment_max_mb` bounds it.
    """
    try:
        found = _console(request).api.chat.attachment(identifier)
        body = found.path.read_bytes()
    except (LookupError, OSError) as error:
        return fail(404, str(error))
    extra = {"Content-Disposition": f"inline; filename*=UTF-8''{quote(found.name)}"}
    # Every kind but the PDF, which Chrome refuses to open in a sandbox at
    # all — and whose viewer is a sandbox of its own.
    if found.type != "application/pdf":
        extra["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src 'self'; media-src 'self'"
        )
    return _send(200, body, found.type, extra)


# -- the MCP server ----------------------------------------------------------


def _form(request: Request) -> dict[str, str] | None:
    """A form, as OAuth posts one — or JSON, which some clients send instead."""
    raw = _read(request)
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace")
    if (request.headers.get("content-type") or "").split(";")[0].strip() == "application/json":
        try:
            said = json.loads(text or "{}")
        except ValueError:
            return {}
        return (
            {str(key): str(value) for key, value in said.items()} if isinstance(said, dict) else {}
        )
    return {key: value for key, value in parse_qsl(text, keep_blank_values=True)}


@doors.get("/.well-known/{rest:path}", include_in_schema=False)
def discovery(request: Request, rest: str) -> Response:
    """Where a client learns how to get a key: RFC 9728, then RFC 8414."""
    route = f"/.well-known/{rest}"
    base = _asking(request).base()
    if route.startswith("/.well-known/oauth-protected-resource"):
        return answer(
            {
                "resource": f"{base}/mcp",
                "resource_name": "Ponos",
                "authorization_servers": [base],
                "scopes_supported": list(oauth.SCOPES),
                "bearer_methods_supported": ["header"],
            }
        )
    if route.startswith(
        ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")
    ):
        return answer(
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
    return fail(404, f"no such route: {route}")


def _grant(request: Request) -> oauth.Grant | Response:
    """The key the request carries — or the 401 that says where to get one.

    The 401 names where the metadata is (RFC 9728): it is what makes Claude
    offer "Connect", with no key as with one expired or taken back.
    """
    header = request.headers.get("Authorization") or ""
    presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
    try:
        grant = oauth.check(presented)
    except db.ERRORS as error:
        return fail(500, f"the keys cannot be read: {error}")
    if grant is None:
        metadata = f"{_asking(request).base()}/.well-known/oauth-protected-resource/mcp"
        said = f'Bearer resource_metadata="{metadata}"'
        if presented:
            said += ', error="invalid_token"'
        return _send(
            401,
            json.dumps({"error": "a token for this server is needed"}).encode(),
            "application/json",
            {"WWW-Authenticate": said},
        )
    return grant


@doors.get("/mcp", include_in_schema=False)
def mcp_stream(request: Request) -> Response:
    # No stream to open: but a key first, as for a POST — the 401 is what
    # tells a client to connect, whatever it tried first.
    grant = _grant(request)
    if isinstance(grant, Response):
        return grant
    return _send(405, b"", "text/plain", {"Allow": "POST"})


@doors.post("/mcp", include_in_schema=False)
def mcp_message(request: Request) -> Response:
    """One JSON-RPC message for the MCP server, with a key of its own.

    Never the console's token nor its cookie: those open everything, and
    a connector is given read, or read and write, and nothing else.
    `Origin` is not checked, as Leadz does not: what it guards against —
    a page resolving its own name to this machine — is refused by the
    `Host` check already, and a page anywhere holds no key to send.
    """
    raw = _read(request)
    if raw is None:
        return fail(413, "a message is smaller than that")
    grant = _grant(request)
    if isinstance(grant, Response):
        return grant
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return answer(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}},
            400,
        )
    said = mcp.handle(_console(request).api, grant, message, _asking(request).base())
    if said is None:
        return _send(202, b"", "application/json")
    if isinstance(said, dict):
        return answer(said)
    return _send(200, json.dumps(said, ensure_ascii=False).encode(), "application/json")


@doors.post("/oauth/register", include_in_schema=False)
def register(request: Request) -> Response:
    raw = _read(request)
    if raw is None:
        return fail(413, "a registration is smaller than that")
    try:
        metadata = json.loads(raw.decode("utf-8") or "{}")
        return answer(oauth.register(metadata), 201)
    except (ValueError, UnicodeDecodeError):
        return answer({"error": "invalid_client_metadata", "error_description": "not JSON"}, 400)
    except oauth.OAuthError as error:
        return answer(error.body(), error.status)


@doors.post("/oauth/token", include_in_schema=False)
def exchange(request: Request) -> Response:
    form = _form(request)
    if form is None:
        return fail(413, "a token request is smaller than that")
    basic = None
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("basic "):
        try:
            pair = base64.b64decode(header[6:].strip()).decode("utf-8")
            identifier, _, secret = pair.partition(":")
            basic = (unquote(identifier), unquote(secret))
        except (ValueError, UnicodeDecodeError):
            return answer({"error": "invalid_client"}, 401)
    try:
        return answer(oauth.exchange(form, basic))
    except oauth.OAuthError as error:
        return answer(error.body(), error.status)


@doors.get("/oauth/authorize", include_in_schema=False)
def authorize_page(request: Request) -> Response:
    # The first of each, and none left blank — as the client sent them.
    params: dict[str, str] = {}
    for key, value in parse_qsl(request.url.query):
        params.setdefault(key, value)
    return _authorize(request, params)


def _authorize(
    request: Request, params: dict[str, str], said: str = "", status: int = 200
) -> Response:
    """The consent page: which client, asking for what — and, signed out, who you are."""
    console, asking = _console(request), _asking(request)
    language = asking.language()
    if claimable(console.api.config, console.entry):
        return _send(
            403,
            consent_refused(language, "This console has not been set up yet.").encode(),
            "text/html; charset=utf-8",
        )
    try:
        asked = oauth.asked(params)
    except oauth.OAuthError as error:
        if error.redirect:
            location = oauth.back(
                error.redirect,
                error=error.error,
                error_description=error.description,
                state=error.state,
                iss=asking.base(),
            )
            return _send(302, b"", "text/plain", {"Location": location})
        return _send(
            400,
            consent_refused(language, error.description).encode(),
            "text/html; charset=utf-8",
        )
    needs = "" if asking.authorised() else ("password" if console.entry else "token")
    page = consent_page(language, asked, params, needs, said).encode()
    # The client that opened this page waits for its answer — in the
    # window it opened, as often as not: that one is not severed from it.
    return _send(
        status,
        page,
        "text/html; charset=utf-8",
        {
            "Content-Security-Policy": page_policy(page, leaves=True),
            "Cross-Origin-Opener-Policy": "unsafe-none",
        },
    )


@doors.post("/oauth/authorize", include_in_schema=False)
def consent(request: Request) -> Response:
    """The consent page, answered: a code back to the client, or a refusal.

    Posted by the page above and by nothing else — its `Origin` is checked,
    and the console's cookie is `SameSite=Strict`, so a page elsewhere
    posting this form for you arrives signed out, and has to know the
    password.
    """
    console, asking = _console(request), _asking(request)
    form = _form(request)
    if form is None:
        return fail(413, "a consent is smaller than that")
    if not asking.same_origin():
        return fail(403, "this request did not come from the console")
    if claimable(console.api.config, console.entry):
        return fail(403, "this console has not been set up yet")
    try:
        asked = oauth.asked(form)
    except oauth.OAuthError:
        return _authorize(request, form)
    base = asking.base()
    if form.get("decision") != "allow":
        location = oauth.back(
            asked.redirect_uri, error="access_denied", state=asked.state, iss=base
        )
        return _send(302, b"", "text/plain", {"Location": location})
    if not asking.authorised():
        # As signing in does: counted before it is checked — see `attempts`.
        knocker = asking.knocker()
        if wait := console.attempts.admit(knocker):
            said = _words(asking.language())("too many attempts — try again in {seconds} s")
            return _authorize(request, form, said.format(seconds=max(1, int(wait + 0.999))), 429)
        if not _proven(console, form):
            wrong = "wrong email or password" if console.entry else "wrong token"
            return _authorize(request, form, _words(asking.language())(wrong), 401)
        console.attempts.forgive(knocker)
    scopes = (
        (oauth.READ, oauth.WRITE)
        if form.get("write") and oauth.WRITE in asked.scopes
        else (oauth.READ,)
    )
    code = oauth.code(asked, scopes)
    location = oauth.back(asked.redirect_uri, code=code, state=asked.state, iss=base)
    return _send(302, b"", "text/plain", {"Location": location})


def _proven(console: Console, form: dict[str, str]) -> bool:
    """The credentials typed on the consent page: the sign-in's, or the token."""
    entry = console.entry
    if entry is not None:
        return entry.opens(form.get("email", ""), form.get("password", ""))
    offered = form.get("token", "").strip()
    return bool(offered) and hmac.compare_digest(offered.encode(), console.secret.encode())
