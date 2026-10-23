#!/usr/bin/env python3
"""The road a ticket travels, end to end, under assertions.

    uv run python tests/functional.py   # or python3, with requirements.txt installed

`tests/run.py` covers the pure part and assumes it touches nothing — not Notion,
not git, not the network. What that leaves uncovered is the road itself: ready
ticket, worktree, session, branch, pull request, status written back. And that
is the half which breaks quietly. A ticket that runs on an empty directory, a
session paid for and thrown away, a pull request nobody ever linked to its
ticket — none of those raises anything. They leave a board that still looks
plausible.

So the world is doubled rather than mocked. A Notion of our own answers on a
local port and keeps a state any test can read back; a repository and a bare
remote stand in for GitHub; a `claude` and a `gh` at the head of `PATH` do what
the real ones do, minus the thinking and the network. The runner is told none of
it: it loads a configuration, reads its board and works. The one thing it cannot
guess is where Notion lives, and that is the single seam added to the code —
`PONOS_NOTION_API`, see `notion.endpoint`.

Nothing here leaves the machine, and nothing is written outside a temporary
directory: `XDG_STATE_HOME` moves with the test, and takes the worktrees, the
logs and the history with it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import support  # noqa: E402
from support import case, fixture  # noqa: E402

from ponos import config as C  # noqa: E402
from ponos import credits, db, images, journal, notion, project_settings, state, store  # noqa: E402
from ponos import http as http_module  # noqa: E402
from ponos.runner import Runner  # noqa: E402
from ponos.ticket import short_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# An update is checked by importing the new version's console, FastAPI with
# it: a `python3` without it runs the suite again under the checkout's `.venv`,
# which `uv sync` makes — as `tests/run.py` does.
_VENV = ROOT / ".venv" / "bin" / "python"
if (
    __name__ == "__main__"
    and importlib.util.find_spec("fastapi") is None
    and _VENV.is_file()
    and Path(sys.prefix).resolve() != _VENV.parents[1].resolve()
):
    os.execv(_VENV, [str(_VENV), *sys.argv])


def _ident() -> str:
    """A Notion identifier: 32 hexadecimal characters, as `is_identifier` reads."""
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# -- a Notion of our own -----------------------------------------------------


def _rich(text: str) -> list[dict]:
    """Rich text as Notion hands it back — content to write, plain_text to read."""
    return [{"type": "text", "text": {"content": text}, "plain_text": text}]


def _stored(value: dict) -> dict:
    """One written property, as a reader would then find it.

    `notion._encode` writes `{"status": {"name": "Done"}}`: the type is the only
    key, and it is not repeated inside. What comes back from the API carries it
    as `type`, and a rich text carries `plain_text` beside the content it was
    given. Doing both here is what makes a value written by the runner readable
    by the runner — which is most of what these tests are about.
    """
    kind = next(iter(value))
    stored = {"type": kind, **value}
    if kind in ("rich_text", "title"):
        stored[kind] = [
            {**part, "plain_text": part.get("text", {}).get("content", "")} for part in value[kind]
        ]
    return stored


class Board:
    """Notion reduced to what `notion.py` actually asks of it.

    Pages, databases, blocks and comments in four dictionaries, and the routing
    that serves them. Everything a test wants to know afterwards — the status a
    ticket ended on, the pull request written into it, what was said in its
    comments — is read straight off here rather than off a transcript of
    requests: the point is the board somebody would look at on Monday.
    """

    def __init__(self) -> None:
        self.databases: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}
        self.blocks: dict[str, list[dict]] = {}
        self.comments: list[dict] = []
        # Files handed over through the File Upload API, and where they are
        # served from afterwards — this server, under a URL that "expires".
        self.uploads: dict[str, dict] = {}
        self.files: dict[str, tuple[bytes, str]] = {}
        self.address = ""
        self.requests: list[str] = []
        # Every request this Notion could not answer, so that a run is never
        # silently short of one: most roads in `notion.py` swallow a refusal.
        self.refused: list[str] = []
        self.me = {"object": "user", "id": _ident(), "name": "Ponos", "type": "bot"}

    # -- building a board ----------------------------------------------------

    def database(self, title: str, properties: dict) -> str:
        identifier = _ident()
        self.databases[identifier] = {
            "object": "database",
            "id": identifier,
            "title": _rich(title),
            "properties": properties,
        }
        return identifier

    def page(
        self,
        properties: dict[str, dict],
        *,
        database: str = "",
        body: str = "",
    ) -> str:
        identifier = _ident()
        self.pages[identifier] = {
            "object": "page",
            "id": identifier,
            "url": f"https://notion.invalid/{identifier}",
            "created_time": _now(),
            "last_edited_time": _now(),
            "parent": (
                {"type": "database_id", "database_id": database}
                if database
                else {"type": "workspace", "workspace": True}
            ),
            "properties": properties,
        }
        self.blocks[identifier] = (
            [
                {
                    "object": "block",
                    "id": _ident(),
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": _rich(line)},
                }
                for line in body.splitlines()
                if line.strip()
            ]
            if body
            else []
        )
        return identifier

    # -- reading it back -----------------------------------------------------

    def value(self, page_id: str, name: str) -> Any:
        page = self.pages[page_id]
        return notion.read(
            notion.Page(id=page_id, url="", title="", properties=page["properties"]), name
        )

    def body(self, page_id: str) -> str:
        """The page's blocks, flattened — enough to say what was written into it."""
        lines = []
        for block in self.blocks.get(page_id, []):
            payload = block.get(block.get("type", ""), {})
            lines.append(
                "".join(part.get("plain_text", "") for part in payload.get("rich_text", []))
            )
        return "\n".join(lines)

    def said(self, page_id: str) -> list[str]:
        """Everything commented on that page, oldest first."""
        return [
            "".join(part.get("plain_text", "") for part in comment["rich_text"])
            for comment in self.comments
            if comment["page"] == page_id
        ]

    # -- serving it ----------------------------------------------------------

    def handle(self, method: str, path: str, query: dict, body: dict, token: str, raw: bytes = b""):
        """One request, routed. The endpoints `notion.py` calls, and those only.

        Anything else is refused *and remembered*: a client that grew a request
        nobody doubled here would otherwise fail somewhere far from here, and
        most of the roads in `notion.py` swallow a refusal on purpose.
        """
        self.requests.append(f"{method} {path}")
        if not token.startswith("Bearer "):
            return 401, {"message": "API token is invalid"}
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] == "v1":
            parts = parts[1:]
        route = (method, *("*" if C.is_identifier(part) else part for part in parts))
        identifier = next((part for part in parts if C.is_identifier(part)), "")

        if route == ("GET", "databases", "*"):
            found = self.databases.get(identifier)
            return (200, found) if found else (404, {"message": "database not found"})
        if route == ("POST", "databases", "*", "query"):
            return 200, self._query(identifier, body)
        if route == ("GET", "pages", "*"):
            found = self.pages.get(identifier)
            return (200, self._signed(found)) if found else (404, {"message": "page not found"})
        if route == ("POST", "file_uploads"):
            upload = _ident()
            self.uploads[upload] = {"status": "pending", **body}
            return 200, {"object": "file_upload", "id": upload, "status": "pending"}
        if route == ("POST", "file_uploads", "*", "send"):
            return self._receive(identifier, raw)
        if route == ("PATCH", "pages", "*"):
            return self._update(identifier, body)
        if route == ("GET", "blocks", "*", "children"):
            return 200, {"results": self.blocks.get(identifier, []), "has_more": False}
        if route == ("PATCH", "blocks", "*", "children"):
            return 200, {"results": self._append(identifier, body.get("children", []))}
        if route == ("PATCH", "blocks", "*"):
            return 200, self._retitle(identifier, body)
        if route == ("GET", "comments"):
            page = (query.get("block_id") or [""])[0].replace("-", "")
            return 200, {
                "results": [one for one in self.comments if one["page"] == page],
                "has_more": False,
            }
        if route == ("POST", "comments"):
            return self._comment(body)
        if route == ("GET", "users", "me"):
            return 200, self.me
        self.refused.append(f"{method} /{'/'.join(parts)}")
        return 404, {"message": f"the fake Notion does not serve {method} /{'/'.join(parts)}"}

    def _query(self, database_id: str, body: dict) -> dict:
        if database_id not in self.databases:
            return {"results": [], "has_more": False}
        filter_ = body.get("filter")
        results = [
            self._signed(page)
            for page in self.pages.values()
            if page["parent"].get("database_id") == database_id
            and not page.get("archived")
            and self._matches(page, filter_)
        ]
        return {"results": results, "has_more": False, "next_cursor": None}

    def _matches(self, page: dict, filter_: dict | None) -> bool:
        if not filter_:
            return True
        if "and" in filter_:
            return all(self._matches(page, one) for one in filter_["and"])
        if "or" in filter_:
            return any(self._matches(page, one) for one in filter_["or"])
        name = filter_.get("property", "")
        value = notion.read(
            notion.Page(id=page["id"], url="", title="", properties=page["properties"]), name
        )
        for kind, condition in filter_.items():
            if kind == "property" or not isinstance(condition, dict):
                continue
            if "equals" in condition and value != condition["equals"]:
                return False
            if "does_not_equal" in condition and value == condition["does_not_equal"]:
                return False
        return True

    def _update(self, page_id: str, body: dict):
        page = self.pages.get(page_id)
        if not page:
            return 404, {"message": "page not found"}
        schema = {}
        database = page["parent"].get("database_id", "")
        if database in self.databases:
            schema = self.databases[database]["properties"]
        if "archived" in body:
            # The trash: the page leaves every query and is still read by its ID.
            page["archived"] = bool(body["archived"])
        for slot in ("cover", "icon"):
            if slot not in body:
                continue
            value = body[slot]
            if value and value.get("type") == "file_upload":
                upload = self.uploads.get(value["file_upload"]["id"], {})
                if upload.get("status") != "uploaded":
                    return 400, {"message": "that file upload has not been sent"}
                name = _ident()
                self.files[name] = (upload["data"], upload.get("content_type", ""))
                value = self.hosted(name, upload.get("filename", "file"))
            page[slot] = value
        for name, value in body.get("properties", {}).items():
            if schema and name not in schema:
                # Notion refuses a property the database does not declare, and
                # the runner leans on that: `update` skips those before writing.
                return 400, {"message": f"{name} is not a property that exists"}
            page["properties"][name] = _stored(value)
        page["last_edited_time"] = _now()
        return 200, self._signed(page)

    def hosted(self, name: str, filename: str) -> dict:
        """A file this Notion keeps, as a page's cover or icon points at it."""
        return {
            "type": "file",
            "file": {"url": f"{self.address}/files/{name}/{filename}", "expiry_time": ""},
        }

    def _signed(self, page: dict) -> dict:
        """The page as it is read: every hosted file under a fresh signature.

        Which is what Notion does, and what the console must not mistake for a
        new picture — the signature changes with each read, the file does not.
        """
        signed = dict(page)
        for slot in ("cover", "icon"):
            value = page.get(slot)
            if value and value.get("type") == "file":
                url = value["file"]["url"].split("?", 1)[0]
                expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                signed[slot] = {
                    "type": "file",
                    "file": {"url": f"{url}?X-Amz-Signature={_ident()}", "expiry_time": expires},
                }
        return signed

    def _receive(self, upload: str, raw: bytes):
        """The second half of an upload: the file, as a multipart form."""
        if upload not in self.uploads:
            return 404, {"message": "no such file upload"}
        head, _, rest = raw.partition(b"\r\n\r\n")
        if b'name="file"' not in head:
            return 400, {"message": "the upload carries no part named file"}
        boundary = raw.split(b"\r\n", 1)[0]
        data = rest[: rest.rindex(b"\r\n" + boundary)]
        self.uploads[upload].update(status="uploaded", data=data)
        return 200, {"object": "file_upload", "id": upload, "status": "uploaded"}

    def _append(self, block_id: str, children: list[dict]) -> list[dict]:
        created = []
        for child in children:
            block = {"object": "block", "id": _ident(), "has_children": False, **child}
            payload = block.get(block.get("type", ""))
            if isinstance(payload, dict) and isinstance(payload.get("rich_text"), list):
                # Written without `plain_text`, read with it — see `_stored`.
                payload["rich_text"] = [
                    {**part, "plain_text": part.get("text", {}).get("content", "")}
                    for part in payload["rich_text"]
                ]
            self.blocks.setdefault(block_id, []).append(block)
            created.append(block)
        # Appended under a block — the live report's toggle — rather than a page:
        # that block now says it has children, as Notion's would.
        for held in self.blocks.values():
            for block in held:
                if block["id"] == block_id and children:
                    block["has_children"] = True
        return created

    def _retitle(self, block_id: str, body: dict) -> dict:
        """A block's text rewritten in place — the live report's title moving on."""
        for held in self.blocks.values():
            for block in held:
                if block["id"] != block_id:
                    continue
                for kind, payload in body.items():
                    if kind == block.get("type") and isinstance(payload.get("rich_text"), list):
                        block[kind]["rich_text"] = [
                            {**part, "plain_text": part.get("text", {}).get("content", "")}
                            for part in payload["rich_text"]
                        ]
                return block
        return {"object": "block", "id": block_id}

    def _comment(self, body: dict):
        discussion = body.get("discussion_id", "")
        page = (body.get("parent") or {}).get("page_id", "").replace("-", "")
        if discussion and not page:
            page = next(
                (one["page"] for one in self.comments if one["discussion_id"] == discussion), ""
            )
        if not page:
            return 400, {"message": "a comment needs a parent page or a discussion"}
        comment = {
            "object": "comment",
            "id": _ident(),
            "page": page,
            "discussion_id": discussion or _ident(),
            "created_time": _now(),
            "created_by": {"object": "user", "id": self.me["id"]},
            "rich_text": [
                {**part, "plain_text": part.get("text", {}).get("content", "")}
                for part in body.get("rich_text", [])
            ],
        }
        self.comments.append(comment)
        return 200, comment


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._answer("GET")

    def do_POST(self) -> None:
        self._answer("POST")

    def do_PATCH(self) -> None:
        self._answer("PATCH")

    def log_message(self, *args: object) -> None:
        """A test suite that narrates every request is a test suite nobody reads."""

    def _answer(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = urlparse(self.path)
        if parsed.path.startswith("/files/"):
            # Where a hosted file is fetched: storage, not the API — no token
            # asked, and the bytes rather than JSON.
            name = parsed.path.split("/")[2]
            data, kind = self.server.board.files.get(name, (b"", ""))  # type: ignore[attr-defined]
            self.send_response(200 if data else 404)
            self.send_header("Content-Type", kind or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}  # a file sent as a form, which `_receive` reads raw
        try:
            status, payload = self.server.board.handle(  # type: ignore[attr-defined]
                method,
                parsed.path,
                parse_qs(parsed.query),
                body,
                self.headers.get("Authorization", ""),
                raw,
            )
        except Exception as error:  # noqa: BLE001 — a fake that raises must still answer
            # 400 rather than 500: the client retries a 500 four times, a minute
            # apart, and a broken double would spend that minute before saying
            # anything. This one is our fault and says so at once.
            self.server.board.refused.append(f"{method} {parsed.path}: {error}")  # type: ignore[attr-defined]
            status, payload = 400, {"message": f"{type(error).__name__}: {error}"}
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextmanager
def _notion_server():
    """A Notion answering on a loopback port nobody chose in advance."""
    board = Board()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.board = board  # type: ignore[attr-defined]
    board.address = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", board
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- the machine the runner thinks it is on ----------------------------------


GIT = '''
"""`git`, recorded and then run for real.

A scenario that wants to say "this ticket touched no repository" has to be able
to say it of every git command, not of the ones somebody thought of.
"""
import json, os, sys

# Written in when the script is laid down: the real git, found before this one
# went to the head of the PATH.
REAL = None

log = os.environ.get("FAKE_GIT_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}) + "\\n")
os.execv(REAL, ["git", *sys.argv[1:]])
'''

CLAUDE = '''
"""A Claude Code session, reduced to what the runner reads of one.

It does the one thing a session is judged on — leaving something behind — and
says so in the stream the runner parses: a commit in a repository, an
`ANSWER.md` where there is none. `FAKE_CLAUDE_FAIL` makes it the other kind of
session, the one that stops and explains itself.
"""
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
# The prompt is never an argument: `--print` reads it from stdin, where the
# runner always sends it — see session.py.
prompt = sys.stdin.read()
session = next((args[args.index(flag) + 1] for flag in ("--session-id", "--resume") if flag in args), "")
model = args[args.index("--model") + 1] if "--model" in args else ""

log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(
            {"cwd": os.getcwd(), "session": session, "model": model, "prompt": prompt,
             "budget": args[args.index("--max-budget-usd") + 1]
             if "--max-budget-usd" in args else "",
             "base_url": os.environ.get("ANTHROPIC_BASE_URL", "")}
        ) + "\\n")


# A session killed from outside, as the OOM killer does it: `FAKE_CLAUDE_KILL`
# is how many starts die of SIGKILL before one is let through, counted in the
# file `FAKE_CLAUDE_COUNT` names.
dying = int(os.environ.get("FAKE_CLAUDE_KILL", "0") or 0)
counter = Path(os.environ.get("FAKE_CLAUDE_COUNT", "/nonexistent/count"))
if dying and counter.parent.is_dir():
    starts = int(counter.read_text() or 0) if counter.exists() else 0
    counter.write_text(str(starts + 1))
    if starts < dying:
        import signal
        os.kill(os.getpid(), signal.SIGKILL)

# A session that lasts: it says it has started, then waits for the test to let
# it go — the window in which something else happens to the machine under it.
held = os.environ.get("FAKE_CLAUDE_HOLD", "")
if held:
    Path(held + ".started").touch()
    for _ in range(600):
        if os.path.exists(held):
            break
        time.sleep(0.1)


def emit(event):
    print(json.dumps(event), flush=True)


emit({"type": "system", "subtype": "init", "session_id": session})

# The short session that classifies a ticket with no type answers one JSON
# object and leaves nothing behind — `FAKE_CLAUDE_KIND` is that object.
if "say what kind of ticket it is" in prompt:
    said = os.environ.get("FAKE_CLAUDE_KIND", "")
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 1, "total_cost_usd": 0.001})
    raise SystemExit(0)

# The same for the sub-type of a code ticket that has its type already.
if "say what kind of change it is" in prompt:
    said = os.environ.get("FAKE_CLAUDE_SUBTYPE", "")
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 1, "total_cost_usd": 0.001})
    raise SystemExit(0)

# The short session that proposes ideas answers a JSON array and nothing more:
# three of them, named after the project it is told the scope of, and different
# from one call to the next — by how many are already listed in the prompt —
# since what is repeated is dropped.
if "You are proposing ideas" in prompt:
    import re

    named = re.search(r"one project, (.+?): ideas", prompt)
    known = prompt.count("- Ajouter ")
    topics = (
        ["le mode sombre", "l'export csv", "la recherche globale", "les raccourcis clavier",
         "un tableau de bord", "les notifications push", "un journal d'audit", "le partage par lien",
         "les modèles de tickets", "une corbeille", "un tutoriel guidé", "les filtres enregistrés"]
    )[known % 10:][:3]
    said = json.dumps([
        {"title": "Ajouter " + topic + " à " + (named.group(1) if named else "l'espace"),
         "description": "Parce que.", "kind": "ticket", "where": "src", "done": ["ok"], "out": []}
        for topic in topics
    ])
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 1, "total_cost_usd": 0.01})
    raise SystemExit(0)

# What a session says on its way, before it says how it ended — the sentence
# the live report writes into the ticket, and nothing else does.
narrated = os.environ.get("FAKE_CLAUDE_SAY", "")
if narrated:
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": narrated}]}})

# What the session cost, for the ones that end badly: `FAKE_CLAUDE_COST`.
spent = float(os.environ.get("FAKE_CLAUDE_COST", "0") or 0)

# The CLI stopping itself at `--max-budget-usd`, which is how it says so.
if os.environ.get("FAKE_CLAUDE_OVER_BUDGET") and "--max-budget-usd" in args:
    emit({"type": "result", "subtype": "error_max_budget_usd", "is_error": False,
          "session_id": session, "num_turns": 7, "total_cost_usd": spent})
    raise SystemExit(0)

# A session that stops to ask, and has been paid for.
asked = os.environ.get("FAKE_CLAUDE_BLOCK", "")
if asked:
    emit({"type": "result", "subtype": "success", "is_error": False,
          "result": "RESULT: blocked — " + asked, "session_id": session,
          "num_turns": 2, "total_cost_usd": spent})
    raise SystemExit(0)

refused = os.environ.get("FAKE_CLAUDE_FAIL", "")
if refused:
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
          "result": refused, "session_id": session, "num_turns": 1, "total_cost_usd": spent})
    raise SystemExit(1)

here = Path.cwd()


def finish(said, turns=3, cost=0.02):
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": turns, "total_cost_usd": cost})
    raise SystemExit(0)


# A session that does its work and stops without saying so: no ANSWER.md, no
# RESULT line. Picked up again to write its report, `once` writes it and
# `always` says nothing a second time either.
silent = os.environ.get("FAKE_CLAUDE_SILENT", "")
if silent and "You stopped without writing your report" in prompt:
    if silent == "always":
        finish("Je regarde encore.", turns=1, cost=0.01)
    (here / "ANSWER.md").write_text("Le domaine pointe sur le serveur.", encoding="utf-8")
    finish("RESULT: ok — compte rendu écrit", turns=1, cost=0.01)
if silent:
    finish("Je branche le domaine.")

# A code ticket whose work happened outside the repository: nothing committed,
# and the report says where it went — `FAKE_CLAUDE_ELSEWHERE` is that report.
elsewhere = os.environ.get("FAKE_CLAUDE_ELSEWHERE", "")
if elsewhere and (here / ".git").exists():
    finish(elsewhere + "\\nRESULT: ok — fait hors du dépôt")

# A code ticket that changed a file and committed nothing.
if os.environ.get("FAKE_CLAUDE_DIRTY") and (here / ".git").exists():
    (here / "FAKE.md").write_text("changed, never committed\\n", encoding="utf-8")
    finish("J'ai modifié FAKE.md.\\nRESULT: ok — le fichier est modifié")

# A pull request whose rebase stopped on a conflict. The fake resolves it the
# way the prompt asks — both sides kept — by dropping the markers and keeping
# every line, then carries the rebase to its end. `FAKE_CLAUDE_RESOLVE=blocked`
# is the other session: the one that reads the conflict as a decision.
if "You are resolving that conflict" in prompt:
    if os.environ.get("FAKE_CLAUDE_RESOLVE") == "blocked":
        said = ("Les deux côtés réécrivent FAKE.md, de deux façons incompatibles.\\n"
                "RESULT: blocked — FAKE.md : garder le texte du ticket ou celui de main ?")
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
        emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
              "session_id": session, "num_turns": 2, "total_cost_usd": 0.05})
        raise SystemExit(0)
    identity = ["-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                "-c", "commit.gpgsign=false"]
    resolved = []
    while True:
        unmerged = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=here,
                                  capture_output=True, text=True).stdout.split()
        if not unmerged:
            break
        for name in unmerged:
            lines = (here / name).read_text(encoding="utf-8").splitlines()
            kept = [line for line in lines
                    if not line.startswith(("<<<<<<<", "=======", ">>>>>>>"))]
            (here / name).write_text("\\n".join(kept) + "\\n", encoding="utf-8")
            subprocess.run(["git", "add", name], cwd=here, check=True)
            resolved.append(name)
        subprocess.run(["git", *identity, "rebase", "--continue"], cwd=here,
                       env={**os.environ, "GIT_EDITOR": "true"}, capture_output=True)
    said = ("\\n".join(f"- `{name}` : les deux versions gardées" for name in resolved)
            + "\\nVérifications : aucune dans ce dépôt.\\n"
            "RESULT: ok — conflit résolu en gardant les deux côtés")
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 4, "total_cost_usd": 0.05})
    raise SystemExit(0)

# A second ticket landed on the base branch while this session was running.
# `FAKE_CLAUDE_MOVES_BASE` names the clone it landed in: a commit on `main`,
# pushed — which is what a merge on GitHub does under a session that started an
# hour ago, and what the branch has to be replayed onto before its own pull
# request is opened.
moved = os.environ.get("FAKE_CLAUDE_MOVES_BASE", "")
if moved and (here / ".git").exists():
    clone = Path(moved)
    (clone / "OTHER.md").write_text("un autre ticket est passé par là\\n", encoding="utf-8")
    subprocess.run(["git", "add", "OTHER.md"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Autre", "-c", "user.email=autre@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Un autre ticket"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)

if (here / ".git").exists():
    # What a session does on its way, for the journal to keep and the page not
    # to: a sentence, and the command that follows it.
    emit({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "J'écris FAKE.md puis je le commite."},
        {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m 'Écrit par la fausse session'"}},
    ]}})
    (here / "FAKE.md").write_text("the session was here\\n", encoding="utf-8")
    # More files in the same commit, for a test that needs a branch touching a
    # bundle and a changelog: `FAKE_CLAUDE_ALSO` maps a sentence of the ticket
    # to the files, path to text, that the session of that ticket writes.
    also = {}
    for needle, files in json.loads(os.environ.get("FAKE_CLAUDE_ALSO") or "{}").items():
        if needle in prompt:
            also.update(files)
    for name, text in also.items():
        (here / name).parent.mkdir(parents=True, exist_ok=True)
        (here / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "FAKE.md", *also], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Écrit par la fausse session"],
                   cwd=here, check=True, capture_output=True)
    said = "CAVEAT: pas essayé sur mobile\\nRESULT: ok — un fichier écrit et commité"
else:
    (here / "ANSWER.md").write_text("La réponse.", encoding="utf-8")
    said = "RESULT: ok — la réponse est dans ANSWER.md"

emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
      "session_id": session, "num_turns": 3, "total_cost_usd": 0.02})
'''

GH = '''
"""`gh`, reduced to the questions the runner asks it.

Opening a pull request is the one gesture of a code ticket that leaves the
machine, so it is the one worth recording: what was asked, from where, and the
URL handed back — which is what the ticket is then supposed to carry.

Merging is the other one, and it is not recorded so much as *carried out*: the
bare remote is here, so this asks it the very question GitHub asks — is the base
branch an ancestor of this one? — and refuses the merge when it is not, in
GitHub's own words. Which is what makes the replay worth testing: a branch that
has been put back on top of `main` merges, one that has not does not.
"""
import json, os, subprocess, sys

args = sys.argv[1:]
# Two files, and the difference matters: the log says what this pass asked and
# is emptied before each one, while the state is what GitHub would still know
# next week — the pull requests that were opened, and those that were merged.
log = os.environ.get("FAKE_GH_LOG", "")
state = os.environ.get("FAKE_GH_STATE", "")


def option(name):
    return args[args.index(name) + 1] if name in args else ""


def recorded():
    if not state or not os.path.exists(state):
        return []
    with open(state, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write(entry):
    for path in (log, state):
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\\n")


def git(*arguments, cwd=None):
    return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True)


def pull_request(url):
    return next(
        (one for one in recorded() if one["command"] == "pr create" and one["url"] == url), {}
    )


if args[:2] == ["pr", "create"]:
    number = len([one for one in recorded() if one["command"] == "pr create"]) + 1
    url = "https://github.com/fake/repo/pull/" + str(number)
    # The branch and the remote it was made from: what GitHub knows of a pull
    # request, and what every question below is answered out of.
    write({"command": "pr create", "cwd": os.getcwd(), "url": url,
           "base": option("--base"), "title": option("--title"), "body": option("--body"),
           "token": os.environ.get("GH_TOKEN", ""),
           "branch": git("rev-parse", "--abbrev-ref", "HEAD", cwd=os.getcwd()).stdout.strip(),
           "remote": git("remote", "get-url", "origin", cwd=os.getcwd()).stdout.strip()})
    print("Creating pull request for " + option("--base"))
    print(url)
    raise SystemExit(0)

if args[:2] == ["pr", "merge"]:
    url = args[2] if len(args) > 2 else ""
    # A refusal that is about the rules rather than the branch — a check still
    # red, a review still required — in whatever words the scenario chose.
    if os.environ.get("FAKE_GH_REFUSE"):
        print(os.environ["FAKE_GH_REFUSE"], file=sys.stderr)
        raise SystemExit(1)
    opened = pull_request(url)
    if opened:
        behind = git("merge-base", "--is-ancestor", opened["base"], opened["branch"],
                     cwd=opened["remote"]).returncode != 0
        if behind:
            print("Pull request is not mergeable: the merge commit cannot be cleanly created",
                  file=sys.stderr)
            raise SystemExit(1)
        # Merged, and merged for real: the base branch of the bare remote moves
        # to what the pull request holds, so a test can read the result.
        landed = git("rev-parse", opened["branch"], cwd=opened["remote"]).stdout.strip()
        git("update-ref", "refs/heads/" + opened["base"], landed, cwd=opened["remote"])
    write({"command": "pr merge", "url": url})
    print("Merged pull request")
    raise SystemExit(0)

if args[:2] == ["pr", "comment"]:
    write({"command": "pr comment", "url": args[2] if len(args) > 2 else "",
           "body": option("--body")})
    raise SystemExit(0)

# The CI of every pull request, as `FAKE_GH_CHECKS` sets it: GitHub's check
# runs, as `statusCheckRollup` lists them. Like the gh Ubuntu ships (2.46), this
# one knows no `pr checks --json` — the runner falls back on the rollup.
checks = json.loads(os.environ.get("FAKE_GH_CHECKS") or "[]")
if args[:2] == ["pr", "checks"]:
    if "--json" in args:
        print("unknown flag: --json", file=sys.stderr)
        raise SystemExit(1)
    if not checks:
        print("no checks reported on the branch", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0 if all(one["conclusion"] == "SUCCESS" for one in checks) else 1)

# What GitHub writes on a job it refused to start, read as `.[].message`.
if args[:1] == ["api"] and any(part.endswith("/annotations") for part in args):
    print(os.environ.get("FAKE_GH_ANNOTATION", ""))
    raise SystemExit(0)

if args[:2] == ["pr", "view"]:
    url = args[2] if len(args) > 2 and args[2].startswith("http") else ""
    opened = pull_request(url)
    if "statusCheckRollup" in args:
        print(json.dumps({"statusCheckRollup": checks}))
        raise SystemExit(0)
    if "headRefName,baseRefName" in args:
        if not opened:
            raise SystemExit(1)
        print(opened["branch"] + " " + opened["base"])
        raise SystemExit(0)
    if "body" in args:
        if not opened:
            raise SystemExit(1)
        print(opened["body"])
        raise SystemExit(0)
    # What GitHub says of a branch before anybody asks for the merge: behind
    # when its base is no longer underneath, conflicting when the two cannot
    # even be merged — which `git merge-tree` answers without a worktree.
    if "mergeable,mergeStateStatus" in args:
        if not opened:
            raise SystemExit(1)
        remote = opened["remote"]
        if git("merge-base", "--is-ancestor", opened["base"], opened["branch"],
               cwd=remote).returncode == 0:
            print("MERGEABLE CLEAN")
        elif git("merge-tree", "--write-tree", opened["base"], opened["branch"],
                 cwd=remote).returncode != 0:
            print("CONFLICTING DIRTY")
        else:
            print("MERGEABLE BEHIND")
        raise SystemExit(0)
    # `--json state` asks about a pull request by its URL; `--json url` asks
    # whether this branch already has one, and here it never does.
    if "state" in args:
        merged = any(
            one["command"] == "pr merge" and one["url"] == url for one in recorded()
        )
        print("MERGED" if merged else "OPEN")
        raise SystemExit(0)
    raise SystemExit(1)

if args[:2] == ["pr", "list"]:
    raise SystemExit(0)

raise SystemExit(1)
'''


def _script(path: Path, source: str) -> None:
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(0o755)


def _binaries(into: Path) -> None:
    """The three commands the runner shells out to, at the head of `PATH`.

    `git` is the real one behind a recorder, `claude` and `gh` are doubles —
    those two are the network and the money.
    """
    into.mkdir(parents=True, exist_ok=True)
    real = shutil.which("git") or "/usr/bin/git"
    _script(into / "git", GIT.replace("REAL = None", f"REAL = {real!r}"))
    _script(into / "claude", CLAUDE)
    _script(into / "gh", GH)


def _git(args: list[str], cwd: Path) -> None:
    """A git command of the fixtures' own, identity included.

    Spelled out rather than inherited: a machine whose global configuration has
    no name, or signs every commit, must not be the reason a test fails.
    """
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Bench",
            "-c",
            "user.email=bench@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}"
        )


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# -- the board, the configuration, the run -----------------------------------


