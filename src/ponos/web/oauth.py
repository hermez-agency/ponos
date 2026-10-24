"""Who may talk to the MCP server, and with which of its two keys.

The console's own way in — its token, a cookie, a password — opens everything:
behind it sits a runner that starts sessions with `bypassPermissions`. The MCP
server is a narrower door, and it gets keys of its own rather than a copy of
those: a key that can only read, and one that can also write, each handed to
one client and taken back from that client alone.

**OAuth 2.1, because that is what a remote connector speaks.** claude.ai adds
a connector by its address and nothing else: it reads where to authorise from
`/.well-known/oauth-protected-resource`, registers itself (RFC 7591), sends you
to `/oauth/authorize`, and exchanges the code it gets back for a token —
with PKCE, so that a code intercepted on its way back is worth nothing. The
same flow the Leadz connector already goes through, and the one the MCP
specification names. Only what that road needs is here: the `code` grant with
`S256`, refresh tokens that turn over at each use — one that comes back after
it turned over takes its whole client with it, since somebody else has used
it — and no implicit flow, no password grant, no client credentials.

**Consent is the console's sign-in.** Registering is open — any client may
say its name — and worth nothing on its own: the authorisation page asks for
the console's password (or its token) unless the browser is already signed in,
and says which client asks for what. Read is always granted; write is ticked,
or not.

**A token for Claude Code without a browser.** `ponos mcp token` draws one on
this machine, for one name and one scope, and it does not expire: it is taken
back with `ponos mcp revoke`. Claude Code can also go through OAuth like
claude.ai does — this is for when a header in a file is simpler.

Nothing secret is stored as itself. A code, a token or a client secret is kept
as its SHA-256: reading the database tells which client holds a key, never the
key. Every check compares digests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from .. import db

# The two keys. Read is every reading tool; write adds the few that write.
READ = "read"
WRITE = "write"
SCOPES = (READ, WRITE)

# A code is used within seconds of being given, or it was not meant to be.
CODE_SECONDS = 300
# An access token is short, its refresh token long: a connector left alone for
# a month still works, and a token copied out of a log stops working within
# the hour.
ACCESS_SECONDS = 3600
REFRESH_DAYS = 90

# How the clients registered over the network are told from the ones drawn here.
LOCAL_PREFIX = "local-"

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")

# What a registration may say about how it authenticates at the token endpoint.
# `none` is a public client with PKCE alone — Claude Code; the two others carry
# a secret, which is drawn here and given once.
AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")


class OAuthError(Exception):
    """A request the authorisation server refuses, said the way RFC 6749 says it."""

    def __init__(
        self, error: str, description: str, status: int = 400, redirect: str = "", state: str = ""
    ) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status
        # Where the refusal may be sent back: an authorisation request whose
        # client and address check out is answered there, not on our page.
        self.redirect = redirect
        self.state = state

    def body(self) -> dict:
        return {"error": self.error, "error_description": self.description}


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    redirect_uris: tuple[str, ...]
    secret: str  # its digest, or "" for a public client

    @property
    def local(self) -> bool:
        return self.id.startswith(LOCAL_PREFIX)


@dataclass(frozen=True)
class Grant:
    """What a bearer token is worth: a client, and the scopes it was given."""

    client: str
    name: str
    scopes: frozenset[str]

    def allows(self, scope: str) -> bool:
        return scope in self.scopes

    @property
    def scope(self) -> str:
        return " ".join(scope for scope in SCOPES if scope in self.scopes)


def back(redirect: str, **values: str) -> str:
    """The client's address, carrying the code or the refusal, and its `state`."""
    joined = urlencode({key: value for key, value in values.items() if value})
    return f"{redirect}{'&' if urlparse(redirect).query else '?'}{joined}"


@dataclass(frozen=True)
class Asked:
    """An authorisation request, checked: what the consent page shows and posts back."""

    client: Client
    redirect_uri: str
    challenge: str
    scopes: tuple[str, ...]
    state: str
    resource: str


# -- small pieces -------------------------------------------------------------


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def scopes_of(text: str) -> tuple[str, ...]:
    """The scopes a request names, in our order — read always among them.

    A client that names none is offered both, and the consent page is where
    write is ticked or not: connectors do not all say what they want, and the
    choice is the person's anyway. One that names only write still reads,
    since there is no writing to a board one cannot see.
    """
    asked = set(str(text or "").split()) or set(SCOPES)
    unknown = asked - set(SCOPES)
    if unknown:
        raise OAuthError("invalid_scope", f"unknown scope: {' '.join(sorted(unknown))}")
    return tuple(scope for scope in SCOPES if scope == READ or scope in asked)


