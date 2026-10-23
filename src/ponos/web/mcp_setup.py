"""What the console's *MCP* tab needs to know, and the one thing it checks.

Two different things are called MCP here, and the tab keeps them apart. The
console *is* an MCP server (`mcp.py`): the tab hands its address to a client —
Claude Code, Claude desktop — to paste. And the sessions Ponos starts *use* MCP
servers (Notion, GitHub, a browser…) that Claude Code itself holds: those are
read from `claude mcp list`, the one command that says both what is configured
and whether it answers, rather than from `~/.claude.json`, which would have
this module re-implement the scopes of a tool that moves faster than it does.

**No secret goes through here.** The tab shows an address, a name, a scope: a
key is drawn on the machine with `ponos mcp token` (see `__main__.command_mcp`,
which says why it is not a button), and a server's command line or URL, which
may carry a key of its own, is cut down to what it is before it is sent.

**The test asks without a key.** An unsigned request to `/mcp` is answered 401
and names where the metadata is: that is a server that is up, speaks MCP's
authorisation and tells where to connect, which is all a client needs before it
signs in. Reading the metadata back catches the case that matters behind a
proxy — an address the client reached that is not the one the server believes
it has, so that every client fails at the sign-in after a connection that
looked fine. Each way it can fail is a `code`; the sentence that says what to
do about it is the page's, in the console's language.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import subprocess
from typing import Any
from urllib.parse import urlsplit

from .. import http, session
from . import oauth

# How long the test waits for an answer, and `claude mcp list` for its checks:
# it starts every stdio server to see whether it answers, and npx may download.
PROBE_TIMEOUT = 8
LIST_TIMEOUT = 60


def overview(local: str, public: str) -> dict[str, Any]:
    """The addresses to paste and the clients that already hold a key — no key."""
    return {
        "local": f"{local}/mcp",
        "public": f"{public.rstrip('/')}/mcp" if public else "",
        "clients": [
            {"id": client["id"], "name": client["name"], "scope": client["scope"]}
            for client in oauth.clients()
        ],
    }


def probe(address: str) -> dict[str, Any]:
    """Ask `address` (ending in `/mcp`) for the 401 a live server gives."""
    if not address:
        return {"ok": False, "code": "no-address", "status": 0}
    try:
        answer = http.send(
            "mcp",
            "POST",
            address,
            content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=PROBE_TIMEOUT,
        )
        status = answer.status
        if status != 401:
            code = "not-found" if status == 404 else "misrouted" if status == 421 else "unexpected"
            return {"ok": False, "code": code, "status": status}
        announced = re.search(
            r'resource_metadata="([^"]+)"', answer.headers.get("WWW-Authenticate") or ""
        )
        if not announced:
            return {"ok": False, "code": "not-mcp", "status": status}
        metadata = http.send("mcp", "GET", announced.group(1), timeout=PROBE_TIMEOUT)
        if metadata.status >= 400:
            return {"ok": False, "code": "unreachable", "status": 0}
        resource = json.loads(metadata.body).get("resource", "")
        if resource != address:
            return {"ok": False, "code": "address-mismatch", "status": status, "seen": resource}
        return {"ok": True, "code": "ok", "status": status}
    except http.Unanswered as error:
        reason = error.cause
        if isinstance(reason, ssl.SSLError):
            return {"ok": False, "code": "certificate", "status": 0}
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return {"ok": False, "code": "timeout", "status": 0}
        if isinstance(reason, socket.gaierror):
            return {"ok": False, "code": "unknown-host", "status": 0}
        if error.offline:
            return {"ok": False, "code": "unreachable", "status": 0}
        # A connection cut halfway through the answer.
        return {"ok": False, "code": "not-mcp", "status": 0}
    except (ValueError, AttributeError):
        # A reply that is not what a server of ours would say: JSON that is not
        # an object, a body that is not JSON at all.
        return {"ok": False, "code": "not-mcp", "status": 0}


# `name: what it runs - ✓ Connected`, one server a line, as `claude mcp list` prints it.
_LINE = re.compile(r"^(?P<name>.+?): (?P<target>.+) - (?P<mark>[✓✗!⚠])\s*(?P<said>.*)$")


def _described(target: str) -> str:
    """What a server runs, without what could be a key in it.

    A URL keeps its host and path (the query and the user are where keys go); a
    command keeps its program — its arguments and environment may hold anything.
    """
    target = re.sub(r"\s*\((?:HTTP|SSE|stdio)\)\s*$", "", target.strip())
    if re.match(r"^https?://", target):
        parts = urlsplit(target)
        return f"{parts.scheme}://{parts.hostname or ''}{f':{parts.port}' if parts.port else ''}{parts.path}"
    return target.split(" ", 1)[0]


def parse(output: str) -> list[dict[str, Any]]:
    """The servers `claude mcp list` printed, each ok, to authenticate, or failing."""
    servers = []
    for line in output.splitlines():
        found = _LINE.match(line.strip())
        if not found:
            continue
        said = found["said"].strip().lower()
        state = "auth" if "auth" in said else "ok" if found["mark"] == "✓" else "error"
        servers.append(
            {"name": found["name"], "target": _described(found["target"]), "state": state}
        )
    return servers


def servers() -> dict[str, Any]:
    """The MCP servers Claude Code holds — those a session of Ponos starts with."""
    binary = session.available()
    if not binary:
        return {"available": False, "servers": [], "failed": False}
    try:
        done = subprocess.run(
            [binary, "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=LIST_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": True, "servers": [], "failed": True}
    return {
        "available": True,
        "servers": parse(done.stdout),
        "failed": done.returncode != 0 and not done.stdout.strip(),
    }