TICKETS = {
    "Name": {"type": "title", "title": {}},
    "Status": {
        "type": "status",
        "status": {
            "options": [
                {"name": name}
                for name in (
                    "Ready",
                    "In progress",
                    "In review",
                    "Validated",
                    "Done",
                    "Failed",
                    "Blocked",
                )
            ]
        },
    },
    "Project": {"type": "relation", "relation": {}},
    "Runner": {"type": "rich_text", "rich_text": {}},
    "Pull Request": {"type": "url", "url": {}},
    "Session": {"type": "rich_text", "rich_text": {}},
    "Priority": {"type": "number", "number": {}},
    "Model": {"type": "select", "select": {"options": [{"name": "opus"}]}},
    "Scheduled": {"type": "date", "date": {}},
    "Duration": {"type": "number", "number": {}},
    "Cost": {"type": "number", "number": {}},
}

# The installation every scenario runs on. The road under test is on — fetch,
# push, pull request — and what is off is not cheating: each of those is a road
# of its own, already covered in `tests/run.py`, or one that reaches outside the
# machine, which is the one thing a test may not do.
SETTINGS = {
    "fetch": True,
    "push": True,
    "open_pull_request": True,
    "keep_worktree_on_failure": False,  # so "no orphan worktree" means something
    "attach_sessions": False,  # nothing is moved into ~/.claude
    "notify": False,  # no desktop notification from a test
    "progress": False,  # the live report is its own machinery
    "reply": False,  # so is answering comments
    "schedule": False,
    "auto_update": False,
    "log_retention_days": 0,
    "timeout_minutes": 1,
    "max_concurrent": 2,
    "relaunch_delay_seconds": 0,  # a killed session is resumed at once
    "min_free_memory_mb": 0,  # whatever this machine has free today
    "min_free_disk_mb": 0,  # and whatever disk it has left
}