def verified(verifier: str, challenge: str) -> bool:
    """PKCE's S256: the verifier hashes to the challenge sent with the request."""
    computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return hmac.compare_digest(computed.rstrip(b"=").decode(), challenge)


def acceptable_redirect(uri: str) -> bool:
    """HTTPS anywhere, plain HTTP only back to this machine — RFC 8252's loopback."""
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.fragment or not parsed.hostname:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS


def same_redirect(offered: str, registered: str) -> bool:
    """The registered address, exactly — but any port, for a loopback one.

    A native client listens on whatever port was free when it started, and
    RFC 8252 says the port of a loopback redirect is not part of the match.
    """
    if offered == registered:
        return True
    try:
        one, two = urlparse(offered), urlparse(registered)
        return (
            one.scheme == two.scheme == "http"
            and one.hostname in LOOPBACK_HOSTS
            and one.hostname == two.hostname
            and one.path == two.path
            and one.query == two.query
        )
    except ValueError:
        return False


# -- clients ------------------------------------------------------------------


def register(metadata: dict) -> dict:
    """Dynamic client registration (RFC 7591): a name, where to send the code.

    Open on purpose — the consent page is the lock, not this — and narrow: an
    address that is neither HTTPS nor this machine is refused, so that a code
    can never be sent in clear across a network.
    """
    if not isinstance(metadata, dict):
        raise OAuthError("invalid_client_metadata", "the registration is a JSON object")
    uris = metadata.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(uri, str) for uri in uris):
        raise OAuthError("invalid_redirect_uri", "redirect_uris is a non-empty list of addresses")
    if len(uris) > 10:
        raise OAuthError("invalid_redirect_uri", "ten redirect_uris at most")
    for uri in uris:
        if not acceptable_redirect(uri):
            raise OAuthError(
                "invalid_redirect_uri", f"{uri} is neither https nor a loopback address"
            )
    method = str(metadata.get("token_endpoint_auth_method") or "none")
    if method not in AUTH_METHODS:
        raise OAuthError(
            "invalid_client_metadata",
            f"token_endpoint_auth_method is one of {', '.join(AUTH_METHODS)}",
        )
    grants = metadata.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
        raise OAuthError("invalid_client_metadata", "only authorization_code and refresh_token")
    name = (
        " ".join(str(metadata.get("client_name") or "").split())[:80]
        or urlparse(uris[0]).hostname
        or "?"
    )
    identifier = secrets.token_urlsafe(18)
    secret = secrets.token_urlsafe(32) if method != "none" else ""
    issued = _now()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO mcp_clients (id, name, redirect_uris, secret, created_at) VALUES (?, ?, ?, ?, ?)",
            (identifier, name, json.dumps(uris), digest(secret) if secret else "", _stamp(issued)),
        )
    answer = {
        "client_id": identifier,
        "client_id_issued_at": int(issued.timestamp()),
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": grants,
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "scope": " ".join(SCOPES),
    }
    if secret:
        answer["client_secret"] = secret
        answer["client_secret_expires_at"] = 0
    return answer


def client(identifier: str) -> Client | None:
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            "SELECT id, name, redirect_uris, secret FROM mcp_clients WHERE id = ?", (identifier,)
        ).fetchone()
    if row is None:
        return None
    try:
        uris = tuple(json.loads(row[2] or "[]"))
    except ValueError:
        uris = ()
    return Client(id=row[0], name=row[1], redirect_uris=uris, secret=row[3])


def authenticated(found: Client, secret: str) -> bool:
    """A client that registered with a secret gives it; a public one gives none."""
    if not found.secret:
        return True
    return bool(secret) and hmac.compare_digest(digest(secret), found.secret)


# -- authorising --------------------------------------------------------------


def asked(params: dict[str, str]) -> Asked:
    """An authorisation request, checked before anybody is asked to consent.

    Raises OAuthError. One whose client or address is wrong must not be sent
    anywhere — the server shows those; the others go back to the client.
    """
    found = client(params.get("client_id", ""))
    if found is None or found.local:
        raise OAuthError("invalid_client", "this client is not registered with this console")
    redirect = params.get("redirect_uri", "")
    if not redirect and len(found.redirect_uris) == 1:
        redirect = found.redirect_uris[0]
    if not any(same_redirect(redirect, known) for known in found.redirect_uris):
        raise OAuthError("invalid_request", "redirect_uri is not one this client registered")
    state = params.get("state", "")
    try:
        if params.get("response_type") != "code":
            raise OAuthError("unsupported_response_type", "only response_type=code")
        challenge = params.get("code_challenge", "")
        if not challenge or params.get("code_challenge_method", "") != "S256":
            raise OAuthError("invalid_request", "PKCE is required, with code_challenge_method=S256")
        scopes = scopes_of(params.get("scope", ""))
    except OAuthError as error:
        raise OAuthError(error.error, error.description, redirect=redirect, state=state) from None
    return Asked(
        client=found,
        redirect_uri=redirect,
        challenge=challenge,
        scopes=scopes,
        state=state,
        resource=params.get("resource", ""),
    )


def _issue(
    connection,
    kind: str,
    client_id: str,
    scope: str,
    seconds: int | None,
    detail: dict | None = None,
) -> str:
    secret = secrets.token_urlsafe(32)
    now = _now()
    connection.execute(
        "INSERT INTO mcp_tokens (hash, kind, client, scope, detail, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            digest(secret),
            kind,
            client_id,
            scope,
            json.dumps(detail or {}),
            _stamp(now),
            _stamp(now + timedelta(seconds=seconds)) if seconds is not None else None,
        ),
    )
    return secret


def code(request: Asked, scopes: tuple[str, ...]) -> str:
    """The code a consent is worth, for a few minutes and one exchange."""
    granted = " ".join(scope for scope in SCOPES if scope in scopes)
    with db.transaction() as connection:
        return _issue(
            connection,
            "code",
            request.client.id,
            granted,
            CODE_SECONDS,
            {"redirect_uri": request.redirect_uri, "challenge": request.challenge},
        )


def _pair(connection, client_id: str, scope: str) -> dict:
    return {
        "access_token": _issue(connection, "access", client_id, scope, ACCESS_SECONDS),
        "token_type": "Bearer",
        "expires_in": ACCESS_SECONDS,
        "refresh_token": _issue(connection, "refresh", client_id, scope, REFRESH_DAYS * 86400),
        "scope": scope,
    }


def _take(connection, secret: str, kind: str, client_id: str) -> tuple[str, dict] | None:
    """A code or refresh token, spent: revoked as it is read, valid or not.

    Read and revoked in the same transaction, so that the same code presented
    twice at once is honoured once.
    """
    row = connection.execute(
        "SELECT id, client, scope, detail, expires_at, revoked_at FROM mcp_tokens"
        " WHERE hash = ? AND kind = ?",
        (digest(secret), kind),
    ).fetchone()
    if row is None:
        return None
    identifier, owner, scope, detail, expires, revoked = row
    connection.execute(
        "UPDATE mcp_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
        (_stamp(_now()), identifier),
    )
    if revoked or owner != client_id or (expires and expires <= _stamp(_now())):
        if revoked and kind == "code":
            # A code used twice is a code somebody else has: what it was
            # exchanged for goes with it (RFC 6749, 4.1.2).
            connection.execute(
                "UPDATE mcp_tokens SET revoked_at = COALESCE(revoked_at, ?)"
                " WHERE client = ? AND kind IN ('access', 'refresh') AND created_at >= ?",
                (_stamp(_now()), owner, _stamp(_now() - timedelta(seconds=CODE_SECONDS * 2))),
            )
        elif revoked and kind == "refresh":
            # A refresh token turns over at each use, so one that comes back
            # has been used already — by the client, or by whoever copied it
            # and got there first. Which of the two holds the live pair cannot
            # be told: the whole client goes, and signs in again.
            connection.execute(
                "UPDATE mcp_tokens SET revoked_at = COALESCE(revoked_at, ?)"
                " WHERE client = ? AND kind IN ('access', 'refresh')",
                (_stamp(_now()), owner),
            )
        return None
    try:
        said = json.loads(detail or "{}")
    except ValueError:
        said = {}
    return scope, said


def exchange(form: dict[str, str], basic: tuple[str, str] | None = None) -> dict:
    """The token endpoint: a code for a pair of tokens, or a refresh for a new pair."""
    client_id = form.get("client_id", "")
    secret = form.get("client_secret", "")
    if basic:
        client_id, secret = basic
    found = client(client_id)
    if found is None or found.local or not authenticated(found, secret):
        raise OAuthError("invalid_client", "unknown client, or wrong secret", 401)
    grant = form.get("grant_type", "")
    if grant not in ("authorization_code", "refresh_token"):
        raise OAuthError("unsupported_grant_type", "authorization_code or refresh_token")
    # Decided inside the transaction, raised once it is committed: a code that
    # is refused is still spent, and a rollback would hand it back.
    refused: OAuthError | None = None
    issued: dict = {}
    with db.transaction() as connection:
        if grant == "authorization_code":
            taken = _take(connection, form.get("code", ""), "code", found.id)
            if taken is None:
                refused = OAuthError(
                    "invalid_grant", "this code is unknown, expired or already used"
                )
            else:
                scope, detail = taken
                registered = str(detail.get("redirect_uri", ""))
                if not same_redirect(form.get("redirect_uri") or registered, registered):
                    refused = OAuthError(
                        "invalid_grant", "redirect_uri differs from the authorisation's"
                    )
                elif not verified(form.get("code_verifier", ""), str(detail.get("challenge", ""))):
                    refused = OAuthError(
                        "invalid_grant", "code_verifier does not match the code_challenge"
                    )
                else:
                    issued = _pair(connection, found.id, scope)
        else:
            taken = _take(connection, form.get("refresh_token", ""), "refresh", found.id)
            if taken is None:
                refused = OAuthError(
                    "invalid_grant", "this refresh token is unknown, expired or already used"
                )
            else:
                scope, _ = taken
                if form.get("scope"):
                    # Narrower, never wider: a refresh is not a second consent.
                    narrowed = set(scopes_of(form["scope"]))
                    scope = " ".join(
                        item for item in SCOPES if item in narrowed and item in scope.split()
                    )
                issued = _pair(connection, found.id, scope)
    if refused is not None:
        raise refused
    return issued