class Bench:
    """One machine, one board, and the gestures a scenario is written in."""

    def __init__(self, root: Path, board: Board, database: str, logs: dict[str, Path]) -> None:
        self.root = root
        self.board = board
        self.database = database
        self.logs = logs
        self.config = root / "config.toml"

    # -- fixtures ------------------------------------------------------------

    def repository(self, name: str) -> Path:
        """A clone with a bare remote of its own, standing in for GitHub."""
        bare = self.root / "remotes" / f"{name}.git"
        work = self.root / "workspace" / name
        bare.parent.mkdir(parents=True, exist_ok=True)
        work.parent.mkdir(parents=True, exist_ok=True)
        _git(["init", "--bare", "--initial-branch=main", str(bare)], self.root)
        _git(["init", "--initial-branch=main", str(work)], self.root)
        (work / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        _git(["add", "README.md"], work)
        _git(["commit", "-m", "premier commit"], work)
        _git(["remote", "add", "origin", str(bare)], work)
        _git(["push", "--set-upstream", "origin", "main"], work)
        return work

    def project(self, name: str, repository: Path | None = None, brief: str = "") -> str:
        """A project page: a title, and the path its tickets are worked on."""
        properties = {"Name": _stored({"title": _rich(name)})}
        if repository is not None:
            properties["Path"] = _stored({"rich_text": _rich(str(repository))})
        return self.board.page(properties, body=brief)

    def ticket(self, title: str, body: str, project: str = "", status: str = "Ready") -> str:
        properties = {
            "Name": _stored({"title": _rich(title)}),
            "Status": _stored({"status": {"name": status}}),
        }
        if project:
            properties["Project"] = _stored({"relation": [{"id": project}]})
        return self.board.page(properties, database=self.database, body=body)

    def typed(self) -> None:
        """The board given its Type column, as `init` gives it to an older one."""
        # A copy: the schema every scenario starts from is shared, and must stay
        # the board of the scenarios that never heard of a type.
        database = self.board.databases[self.database]
        database["properties"] = {
            **database["properties"],
            "Type": {
                "type": "select",
                "select": {
                    "options": [
                        {"name": name}
                        for name in ("Code", "Rédaction", "Action externe", "Publication")
                    ]
                },
            },
        }

    def subtyped(self) -> None:
        """The board given its Type and Sous-type columns, as `init` gives them now."""
        self.typed()
        database = self.board.databases[self.database]
        database["properties"] = {
            **database["properties"],
            "Sous-type": {
                "type": "select",
                "select": {
                    "options": [
                        {"name": name}
                        for name in (
                            "Bug",
                            "Feature",
                            "Amélioration",
                            "Chore",
                            "Refactor",
                            "Perf",
                            "Docs",
                            "Sécurité",
                        )
                    ]
                },
            },
        }

    def with_ci(self, repository: Path) -> None:
        """A workflow on `main`: the runner now waits for the checks of its pull requests."""
        workflows = repository / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        _git(["add", ".github"], repository)
        _git(["commit", "-m", "une CI"], repository)
        _git(["push", "origin", "main"], repository)

    def move(self, ticket: str, column: str) -> None:
        """A ticket dragged from one column to the next, as you would in Notion."""
        self.board.pages[ticket]["properties"]["Status"] = _stored({"status": {"name": column}})

    def land(self, repository: Path, filename: str, text: str = "un autre ticket\n") -> None:
        """Another ticket merged: one commit on `main`, pushed to the remote.

        What every pull request still open is suddenly behind on, and the whole
        of what a repository taking ten tickets a day does to them.
        """
        (repository / filename).write_text(text, encoding="utf-8")
        _git(["add", filename], repository)
        _git(["commit", "-m", f"Un autre ticket — {filename}"], repository)
        _git(["push", "origin", "main"], repository)

    # -- running -------------------------------------------------------------

    def run(self) -> list[dict]:
        """One pass of the runner, exactly the one the timer makes."""
        for path in self.logs.values():
            path.write_text("", encoding="utf-8")
        results = Runner(C.load(self.config), quiet=True).tick()
        assert not self.board.refused, f"the fake Notion could not answer {self.board.refused}"
        return results

    # -- reading back --------------------------------------------------------

    def status(self, ticket: str) -> str:
        return str(self.board.value(ticket, "Status") or "")

    def git_calls(self) -> list[dict]:
        return _lines(self.logs["FAKE_GIT_LOG"])

    def pull_requests(self) -> list[dict]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr create"]

    def pull_request_comments(self) -> list[dict]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr comment"]

    def merges(self) -> list[dict]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr merge"]

    def sessions(self) -> list[dict]:
        return _lines(self.logs["FAKE_CLAUDE_LOG"])

    def worktrees(self, repository: Path) -> list[str]:
        """The worktrees git knows about, the repository itself excluded."""
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(repository),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return [
            line.split(" ", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("worktree ") and line.split(" ", 1)[1] != str(repository)
        ]

    def branches(self, repository: Path) -> list[str]:
        """What the bare remote of that repository holds."""
        bare = self.root / "remotes" / f"{repository.name}.git"
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=str(bare),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def content(self, repository: Path, branch: str, path: str) -> str:
        """A file as the bare remote holds it on that branch."""
        bare = self.root / "remotes" / f"{repository.name}.git"
        result = subprocess.run(
            ["git", "show", f"{branch}:{path}"],
            cwd=str(bare),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout

    def files_on(self, repository: Path, branch: str) -> list[str]:
        bare = self.root / "remotes" / f"{repository.name}.git"
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", branch],
            cwd=str(bare),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


CONFIGURATION = """# Written by tests/functional.py — a whole installation, in a temporary directory.
[notion]
tickets_database = "{database}"

[runner]
workspace_root = "{workspace}"
{settings}
"""


@contextmanager
def bench(**overrides: object):
    """A machine with a Notion, a workspace and a PATH of its own.

    Everything it changes is put back on the way out, the temporary directory
    included — so two scenarios never share a board, a state directory or a
    branch, and a scenario that fails leaves the machine as it found it.
    """
    with tempfile.TemporaryDirectory(prefix="ponos-functional-") as directory:
        root = Path(directory)
        _binaries(root / "bin")
        with _notion_server() as (api, board):
            logs = {
                name: root / "logs" / f"{name.lower()}.jsonl"
                for name in ("FAKE_GIT_LOG", "FAKE_GH_LOG", "FAKE_CLAUDE_LOG")
            }
            for path in logs.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            environment = {
                notion.API_ENV: api,
                # What GitHub would still know next week, unlike the logs, which
                # are emptied before each pass — see the fake `gh`.
                "FAKE_GH_STATE": str(root / "logs" / "github.jsonl"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "PATH": f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_CLAUDE_FAIL": "",
                "FAKE_CLAUDE_KIND": "",
                "FAKE_CLAUDE_SAY": "",
                "FAKE_CLAUDE_RESOLVE": "",
                "FAKE_CLAUDE_COST": "",
                "FAKE_CLAUDE_BLOCK": "",
                "FAKE_CLAUDE_OVER_BUDGET": "",
                "FAKE_CLAUDE_KILL": "",
                "FAKE_CLAUDE_SILENT": "",
                "FAKE_CLAUDE_ELSEWHERE": "",
                "FAKE_CLAUDE_DIRTY": "",
                "FAKE_CLAUDE_SUBTYPE": "",
                "FAKE_GH_REFUSE": "",
                "FAKE_GH_CHECKS": "",
                "FAKE_GH_ANNOTATION": "",
                **{name: str(path) for name, path in logs.items()},
            }
            with _environ(environment):
                database = board.database("Tickets", TICKETS)
                settings = {**SETTINGS, **overrides}
                (root / "config.toml").write_text(
                    CONFIGURATION.format(
                        database=database,
                        workspace=root / "workspace",
                        settings="\n".join(
                            f"{key} = {json.dumps(value)}" for key, value in settings.items()
                        ),
                    ),
                    encoding="utf-8",
                )
                # Beside the file, where secrets live: config.toml holds none.
                (root / "secrets.env").write_text(
                    "PONOS_NOTION_TOKEN=ntn_functional_tests\n", encoding="utf-8"
                )
                (root / "secrets.env").chmod(0o600)
                yield Bench(root, board, database, logs)


@contextmanager
def _environ(changes: dict[str, str]):
    previous = {name: os.environ.get(name) for name in changes}
    os.environ.update(changes)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def runner_settings(**overrides: object):
    """What a case changes of `[runner]` on the `machine` it is given."""

    def settle(function):
        function.runner_settings = overrides
        return function

    return settle


@fixture
def machine(case):
    """The `bench` a case runs on, with the `@runner_settings` it asked for."""
    with bench(**getattr(case, "runner_settings", {})) as machine:
        yield machine


# -- the scenarios -----------------------------------------------------------


@case
@runner_settings(ideas_schedule="every_4h", ideas_scope="selected", ideas_per_batch=3)
def a_scheduled_pass_finds_ideas_for_the_projects_ticked_and_for_those_only(machine):
    """Every four hours, two projects of three ticked: ideas for them at each pass.

    The whole road of the pass, on the doubles: the fake Notion's project index,
    the fake `claude` answering ten at a time, the console's own `Api` reading
    the configuration the machine wrote. A project that turns itself off from its
    page is left out of the next pass; one added after the schedule was set is
    covered as soon as the scope is "all".
    """
    from ponos import idea_schedule, ideas
    from ponos.web import api as web_api

    alpha = machine.project("Alpha").replace("-", "")
    beta = machine.project("Beta").replace("-", "")
    gamma = machine.project("Gamma").replace("-", "")
    C.edit(machine.config, [("runner", "ideas_projects", f"{alpha}, {gamma}")])
    api = web_api.Api(C.load(machine.config))
    # The fake Notion has no workspace page to find the projects database under,
    # so the console is given the index it would have read from it.
    api._projects = {
        identifier: {
            "id": identifier,
            "name": name,
            "kind": "code",
            "url": "",
            "repository": "",
            "path": "",
        }
        for identifier, name in ((alpha, "Alpha"), (beta, "Beta"), (gamma, "Gamma"))
    }
    api._projects_at = time.time()
    try:
        start = datetime.now().astimezone()
        assert api.planned.look(start) is None, "the first moment is drawn, not fired"
        first = api.planned.look(start + timedelta(hours=4, minutes=1))
        assert first is not None and first.projects == 2 and first.found == 6
        assert [len(ideas.listed(project)) for project in (alpha, beta, gamma)] == [3, 0, 3]
        assert api.planned.look(start + timedelta(hours=4, minutes=2)) is None
        second = api.planned.look(start + timedelta(hours=8, minutes=5))
        assert second is not None and second.found == 6
        assert [len(ideas.listed(project)) for project in (alpha, beta, gamma)] == [6, 0, 6]
        assert idea_schedule.last().found == 6
        calls = [call for call in machine.sessions() if "You are proposing ideas" in call["prompt"]]
        assert len(calls) == 4, "one session per project and per pass"

        api.save_project_settings(alpha, {"ideas": {"enabled": False}})
        third = api.planned.look(start + timedelta(hours=12, minutes=10))
        assert third is not None and third.projects == 1
        assert [len(ideas.listed(project)) for project in (alpha, beta, gamma)] == [6, 0, 9]

        planned = api.planned.save({"schedule": "off"})
        assert planned["next"] == "" and planned["settings"]["schedule"] == "off"
        assert api.planned.look(start + timedelta(days=3)) is None, "off is no pass at all"
    finally:
        api.watch.stop()


@case
def a_code_ticket_comes_back_as_a_pull_request_with_nothing_but_an_access_token(machine):
    """`PONOS_GITHUB_TOKEN` is the whole of GitHub's setup: no App, no `gh` account.

    The pull request is opened with the token, and the token is written
    nowhere the board, the journal or the configuration could show it.
    """
    token = "github_pat_functional_0123456789abcdefghij"
    with _environ({"PONOS_GITHUB_TOKEN": token}):
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

        results = machine.run()

        assert results and results[0]["status"] == "done", results
        opened = machine.pull_requests()
        assert len(opened) == 1 and opened[0]["token"] == token, opened
        assert not any(token in said for said in machine.board.said(ticket)), (
            "the token reached the ticket"
        )
        for path in Path(os.environ["XDG_CONFIG_HOME"]).rglob("*"):
            assert not path.is_file() or token not in path.read_text(errors="replace"), path


@case
def a_code_ticket_comes_back_as_a_pull_request(machine):
    """Ready → worktree → session → branch → pull request → the ticket says so.

    The whole road in one pass, and the last step is the one that goes wrong
    quietly: a pull request that opens and is never written back onto the ticket
    leaves a board saying the work is still to do.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

    results = machine.run()

    assert len(results) == 1, results
    assert results[0]["status"] == "done", results
    assert machine.status(ticket) == "In review", machine.status(ticket)

    branch = results[0]["branch"]
    assert branch.startswith("ticket/corriger-l-entete-"), branch
    assert branch in machine.branches(repository), machine.branches(repository)
    assert "FAKE.md" in machine.files_on(repository, branch)

    opened = machine.pull_requests()
    assert len(opened) == 1, opened
    assert opened[0]["base"] == "main", opened[0]
    assert opened[0]["title"] == "Corriger l'entête", opened[0]
    page = machine.board.pages[ticket]["url"]
    assert page in opened[0]["body"], "the pull request does not link back to the ticket"
    assert machine.board.value(ticket, "Pull Request") == opened[0]["url"]

    assert str(machine.board.value(ticket, "Runner") or "").startswith("ponos@")
    assert machine.board.value(ticket, "Session"), "the session was not written onto the ticket"
    assert machine.board.value(ticket, "Duration") is not None

    said = machine.board.said(ticket)
    assert said, "the ticket came back without a word"
    assert opened[0]["url"] in said[-1], said[-1]
    # What the session could not check rides on the report, for the console's
    # Decide panel to read back — see decisions.py.
    assert said[-1].splitlines()[3].endswith(": pas essayé sur mobile"), said[-1]
    assert not machine.worktrees(repository), "a worktree was left behind on a run that worked"

    # Every step in the local journal — with the live block off, too: it
    # is written whatever the board and whatever `runner.progress` says.
    runs = journal.runs(ticket)
    assert len(runs) == 1, runs
    assert runs[0]["status"] == "done" and runs[0]["reason"] == opened[0]["url"], runs[0]
    assert runs[0]["cost_usd"] == 0.02, runs[0]
    steps = journal.steps(runs[0]["id"])["steps"]
    assert [(step["kind"], step["label"]) for step in steps] == [
        ("said", "J'écris FAKE.md puis je le commite."),
        ("tool", "Bash"),
        ("said", "CAVEAT: pas essayé sur mobile\nRESULT: ok — un fichier écrit et commité"),
    ], steps
    assert "git commit" in steps[1]["detail"], steps[1]
    db.close()


@case
@runner_settings(progress=True)
def the_page_keeps_what_the_agent_said_and_the_journal_every_step(machine):
    """The ticket gets the gist; the console, reading the journal, gets the rest.

    A sentence and a command, from one session: the sentence goes onto the
    page, under the live block, and the command does not — it is in the
    journal, beside the sentence, in the order they came.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    page = "\n".join(machine.board.body(key) for key in list(machine.board.blocks))
    assert "Le titre est faux, corrige-le." in page, page
    assert "J'écris FAKE.md puis je le commite." in page, page
    assert "RESULT: ok — un fichier écrit et commité" in page, page
    assert "git commit" not in page and "Bash" not in page, "a command was written onto the ticket"
    (run,) = journal.runs(ticket)
    kinds = [step["kind"] for step in journal.steps(run["id"])["steps"]]
    assert kinds == ["said", "tool", "said"], kinds
    db.close()


@case
def a_writing_ticket_is_answered_in_its_page_and_touches_no_repository(machine):
    """A project with no repository: the deliverable is the Notion page.

    And nothing else. A document ticket that quietly made a worktree, or ran one
    git command anywhere, would be a writing task turned into a commit on
    something — which is the failure this scenario exists to catch.
    """
    project = machine.project("Lettre d'information", None, brief="On écrit court.")
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes sur l'automne.", project)

    results = machine.run()

    assert len(results) == 1, results
    assert results[0]["status"] == "done" and results[0]["kind"] == "document", results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    assert "La réponse." in machine.board.body(ticket), machine.board.body(ticket)
    assert results[0]["blocks"] > 0

    assert not machine.git_calls(), machine.git_calls()
    assert not machine.pull_requests(), "a document ticket opened a pull request"
    assert machine.board.value(ticket, "Pull Request") is None

    sessions = machine.sessions()
    assert len(sessions) == 1, sessions
    assert "On écrit court." in sessions[0]["prompt"], "the project's brief never reached it"
    state = Path(os.environ["XDG_STATE_HOME"]) / "ponos"
    assert not (state / "worktrees").exists(), "a document ticket made a worktree"
    assert not list((state / "scratch").glob("*")), "its scratch directory was left behind"


@case
@runner_settings(progress=True)
def a_ticket_run_again_is_not_briefed_on_its_previous_run(machine):
    """Ready a second time: the session reads the brief, not the last run's story.

    Each run leaves its live report on the page, folded in a toggle. A ticket
    sent back to Ready that handed all of it to its next session would pay for
    every step of every earlier run, at every run — and hand it old steps to
    take for instructions. The answer the first run wrote stays: it is part of
    what the page now says.
    """
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes sur l'automne.", project)

    with _environ({"FAKE_CLAUDE_SAY": "Je relis d'abord la charte éditoriale."}):
        results = machine.run()
    assert results[0]["status"] == "done", results
    toggles = [block for block in machine.board.blocks[ticket] if block["type"] == "toggle"]
    assert len(toggles) == 1 and toggles[0]["has_children"], machine.board.blocks[ticket]
    story = machine.board.blocks[toggles[0]["id"]]
    assert any("la charte éditoriale" in str(block) for block in story), story

    machine.move(ticket, "Ready")
    machine.board.requests.clear()
    results = machine.run()
    assert results[0]["status"] == "done", results

    prompt = machine.sessions()[-1]["prompt"]
    assert "Deux paragraphes sur l'automne." in prompt, prompt
    assert "La réponse." in prompt, "the answer the first run wrote is still the page's"
    assert "la charte éditoriale" not in prompt, "the first run's story reached the second"
    assert f"GET /v1/blocks/{toggles[0]['id']}/children" not in machine.board.requests, (
        "the first run's toggle was opened to be skipped"
    )


@case
def a_ticket_with_no_type_is_classified_then_published_only_once_validated(machine):
    """Ready with no type → classified → prepared → review → validated → done.

    On a project that *has* a repository, which is the case that matters: a
    publication there is still prepared in its page and never in a branch, and
    nothing leaves the machine between the two passes — only the one that comes
    after you moved it to Validated publishes it.
    """
    machine.typed()
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Annoncer la version 2", "Un post LinkedIn pour la v2.", project)
    os.environ["FAKE_CLAUDE_KIND"] = json.dumps(
        {
            "type": "publication",
            "reason": "Le ticket demande un post public.",
            "confidence": "high",
            "alternative": "",
        }
    )

    results = machine.run()

    assert [result["status"] for result in results] == ["done"], results
    assert results[0]["kind"] == "publication", results
    # Spelled the way the board already spells it, and said in a comment.
    assert machine.board.value(ticket, "Type") == "Publication"
    said = machine.board.said(ticket)
    assert said[0].startswith("🏷️") and "Le ticket demande un post public." in said[0], said
    assert machine.status(ticket) == "In review", "a publication is prepared, then read"
    sessions = machine.sessions()
    assert len(sessions) == 2, sessions
    assert "say what kind of ticket it is" in sessions[0]["prompt"]
    assert "prepare it, do not publish it" in sessions[1]["prompt"]
    assert str(repository) in sessions[1]["prompt"], "the repository is still there to read"
    assert not machine.git_calls() or all(
        "worktree" not in call["args"] for call in machine.git_calls()
    ), "a publication was given a worktree"
    assert not machine.pull_requests()
    assert "La réponse." in machine.board.body(ticket)

    # Nothing happens to a ticket in review, however many passes go by.
    assert machine.run() == [] and machine.status(ticket) == "In review"

    machine.move(ticket, "Validated")
    results = machine.run()

    assert [result.get("kind") for result in results] == ["delivery"], results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    published = machine.sessions()
    assert len(published) == 1 and "You are publishing, not producing" in published[0]["prompt"]
    assert machine.board.value(ticket, "Type") == "Publication", "the type is left alone"


@case
@runner_settings(force_validated_code=True)
def a_code_ticket_whose_validation_is_forced_is_merged_and_done_in_one_pass(machine):
    """Force validated for Code: the pull request is opened, then merged, unread.

    What the remote holds afterwards is the proof: `main` carries what the
    session wrote. And the report says why nobody was asked.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    results = machine.run()

    assert [result["status"] for result in results] == ["done"], results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    opened = machine.pull_requests()
    assert len(opened) == 1, opened
    merges = machine.merges()
    assert [merge["url"] for merge in merges] == [opened[0]["url"]], merges
    assert "FAKE.md" in machine.files_on(repository, "main")
    said = machine.board.said(ticket)
    assert "Validated automatically (Force validated: Code) — the global setting" in said[-1], said[
        -1
    ]
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_project_with_its_own_validation_is_read_before_the_file_in_both_directions():
    """Merged on the project that asked for it, kept for review on the one that did not.

    The file says the opposite of each project, and each project wins. The
    report on the merged one says the decision was the project's.
    """
    with bench(force_validated_code=False) as machine:
        perso = machine.project("Perso", machine.repository("perso"))
        client = machine.project("Client", machine.repository("client"))
        project_settings.set_validation(perso, "Perso", {"code": True})
        project_settings.set_validation(client, "Client", {"code": False})
        merged = machine.ticket("Corriger l'entête", "Le titre est faux.", perso)

        machine.run()

        assert machine.status(merged) == "Done", machine.status(merged)
        said = machine.board.said(merged)
        assert (
            "Validated automatically (Force validated: Code) — the project's setting" in said[-1]
        ), said[-1]
        db.close()

    with bench(force_validated_code=True) as machine:
        client = machine.project("Client", machine.repository("client"))
        project_settings.set_validation(client, "Client", {"code": False})
        kept = machine.ticket("Corriger le pied de page", "Le lien est faux.", client)

        machine.run()

        assert machine.status(kept) == "In review", machine.status(kept)
        assert not machine.merges(), machine.merges()
        assert "Validated automatically" not in machine.board.said(kept)[-1]
        db.close()


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_github_refuses_leaves_the_ticket_in_review_with_the_reason(machine):
    """Checks red, rights missing: not done, and the refusal on the card."""
    machine.board.databases[machine.database]["properties"] = {
        **machine.board.databases[machine.database]["properties"],
        "Progress": {"type": "rich_text", "rich_text": {}},
    }
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    os.environ["FAKE_GH_REFUSE"] = 'Required status check "build" is failing'

    machine.run()

    assert machine.status(ticket) == "In review", machine.status(ticket)
    assert "main" in machine.branches(repository)
    assert "FAKE.md" not in machine.files_on(repository, "main"), "merged all the same"
    said = machine.board.said(ticket)
    assert "Force validated: Code" in said[-1], said[-1]
    assert "is failing" in said[-1], said[-1]
    card = str(machine.board.value(ticket, "Progress") or "")
    assert "Not merged" in card and "is failing" in card, card


def _check_runs(*verdicts: str) -> str:
    """`FAKE_GH_CHECKS` for jobs that ended with these conclusions."""
    return json.dumps(
        [
            {
                "__typename": "CheckRun",
                "name": f"job {number}",
                "status": "COMPLETED",
                "conclusion": verdict,
                "detailsUrl": f"https://github.com/fake/repo/actions/runs/7/job/{number}",
            }
            for number, verdict in enumerate(verdicts, start=1)
        ]
    )


@case
@runner_settings(force_validated_code=True, max_concurrent=1)
def a_code_ticket_is_merged_once_its_ci_is_green_whatever_its_sub_type(machine):
    """Force validated reads the type, never the sub-type: written, from a prefix or
    deduced, each code ticket waits for its green CI and lands on `main`, done."""
    # One at a time, one repository each: the fake `gh` numbers its pull
    # requests as it goes, and two opened at once would share a number.
    machine.subtyped()
    repositories = []
    tickets = []
    for name, title, subtype in (
        ("site", "Corriger l'entête", "Bug"),
        ("blog", "[Feature] Un badge", ""),
        ("shop", "Le pied de page", ""),
    ):
        repository = machine.repository(name)
        machine.with_ci(repository)
        ticket = machine.ticket(title, "Une phrase.", machine.project(name, repository))
        machine.board.pages[ticket]["properties"]["Type"] = _stored({"select": {"name": "Code"}})
        if subtype:
            machine.board.pages[ticket]["properties"]["Sous-type"] = _stored(
                {"select": {"name": subtype}}
            )
        repositories.append(repository)
        tickets.append(ticket)
    written, prefixed, deduced = tickets
    os.environ["FAKE_CLAUDE_SUBTYPE"] = json.dumps(
        {"subtype": "bug", "reason": "Un lien cassé.", "confidence": "high"}
    )
    os.environ["FAKE_GH_CHECKS"] = _check_runs("SUCCESS", "SUCCESS")

    machine.run()

    for ticket, subtype in ((written, "Bug"), (prefixed, "Feature"), (deduced, "Bug")):
        assert machine.status(ticket) == "Done", (ticket, machine.status(ticket))
        assert machine.board.value(ticket, "Sous-type") == subtype, ticket
        assert "Force validated: Code" in machine.board.said(ticket)[-1]
    assert len(machine.merges()) == 3, machine.merges()
    assert all("FAKE.md" in machine.files_on(one, "main") for one in repositories)


@case
@runner_settings(force_validated_code=True)
def a_ticket_blocked_on_its_type_is_merged_once_somebody_gives_it(machine):
    """A type in doubt stops the ticket with the question; answered, it takes the
    whole road like any other, forced merge included."""
    machine.subtyped()
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("[Bug] Le formulaire", "Il ne part plus.", project)
    os.environ["FAKE_CLAUDE_KIND"] = json.dumps(
        {
            "type": "code",
            "reason": "Peut-être.",
            "confidence": "low",
            "alternative": "",
        }
    )

    machine.run()

    assert machine.status(ticket) == "Blocked", machine.status(ticket)
    assert "Type" in machine.board.said(ticket)[-1], machine.board.said(ticket)[-1]
    assert not machine.pull_requests()

    machine.board.pages[ticket]["properties"]["Type"] = _stored({"select": {"name": "Code"}})
    machine.move(ticket, "Ready")
    machine.run()

    assert machine.status(ticket) == "Done", machine.status(ticket)
    assert machine.board.value(ticket, "Sous-type") == "Bug"
    assert len(machine.merges()) == 1, machine.merges()


@case
def a_forced_merge_stopped_by_its_ci_says_on_the_card_which_ci_and_why():
    """Red by the code: the checks are named. Never started by GitHub: its reason,
    word for word — it is the account to look at, not the code. Neither merged."""
    not_started = (
        "The job was not started because recent account payments have failed or your "
        "spending limit needs to be increased."
    )
    for verdicts, annotation, expected in (
        (("SUCCESS", "FAILURE"), "", "red on `job 2`"),
        (("FAILURE", "FAILURE"), not_started, "spending limit"),
    ):
        with bench(force_validated_code=True) as machine:
            machine.board.databases[machine.database]["properties"] = {
                **machine.board.databases[machine.database]["properties"],
                "Progress": {"type": "rich_text", "rich_text": {}},
            }
            repository = machine.repository("site")
            machine.with_ci(repository)
            project = machine.project("Site", repository)
            ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
            os.environ["FAKE_GH_CHECKS"] = _check_runs(*verdicts)
            os.environ["FAKE_GH_ANNOTATION"] = annotation

            machine.run()

            assert machine.status(ticket) == "In review", machine.status(ticket)
            assert not machine.merges(), machine.merges()
            assert "FAKE.md" not in machine.files_on(repository, "main")
            said = machine.board.said(ticket)[-1]
            assert "Not merged, left in review" in said and expected in said, said
            card = str(machine.board.value(ticket, "Progress") or "")
            assert expected in card, card


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_refused_for_being_behind_waits_in_validated_and_lands_next_pass(machine):
    """Two tickets on one repository: the other one landed while this one's CI ran.

    GitHub refuses the merge for a branch that is out of date. That is not a
    question about the work, so the ticket waits in validated rather than in
    review — and the next pass, which reads that column as it always does,
    replays the branch onto what `main` holds and merges it. Nobody moved it.
    """
    machine.board.databases[machine.database]["properties"] = {
        **machine.board.databases[machine.database]["properties"],
        "Progress": {"type": "rich_text", "rich_text": {}},
    }
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_GH_REFUSE": "Head branch is out of date with the base branch"}):
        first = machine.run()

    assert machine.status(ticket) == "Validated", machine.status(ticket)
    assert first[0].get("postponed"), first
    said = machine.board.said(ticket)[-1]
    assert said.startswith("⏸️"), said
    assert "postponed to the next pass" in said and "out of date" in said, said
    assert "refused" not in said.lower(), said
    card = str(machine.board.value(ticket, "Progress") or "")
    assert "postponed to the next pass" in card, card

    machine.land(repository, "OTHER.md")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    landed = machine.files_on(repository, "main")
    assert "OTHER.md" in landed and "FAKE.md" in landed, landed
    assert "replayed onto" in machine.board.said(ticket)[-1]


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_in_conflict_waits_in_validated_and_its_conflict_is_resolved(machine):
    """Behind on the very file it writes: validated, then the usual resolution."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_GH_REFUSE": "Pull Request has merge conflicts"}):
        machine.run()
    assert machine.status(ticket) == "Validated", machine.status(ticket)

    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    landed = machine.content(repository, "main", "FAKE.md")
    assert "ce que l'autre ticket a écrit" in landed and "the session was here" in landed
    assert [one for one in machine.sessions() if "resolving that conflict" in one["prompt"]]


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_with_no_validated_column_still_waits_in_review(machine):
    """The column is opt-in: a board without it keeps the refusal in review."""
    # A copy, as `typed` makes one: the schema every scenario starts from is shared.
    database = machine.board.databases[machine.database]
    options = database["properties"]["Status"]["status"]["options"]
    database["properties"] = {
        **database["properties"],
        "Status": {
            "type": "status",
            "status": {"options": [one for one in options if one["name"] != "Validated"]},
        },
    }
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_GH_REFUSE": "Head branch is out of date with the base branch"}):
        machine.run()

    assert machine.status(ticket) == "In review", machine.status(ticket)
    said = machine.board.said(ticket)[-1]
    assert "Not merged, left in review" in said, said


@case
@runner_settings(force_validated_code=True)
def force_validated_never_touches_a_failed_session_nor_a_ticket_already_in_review(machine):
    """The two guards: only a success is validated, only a ticket run from now on."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    waiting = machine.ticket("Déjà relu à moitié", "Rien.", project, status="In review")
    machine.board.pages[waiting]["properties"]["Pull Request"] = _stored(
        {"url": "https://github.com/fake/repo/pull/99"}
    )
    broken = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    os.environ["FAKE_CLAUDE_FAIL"] = "la session a planté"

    machine.run()

    assert machine.status(broken) == "Failed", machine.status(broken)
    assert machine.status(waiting) == "In review", machine.status(waiting)
    assert not machine.merges(), machine.merges()


@case
@runner_settings(force_validated_publication=True)
def a_publication_whose_validation_is_forced_goes_out_without_waiting(machine):
    """Force validated for Publication: prepared, then published, in one pass."""
    machine.typed()
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Annoncer la version 2", "Un post LinkedIn pour la v2.", project)
    machine.board.pages[ticket]["properties"]["Type"] = _stored({"select": {"name": "Publication"}})

    results = machine.run()

    assert [result.get("kind") for result in results] == ["delivery"], results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    sessions = machine.sessions()
    assert len(sessions) == 2, sessions
    assert "prepare it, do not publish it" in sessions[0]["prompt"]
    assert "You are publishing, not producing" in sessions[1]["prompt"]
    said = machine.board.said(ticket)
    assert said[0].startswith("🧠"), "the model chosen, before the work"
    said = said[1:]
    assert len(said) == 1 and said[0].startswith("✅"), said
    assert "Validated automatically (Force validated: Publication)" in said[0], said


@case
@runner_settings(force_validated_publication=True)
def a_publication_whose_validation_is_forced_costs_its_two_sessions(machine):
    """Prepared, then published: two sessions paid, in the column and in the history."""
    machine.typed()
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Annoncer la version 2", "Un post LinkedIn pour la v2.", project)
    machine.board.pages[ticket]["properties"]["Type"] = _stored({"select": {"name": "Publication"}})

    with _environ({"FAKE_CLAUDE_COST": ""}):
        results = machine.run()

    assert len(machine.sessions()) == 2, machine.sessions()
    assert machine.board.value(ticket, "Cost") == 0.04, machine.board.value(ticket, "Cost")
    assert results[0]["cost_usd"] == 0.04, results
    assert state.spent_today() == 0.04, state.spent_today()


@case
def a_ticket_with_no_model_runs_on_the_one_chosen_for_it_and_a_model_written_as_written(machine):
    project = machine.project("Notes", None)
    light = machine.ticket(
        "Retirer un paragraphe", "Le texte sous le titre ne sert à rien.", project
    )
    heavy = machine.ticket("Audit complet", "Audit de sécurité et de performance du site.", project)
    forced = machine.ticket("Retirer une ligne", "La dernière du pied de page.", project)
    machine.board.pages[forced]["properties"]["Model"] = _stored({"select": {"name": "opus"}})

    machine.run()

    ran = {
        title: entry["model"]
        for entry in machine.sessions()
        for title in ("Retirer un paragraphe", "Audit complet", "Retirer une ligne")
        if title in entry["prompt"]
    }
    assert ran == {
        "Retirer un paragraphe": "haiku",
        "Audit complet": "opus",
        "Retirer une ligne": "opus",
    }, ran
    assert machine.board.said(light)[0].startswith("🧠 Model chosen automatically — haiku")
    assert "heavy work (audit, sécurité, performance)" in machine.board.said(heavy)[0]
    assert not any(line.startswith("🧠") for line in machine.board.said(forced))
    # The pick is on the board as well as in the comment; a model somebody
    # wrote is left as it was.
    assert machine.board.value(light, "Model") == "haiku", machine.board.value(light, "Model")
    assert machine.board.value(heavy, "Model") == "opus", machine.board.value(heavy, "Model")
    assert machine.board.value(forced, "Model") == "opus"


@case
def a_ticket_on_an_openrouter_model_runs_on_openrouter_and_is_blocked_without_its_key(machine):
    project = machine.project("Notes", None)
    routed = machine.ticket("Écrire l'annonce", "Trois lignes.", project)
    machine.board.pages[routed]["properties"]["Model"] = _stored(
        {"select": {"name": "openai/gpt-5"}}
    )

    # Without the key, the slug means nothing to the CLI: said as what it is.
    machine.run()
    assert machine.status(routed) == "Blocked"
    assert "OpenRouter key is missing" in machine.board.said(routed)[-1], machine.board.said(routed)
    assert not machine.sessions(), "nothing ran on a model nobody can reach"

    with _environ({"OPENROUTER_API_KEY": "sk-or-functional-tests"}):
        machine.move(routed, "Ready")
        machine.run()
    (entry,) = machine.sessions()
    assert entry["model"] == "openai/gpt-5"
    assert entry["base_url"].startswith("https://openrouter.ai"), entry
    assert machine.status(routed) != "Blocked"
    assert machine.board.value(routed, "Model") == "openai/gpt-5", "the slug stays on the ticket"


@case
def a_ticket_the_runner_hesitates_over_is_blocked_and_nothing_runs(machine):
    """A doubt with a publication is a question, not a session — and a type
    somebody chose is never classified again, let alone overwritten."""
    machine.typed()
    project = machine.project("Lettre d'information", None)
    unsure = machine.ticket("La newsletter", "La newsletter d'octobre.", project)
    chosen = machine.ticket("L'édito", "Deux paragraphes.", project)
    machine.board.pages[chosen]["properties"]["Type"] = _stored({"select": {"name": "Rédaction"}})
    os.environ["FAKE_CLAUDE_KIND"] = json.dumps(
        {
            "type": "writing",
            "reason": "Rédiger, ou peut-être envoyer, la newsletter.",
            "confidence": "medium",
            "alternative": "publication",
        }
    )

    results = machine.run()

    # Stopped before it was claimed, like a ticket with no project: the
    # board says so, and the pass has only the other one to report.
    assert [(result["id"], result["status"]) for result in results] == [(chosen, "done")], results
    assert machine.status(unsure) == "Blocked"
    assert machine.board.value(unsure, "Type") is None, "a doubt writes no type"
    question = machine.board.said(unsure)[-1]
    assert "Rédaction" in question and "Publication" in question, question
    assert machine.board.value(chosen, "Type") == "Rédaction"
    prompts = [one["prompt"] for one in machine.sessions()]
    assert sum("say what kind of ticket it is" in one for one in prompts) == 1, (
        "only the ticket with no type is classified"
    )
    assert len(prompts) == 2, "the blocked ticket ran nothing but its classification"


@case
def a_deleted_project_and_its_tickets_cost_no_session(machine):
    """In the Notion trash, a project is out of every query — and a ticket still
    pointing at it is put back, not worked on with whatever the page held.

    The trash keeps a page readable by its ID, which is the thing to guard: the
    ready ticket below still names it, and without the check the runner would
    find the repository through the trashed page and spend a session on it.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    other = machine.project("Autre", machine.repository("autre"))
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    kept = machine.ticket("Un autre travail", "Ailleurs.", other)

    notion.Client("ntn_functional_tests").trash(project)
    assert machine.board.pages[project]["archived"] is True

    results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(kept, "done")], results
    assert machine.status(ticket) == "Blocked", machine.status(ticket)
    assert "deleted" in machine.board.said(ticket)[-1], machine.board.said(ticket)
    assert all("Corriger l'entête" not in one["prompt"] for one in machine.sessions())
    assert not machine.worktrees(repository), "a deleted project got a worktree"
    assert repository.is_dir(), "the clone on the machine is never ours to remove"


@case
def a_session_that_fails_leaves_a_readable_ticket_and_no_worktree(machine):
    """The failure has to be readable on the board, and cost nothing on disk.

    A failed run used to be the one that left things behind: a ticket stuck in
    "in progress" and a worktree holding a branch, which then refuses the next
    attempt at the very same ticket.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Une tâche impossible", "Fais l'impossible.", project)

    with _environ({"FAKE_CLAUDE_FAIL": "la session s'est arrêtée : rien à faire ici"}):
        results = machine.run()

    assert len(results) == 1, results
    assert results[0]["status"] == "failed", results
    assert machine.status(ticket) == "Failed", machine.status(ticket)

    said = machine.board.said(ticket)
    assert said, "a ticket that failed was not told why"
    assert "rien à faire ici" in said[-1], said[-1]

    assert not machine.worktrees(repository), machine.worktrees(repository)
    worktrees = Path(os.environ["XDG_STATE_HOME"]) / "ponos" / "worktrees"
    assert not list(worktrees.glob("*")), "the worktree is still on disk"
    assert not machine.pull_requests(), "a failed session still opened a pull request"
    assert machine.branches(repository) == ["main"], machine.branches(repository)


@case
def an_external_action_that_commits_nothing_is_done_with_its_report(machine):
    """The deployment was the work: no commit was asked for, and none is waited on.

    Typed as an external action, it never sees the repository; left as code by
    a hesitant classification, it is still not code — and a code ticket that
    says it worked in Dokploy and committed nothing is done, not blocked.
    """
    machine.typed()
    repository = machine.repository("leadz")
    project = machine.project("Leadz", repository)
    hesitant = machine.ticket("Réparer le déploiement", "La prod est cassée.", project)
    os.environ["FAKE_CLAUDE_KIND"] = json.dumps(
        {
            "type": "code",
            "reason": "Il faut peut-être corriger la configuration.",
            "confidence": "low",
            "alternative": "external",
        }
    )

    results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(hesitant, "done")], results
    assert machine.board.value(hesitant, "Type") == "Action externe"
    classified = machine.board.said(hesitant)[0]
    assert "n'exige pas de commit" in classified or "asks for no commit" in classified, classified
    assert machine.status(hesitant) == "Done", machine.status(hesitant)
    assert not machine.pull_requests()

    # Typed as code by somebody, and done in Dokploy all the same.
    coded = machine.ticket("Ajouter la variable en prod", "SMTP_HOST manque.", project)
    machine.board.pages[coded]["properties"]["Type"] = _stored({"select": {"name": "Code"}})
    report = "J'ai ajouté SMTP_HOST dans Dokploy et redéployé l'application."
    with _environ({"FAKE_CLAUDE_ELSEWHERE": report}):
        results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(coded, "done")], results
    assert machine.status(coded) == "Done", machine.status(coded)
    assert report in machine.board.body(coded), machine.board.body(coded)
    assert "RESULT:" not in machine.board.body(coded), "the verdict is the status"
    assert not machine.pull_requests(), "nothing to review"
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_code_ticket_that_changes_code_without_committing_it_is_still_blocked(machine):
    """The one case the commit is the deliverable, and it is not there."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    dirty = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_CLAUDE_DIRTY": "1"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.status(dirty) == "Blocked", machine.status(dirty)

    # Clean, but saying it changed the code, from a deployment ticket.
    claimed = machine.ticket("Corriger le déploiement", "Le build casse.", project)
    said = "J'ai corrigé le fichier docker/entrypoint.py puis redéployé dans Dokploy."
    with _environ({"FAKE_CLAUDE_ELSEWHERE": said}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.status(claimed) == "Blocked", machine.status(claimed)
    assert len(machine.sessions()) == 1, "a session that concluded is not asked again"


@case
def a_session_that_stops_without_its_report_is_asked_for_it_once(machine):
    """Picked up in its own conversation, for the report and nothing else —
    blocked only when that fails too, and never asked twice for one ticket."""
    project = machine.project("Leadz", None)
    ticket = machine.ticket("Brancher le domaine", "leadz.ninja sur le serveur.", project)

    with _environ({"FAKE_CLAUDE_SILENT": "once", "FAKE_CLAUDE_COST": ""}):
        results = machine.run()

    assert results[0]["status"] == "done", results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    assert "Le domaine pointe sur le serveur." in machine.board.body(ticket)
    first, again = machine.sessions()
    assert again["session"] == first["session"], "the same conversation, carried on"
    assert "You stopped without writing your report" in again["prompt"]
    assert "leadz.ninja" not in again["prompt"], "the ticket is not sent again"
    assert results[0]["cost_usd"] == 0.03, "both halves are paid for"

    silent = machine.ticket("Brancher l'autre domaine", "leadz.io aussi.", project)
    with _environ({"FAKE_CLAUDE_SILENT": "always"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.status(silent) == "Blocked", machine.status(silent)
    assert len(machine.sessions()) == 2, machine.sessions()

    # Back to ready: it already had its second chance.
    machine.move(silent, "Ready")
    with _environ({"FAKE_CLAUDE_SILENT": "always"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert len(machine.sessions()) == 1, "not picked up a second time"


def _budget(machine: Bench, **limits: float) -> None:
    """The installation's `[budget]`, written into its configuration."""
    with open(machine.config, "a", encoding="utf-8") as handle:
        handle.write(
            "\n[budget]\n" + "".join(f"{key} = {value}\n" for key, value in limits.items())
        )


@case
def a_blocked_or_failed_session_has_its_cost_written_on_the_ticket(machine):
    """Paid for is paid for: the Cost column used to know only the finished ones."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    failing = machine.ticket("Une tâche qui plante", "Fais l'impossible.", project)
    with _environ({"FAKE_CLAUDE_FAIL": "la session a planté", "FAKE_CLAUDE_COST": "0.42"}):
        results = machine.run()
    assert results[0]["status"] == "failed", results
    assert machine.board.value(failing, "Cost") == 0.42, machine.board.value(failing, "Cost")
    assert results[0]["cost_usd"] == 0.42, "and the history knows it"

    asking = machine.ticket("Une tâche qui hésite", "Choisis.", project)
    with _environ({"FAKE_CLAUDE_BLOCK": "A ou B ?", "FAKE_CLAUDE_COST": "0.17"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.status(asking) == "Blocked", machine.status(asking)
    assert machine.board.value(asking, "Cost") == 0.17, machine.board.value(asking, "Cost")


@case
def a_session_past_the_ticket_limit_stops_cleanly_and_blocks_the_ticket_with_the_reason():
    with bench() as machine:
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        _budget(machine, per_ticket_usd=2.5)
        ticket = machine.ticket("Une tâche sans fin", "Continue.", project)
        with _environ({"FAKE_CLAUDE_OVER_BUDGET": "1", "FAKE_CLAUDE_COST": "2.51"}):
            results = machine.run()

        assert machine.sessions()[0]["budget"] == "2.50", "the limit reaches the session itself"
        assert results[0]["status"] == "blocked", results
        assert machine.status(ticket) == "Blocked", machine.status(ticket)
        assert machine.board.value(ticket, "Cost") == 2.51, "the cost of the session cut short"
        assert "per_ticket_usd" in machine.board.said(ticket)[-1], machine.board.said(ticket)
        assert not machine.worktrees(repository), "and no worktree left behind"

    with bench() as machine:
        _budget(machine)  # no limit set: nothing is handed to the session
        repository = machine.repository("site")
        machine.ticket("Une tâche", "Fais-la.", machine.project("Site", repository))
        machine.run()
        assert machine.sessions()[0]["budget"] == ""


@case
def past_the_daily_limit_nothing_new_is_started_and_the_ready_tickets_wait(machine):
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    _budget(machine, daily_usd=1.0)
    first = machine.ticket("Une tâche chère", "Fais-la.", project)
    with _environ({"FAKE_CLAUDE_BLOCK": "A ou B ?", "FAKE_CLAUDE_COST": "1.5"}):
        machine.run()
    assert machine.status(first) == "Blocked", machine.status(first)

    second = machine.ticket("Une tâche qui attend", "Plus tard.", project)
    results = machine.run()
    assert machine.sessions() == [], "a session was started past the daily limit"
    assert machine.status(second) == "Ready", machine.status(second)
    assert results == [], results
    assert credits.held(what="budget") > time.time(), "the wait is written down for the runs after"


@case
def a_branch_is_replayed_on_a_base_that_moved_under_the_session():
    """The pull request opens on top of what the repository holds now.

    A board that sends ten tickets at one repository is a base branch that
    moves under every one of them: the first merge lands, and the nine sessions
    still running are opening pull requests against a `main` of an hour ago.
    Here the base moves *during* the session — which is what the fake one does
    when `FAKE_CLAUDE_MOVES_BASE` names a clone — and the branch that reaches
    the remote carries both commits, not a conflict somebody has to sort out.

    The same scenario with `rebase = false` is what says the test is about the
    rebase rather than about git: the branch then goes out as it was written,
    without what landed on main under it.
    """
    for rebase, expected in ((True, True), (False, False)):
        with bench(rebase=rebase) as machine:
            repository = machine.repository("site")
            project = machine.project("Site", repository)
            ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

            with _environ({"FAKE_CLAUDE_MOVES_BASE": str(repository)}):
                results = machine.run()

            assert results[0]["status"] == "done", results
            assert machine.status(ticket) == "In review", machine.status(ticket)
            branch = results[0]["branch"]
            files = machine.files_on(repository, branch)
            assert "FAKE.md" in files, files
            assert ("OTHER.md" in files) is expected, (rebase, files)
            assert len(machine.pull_requests()) == 1, machine.pull_requests()
            said = machine.board.said(ticket)
            assert ("rejouée sur" in said[-1] or "replayed onto" in said[-1]) is expected, said[-1]


@case
def a_validated_merge_refused_for_being_behind_is_replayed_and_lands(machine):
    """Validated on Monday, behind by Tuesday: the runner puts it back on top.

    The pull request was opened on a `main` that has moved since — another
    ticket landed — so GitHub refuses the merge, exactly as the fake one does
    here: the base is no longer an ancestor of the branch. The branch is
    replayed onto it, force-pushed with a lease, and the merge is asked again.
    What the test reads afterwards is the remote itself: `main` carries both
    what landed under the ticket and what the ticket wrote.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    machine.run()
    assert machine.status(ticket) == "In review", machine.status(ticket)

    machine.land(repository, "OTHER.md")
    machine.move(ticket, "Validated")

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    assert len(machine.merges()) == 1, "the merge was asked once too often, or never"
    landed = machine.files_on(repository, "main")
    assert "OTHER.md" in landed and "FAKE.md" in landed, landed
    # And the replay left nothing behind: the worktree it needed is gone.
    scratch = Path(os.environ["XDG_STATE_HOME"]) / "ponos" / "scratch"
    assert not list(scratch.glob("rebase-*")), list(scratch.glob("rebase-*"))
    assert not machine.worktrees(repository), machine.worktrees(repository)
    said = machine.board.said(ticket)
    assert "replayed onto" in said[-1], said[-1]


@case
def a_validated_merge_that_conflicts_is_resolved_and_lands_with_both_changes(machine):
    """Two tickets on the same file: the first is merged, the second still lands.

    The case the runner used to give up on — “Pull Request has merge conflicts”
    — and the one a board with several tickets per repository meets every day.
    The branch is replayed onto `main`, git stops on the file both touched, a
    session resolves it keeping both sides, and what reaches the remote is a
    `main` carrying the two changes. Nobody was asked anything.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    first = machine.run()
    branch = first[0]["branch"]
    before = float(machine.board.value(ticket, "Cost") or 0)

    # The other ticket, merged first, wrote the very file this one writes.
    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    machine.move(ticket, "Validated")

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "Done", machine.status(ticket)
    landed = machine.content(repository, "main", "FAKE.md")
    assert "ce que l'autre ticket a écrit" in landed, landed
    assert "the session was here" in landed, landed
    assert "<<<<<<<" not in landed, landed

    # The session was told what it needed: the ticket, and the file.
    resolving = [one for one in machine.sessions() if "resolving that conflict" in one["prompt"]]
    assert len(resolving) == 1, machine.sessions()
    assert "Le titre est faux." in resolving[0]["prompt"]
    assert "`FAKE.md`" in resolving[0]["prompt"]
    assert (
        "ce que l'autre ticket a écrit" in resolving[0]["prompt"]
        or "Un autre ticket" in resolving[0]["prompt"]
    )

    # Traced on both sides: the pull request, and the ticket.
    commented = machine.pull_request_comments()
    assert len(commented) == 1 and "FAKE.md" in commented[0]["body"], commented
    said = machine.board.said(ticket)[-1]
    assert "FAKE.md" in said and "les deux versions gardées" in said, said
    # And paid for on the ticket that asked for it, on top of what it cost.
    assert round(float(machine.board.value(ticket, "Cost")) - before, 3) == 0.05

    assert branch in machine.branches(repository)
    assert not machine.worktrees(repository), machine.worktrees(repository)
    scratch = Path(os.environ["XDG_STATE_HOME"]) / "ponos" / "scratch"
    assert not list(scratch.glob("resolve-*")), list(scratch.glob("resolve-*"))


@case
def a_conflict_that_is_a_decision_blocks_the_ticket_with_the_question(machine):
    """The session reads the conflict as two behaviours that cannot both hold.

    Nothing is pushed on the pull request's branch and nothing is merged: the
    ticket goes to blocked, and what it asks is the conflict — the file and the
    question — rather than GitHub's refusal.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    first = machine.run()
    branch = first[0]["branch"]
    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    pushed = machine.content(repository, branch, "FAKE.md")
    machine.move(ticket, "Validated")

    with _environ({"FAKE_CLAUDE_RESOLVE": "blocked"}):
        results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert machine.status(ticket) == "Blocked", machine.status(ticket)
    said = machine.board.said(ticket)[-1]
    assert "garder le texte du ticket ou celui de main" in said, said
    assert "FAKE.md" in said, said
    assert not machine.merges(), "a conflict nobody resolved was merged"
    assert machine.content(repository, branch, "FAKE.md") == pushed, "the branch was rewritten"
    assert machine.content(repository, "main", "FAKE.md") == "ce que l'autre ticket a écrit\n"
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
@runner_settings(resolve_conflicts_except="Site")
def a_project_left_out_of_resolution_blocks_on_its_conflict_as_before(machine):
    """`resolve_conflicts_except` names it: no session, the refusal as it came."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    machine.run()
    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    machine.move(ticket, "Validated")
    results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert not machine.sessions(), machine.sessions()
    assert not machine.merges()


def _with_a_bundle(machine: Bench, name: str) -> Path:
    """A repository that declares a generated bundle, and keeps a changelog.

    `dist/bundle.js` is what `build` writes from `parts/*.txt`, as a frontend
    build writes its assets from its sources: it is never edited by hand, and
    two branches that each add a part disagree about it on every merge.
    """
    repository = machine.repository(name)
    seeded = {
        ".ponos.toml": 'generated = ["dist/**"]\nbuild = "mkdir -p dist && cat parts/*.txt > dist/bundle.js"\n',
        "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n",
        "parts/0.txt": "zéro\n",
        "dist/bundle.js": "zéro\n",
    }
    _write(repository, seeded, "bundle et changelog")
    return repository


def _write(repository: Path, files: dict[str, str], message: str) -> None:
    """Files committed on `main` and pushed: another ticket, merged."""
    for name, text in files.items():
        (repository / name).parent.mkdir(parents=True, exist_ok=True)
        (repository / name).write_text(text, encoding="utf-8")
    _git(["add", *files], repository)
    _git(["commit", "-m", message], repository)
    _git(["push", "origin", "main"], repository)


def _adds(*parts: str) -> dict[str, str]:
    """The environment that has the session of each "Ajoute la partie X." write its part."""
    return {"FAKE_CLAUDE_ALSO": json.dumps({f"la partie {part}.": _adding(part) for part in parts})}


def _adding(part: str) -> dict[str, str]:
    """What a ticket that adds one part writes: the part, the bundle, a changelog line."""
    return {
        f"parts/{part}.txt": f"{part}\n",
        "dist/bundle.js": f"zéro\n{part}\n",
        "CHANGELOG.md": f"# Changelog\n\n## Unreleased\n\n- {part}\n",
    }


@case
def branches_differing_only_in_generated_files_and_the_changelog_merge_without_a_session(machine):
    """The conflicts a busy repository makes every day, settled where git stops.

    Two branches add a part each: they disagree about the bundle the build
    writes and about the line of the changelog. Nothing in that is a decision —
    the bundle is built again, the changelog keeps both lines — so no session
    is started, and what lands on `main` is the build of both parts.
    """
    repository = _with_a_bundle(machine, "site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Ajouter a", "Ajoute la partie a.", project)

    with _environ(_adds("a")):
        machine.run()
    assert machine.status(ticket) == "In review", machine.status(ticket)

    _write(repository, _adding("b"), "Un autre ticket — b")
    machine.move(ticket, "Validated")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert not machine.sessions(), "a session was started for a conflict nobody had to decide"
    assert machine.content(repository, "main", "dist/bundle.js") == "zéro\na\nb\n"
    changelog = machine.content(repository, "main", "CHANGELOG.md")
    assert "- a" in changelog and "- b" in changelog, changelog
    assert changelog.index("- b") < changelog.index("- a"), "the base's entries come first"
    assert "<<<<<<<" not in changelog
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
@runner_settings(max_concurrent=1)
def three_validated_pull_requests_on_one_repository_merge_one_after_the_other(machine):
    """The base moves under every one of them, and none is blocked for it.

    Each of the three adds a part, a line of the changelog and the bundle that
    follows from them; each merge makes the others conflict on both. They are
    merged in a line, each replayed on the base the one before left, with no
    session and no ticket blocked on “keeps moving faster”.
    """
    repository = _with_a_bundle(machine, "site")
    project = machine.project("Site", repository)
    tickets = [
        machine.ticket(f"Ajouter {part}", f"Ajoute la partie {part}.", project) for part in "abc"
    ]
    with _environ(_adds("a", "b", "c")):
        machine.run()
    assert [machine.status(ticket) for ticket in tickets] == ["In review"] * 3
    for ticket in tickets:
        machine.move(ticket, "Validated")

    results = machine.run()

    assert [one["status"] for one in results] == ["done"] * 3, results
    assert [machine.status(ticket) for ticket in tickets] == ["Done"] * 3
    assert len(machine.merges()) == 3, machine.merges()
    assert not machine.sessions(), machine.sessions()
    assert machine.content(repository, "main", "dist/bundle.js") == "zéro\na\nb\nc\n"
    changelog = machine.content(repository, "main", "CHANGELOG.md")
    assert all(f"- {part}" in changelog for part in "abc"), changelog
    for ticket in tickets:
        assert "moves faster" not in " ".join(machine.board.said(ticket)), ticket


@case
def a_conflict_in_code_is_resolved_by_a_session_that_is_not_told_about_generated_files(machine):
    """Settled files are off the list, and the bundle is built again after the session.

    The branch and the base both rewrite `FAKE.md` — a decision a session keeps
    both sides of — and both add a part. The session is told about `FAKE.md`
    only; once it is done the bundle is built from both parts.
    """
    repository = _with_a_bundle(machine, "site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Ajouter a", "Ajoute la partie a.", project)

    with _environ(_adds("a")):
        machine.run()
    _write(
        repository,
        {**_adding("b"), "FAKE.md": "ce que l'autre ticket a écrit\n"},
        "Un autre ticket — b",
    )
    machine.move(ticket, "Validated")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    resolving = [one for one in machine.sessions() if "resolving that conflict" in one["prompt"]]
    assert len(resolving) == 1, machine.sessions()
    assert "- `FAKE.md`" in resolving[0]["prompt"]
    assert "- `dist/bundle.js`" not in resolving[0]["prompt"]
    assert "- `CHANGELOG.md`" not in resolving[0]["prompt"]
    assert machine.content(repository, "main", "dist/bundle.js") == "zéro\na\nb\n"


@case
def a_failing_build_stops_the_replay_and_nothing_is_pushed(machine):
    """Bundles that do not match their sources are worse than a blocked ticket."""
    repository = _with_a_bundle(machine, "site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Ajouter a", "Ajoute la partie a.", project)

    with _environ(_adds("a")):
        first = machine.run()
    branch = first[0]["branch"]
    pushed = machine.content(repository, branch, "dist/bundle.js")
    broken = {
        ".ponos.toml": 'generated = ["dist/**"]\nbuild = "exit 3"\n',
        **_adding("b"),
    }
    _write(repository, broken, "Un autre ticket — b, et un build cassé")
    machine.move(ticket, "Validated")
    results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert not machine.merges()
    assert machine.content(repository, branch, "dist/bundle.js") == pushed, "the branch moved"


@case
def a_ticket_runs_in_the_repository_its_project_names(machine):
    """Two projects, one ticket: the relation decides which repository is touched.

    The expensive mistake here is silent — a ticket committed to the wrong clone
    is work nobody ever finds — so the other repository is checked as closely as
    the right one.
    """
    site = machine.repository("site")
    api = machine.repository("api")
    machine.project("Site", site)
    second = machine.project("API", api)
    machine.ticket("Ajouter une route", "Une route de plus.", second)

    results = machine.run()

    assert results[0]["status"] == "done", results
    assert results[0]["project"] == "API", results
    branch = results[0]["branch"]
    assert branch.startswith("ticket/ajouter-une-route-"), branch

    assert branch in machine.branches(api), machine.branches(api)
    assert machine.branches(site) == ["main"], machine.branches(site)
    assert "FAKE.md" in machine.files_on(api, branch)
    assert "FAKE.md" not in machine.files_on(site, "main")

    sessions = machine.sessions()
    assert len(sessions) == 1, sessions
    # The worktree is named after the project it belongs to, and the session
    # ran in it — which is the same statement as the two above, said where
    # the work actually happened rather than where it landed.
    assert Path(sessions[0]["cwd"]).name.startswith("api-"), sessions[0]["cwd"]
    assert not machine.worktrees(site) and not machine.worktrees(api)


@case
def a_picture_chosen_in_the_console_is_the_cover_in_notion_and_the_other_way_round():
    """Both directions, over HTTP, against a Notion that signs its URLs.

    The console's picture is uploaded and set as the page's cover; read back
    under a new signature, it is recognised rather than downloaded again or
    sent a second time. Then somebody changes the cover in Notion, and the
    next reading brings their picture — fetched from Notion's storage, not
    from the API, and without the token.
    """
    png = b"\x89PNG\r\n\x1a\n" + b"console" * 8
    theirs = b"\xff\xd8\xff\xe0" + b"notion" * 8
    directory = Path(tempfile.mkdtemp())
    try:
        with _notion_server() as (url, board), _environ({notion.API_ENV: url}):
            project = board.page({"Name": {"type": "title", "title": _rich("Opoil")}})
            client = notion.Client("ntn_functional")
            cache = images.Cache(directory, database=directory / "ponos.db")

            def push(slot: str, picture: store.Picture) -> notion.Page:
                return client.set_picture(project, slot, picture)

            cache.observe(client.page(project), push)
            cache.change(
                project, "cover", store.Picture(data=png, type="image/png", name="opoil.png"), push
            )
            cover = board.pages[project]["cover"]
            assert cover["type"] == "file", cover
            assert list(board.files.values()) == [(png, "image/png")]

            sent = len(board.requests)
            cache.observe(client.page(project), push)
            assert not any(
                "file_uploads" in line or line.startswith("PATCH") for line in board.requests[sent:]
            ), board.requests[sent:]
            assert cache.picture(project, "cover", lambda: client.page(project)) == (
                png,
                "image/png",
            )

            # Changed in Notion, by hand: another file, and an emoji for the icon.
            board.files["theirs"] = (theirs, "image/jpeg")
            board.pages[project]["cover"] = board.hosted("theirs", "theirs.jpg")
            board.pages[project]["icon"] = {"type": "emoji", "emoji": "🛢️"}
            time.sleep(1.1)  # the fake's clock is to the second, like Notion's
            board.pages[project]["last_edited_time"] = _now()

            cache.observe(client.page(project), push)
            assert cache.shown(project, "icon") == {"kind": "emoji", "emoji": "🛢️"}
            data = cache.picture(project, "cover", lambda: client.page(project))
            assert data == (theirs, "image/jpeg"), data
            assert not board.refused, board.refused
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@case
def a_pass_started_during_an_update_runs_on_one_version_and_never_on_both(machine):
    """On 30 September 2026 a pass started while an update rewrote the app in
    place, imported a `files.py` already new with a `store.py` still old, and
    died on `ImportError: cannot import name 'SLOTS'`.

    So the road is driven the way the timer drives it: through the installed
    launcher, as processes of their own. A pass is held in the middle of its
    session while a version lands whose two modules only work together; a pass
    started then, and one started after, must run whole on one version — and
    the one held must finish on the version it started on, still on disk.
    """
    from ponos import update

    home = machine.root / "home"
    remote, work, app = (home / name for name in ("remote.git", "work", "app"))
    _git(["init", "--bare", "--initial-branch=main", str(remote)], machine.root)
    _git(["clone", str(remote), str(work)], machine.root)
    ignore = shutil.ignore_patterns("__pycache__")
    for part in ("src", "bin", "systemd"):
        shutil.copytree(ROOT / part, work / part, ignore=ignore)
    # What the code imports beyond the standard library: each version's
    # environment is made from it, before `app` points there.
    shutil.copy(ROOT / "requirements.txt", work / "requirements.txt")

    def land(message: str) -> str:
        _git(["add", "-A"], work)
        _git(["commit", "--quiet", "-m", message], work)
        _git(["push", "--quiet", "origin", "HEAD:main"], work)
        return subprocess.run(
            ["git", "-C", str(work), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    first = land("one")
    # Installed the way install.sh does it: `app` a link to `app-<commit>`.
    # A plain directory is renamed by the first update, and a pass started in
    # that one moment does not start at all — `update._versioned` says so.
    _git(["clone", str(remote), str(app.with_name(f"app-{first[:12]}"))], machine.root)
    app.symlink_to(f"app-{first[:12]}")
    # The launcher as install.sh writes it, and a PATH with no systemctl on
    # it: the units of the machine running the test are not the test's.
    launcher = home / ".local" / "bin" / "ponos"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        (ROOT / "bin" / "ponos.in")
        .read_text()
        .replace("@APP_DIR@", str(app))
        .replace("@PYTHON@", sys.executable)
    )
    launcher.chmod(0o755)
    tools = machine.root / "tools"
    tools.mkdir()
    (tools / "bash").symlink_to(shutil.which("bash") or "/bin/bash")
    # uv when the machine has it, as `environment.create` would find it;
    # pip from the environment otherwise — both download the same pins.
    if shutil.which("uv"):
        (tools / "uv").symlink_to(shutil.which("uv") or "")
    hold = machine.root / "hold"
    environment = {
        "HOME": str(home),
        "PATH": os.pathsep.join([str(launcher.parent), str(machine.root / "bin"), str(tools)]),
        "PONOS_CONFIG": str(machine.config),
        "FAKE_CLAUDE_HOLD": str(hold),
        # The install.sh layout, wherever the suite runs — the CI runs it in
        # the image too, where a new version is a new image instead.
        "PONOS_CONTAINER": "",
    }

    def started(*arguments: str) -> subprocess.Popen:
        return subprocess.Popen(
            [str(launcher), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    project = machine.project("Lettre d'information")
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes.", project)
    with _environ(environment):
        held = started("run")
        for _ in range(300):
            if Path(f"{hold}.started").exists() or held.poll() is not None:
                break
            time.sleep(0.1)
        assert Path(f"{hold}.started").exists(), held.communicate()[0]

        # The incident's shape: a module that needs a name only the new
        # version of another one has.
        store_py = work / "src/ponos/store.py"
        store_py.write_text(store_py.read_text() + "\nHANDOVER = 'v2'\n")
        runner_py = work / "src/ponos/runner.py"
        runner_py.write_text(
            runner_py.read_text().replace(
                "from .ticket import Ticket\n",
                "from .ticket import Ticket\nfrom .store import HANDOVER  # noqa: F401\n",
                1,
            )
        )
        init_py = work / "src/ponos/__init__.py"
        init_py.write_text(init_py.read_text().replace('__version__ = "', '__version__ = "9.', 1))
        second = land("two")

        # Started while the update copies, resets and checks the new version.
        during: list[str] = []
        installing = threading.Thread(
            target=lambda: during.append(update.install(update.check(app, "main"), 600, app))
        )
        installing.start()
        meanwhile: list[subprocess.Popen] = []
        while installing.is_alive():
            # A few at a time: a pass every 50 ms, unbounded, slowed the
            # update past a minute in the image — and past the held pass.
            if sum(one.poll() is None for one in meanwhile) < 3:
                meanwhile.append(started("run"))
            time.sleep(0.05)
        installing.join()
        assert during == [""], during
        assert app.resolve().name == f"app-{second[:12]}"
        # The new version's own environment, holding what it imports, before
        # anything ran on it.
        probe = subprocess.run(
            [str(app / ".venv" / "bin" / "python"), "-c", "import httpx, fastapi, uvicorn"],
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0, probe.stderr

        meanwhile.append(started("run"))
        for one in meanwhile:
            said = one.communicate(timeout=120)[0]
            assert one.returncode == 0 and "Error" not in said, said
            assert "already in progress" in said, said

        # The held pass started on the old version; it is still whole on disk.
        previous = app.with_name(f"app-{first[:12]}")
        assert "HANDOVER" not in (previous / "src/ponos/store.py").read_text(), (
            "the version a pass was running on was written over"
        )
        hold.touch()
        said = held.communicate(timeout=120)[0]
        assert held.returncode == 0 and "Error" not in said, said
        assert machine.status(ticket) == "Done", machine.status(ticket)

        version = started("--version")
        assert "9." in version.communicate(timeout=60)[0], "the next pass is not the new version"
        after = started("run")
        said = after.communicate(timeout=120)[0]
        assert after.returncode == 0 and "Error" not in said, said


def _worktree_of(machine: Bench) -> Path:
    """The one worktree a failed ticket left in the state directory."""
    (path,) = (Path(os.environ["XDG_STATE_HOME"]) / "ponos" / "worktrees").glob("*")
    return path


@case
@runner_settings(keep_worktree_on_failure=True)
def a_worktree_left_in_the_middle_of_a_rebase_is_saved_and_the_ticket_starts_again(machine):
    """A session killed while it resolved conflicts: 36 tickets could not get a worktree.

    The worktree is in a rebase with an untracked file next to it, and
    `add_worktree` used to refuse it for good ("still holds work"). It is saved
    to a branch of its own, the rebase is given up, and the ticket carries on
    from its own branch — told, in its prompt, where the backup is.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Reprendre un rebase", "Fais-le.", project)
    with _environ({"FAKE_CLAUDE_FAIL": "la session a planté"}):
        machine.run()
    worktree = _worktree_of(machine)

    # The branch moves one way, main another, and the replay stops on it.
    (worktree / "README.md").write_text("# côté ticket\n", encoding="utf-8")
    _git(["commit", "-am", "côté ticket"], worktree)
    machine.land(repository, "README.md", "# côté main\n")
    _git(["fetch", "origin"], worktree)
    stopped = subprocess.run(
        ["git", "rebase", "origin/main"], cwd=str(worktree), capture_output=True, text=True
    )
    assert stopped.returncode != 0, "the rebase was meant to stop on a conflict"
    (worktree / "a-moitie-fait.txt").write_text("du travail non commité\n", encoding="utf-8")

    machine.move(ticket, "Ready")
    results = machine.run()

    assert results[0]["status"] == "done", results
    said = "\n".join(machine.board.said(ticket))
    assert "could not make the worktree" not in said and "pas pu créer le worktree" not in said, (
        said
    )
    backups = [
        name
        for name in subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=str(repository),
            capture_output=True,
            text=True,
        ).stdout.split()
        if name.startswith("ponos/backup/")
    ]
    assert len(backups) == 1 and f"/{short_id(ticket)}-" in backups[0], backups
    saved = subprocess.run(
        ["git", "show", f"{backups[0]}:a-moitie-fait.txt"],
        cwd=str(repository),
        capture_output=True,
        text=True,
    )
    assert saved.stdout.strip() == "du travail non commité", saved
    assert backups[0] in machine.sessions()[-1]["prompt"], "the session is not told of the backup"
    assert backups[0] in said, said


@case
def a_session_killed_is_resumed_once_and_blocked_as_killed_if_it_dies_again(machine):
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    machine.ticket("Une session tuée", "Fais-le.", project)
    count = machine.root / "logs" / "count"

    with _environ({"FAKE_CLAUDE_KILL": "1", "FAKE_CLAUDE_COUNT": str(count)}):
        results = machine.run()
    assert results[0]["status"] == "done", results
    started = machine.sessions()
    assert len(started) == 2, "one start, and one more"
    assert started[0]["session"] == started[1]["session"], "the same conversation is carried on"

    count.unlink()
    again = machine.ticket("Une session tuée deux fois", "Fais-le.", project)
    with _environ({"FAKE_CLAUDE_KILL": "9", "FAKE_CLAUDE_COUNT": str(count)}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert results[0]["code"] == "session.killed", results[0]
    assert len(machine.sessions()) == 2, "once more, and no third time"
    assert machine.status(again) == "Blocked", machine.status(again)
    said = "\n".join(machine.board.said(again))
    assert "SIGKILL" in said, said
    assert not machine.worktrees(repository), "no worktree left behind"


@case
def a_board_that_cannot_be_reached_marks_no_ticket_failed_and_the_run_does_not_fail(machine):
    import argparse

    from ponos import __main__ as command

    repository = machine.repository("site")
    ticket = machine.ticket("Pendant la coupure", "Fais-le.", machine.project("Site", repository))
    patched, http_module.sleep = http_module.sleep, lambda seconds: None
    try:
        with _environ(
            {
                notion.API_ENV: "http://ponos-offline.invalid",
                "PONOS_CONFIG": str(machine.config),
            }
        ):
            code = command.command_run(
                argparse.Namespace(every=None, dry_run=False, limit=None, ticket="")
            )
    finally:
        http_module.sleep = patched
    assert code == 0, "the service must not fail while the network is away"
    assert machine.status(ticket) == "Ready", machine.status(ticket)
    assert not [
        page
        for page in machine.board.pages.values()
        if "Failed" in str(page["properties"].get("Status"))
    ]
    assert not machine.sessions(), "nothing runs without a board"
    assert machine.run()[0]["status"] == "done", "and the next pass, with the network back, runs it"


def _with_an_on_prompt(machine: Bench, ticket: str, prompt: str) -> None:
    """The board given its « On » column, and a ticket the prompt written in it."""
    database = machine.board.databases[machine.database]
    database["properties"] = {
        **database["properties"],
        "On": {"type": "rich_text", "rich_text": {}},
    }
    machine.board.pages[ticket]["properties"]["On"] = _stored({"rich_text": _rich(prompt)})


@case
def a_status_that_moves_runs_the_on_prompt_once_and_a_restart_does_not_run_it_again(machine):
    """The prompt of a ticket, woken by a change and by nothing else.

    A fresh `Runner` for every pass is the restart: what keeps a change from
    running twice is not in the process. And the first reading of a ticket is a
    starting point — turning the feature on must not replay a board's past.
    """
    from ponos import transitions

    ticket = machine.ticket("Déployer le site", "Rien à faire ici.", status="Failed")
    _with_an_on_prompt(machine, ticket, "Si on passe en Blocked, note-le dans le brief.")

    assert machine.run() == [] and not machine.sessions(), "a first sight is not a change"

    machine.move(ticket, "Blocked")
    results = machine.run()
    assert [entry["status"] for entry in results] == ["on-ok"], results
    assert results[0]["transition"] == "Failed → Blocked", results
    sessions = machine.sessions()
    assert len(sessions) == 1, sessions
    prompt = sessions[0]["prompt"]
    assert "Old status: Failed" in prompt and "New status: Blocked" in prompt, prompt
    assert "Si on passe en Blocked, note-le dans le brief." in prompt
    assert "Déployer le site" in prompt, "the ticket reaches the prompt"
    assert sessions[0]["budget"] == "1.00", "an execution has a ceiling"

    # The log is emptied before each pass: a session here would be a second one.
    for _ in range(2):
        assert machine.run() == [] and not machine.sessions(), "one execution per change"

    machine.move(ticket, "Failed")
    assert len(machine.run()) == 1 and len(machine.sessions()) == 1, "the next change runs it again"
    history = transitions.history(ticket)
    assert [(row["old"], row["new"], row["state"]) for row in history] == [
        ("Blocked", "Failed", "ok"),
        ("Failed", "Blocked", "ok"),
    ], history
    assert history[0]["cost_usd"], "what an execution cost is kept"
    assert machine.status(ticket) == "Failed", "the prompt's own session moved nothing"


@case
def an_on_prompt_that_fails_says_so_on_the_ticket_and_leaves_its_status_alone(machine):
    from ponos import transitions

    ticket = machine.ticket("Fragile", "Rien.", status="Failed")
    _with_an_on_prompt(machine, ticket, "Fais quelque chose.")
    machine.run()

    machine.move(ticket, "Blocked")
    with _environ({"FAKE_CLAUDE_FAIL": "le réseau est tombé"}):
        results = machine.run()

    assert [entry["status"] for entry in results] == ["on-failed"], results
    assert machine.status(ticket) == "Blocked", "an error never moves a status"
    said = machine.board.said(ticket)
    assert said and "« On »" in said[-1] and "Failed → Blocked" in said[-1], said
    assert transitions.history(ticket)[0]["state"] == "failed"
    assert machine.run() == [] and not machine.sessions(), "a failed change is not tried again"


@case
def an_on_prompt_is_not_run_when_the_feature_is_off_nor_for_an_empty_prompt():
    with bench(on=False) as machine:
        ticket = machine.ticket("Muet", "Rien.", status="Failed")
        _with_an_on_prompt(machine, ticket, "Fais quelque chose.")
        machine.run()
        machine.move(ticket, "Blocked")
        machine.run()
        assert not machine.sessions(), "runner.on = false runs nothing"

    with bench() as machine:
        ticket = machine.ticket("Sans prompt", "Rien.", status="Failed")
        _with_an_on_prompt(machine, ticket, "")
        machine.run()
        machine.move(ticket, "Blocked")
        machine.run()
        assert not machine.sessions(), "an empty prompt does nothing"


def main() -> int:
    return support.run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