# -- checking -----------------------------------------------------------------


def check(secret: str) -> Grant | None:
    """What a bearer token presented to `/mcp` is worth — None for nothing."""
    if not secret:
        return None
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            "SELECT t.client, c.name, t.scope, t.expires_at FROM mcp_tokens t"
            " JOIN mcp_clients c ON c.id = t.client"
            " WHERE t.hash = ? AND t.kind IN ('access', 'local') AND t.revoked_at IS NULL",
            (digest(secret),),
        ).fetchone()
    if row is None:
        return None
    owner, name, scope, expires = row
    if expires and expires <= _stamp(_now()):
        return None
    return Grant(client=owner, name=name, scopes=frozenset(scope.split()))


# -- this machine's own -------------------------------------------------------


def local(name: str, write: bool) -> tuple[str, str]:
    """A token for Claude Code, drawn here: (its client id, the token).

    A client of its own, so that the journal says which one wrote, and so
    that revoking it touches nothing else.
    """
    name = " ".join(name.split())[:80] or "Claude Code"
    identifier = LOCAL_PREFIX + secrets.token_hex(4)
    scope = " ".join(SCOPES) if write else READ
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO mcp_clients (id, name, redirect_uris, secret, created_at) VALUES (?, ?, '[]', '', ?)",
            (identifier, name, _stamp(_now())),
        )
        token = _issue(connection, "local", identifier, scope, None)
    return identifier, token


def clients() -> list[dict]:
    """Every client, with the scope of its live tokens — for `ponos mcp list`."""
    now = _stamp(_now())
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT c.id, c.name, c.created_at,"
            " GROUP_CONCAT(DISTINCT t.scope) FROM mcp_clients c"
            " LEFT JOIN mcp_tokens t ON t.client = c.id AND t.kind IN ('access', 'refresh', 'local')"
            " AND t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at > ?)"
            " GROUP BY c.id ORDER BY c.created_at",
            (now,),
        ).fetchall()
    listed = []
    for identifier, name, created, scopes in rows:
        held = set(" ".join((scopes or "").split(",")).split())
        listed.append(
            {
                "id": identifier,
                "name": name,
                "created_at": created,
                "scope": " ".join(scope for scope in SCOPES if scope in held),
            }
        )
    return listed


def revoke_connectors() -> int:
    """Take back the keys of every client signed in over OAuth — `serve --sign-out-everywhere`.

    The connectors went through the console's sign-in to get them, and signing
    out everywhere has to reach them too: a refresh token lives ninety days and
    turns over at each use, so left alone it never runs out. The tokens drawn
    with `ponos mcp token` stay, as the console's token does: they were drawn
    on this machine, and are taken back one by one with `ponos mcp revoke`.
    Returns how many were still good.
    """
    with db.transaction() as connection:
        cursor = connection.execute(
            "UPDATE mcp_tokens SET revoked_at = ? WHERE revoked_at IS NULL"
            " AND kind IN ('code', 'access', 'refresh') AND client NOT LIKE ?",
            (_stamp(_now()), LOCAL_PREFIX + "%"),
        )
    return cursor.rowcount


def revoke(identifier: str) -> int:
    """Take back every key of one client. Returns how many were still good."""
    with db.transaction() as connection:
        cursor = connection.execute(
            "UPDATE mcp_tokens SET revoked_at = ? WHERE client = ? AND revoked_at IS NULL",
            (_stamp(_now()), identifier),
        )
        known = connection.execute(
            "SELECT 1 FROM mcp_clients WHERE id = ?", (identifier,)
        ).fetchone()
    if known is None:
        raise LookupError(f"no MCP client {identifier}")
    return cursor.rowcount
