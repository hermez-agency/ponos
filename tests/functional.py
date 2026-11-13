#!/usr/bin/env python3
"""The road a ticket travels, end to end, under assertions.

    uv run python tests/functional.py   # or python3, with requirements.txt installed

`tests/run.py` covers the pure part and assumes it touches nothing — not git,
not the network. What that leaves uncovered is the road itself: ready ticket,
worktree, session, branch, pull request, status written back. And that is the
half which breaks quietly. A ticket that runs on an empty directory, a session
paid for and thrown away, a pull request nobody ever linked to its ticket —
none of those raises anything. They leave a board that still looks plausible.

So the world is doubled rather than mocked. The board is the real one —
`ponos.db`, in a state directory of the test's own — and a scenario writes and
reads it the way the console would, through the store; a repository and a bare
remote stand in for GitHub; a `claude` and a `gh` at the head of `PATH` do what
the real ones do, minus the thinking and the network. The runner is told none
of it: it loads a configuration, reads its board and works.

Nothing here leaves the machine, and nothing is written outside a temporary
directory: `XDG_STATE_HOME` moves with the test, and takes the board, the
worktrees, the logs and the history with it.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# `python -I` leaves the script's own directory off `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
from support import case, fixture  # noqa: E402

from ponos import (  # noqa: E402
    base,
    credits,
    db,
    diagnostic,
    github_checks,
    journal,
    library,
    local_ci,
    pages,
    planning,
    preview,
    project_settings,
    provider,
    question,
    schema,
    state,
    store,
    tickets,
)
from ponos import config as C  # noqa: E402
from ponos.runner import Runner  # noqa: E402
from ponos.ticket import short_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

Case = TypeVar("Case", bound=Callable[..., None])

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
    """A page identifier: 32 hexadecimal characters."""
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# -- the board, as a person reaches it ----------------------------------------


class Board:
    """`ponos.db`, written and read through the store — the gestures of the console.

    Everything a test wants to know afterwards — the status a ticket ended on,
    the pull request written into it, what was said in its comments — is read
    straight off the board somebody would look at on Monday, not off a
    transcript of what the runner did.
    """

    def __init__(self, config: Path) -> None:
        self.config = config

    @property
    def client(self) -> store.Store:
        """The store the runner opens, on the file the bench wrote — read again each time."""
        return store.open(C.load(self.config))

    # -- writing -------------------------------------------------------------

    def set(self, page_id: str, name: str, value: Any) -> None:
        """One column of a ticket, as a person would change it."""
        self.client.update("tickets", page_id, {name: value})

    def comment(self, page_id: str, text: str) -> None:
        """Somebody else's comment on a ticket, in a discussion of its own."""
        tickets.comment(page_id, text, author="someone", discussion=_ident())

    def trash(self, page_id: str) -> None:
        self.client.trash(page_id)

    # -- reading it back -----------------------------------------------------

    def value(self, page_id: str, name: str) -> Any:
        return store.read(self.client.page(page_id), name)

    def url(self, page_id: str) -> str:
        return self.client.page(page_id).url

    def body(self, page_id: str) -> str:
        """The page's text — enough to say what was written into it."""
        return self.client.blocks_text(page_id)

    def said(self, page_id: str) -> list[str]:
        """Everything commented on that page, oldest first."""
        return [comment.text for comment in self.client.comments(page_id)]

    def tickets(self) -> list[tickets.Record]:
        return tickets.listing()


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

# `claude auth status`, as `provider.cli_login` asks it: signed in, unless
# `FAKE_CLAUDE_SIGNED_OUT` says the account's sign-in has expired.
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": not os.environ.get("FAKE_CLAUDE_SIGNED_OUT"),
                      "authMethod": "claude.ai", "email": "ada@example.com"}))
    raise SystemExit(0)

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
             "mode": args[args.index("--permission-mode") + 1] if "--permission-mode" in args else "",
             "budget": args[args.index("--max-budget-usd") + 1]
             if "--max-budget-usd" in args else "",
             "permission_mode": args[args.index("--permission-mode") + 1]
             if "--permission-mode" in args else "",
             "base_url": os.environ.get("ANTHROPIC_BASE_URL", ""),
             "skills": sorted(os.listdir(".claude/skills")) if os.path.isdir(".claude/skills") else [],
             "claude_md": Path("CLAUDE.md").read_text(encoding="utf-8")
             if os.path.isfile("CLAUDE.md") else ""}
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


# What the Bash tool does with every command it runs: a session of its own, out
# of the CLI's process group — a `pnpm dev` started that way is not in the group
# the runner kills. `FAKE_CLAUDE_DETACH` is where its pid is written.
detached = os.environ.get("FAKE_CLAUDE_DETACH", "")
if detached:
    server = subprocess.Popen(["setsid", "sleep", "600"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(detached).write_text(str(server.pid))


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

# The self-review before the push reads and writes nothing: it answers what
# `FAKE_CLAUDE_REVIEW` says — `REVIEW: ok` when nothing does — for free, so
# that what every other scenario counts is what it counted before.
if "You are reviewing a branch before its pull request is opened" in prompt:
    said = os.environ.get("FAKE_CLAUDE_REVIEW", "") or "REVIEW: ok"
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 1,
          "total_cost_usd": float(os.environ.get("FAKE_CLAUDE_REVIEW_COST", "0") or 0)})
    raise SystemExit(0)

# The ticket's session, picked up on what the review found: it fixes the first
# point — `REVIEWED.md` committed — and leaves the others, saying so.
if "a review read your diff against the ticket" in prompt:
    here = Path.cwd()
    (here / "REVIEWED.md").write_text("fixed after review\\n", encoding="utf-8")
    subprocess.run(["git", "add", "REVIEWED.md"], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Corrige la relecture"],
                   cwd=here, check=True, capture_output=True)
    import re

    points = re.findall(r"^\\d+\\. (.+)$", prompt, re.MULTILINE)
    said = "\\n".join(
        ["FIXED: REVIEWED.md — le critère de fin est tenu"]
        + ["LEFT: " + point + " — hors du ticket" for point in points[1:]]
        + ["RESULT: ok — la relecture est traitée"]
    )
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 2, "total_cost_usd": 0.03})
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

# A sign-in that expired: the session dies at once, free, on this sentence.
if os.environ.get("FAKE_CLAUDE_SIGNED_OUT"):
    emit({"type": "result", "subtype": "success", "is_error": True,
          "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
          "session_id": session, "num_turns": 0, "total_cost_usd": 0})
    raise SystemExit(1)

refused = os.environ.get("FAKE_CLAUDE_FAIL", "")
if refused:
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
          "result": refused, "session_id": session, "num_turns": 1, "total_cost_usd": spent})
    raise SystemExit(1)

# A session given Ponos's browser (`--mcp-config`): it starts `ponos-browser` the
# way Claude Code does, and plays `FAKE_CLAUDE_BROWSE` — a JSON list of
# [tool, arguments], where "$NAME" is the value of a variable it holds, the way a
# model would copy one out of its environment — writing every call and every
# answer into its stream as the CLI does. What came back is its ANSWER.md.
browse = os.environ.get("FAKE_CLAUDE_BROWSE", "")
if browse and "--mcp-config" in args:
    servers = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())["mcpServers"]
    spec = servers["ponos-browser"]
    server = subprocess.Popen([spec["command"], *spec["args"]], env={**os.environ, **spec["env"]},
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def rpc(number, method, params):
        server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": number, "method": method,
                                       "params": params}) + "\\n")
        server.stdin.flush()
        return json.loads(server.stdout.readline())

    rpc(0, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    answers = []
    for number, (tool, arguments) in enumerate(json.loads(browse), start=1):
        arguments = {key: os.environ.get(value[1:], value)
                     if isinstance(value, str) and value.startswith("$") else value
                     for key, value in arguments.items()}
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{number}", "name": "mcp__ponos-browser__" + tool,
             "input": arguments}]}})
        reply = rpc(number, "tools/call", {"name": tool, "arguments": arguments})["result"]
        emit({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{number}", "content": reply["content"],
             "is_error": reply["isError"]}]}})
        first = reply["content"][0]
        answers.append(tool + ": " + (first.get("text") or "[" + first["type"] + "]"))
    server.stdin.close()
    server.wait(timeout=60)
    (Path.cwd() / "ANSWER.md").write_text("\\n\\n".join(answers), encoding="utf-8")
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "Fait."}]}})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "result": "RESULT: ok — navigation faite", "session_id": session, "num_turns": 4,
          "total_cost_usd": 0.02})
    raise SystemExit(0)

here = Path.cwd()


def finish(said, turns=3, cost=0.02):
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": turns, "total_cost_usd": cost})
    raise SystemExit(0)


# A session in plan mode — a ticket ticked « Plan d'abord »: it cannot write,
# so it says its plan between the tags and stops blocked, committing nothing.
if "--permission-mode" in args and args[args.index("--permission-mode") + 1] == "plan":
    finish("Je lis le dépôt.\\n<plan>\\n1. Écrire FAKE.md\\n\\n- Fichiers : FAKE.md\\n- Risques : aucun\\n"
           "- Coût : S\\n</plan>\\nRESULT: blocked — écrire FAKE.md")

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

# A diagnostic: it looks through the repository it is told it may read for the
# line `FAKE_CLAUDE_DIAGNOSE` names. Found, it reports the file and the line, and
# writes two fix tickets, the second after the first. Found nowhere, it stops
# blocked on what it ruled out — leaving a FIXES.json anyway, which a diagnostic
# that found nothing must never turn into tickets.
sought = os.environ.get("FAKE_CLAUDE_DIAGNOSE", "")
if sought and "# This ticket is a diagnostic" in prompt:
    import re

    where = re.search(r"repository is at (\\S+?): read it", prompt)
    hits = []
    if where:
        root = Path(where.group(1))
        for path in sorted(root.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if sought in line:
                    hits.append((str(path.relative_to(root)), number, line.strip()))
    guess = {"title": "Réécrire tout le calcul", "context": "Peut-être.", "expected": "Tout.",
             "done": "Quand ça marche.", "out": "Rien."}
    if not hits:
        (here / "FIXES.json").write_text(json.dumps([guess]), encoding="utf-8")
        finish("J'ai lu le dépôt, l'historique et les journaux : aucune ligne ne produit ce "
               "symptôme.\\nÉliminé : le calcul, la configuration.\\nCATEGORY: question\\n"
               "QUESTION: Sur quelle machine le total est-il faux ?\\nMODE: free\\n"
               "RESULT: blocked — la cause n'est pas dans le dépôt")
    name, number, line = hits[0]
    (here / "ANSWER.md").write_text(
        "## Symptôme\\n\\nLe total est faux.\\n\\n## Cause\\n\\n`" + name + ":" + str(number)
        + "` : `" + line + "` soustrait au lieu d'additionner.\\n\\n## Ce qui reste incertain"
        "\\n\\nRien.\\n\\n## Corrections\\n\\n- Additionner dans total\\n- Tester le total\\n",
        encoding="utf-8",
    )
    (here / "FIXES.json").write_text(json.dumps([
        {"title": "Additionner dans total", "context": "`" + name + ":" + str(number)
         + "` soustrait.", "expected": "Remplacer `-` par `+` dans `total`.",
         "done": "`total(2, 3)` vaut 5.", "out": "Le reste du module.", "subtype": "bug",
         "priority": 80},
        {"title": "Tester le total", "context": "Aucun test ne couvre `total`.",
         "expected": "Un test de `total`.", "done": "Le test passe.", "out": "Le code.",
         "after": [0]},
    ]), encoding="utf-8")
    finish("RESULT: ok — la cause est " + name + ":" + str(number))

# A ticket run without its repository that asks for one: the session says so on
# its `KIND: code` line — `FAKE_CLAUDE_WRONG_KIND` is why — and does nothing.
# Given its worktree, it commits like any other.
wrong = os.environ.get("FAKE_CLAUDE_WRONG_KIND", "")
if wrong and not (here / ".git").exists():
    finish("Il me faut le dépôt.\\nKIND: code\\nRESULT: blocked — " + wrong)

# A code ticket whose work happened outside the repository: nothing committed,
# and the report says where it went — `FAKE_CLAUDE_ELSEWHERE` is that report.
elsewhere = os.environ.get("FAKE_CLAUDE_ELSEWHERE", "")
if elsewhere and (here / ".git").exists():
    finish(elsewhere if "RESULT:" in elsewhere else elsewhere + "\\nRESULT: ok — fait hors du dépôt")

# A code ticket that changed a file and committed nothing.
if os.environ.get("FAKE_CLAUDE_DIRTY") and (here / ".git").exists():
    (here / "FAKE.md").write_text("changed, never committed\\n", encoding="utf-8")
    finish("J'ai modifié FAKE.md.\\nRESULT: ok — le fichier est modifié")

# A second ticket landed on the base branch while this session was running.
# `FAKE_CLAUDE_MOVES_BASE` names the clone it landed in: a commit on `main`,
# pushed — which is what a merge on GitHub does under a session that started an
# hour ago, and what the branch has to be replayed onto before its own pull
# request is opened, or merged once its conflict is resolved.
def move_base(moved):
    clone = Path(moved)
    other = clone / "OTHER.md"
    before = other.read_text(encoding="utf-8") if other.exists() else ""
    other.write_text(before + "un autre ticket est passé par là\\n", encoding="utf-8")
    subprocess.run(["git", "add", "OTHER.md"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Autre", "-c", "user.email=autre@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Un autre ticket"],
                   cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)


moved = os.environ.get("FAKE_CLAUDE_MOVES_BASE", "")

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
    # Somebody else pushed to the pull request's branch while it was resolved:
    # one commit on top of the one the replay started from, which the lease the
    # runner pushes on was taken on.
    if os.environ.get("FAKE_CLAUDE_PUSHES_OVER"):
        import re

        branch, was = re.search(r"`([^`]+)` \\(at `([0-9a-f]+)`\\)", prompt).groups()
        tree = subprocess.run(["git", "rev-parse", was + "^{tree}"], cwd=here, check=True,
                              capture_output=True, text=True).stdout.strip()
        theirs = subprocess.run(["git", *identity, "commit-tree", "-p", was, "-m",
                                 "Poussé par quelqu'un d'autre", tree], cwd=here, check=True,
                                capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "push", "origin", theirs + ":refs/heads/" + branch], cwd=here,
                       check=True, capture_output=True)
    if moved:
        move_base(moved)
    said = ("\\n".join(f"- `{name}` : les deux versions gardées" for name in resolved)
            + "\\nVérifications : aucune dans ce dépôt.\\n"
            "RESULT: ok — conflit résolu en gardant les deux côtés")
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
          "session_id": session, "num_turns": 4, "total_cost_usd": 0.05})
    raise SystemExit(0)

# A pull request reviewed on GitHub: the session addresses each comment with a
# commit, and answers each thread by its id, as the prompt asks.
if "Review comments left on GitHub" in prompt:
    import re

    ids = re.findall(r"^\\[([\\w-]+)\\] @", prompt, re.MULTILINE)
    (here / "REVIEWED.md").write_text("reviewed\\n", encoding="utf-8")
    subprocess.run(["git", "add", "REVIEWED.md"], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Traite la revue"],
                   cwd=here, check=True, capture_output=True)
    if os.environ.get("FAKE_CLAUDE_REVIEW_NOTHING"):
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=here, check=True,
                       capture_output=True)
        said = "\\n".join(f"REPLY {one}: c'est voulu, rien à changer" for one in ids)
        finish(said + "\\nRESULT: ok — rien à changer, expliqué dans les fils", turns=2)
    said = "\\n".join(f"REPLY {one}: corrigé dans REVIEWED.md" for one in ids)
    finish(said + "\\nRESULT: ok — revue traitée", turns=2)

# A validated pull request red by its own fault: the repair session fixes it
# the way the CI of the scenarios checks — `FIXED.md` committed, nothing pushed.
if "You are repairing that" in prompt:
    (here / "FIXED.md").write_text("fixed\\n", encoding="utf-8")
    subprocess.run(["git", "add", "FIXED.md"], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Répare la CI"],
                   cwd=here, check=True, capture_output=True)
    finish("Le test cherchait FIXED.md.\\nRESULT: ok — FIXED.md ajouté", turns=2, cost=0.04)

# The project's CI, run on this machine before the push, went red: the fake
# fixes it the way the CI of the scenarios checks — `FIXED.md` committed.
if "the project's CI was run on this machine" in prompt:
    (here / "FIXED.md").write_text("fixed\\n", encoding="utf-8")
    subprocess.run(["git", "add", "FIXED.md"], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Corrige la CI locale"],
                   cwd=here, check=True, capture_output=True)
    finish("RESULT: ok — la CI locale est corrigée", turns=2, cost=0.01)

if moved and (here / ".git").exists():
    move_base(moved)

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
    # `-f`: a file the worktree's exclusions leave out is committed all the
    # same, as a session typing `git add -f` would.
    subprocess.run(["git", "add", "-f", "FAKE.md", *also], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Écrit par la fausse session"],
                   cwd=here, check=True, capture_output=True)
    said = "CAVEAT: pas essayé sur mobile\\nRESULT: ok — un fichier écrit et commité"
    # The ticket's result, between its tags, when `FAKE_CLAUDE_RESULT` gives one.
    if os.environ.get("FAKE_CLAUDE_RESULT"):
        said = "<result>\\n" + os.environ["FAKE_CLAUDE_RESULT"] + "\\n</result>\\n" + said
else:
    (here / "ANSWER.md").write_text("La réponse.", encoding="utf-8")
    said = "J'ai relu deux sources.\\nRESULT: ok — la réponse est dans ANSWER.md"

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
# A CI that reads the branch: green once the pull request's branch holds the
# file `FAKE_GH_GREEN_WITH` names — the fix a repair session commits.
green_with = os.environ.get("FAKE_GH_GREEN_WITH", "")
if green_with and args[:2] in (["pr", "checks"], ["pr", "view"]) and len(args) > 2:
    opened = pull_request(args[2])
    if opened and git("cat-file", "-e", opened["branch"] + ":" + green_with,
                      cwd=opened["remote"]).returncode == 0:
        checks = [dict(one, conclusion="SUCCESS") for one in checks]
if args[:2] == ["pr", "checks"]:
    if "--json" in args:
        print("unknown flag: --json", file=sys.stderr)
        raise SystemExit(1)
    if not checks:
        print("no checks reported on the branch", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0 if all(one["conclusion"] == "SUCCESS" for one in checks) else 1)

# The reviews of the pull requests, as `FAKE_GH_REVIEWS` holds them: `{"reviews":
# [...], "comments": [...], "replies": []}` in GitHub's own shapes. A reply
# posted in a thread is written back under `replies`, to be read by the scenario.
reviews_file = os.environ.get("FAKE_GH_REVIEWS", "")
if args[:1] == ["api"] and reviews_file and "/pulls/" in " ".join(args):
    method = args[args.index("-X") + 1] if "-X" in args else "GET"
    target = next(part for part in args[1:] if part.startswith("repos/"))
    path, _, query = target.partition("?")
    with open(reviews_file, encoding="utf-8") as handle:
        held = json.load(handle)
    if method == "POST" and path.endswith("/replies"):
        held["replies"].append({"to": path.split("/")[-2],
                                "body": args[args.index("-f") + 1].partition("=")[2]})
        with open(reviews_file, "w", encoding="utf-8") as handle:
            json.dump(held, handle)
        print("{}")
    elif method == "GET" and path.endswith("/reviews"):
        print(json.dumps(held["reviews"] if "page=1" in query else []))
    elif method == "GET" and path.endswith("/comments"):
        print(json.dumps(held["comments"] if "page=1" in query else []))
    else:
        raise SystemExit(1)
    raise SystemExit(0)

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
    if "headRefOid" in args:
        if not opened:
            raise SystemExit(1)
        print(git("rev-parse", opened["branch"], cwd=opened["remote"]).stdout.strip())
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

if args[:2] == ["run", "rerun"]:
    write({"command": "run rerun", "run": args[2] if len(args) > 2 else ""})
    raise SystemExit(0)

if args[:2] == ["pr", "list"]:
    raise SystemExit(0)

raise SystemExit(1)
'''


def _script(path: Path, source: str) -> None:
    # `-S`: no `site`, so none of the `.pth` files of the environment — among
    # them the one through which `pytest --cov` measures every Python it sees
    # start. A double holds none of `src/ponos`, imports nothing but the
    # standard library, and `git` runs dozens of times per scenario: measured,
    # it tripled what a scenario costs under coverage, for nothing counted.
    path.write_text(f"#!{sys.executable} -S\n{source}", encoding="utf-8")
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


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# -- the board, the configuration, the run -----------------------------------


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
    "self_review": False,  # and so is the self-review, which adds a session to every code ticket
    "schedule": False,
    "auto_update": False,
    "log_retention_days": 0,
    "timeout_minutes": 1,
    "max_concurrent": 2,
    "relaunch_delay_seconds": 0,  # a killed session is resumed at once
    "min_free_memory_mb": 0,  # whatever this machine has free today
    "min_free_disk_mb": 0,  # and whatever disk it has left
    "max_load_per_core": 0,  # and however busy its cores are
}


class Bench:
    """One machine, one board, and the gestures a scenario is written in."""

    def __init__(
        self,
        root: Path,
        board: Board,
        logs: dict[str, Path],
        settings: dict[str, object],
    ) -> None:
        self.root = root
        self.settings = settings
        self.board = board
        # Whether the scenario has asked for the runner to work out the types
        # of its tickets — see `typed`.
        self._typed = False
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
        board = pages.Pages()
        values = {"Path": str(repository)} if repository is not None else {}
        identifier = board.create_row("projects", name, values)
        if brief:
            board.replace_markdown(identifier, brief)
        return identifier

    def ticket(
        self,
        title: str,
        body: str,
        project: str = "",
        status: str = "ready",
        kind: str = "",
        subtype: str = "",
    ) -> str:
        """A ticket, untyped unless `kind` says it — a daemon of its own classifies the others.

        `subtype` is the option a code ticket's « Sous-type » holds, `Bug`.
        """
        return tickets.create(
            title, status=status, project=project, mission=body, kind=kind, subtype=subtype
        ).id

    def typed(self) -> None:
        """The runner asked to work out the type of a ticket that has none.

        Every other scenario runs its untyped tickets by what their project
        holds, the road a ticket took before there were types: the
        classification is a session of its own, counted where it runs.
        """
        self._typed = True

    def subtyped(self) -> None:
        """The same, for the sub-type of a code ticket."""
        self.typed()

    def with_ci(self, repository: Path) -> None:
        """A workflow on `main`: the runner now waits for the checks of its pull requests."""
        workflows = repository / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("on: pull_request\n", encoding="utf-8")
        _git(["add", ".github"], repository)
        _git(["commit", "-m", "une CI"], repository)
        _git(["push", "origin", "main"], repository)

    def move(self, ticket: str, column: str) -> None:
        """A ticket dragged from one column to the next, as you would in the console."""
        self.board.set(ticket, "statut", column)

    def land(self, repository: Path, filename: str, text: str = "un autre ticket\n") -> None:
        """Another ticket merged: one commit on `main`, pushed to the remote.

        What every pull request still open is suddenly behind on, and the whole
        of what a repository taking ten tickets a day does to them.
        """
        (repository / filename).write_text(text, encoding="utf-8")
        _git(["add", filename], repository)
        _git(["commit", "-m", f"Un autre ticket — {filename}"], repository)
        _git(["push", "origin", "main"], repository)

    # -- the reviews of the pull requests ------------------------------------

    def review(
        self,
        reviews: list[dict[str, Any]] | None = None,
        comments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """What the fake GitHub holds of the reviews of every pull request, and the replies posted.

        Written whole each time: what a reviewer has said so far, as GitHub's own shapes.
        The replies the runner posted are kept, and returned.
        """
        path = self.root / "logs" / "reviews.json"
        replies = json.loads(path.read_text("utf-8"))["replies"] if path.exists() else []
        path.write_text(
            json.dumps({"reviews": reviews or [], "comments": comments or [], "replies": replies}),
            encoding="utf-8",
        )
        os.environ["FAKE_GH_REVIEWS"] = str(path)
        # A reviewer is asked about once a minute: let the next pass ask again.
        for record in self.board.tickets():
            ticket_id = record.id
            if row := state.review_row(ticket_id):
                state.keep_review(ticket_id, {**row, "asked": 0.0})
        return replies

    # -- running -------------------------------------------------------------

    def load(self) -> C.Config:
        """The configuration the file makes — and the constants a scenario changes.

        Most of what a scenario sets is no key of the file any more (a
        constant of the code): it is put on the runner after the file is read.
        """
        config = C.load(self.config)
        known: dict[str, Any] = {
            name: value for name, value in self.settings.items() if hasattr(config.runner, name)
        }
        known.setdefault("classify", self._typed)
        return replace(config, runner=replace(config.runner, **known))

    def run(self) -> list[dict[str, Any]]:
        """One pass of the runner, exactly the one the timer makes."""
        for path in self.logs.values():
            path.write_text("", encoding="utf-8")
        results = Runner(self.load(), quiet=True).tick()
        return results

    # -- reading back --------------------------------------------------------

    def status(self, ticket: str) -> str:
        return str(self.board.value(ticket, "statut") or "")

    def git_calls(self) -> list[dict[str, Any]]:
        return _lines(self.logs["FAKE_GIT_LOG"])

    def pull_requests(self) -> list[dict[str, Any]]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr create"]

    def pull_request_comments(self) -> list[dict[str, Any]]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr comment"]

    def merges(self) -> list[dict[str, Any]]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr merge"]

    def sessions(self) -> list[dict[str, Any]]:
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
[runner]
workspace_root = "{workspace}"
{settings}
"""


@contextmanager
def bench(**overrides: object) -> Iterator[Bench]:
    """A machine with a board, a workspace and a PATH of its own.

    Everything it changes is put back on the way out, the temporary directory
    included — so two scenarios never share a board, a state directory or a
    branch, and a scenario that fails leaves the machine as it found it.

    The pause GitHub is given after a rerun is asked (`RERUN_SETTLE_SECONDS`)
    is none here: the fake `gh` answers at once, and every case that runs a
    red job again would otherwise sleep it for real, making the tail of the
    suite.
    """
    with tempfile.TemporaryDirectory(prefix="ponos-functional-") as directory:
        root = Path(directory)
        _binaries(root / "bin")
        logs = {
            name: root / "logs" / f"{name.lower()}.jsonl"
            for name in ("FAKE_GIT_LOG", "FAKE_GH_LOG", "FAKE_CLAUDE_LOG")
        }
        for path in logs.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        environment = {
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
            "FAKE_CLAUDE_PUSHES_OVER": "",
            "FAKE_CLAUDE_COST": "",
            "FAKE_CLAUDE_BLOCK": "",
            "FAKE_CLAUDE_OVER_BUDGET": "",
            "FAKE_CLAUDE_KILL": "",
            "FAKE_CLAUDE_SILENT": "",
            "FAKE_CLAUDE_ELSEWHERE": "",
            "FAKE_CLAUDE_DIRTY": "",
            "FAKE_CLAUDE_SUBTYPE": "",
            "FAKE_CLAUDE_DETACH": "",
            "FAKE_CLAUDE_REVIEW": "",
            "FAKE_CLAUDE_REVIEW_COST": "",
            "FAKE_GH_REFUSE": "",
            "FAKE_GH_CHECKS": "",
            "FAKE_GH_ANNOTATION": "",
            "FAKE_GH_GREEN_WITH": "",
            "FAKE_GH_REVIEWS": "",
            "FAKE_CLAUDE_REVIEW_NOTHING": "",
            "FAKE_CLAUDE_BROWSE": "",
            "FAKE_CLAUDE_DIAGNOSE": "",
            "FAKE_CLAUDE_RESULT": "",
            **{name: str(path) for name, path in logs.items()},
        }
        with _environ(environment):
            settings = {**SETTINGS, **overrides}
            (root / "config.toml").write_text(
                CONFIGURATION.format(
                    workspace=root / "workspace",
                    # Only the keys the file has: the rest is put on the runner (`load`).
                    settings="\n".join(
                        f"{key} = {json.dumps(value)}"
                        for key, value in settings.items()
                        if key in schema.RunnerTable.model_fields
                    ),
                ),
                encoding="utf-8",
            )
            settle = github_checks.RERUN_SETTLE_SECONDS
            github_checks.RERUN_SETTLE_SECONDS = 0
            try:
                yield Bench(root, Board(root / "config.toml"), logs, settings)
            finally:
                github_checks.RERUN_SETTLE_SECONDS = settle
                db.close()


@contextmanager
def _environ(changes: dict[str, str]) -> Iterator[None]:
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


def runner_settings(**overrides: object) -> Callable[[Case], Case]:
    """What a case changes of `[runner]` on the `machine` it is given."""

    def settle(function: Case) -> Case:
        function.runner_settings = overrides  # type: ignore[attr-defined]  # read back by `machine`
        return function

    return settle


@fixture
def machine(case: Callable[..., None]) -> Iterator[Bench]:
    """The `bench` a case runs on, with the `@runner_settings` it asked for."""
    with bench(**getattr(case, "runner_settings", {})) as machine:
        yield machine


# -- the scenarios -----------------------------------------------------------


@case
@runner_settings(ideas_schedule="every_4h", ideas_scope="selected", ideas_per_batch=3)
def a_scheduled_pass_finds_ideas_for_the_projects_ticked_and_for_those_only(machine: Bench) -> None:
    """Every four hours, two projects of three ticked: ideas for them at each pass.

    The whole road of the pass, on the doubles: the board's project index,
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
    api = web_api.Api(machine.load())
    # The console is given the index it would have read from the board.
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
        last = idea_schedule.last()
        assert last is not None and last.found == 6
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
def a_code_ticket_comes_back_as_a_pull_request_with_nothing_but_an_access_token(
    machine: Bench,
) -> None:
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
def a_code_ticket_s_result_is_its_summary_with_the_files_and_the_diff(machine: Bench) -> None:
    """The session's result block, and what only the runner knows under it."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

    with _environ({"FAKE_CLAUDE_RESULT": "Le titre de l'entête dit enfin le nom du site."}):
        machine.run()

    record = tickets.get(ticket)
    assert record is not None
    assert record.result.startswith("Le titre de l'entête dit enfin le nom du site."), record.result
    assert "FAKE.md" in record.result and "1 file changed" in record.result, record.result
    opened = machine.pull_requests()[0]["url"]
    assert record.result.endswith(f"({opened}/files)"), record.result
    assert "Le titre de l'entête" not in record.journal, record.journal
    assert "<result>" not in record.journal


@case
def a_code_ticket_without_a_result_says_so_rather_than_passing_for_done(machine: Bench) -> None:
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

    machine.run()

    record = tickets.get(ticket)
    assert record is not None
    assert record.result == "", record.result
    said = machine.board.said(ticket)[-1]
    assert "No result rendered" in said or "Aucun résultat rendu" in said, said
    assert "Aucun résultat rendu" in record.journal or "No result rendered" in record.journal


@case
def a_code_ticket_comes_back_as_a_pull_request(machine: Bench) -> None:
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
    assert machine.status(ticket) == "review", machine.status(ticket)

    branch = results[0]["branch"]
    assert branch.startswith("ticket/corriger-l-entete-"), branch
    assert branch in machine.branches(repository), machine.branches(repository)
    assert "FAKE.md" in machine.files_on(repository, branch)

    opened = machine.pull_requests()
    assert len(opened) == 1, opened
    assert opened[0]["base"] == "main", opened[0]
    assert opened[0]["title"] == "Corriger l'entête", opened[0]
    page = machine.board.url(ticket)
    assert page in opened[0]["body"], "the pull request does not link back to the ticket"
    assert machine.board.value(ticket, "Pull Request") == opened[0]["url"]

    assert str(machine.board.value(ticket, "Agent") or "").startswith("ponos@")
    assert machine.board.value(ticket, "Session"), "the session was not written onto the ticket"
    assert tickets.get(ticket).duration >= 0  # type: ignore[union-attr]

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
def a_pdf_kept_for_one_project_reaches_its_sessions_and_no_other(machine: Bench) -> None:
    """Context → Library: a file for project X is in the prompt of X's next session, readable there.

    Told by its path on this machine, never copied into the worktree — and the
    session of another project hears nothing of it.
    """
    charter = b"%PDF-1.4 the brand charter"
    site = machine.project("Site", machine.repository("site"))
    blog = machine.project("Blog", machine.repository("blog"))
    kept = library.save(
        "charter.pdf",
        io.BytesIO(charter),
        len(charter),
        1 << 20,
        description="The brand charter",
        project_list=[site],
    )
    machine.ticket("Refaire l'entête du site", "Suis la charte.", site)
    machine.ticket("Refaire l'entête du blog", "Suis la charte.", blog)

    results = machine.run()

    assert len(results) == 2 and {one["status"] for one in results} == {"done"}, results
    told = {
        name: [one for one in machine.sessions() if f"Refaire l'entête du {name}" in one["prompt"]]
        for name in ("site", "blog")
    }
    assert told["site"] and told["blog"], told
    path = str(library.path_of(kept))
    line = f"- {path} — charter.pdf — The brand charter"
    assert "# Reference files" in told["site"][0]["prompt"], told["site"][0]["prompt"]
    assert line in told["site"][0]["prompt"]
    assert Path(path).read_bytes() == charter, "the session reads it where it was told"
    assert not Path(told["site"][0]["cwd"], "charter.pdf").exists(), "copied into the worktree"
    assert all("charter.pdf" not in one["prompt"] for one in told["blog"]), told["blog"]
    db.close()


@case
def a_skill_made_for_a_project_is_in_the_worktree_of_its_next_session_and_of_no_other(
    machine: Bench,
) -> None:
    """Contexte › Skills: a skill for project X reaches X's sessions, not Y's.

    A global one reaches both; and none of them ends in the branch the ticket
    delivers — the skills are left out of git, for the commit and for the pull request.
    """
    from ponos import skills

    repository = machine.repository("site")
    site = machine.project("Site", repository)
    other = machine.project("Autre", machine.repository("autre"))
    skills.create("pour-site", "Pour Site.", "# Site\n", [site])
    skills.create("pour-tous", "Pour tous.", "# Tous\n")
    first = machine.ticket("Corriger l'entête", "Le titre est faux.", site)
    second = machine.ticket("Corriger le pied", "Le pied est faux.", other)

    results = machine.run()

    assert {result["status"] for result in results} == {"done"}, results
    seen = [call["skills"] for call in machine.sessions()]
    by_prompt = {
        ("Corriger l'entête" in call["prompt"]): call["skills"] for call in machine.sessions()
    }
    assert by_prompt[True] == ["pour-site", "pour-tous"], seen
    assert by_prompt[False] == ["pour-tous"], seen
    assert first != second
    for branch in machine.branches(repository):
        assert not any(".claude/skills" in name for name in machine.files_on(repository, branch))
    db.close()


@case
def a_repository_with_only_agents_md_is_read_by_its_session_and_its_branch_carries_no_agent_file(
    machine: Bench,
) -> None:
    """AGENTS.md is the convention: the session reads it through a CLAUDE.md Ponos
    puts in the worktree, gets Ponos's skills there, and none of it is pushed."""
    from ponos import skills

    repository = machine.repository("site")
    (repository / "AGENTS.md").write_text("Un cas par module.\n", encoding="utf-8")
    _git(["add", "AGENTS.md"], repository)
    _git(["commit", "-m", "les instructions"], repository)
    _git(["push", "origin", "main"], repository)
    site = machine.project("Site", repository)
    skills.create("pour-tous", "Pour tous.", "# Tous\n")
    machine.ticket("Corriger l'entête", "Le titre est faux.", site)

    results = machine.run()

    assert [result["status"] for result in results] == ["done"], results
    [call] = [call for call in machine.sessions() if "Corriger l'entête" in call["prompt"]]
    assert call["claude_md"] == "@AGENTS.md\n", call
    assert call["skills"] == ["pour-tous"], call
    branch = results[0]["branch"]
    files = machine.files_on(repository, branch)
    assert "FAKE.md" in files and "AGENTS.md" in files, files
    assert not {"CLAUDE.md", ".claude", "skills-lock.json"} & set(files), files
    db.close()


@case
def a_branch_that_commits_agent_files_is_not_pushed_and_the_ticket_says_why(
    machine: Bench,
) -> None:
    """A session that forces `.claude/` into a commit: nothing reaches the remote."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)
    leaked = {"Le titre est faux, corrige-le.": {".claude/settings.local.json": "{}\n"}}

    with _environ({"FAKE_CLAUDE_ALSO": json.dumps(leaked)}):
        results = machine.run()

    assert results and results[0]["code"] == "merge.agent-files", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "merge.agent-files"
    said = "\n".join(machine.board.said(ticket))
    assert ".claude/settings.local.json" in said, said
    pushed = [name for name in machine.branches(repository) if name.startswith("ticket/")]
    assert not pushed, f"the branch reached the remote: {pushed}"
    assert not machine.pull_requests(), "a branch with agent files was opened as a pull request"


@case
def a_ticket_planned_first_commits_nothing_until_its_plan_is_approved(machine: Bench) -> None:
    """« Plan d'abord » ticked: a plan and a yes-no question, no commit; a yes: the pull request.

    The first session runs in plan mode and its plan lands in the report, under
    the question the console draws Yes and No buttons for. The yes is answered
    the way a phone answers it — a comment — and the second session carries
    the plan in its prompt, in the ordinary mode, with the box unticked.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Refondre l'entête", "Tout l'entête est à revoir.", project)
    machine.board.set(ticket, "Plan d'abord", True)

    results = machine.run()

    assert results[0]["status"] == "blocked", results
    assert results[0]["code"] == "session.question", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.sessions()[-1]["permission_mode"] == "plan", machine.sessions()[-1]
    assert not machine.pull_requests(), "a ticket planned first opened a pull request"
    assert not any(
        branch.startswith("ticket/") and "FAKE.md" in machine.files_on(repository, branch)
        for branch in machine.branches(repository)
    ), "a ticket planned first committed before its plan was approved"
    report = machine.board.said(ticket)[-1]
    assert "Shall I carry out this plan? → yes / no" in report, report
    assert "📋 The plan\n\n1. Écrire FAKE.md" in report, report
    asked = question.waiting(machine.board.said(ticket))
    assert asked is not None and asked.mode == "yes-no", asked

    def answer(text: str) -> None:
        machine.board.comment(ticket, text)

    # A sentence amends the plan: planned again, the plan answered in the prompt.
    answer("Ajoute une étape de test.")
    results = machine.run()
    assert results[0]["status"] == "blocked", results
    again = machine.sessions()[-1]
    assert again["permission_mode"] == "plan", again
    assert "Propose the plan again" in again["prompt"], again["prompt"]
    assert "1. Écrire FAKE.md" in again["prompt"], again["prompt"]
    assert not machine.pull_requests()

    answer("oui")
    results = machine.run()

    assert results[0]["status"] == "done", results
    assert machine.status(ticket) == "review", machine.status(ticket)
    last = machine.sessions()[-1]
    assert last["permission_mode"] != "plan", last
    assert "# The plan you carry out" in last["prompt"], last["prompt"]
    assert "1. Écrire FAKE.md" in last["prompt"], last["prompt"]
    assert machine.board.value(ticket, "Plan d'abord") is False
    assert len(machine.pull_requests()) == 1, machine.pull_requests()
    db.close()


@case
def a_project_rule_plans_its_high_tickets_first_once_even_on_a_board_without_the_box(
    machine: Bench,
) -> None:
    """Priority 80 over a rule at 70: planned first, though no column says so.

    The plan proposed in the comments is what carries it on: a yes runs it the
    ordinary way, and the rule — read on a first run only — does not plan it again.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    project_settings.set_plan(project, "Site", planning.Rule(priority=70))
    ticket = machine.ticket("Revoir le cache", "Le cache est lent.", project)
    low = machine.ticket("Corriger une coquille", "Une lettre de trop.", project)
    machine.board.set(ticket, "Priorité", 80)
    machine.board.set(low, "Priorité", 20)

    results = {result["id"]: result for result in machine.run()}

    assert results[ticket.replace("-", "")]["status"] == "blocked", results
    assert results[low.replace("-", "")]["status"] == "done", results
    planned = [one for one in machine.sessions() if one["permission_mode"] == "plan"]
    assert len(planned) == 1 and "Le cache est lent." in planned[0]["prompt"], planned

    machine.board.comment(ticket, "ok")
    results = {result["id"]: result for result in machine.run()}

    assert results[ticket.replace("-", "")]["status"] == "done", results
    assert machine.sessions()[-1]["permission_mode"] != "plan", machine.sessions()[-1]
    db.close()


@case
def a_ticket_after_another_is_not_claimed_until_that_one_is_done(machine: Bench) -> None:
    """A « Après » B, B in progress: A stays ready; B done: A starts at the next pass.

    The cause of block number one in October: a series made ready at once, and
    every ticket but the first paying a session to say « the one I need is not
    done yet ». The ticket waited for is in progress on another machine — the
    sweep leaves it where it is — so the only thing holding A back is « Après ».
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    first = machine.ticket("Migration 1", "Déplace le dépôt.", project, status="progress")
    machine.board.set(first, "Agent", "ponos@elsewhere")
    second = machine.ticket("Migration 2", "Suis le dépôt déplacé.", project)
    machine.board.set(second, "Après", [first])

    assert machine.run() == []
    assert machine.status(second) == "ready", machine.status(second)
    assert not machine.sessions(), "a session was paid for a ticket whose prerequisite is not done"

    machine.move(first, "done")
    results = machine.run()

    assert [result["id"] for result in results] == [second.replace("-", "")], results
    assert machine.status(second) == "review", machine.status(second)
    db.close()


@case
def a_server_the_bash_tool_started_in_its_own_session_does_not_outlive_the_session(
    machine: Bench,
) -> None:
    """`setsid sleep 600` from the worktree, then the session ends: the sleep goes too.

    Each command of Claude Code's Bash tool opens a session of its own, so the
    group the runner kills at the end of a session does not hold a Vitest, a
    Playwright or a `pnpm dev` it started. What still ties them to the ticket is
    the directory they run in.
    """
    pidfile = machine.root / "detached.pid"
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    machine.ticket("Lancer le serveur", "Lance le serveur de dev.", project)

    with _environ({"FAKE_CLAUDE_DETACH": str(pidfile)}):
        results = machine.run()

    assert results and results[0]["status"] == "done", results
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while _running(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    try:
        assert not _running(pid), "a process the session started from its worktree survived it"
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


# A Chrome that "photographs" a page by writing what the address answers.
PICTURING_CHROME = """import sys, urllib.error, urllib.request
target = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--screenshot="))
try:
    said = urllib.request.urlopen(sys.argv[-1], timeout=10).read()
except urllib.error.HTTPError as error:
    said = b"HTTP %d" % error.code
open(target, "wb").write(said)
"""


@case
def an_interface_ticket_comes_back_with_its_pages_before_and_after_on_the_pull_request(
    machine: Bench,
) -> None:
    """`preview` set: the branch and the base served, each page taken, nothing left running.

    The page photographed is the file the session writes: absent on the base,
    there on the branch — so each side is the one it says. The pictures go to
    origin outside any branch, and the comment on the pull request shows them
    from that commit.
    """
    _script(machine.root / "bin" / "google-chrome", PICTURING_CHROME)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    command = f"{sys.executable} -m http.server {port} --bind 127.0.0.1 & wait"
    url = f"http://127.0.0.1:{port}"
    project_settings.set_preview(
        project, "Site", preview.parse({"command": command, "url": url, "pages": ["/FAKE.md"]})
    )
    ticket = machine.ticket("Changer la couleur", "Le bouton passe en vert.", project)

    results = machine.run()

    assert results[0]["status"] == "done", results
    shots = preview.listing(ticket)
    assert [(s["side"], s["page"]) for s in shots] == [
        ("before", "/FAKE.md"),
        ("after", "/FAKE.md"),
    ], shots
    folder = preview.folder(ticket)
    assert (folder / "before-0.png").read_bytes() == b"HTTP 404", "the base was not the base"
    assert (folder / "after-0.png").read_bytes() != b"HTTP 404", "the branch was not the branch"
    assert not preview._answers(url), "the project's server outlived the pass"
    assert not machine.worktrees(repository), "the base's checkout was left behind"

    remote = machine.root / "remotes" / "site.git"
    pushed = subprocess.run(
        ["git", "rev-parse", f"refs/ponos/previews/{short_id(ticket)}"],
        cwd=remote,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert pushed, "the pictures were not pushed"
    comments = [
        entry for entry in _lines(machine.logs["FAKE_GH_LOG"]) if entry["command"] == "pr comment"
    ]
    assert len(comments) == 1, comments
    body = comments[0]["body"]
    picture = f"https://github.com/fake/repo/blob/{pushed}/after-0.png?raw=true"
    assert f"![after]({picture})" in body, body
    assert "![before](" in body, body


def _running(pid: int) -> bool:
    """Whether `pid` is alive — a zombie, already ended, is not."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


@case
@runner_settings(progress=True)
def the_page_keeps_the_report_and_the_journal_every_step(machine: Bench) -> None:
    """The ticket gets what was done; the console, reading the journal, gets the rest.

    A sentence and a command, from one session: neither goes onto the page —
    the step by step is the journal's, in the order they came — and the page
    ends on its part « What was done », the session's result in one sentence.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    page = machine.board.body(ticket)
    mission, done = page.split("What was done")
    assert "Le titre est faux, corrige-le." in mission, page
    assert "un fichier écrit et commité" in done, page
    assert "J'écris FAKE.md puis je le commite." not in page, page
    assert "git commit" not in page and "Bash" not in page, "a command was written onto the ticket"
    (run,) = journal.runs(ticket)
    kinds = [step["kind"] for step in journal.steps(run["id"])["steps"]]
    assert kinds == ["said", "tool", "said"], kinds
    db.close()


@case
def a_writing_ticket_is_answered_in_its_page_and_touches_no_repository(machine: Bench) -> None:
    """A project with no repository: the deliverable is the ticket's page.

    And nothing else. A document ticket that quietly made a worktree, or ran one
    git command anywhere, would be a writing task turned into a commit on
    something — which is the failure this scenario exists to catch.
    """
    project = machine.project("Lettre d'information", None, brief="On écrit court.")
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes sur l'automne.", project)

    results = machine.run()

    assert len(results) == 1, results
    assert results[0]["status"] == "done" and results[0]["kind"] == "document", results
    assert machine.status(ticket) == "done", machine.status(ticket)
    assert "La réponse." in machine.board.body(ticket), machine.board.body(ticket)
    assert results[0]["blocks"] > 0
    # The deliverable is the ticket's result, and the session's own words its
    # journal: neither is mixed into the other — see results.py.
    record = tickets.get(ticket)
    assert record is not None and record.result == "La réponse.", record
    assert "J'ai relu deux sources." in record.journal and "La réponse." not in record.journal
    assert [one.source for one in tickets.results(ticket)] == ["session"]

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
def a_change_asked_on_a_result_is_run_from_the_result_it_had(machine: Bench) -> None:
    """« Request a change »: the instruction in the comments, the result in the prompt."""
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes sur l'automne.", project)
    machine.run()
    tickets.set_result(ticket, "Premier jet, retouché.", source="edit", author="Léa")

    machine.board.comment(ticket, "Modification demandée sur le résultat — plus court.")
    machine.move(ticket, "ready")
    machine.run()

    prompt = machine.sessions()[-1]["prompt"]
    assert "<current-result>\nPremier jet, retouché.\n</current-result>" in prompt, prompt
    assert "plus court." in prompt
    kept = tickets.results(ticket)
    assert [(one.version, one.source) for one in kept] == [
        (3, "session"),
        (2, "edit"),
        (1, "session"),
    ], kept
    assert kept[0].text == "La réponse."


def _diagnosed_repository(machine: Bench) -> tuple[Path, str]:
    """A repository with a known bug on `main`, its project, and a board that can link tickets."""
    machine.typed()
    repository = machine.repository("calcul")
    machine.land(repository, "calc.py", "def total(a, b):\n    return a - b\n")
    return repository, machine.project("Calcul", repository)


def _diagnostic(machine: Bench, project: str) -> str:
    ticket = machine.ticket("Le total est faux", "La somme de 2 et 3 donne -1.", project)
    machine.board.set(ticket, "Type", "Diagnostic")
    return ticket


def _other_tickets(machine: Bench, *known: str) -> list[tuple[str, str]]:
    """The tickets the scenario did not write itself: their id and their title."""
    return [
        (record.id, record.title) for record in machine.board.tickets() if record.id not in known
    ]


@case
def a_diagnostic_finds_the_cause_on_its_line_and_creates_the_fix_tickets_linked_to_it(
    machine: Bench,
) -> None:
    """A known bug in the repository: the cause on its file and line, two fix tickets, closed.

    Read only — no worktree, no branch, no pull request —, the report in the
    page, and the tickets the session wrote created by the runner: in the
    drafts, each « after » the diagnostic, the second after the first too, and
    a mission that holds its four parts.
    """
    repository, project = _diagnosed_repository(machine)
    ticket = _diagnostic(machine, project)

    with _environ({"FAKE_CLAUDE_DIAGNOSE": "return a - b"}):
        results = machine.run()

    assert [result["status"] for result in results] == ["done"], results
    assert machine.status(ticket) == "done", "a diagnostic closes once its tickets are written"
    report = machine.board.body(ticket)
    assert "calc.py:2" in report and "soustrait" in report, report

    sessions = machine.sessions()
    assert len(sessions) == 1, sessions
    prompt = sessions[0]["prompt"]
    assert "find the cause, fix nothing" in prompt, prompt
    assert str(repository) in prompt and "What you may reach" in prompt, prompt
    assert not machine.pull_requests(), "a diagnostic opened a pull request"
    assert not any("worktree" in call["args"] for call in machine.git_calls()), "it got a worktree"

    created = _other_tickets(machine, ticket)
    by_title = {title: page_id for page_id, title in created}
    assert sorted(by_title) == ["Additionner dans total", "Tester le total"], by_title
    first, second = by_title["Additionner dans total"], by_title["Tester le total"]
    for fix in (first, second):
        assert machine.status(fix) == "draft", machine.status(fix)
        assert machine.board.value(fix, "Type") == "Code"
        assert machine.board.value(fix, "Project") == [project], machine.board.value(fix, "Project")
    bare = [one.replace("-", "") for one in machine.board.value(first, "Après")]
    assert bare == [ticket.replace("-", "")], bare
    bare = sorted(one.replace("-", "") for one in machine.board.value(second, "Après"))
    assert bare == sorted([ticket.replace("-", ""), first.replace("-", "")]), bare
    mission = machine.board.body(first)
    for part in ("Context", "Expected", "Done when", "Out of scope", "calc.py:2"):
        assert part in mission, mission
    assert "Fix tickets created (2)" in "\n".join(machine.board.said(ticket)), machine.board.said(
        ticket
    )


@case
def a_project_can_send_the_fix_tickets_of_its_diagnostics_straight_to_ready(
    machine: Bench,
) -> None:
    """Ready on the project's Diagnostic card: each fix starts once what it comes after is done.

    The first comes after the diagnostic alone, which closes in the same pass:
    it runs at once and waits in review. The second comes after the first too,
    and stays ready.
    """
    repository, project = _diagnosed_repository(machine)
    project_settings.set_diagnostic(project, "Calcul", diagnostic.Access(ready=True))
    ticket = _diagnostic(machine, project)

    with _environ({"FAKE_CLAUDE_DIAGNOSE": "return a - b"}):
        results = machine.run()

    assert machine.status(ticket) == "done", results
    statuses = {
        str(machine.board.value(fix, "Name") or ""): machine.status(fix)
        for fix, _ in _other_tickets(machine, ticket)
    }
    assert statuses == {"Additionner dans total": "review", "Tester le total": "ready"}, statuses
    assert len(machine.pull_requests()) == 1, "the first fix did not run as code"
    db.close()


@case
def a_diagnostic_that_finds_no_cause_is_blocked_on_a_question_and_creates_nothing(
    machine: Bench,
) -> None:
    """Nothing in the repository: blocked, what was ruled out and the question — and no ticket.

    Even though the session left a FIXES.json behind: a diagnostic that did not
    find its cause does not get to write a fix on a guess.
    """
    _, project = _diagnosed_repository(machine)
    ticket = _diagnostic(machine, project)

    with _environ({"FAKE_CLAUDE_DIAGNOSE": "une ligne qui n'existe pas"}):
        results = machine.run()

    assert machine.status(ticket) == "blocked", (machine.status(ticket), results)
    assert not _other_tickets(machine, ticket), "a fix ticket was written on a guess"
    said = "\n".join(machine.board.said(ticket))
    assert "Sur quelle machine le total est-il faux ?" in said, said
    assert not machine.pull_requests()


@case
@runner_settings(progress=True)
def a_ticket_run_again_is_not_briefed_on_its_previous_run(machine: Bench) -> None:
    """Ready three times: one part « What was done », three lines of history.

    The part is replaced at the end of every session, never stacked, and a
    session is told the mission alone: a ticket sent back to Ready that handed
    its next session every earlier report would pay for them at every run —
    and hand it old answers to take for instructions.
    """
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes sur l'automne.", project)

    with _environ({"FAKE_CLAUDE_SAY": "Je relis d'abord la charte éditoriale."}):
        results = machine.run()
    assert results[0]["status"] == "done", results
    for _ in range(2):
        machine.move(ticket, "ready")
        results = machine.run()
        assert results[0]["status"] == "done", results

    page = machine.board.body(ticket)
    headings = [line for line in page.splitlines() if line.startswith("## ")]
    assert headings.count("## What was done") == 1, headings
    history = [
        line for line in page.split("## What was done")[1].splitlines() if line.startswith("- ")
    ]
    assert len(history) == 3, page
    assert page.count("La réponse.") == 1, page
    assert "la charte éditoriale" not in machine.board.body(ticket), "a step reached the page"

    for later in machine.sessions()[1:]:
        prompt = later["prompt"]
        assert "Deux paragraphes sur l'automne." in prompt, prompt
        assert "La réponse." not in prompt, "an earlier report reached the next session"
        assert "What was done" not in prompt and "History" not in prompt, prompt


@case
def a_ticket_with_no_type_is_classified_then_published_only_once_validated(machine: Bench) -> None:
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
    assert machine.status(ticket) == "review", "a publication is prepared, then read"
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
    assert machine.run() == [] and machine.status(ticket) == "review"

    machine.move(ticket, "validated")
    results = machine.run()

    assert [result.get("kind") for result in results] == ["delivery"], results
    assert machine.status(ticket) == "done", machine.status(ticket)
    published = machine.sessions()
    assert len(published) == 1 and "You are publishing, not producing" in published[0]["prompt"]
    assert machine.board.value(ticket, "Type") == "Publication", "the type is left alone"


# `docker`, reduced to what the local CI asks of it: `info` answers, and every
# other call is recorded — `ps` finds one container of the ticket's compose
# project, which is what the clean-up has to remove.
DOCKER = """
import json, os, sys

args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")
if args[:1] == ["info"]:
    print("29.0.0")
elif args[:1] == ["ps"] and any("com.docker.compose.project=" in arg for arg in args):
    print("c0ffee")
elif args[:1] == ["rm"]:
    print("\\n".join(args[3:]))
"""


@contextmanager
def _docker(root: Path) -> Iterator[Callable[[], list[list[str]]]]:
    """A `docker` that answers, at the head of the bench's `PATH`; its calls, as it records them."""
    _script(root / "bin" / "docker", DOCKER)
    log = root / "logs" / "docker.jsonl"
    log.write_text("", encoding="utf-8")
    local_ci._docker = None
    try:
        with _environ({"FAKE_DOCKER_LOG": str(log)}):
            yield lambda: [json.loads(line) for line in log.read_text().splitlines()]
    finally:
        local_ci._docker = None


@case
@runner_settings(local_ci=True)
def a_ticket_whose_local_ci_fails_is_fixed_before_its_pull_request_opens(machine: Bench) -> None:
    """Red here, fixed by the same session, green here — and only then the pull request.

    The ticket keeps one line of it, and not a line of the CI's output; the
    containers of the ticket's CI are gone once it has run.
    """
    with _docker(machine.root) as calls:
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        project_settings.set_local_ci(
            project, "Site", None, "test -f FIXED.md || { echo FIXED.md manque; exit 1; }"
        )
        ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

        results = machine.run()

        assert results[0]["status"] == "done", results
        assert machine.status(ticket) == "review", machine.status(ticket)
        sessions = machine.sessions()
        assert len(sessions) == 2, sessions
        assert "the project's CI was run on this machine" in sessions[1]["prompt"], sessions[1]
        assert "FIXED.md manque" in sessions[1]["prompt"], "the session was not shown the failure"
        assert sessions[1]["session"] == sessions[0]["session"], "not the same session"
        opened = machine.pull_requests()
        assert len(opened) == 1, opened
        branch = results[0]["branch"]
        assert "FIXED.md" in machine.files_on(repository, branch), "the fix was not pushed"
        said = machine.board.said(ticket)[-1]
        assert "Local CI: failed, fixed in 2 attempts." in said, said
        assert "FIXED.md manque" not in said, "the CI's output reached the ticket"
        name = local_ci.name(ticket)
        removed = [call for call in calls() if call[:1] == ["rm"]]
        assert removed and all(call[-1] == "c0ffee" for call in removed), calls()
        assert any(f"label=com.docker.compose.project={name}" in call for call in calls())
        assert results[0]["cost_usd"] == 0.03, results[0]
        db.close()


@case
@runner_settings(self_review=True)
def a_branch_short_of_its_done_criterion_is_reviewed_fixed_once_and_its_pull_request_says_so(
    machine: Bench,
) -> None:
    """The review reads the ticket and the diff, the session is picked up once, the PR tells.

    Three sessions and no more: the ticket's, the review's — in plan mode, on
    `runner.review_model` — and the ticket's again, carried on. What all three
    cost is the ticket's.
    """
    os.environ["FAKE_CLAUDE_REVIEW"] = (
        "Le critère de fin demande un REVIEWED.md.\n"
        "REVIEW: blocking\n"
        "- REVIEWED.md: le critère de fin n'est pas tenu\n"
        "- docs/guide.md: le comportement n'est pas documenté"
    )
    os.environ["FAKE_CLAUDE_REVIEW_COST"] = "0.01"
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket(
        "Corriger l'entête",
        "Le titre est faux.\n\n## Critère de fin\n- REVIEWED.md existe",
        project,
    )

    results = machine.run()

    assert results[0]["status"] == "done", results
    sessions = machine.sessions()
    assert len(sessions) == 3, [one["prompt"][:60] for one in sessions]
    review, fix = sessions[1], sessions[2]
    assert "You are reviewing a branch" in review["prompt"], review["prompt"][:200]
    assert "REVIEWED.md existe" in review["prompt"], "the reviewer was not given the done criterion"
    assert "+the session was here" in review["prompt"], "the reviewer was not given the diff"
    assert (review["mode"], review["model"]) == ("plan", "sonnet"), review
    assert review["session"] != sessions[0]["session"], "the review is a session of its own"
    assert fix["session"] == sessions[0]["session"], "the ticket's session is not the one picked up"
    assert "`REVIEWED.md`: le critère de fin n'est pas tenu" in fix["prompt"], fix["prompt"]
    branch = results[0]["branch"]
    assert "REVIEWED.md" in machine.files_on(repository, branch), "the fix was not pushed"
    body = machine.pull_requests()[0]["body"]
    assert "### Review" in body and "Fixed:" in body and "Left:" in body, body
    assert "le critère de fin est tenu" in body, body
    assert body.index("### Review") < body.index("---"), "the review sits above the footer"
    said = machine.board.said(ticket)[-1]
    assert "Review: 2 blocking points, the session picked up once — fixed: 1, left: 1." in said, (
        said
    )
    assert results[0]["cost_usd"] == 0.06, results[0]


@case
@runner_settings(self_review=True)
def a_review_with_nothing_blocking_adds_nothing_to_the_pull_request(machine: Bench) -> None:
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    results = machine.run()

    assert results[0]["status"] == "done", results
    assert len(machine.sessions()) == 2, "picked up although nothing was blocking"
    assert "Review" not in machine.pull_requests()[0]["body"], machine.pull_requests()[0]["body"]
    assert "Review: nothing blocking." in machine.board.said(ticket)[-1]


@case
@runner_settings(self_review=True)
def a_project_that_turned_the_review_off_is_pushed_unread(machine: Bench) -> None:
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    project_settings.set_self_review(project, "Site", False)
    machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    results = machine.run()

    assert results[0]["status"] == "done", results
    assert len(machine.sessions()) == 1, "reviewed although the project said no"
    db.close()


@case
@runner_settings(local_ci=True, local_ci_attempts=2)
def a_local_ci_still_red_after_its_attempts_blocks_the_ticket_and_opens_nothing(
    machine: Bench,
) -> None:
    with _docker(machine.root):
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        # What it prints is not in what it is: the output is what must stay off the ticket.
        project_settings.set_local_ci(project, "Site", None, "printf 'lo%s\\n' gs-du-ci; exit 3")
        ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

        results = machine.run()

        assert machine.status(ticket) == "blocked", machine.status(ticket)
        assert results[0]["code"] == "merge.local-ci-failed", results[0]
        assert not machine.pull_requests(), "a pull request opened on a red local CI"
        assert len(machine.sessions()) == 2, machine.sessions()
        said = machine.board.said(ticket)[-1]
        assert "logs-du-ci" not in said, said
        assert "logs-du-ci" in machine.sessions()[1]["prompt"], machine.sessions()[1]
        db.close()


@case
@runner_settings(local_ci=True)
def without_docker_the_local_ci_is_skipped_and_the_ticket_runs_as_before(machine: Bench) -> None:
    local_ci._docker = (time.monotonic(), local_ci.Docker(False, False))
    try:
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        project_settings.set_local_ci(project, "Site", None, "exit 1")
        ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

        machine.run()

        assert machine.status(ticket) == "review", machine.status(ticket)
        assert len(machine.pull_requests()) == 1
        assert len(machine.sessions()) == 1
        assert "Local CI" not in machine.board.said(ticket)[-1]
    finally:
        local_ci._docker = None
    db.close()


@case
@runner_settings(force_validated_code=True)
def a_code_ticket_whose_validation_is_forced_is_merged_and_done_in_one_pass(machine: Bench) -> None:
    """Force validated for Code: the pull request is opened, then merged, unread.

    What the remote holds afterwards is the proof: `main` carries what the
    session wrote. And the report says why nobody was asked.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    results = machine.run()

    assert [result["status"] for result in results] == ["done"], results
    assert machine.status(ticket) == "done", machine.status(ticket)
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
def a_project_with_its_own_validation_is_read_before_the_file_in_both_directions() -> None:
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

        assert machine.status(merged) == "done", machine.status(merged)
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

        assert machine.status(kept) == "review", machine.status(kept)
        assert not machine.merges(), machine.merges()
        assert "Validated automatically" not in machine.board.said(kept)[-1]
        db.close()


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_github_refuses_leaves_the_ticket_in_review_with_the_reason(
    machine: Bench,
) -> None:
    """Checks red, rights missing: not done, and the refusal on the card."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    os.environ["FAKE_GH_REFUSE"] = 'Required status check "build" is failing'

    machine.run()

    assert machine.status(ticket) == "review", machine.status(ticket)
    assert "main" in machine.branches(repository)
    assert "FAKE.md" not in machine.files_on(repository, "main"), "merged all the same"
    said = machine.board.said(ticket)
    assert "Force validated: Code" in said[-1], said[-1]
    assert "is failing" in said[-1], said[-1]
    card = str(machine.board.value(ticket, "Progress") or "")
    assert "Not merged" in card and "is failing" in card, card
    assert "left in review" not in card, card


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
def a_code_ticket_is_merged_once_its_ci_is_green_whatever_its_sub_type(machine: Bench) -> None:
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
        machine.board.set(ticket, "Type", "Code")
        if subtype:
            machine.board.set(ticket, "Sous-type", subtype)
        repositories.append(repository)
        tickets.append(ticket)
    written, prefixed, deduced = tickets
    os.environ["FAKE_CLAUDE_SUBTYPE"] = json.dumps(
        {"subtype": "bug", "reason": "Un lien cassé.", "confidence": "high"}
    )
    os.environ["FAKE_GH_CHECKS"] = _check_runs("SUCCESS", "SUCCESS")

    machine.run()

    for ticket, subtype in ((written, "Bug"), (prefixed, "Feature"), (deduced, "Bug")):
        assert machine.status(ticket) == "done", (ticket, machine.status(ticket))
        assert machine.board.value(ticket, "Sous-type") == subtype, ticket
        assert "Force validated: Code" in machine.board.said(ticket)[-1]
    assert len(machine.merges()) == 3, machine.merges()
    assert all("FAKE.md" in machine.files_on(one, "main") for one in repositories)


@case
@runner_settings(force_validated_code=True)
def a_ticket_blocked_on_its_type_is_merged_once_somebody_gives_it(machine: Bench) -> None:
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

    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert "Type" in machine.board.said(ticket)[-1], machine.board.said(ticket)[-1]
    assert not machine.pull_requests()

    machine.board.set(ticket, "Type", "Code")
    machine.move(ticket, "ready")
    machine.run()

    assert machine.status(ticket) == "done", machine.status(ticket)
    assert machine.board.value(ticket, "Sous-type") == "Bug"
    assert len(machine.merges()) == 1, machine.merges()


def _stopped_by_its_ci(
    machine: Bench, verdicts: tuple[str, str], annotation: str, expected: str
) -> None:
    """A forced merge whose checks are red: left in review, the cause on its card."""
    repository = machine.repository("site")
    machine.with_ci(repository)
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    os.environ["FAKE_GH_CHECKS"] = _check_runs(*verdicts)
    os.environ["FAKE_GH_ANNOTATION"] = annotation

    machine.run()

    assert machine.status(ticket) == "review", machine.status(ticket)
    assert not machine.merges(), machine.merges()
    assert "FAKE.md" not in machine.files_on(repository, "main")
    said = machine.board.said(ticket)[-1]
    assert "Not merged, left in review" in said and expected in said, said
    card = str(machine.board.value(ticket, "Progress") or "")
    assert expected in card, card


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_red_by_its_code_names_the_red_checks_on_the_card(machine: Bench) -> None:
    """Red by the code: the checks are named, and it is not merged."""
    _stopped_by_its_ci(machine, ("SUCCESS", "FAILURE"), "", "red on `job 2`")


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_never_started_by_github_says_its_reason_on_the_card(machine: Bench) -> None:
    """Never started by GitHub for another reason than its billing: its reason,
    word for word, and it is not merged."""
    not_started = "The job was not started because the workflow was disabled."
    _stopped_by_its_ci(machine, ("FAILURE", "FAILURE"), not_started, "workflow was disabled")


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_github_refuses_for_the_billing_waits_validated_until_it_is_paid(
    machine: Bench,
) -> None:
    """Every job refused by the account's billing: not a question, not a session.

    The ticket waits in validated with the cause on its card, the account is in
    the health of the installation, and the passes after ask nothing of a
    session. Paid, the refused jobs are run again and the pull request lands.
    """
    from ponos import health

    repository = machine.repository("site")
    machine.with_ci(repository)
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    os.environ["FAKE_GH_CHECKS"] = _check_runs("FAILURE", "FAILURE")
    os.environ["FAKE_GH_ANNOTATION"] = (
        "The job was not started because recent account payments have failed or your "
        "spending limit needs to be increased."
    )

    machine.run()

    assert machine.status(ticket) == "validated", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "ci.billing"
    assert not machine.merges(), machine.merges()
    said = machine.board.said(ticket)[-1]
    assert "blocked by the billing of the" in said and "postponed" in said, said
    assert [check.code for check in health._github_billing()] == ["github.billing"]

    machine.run()

    assert machine.status(ticket) == "validated", machine.status(ticket)
    assert not machine.sessions(), "no session is sent after a bill"
    assert not machine.merges()

    os.environ["FAKE_GH_CHECKS"] = _check_runs("SUCCESS", "SUCCESS")
    os.environ["FAKE_GH_ANNOTATION"] = ""
    for hold in state.billing_holds():
        state.billing_probed(hold["account"], 0.0)
    machine.run()

    assert machine.status(ticket) == "done", machine.status(ticket)
    assert len(machine.merges()) == 1, machine.merges()
    assert not machine.sessions(), machine.sessions()
    assert health._github_billing() == []


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_refused_for_being_behind_waits_in_validated_and_lands_next_pass(
    machine: Bench,
) -> None:
    """Two tickets on one repository: the other one landed while this one's CI ran.

    GitHub refuses the merge for a branch that is out of date. That is not a
    question about the work, so the ticket waits in validated rather than in
    review — and the next pass, which reads that column as it always does,
    replays the branch onto what `main` holds and merges it. Nobody moved it.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_GH_REFUSE": "Head branch is out of date with the base branch"}):
        first = machine.run()

    assert machine.status(ticket) == "validated", machine.status(ticket)
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
    assert machine.status(ticket) == "done", machine.status(ticket)
    landed = machine.files_on(repository, "main")
    assert "OTHER.md" in landed and "FAKE.md" in landed, landed
    assert "replayed onto" in machine.board.said(ticket)[-1]


@case
@runner_settings(force_validated_code=True)
def a_forced_merge_in_conflict_waits_in_validated_and_its_conflict_is_resolved(
    machine: Bench,
) -> None:
    """Behind on the very file it writes: validated, then the usual resolution."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_GH_REFUSE": "Pull Request has merge conflicts"}):
        machine.run()
    assert machine.status(ticket) == "validated", machine.status(ticket)

    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "done", machine.status(ticket)
    landed = machine.content(repository, "main", "FAKE.md")
    assert "ce que l'autre ticket a écrit" in landed and "the session was here" in landed
    assert [one for one in machine.sessions() if "resolving that conflict" in one["prompt"]]


@case
@runner_settings(force_validated_code=True)
def force_validated_never_touches_a_failed_session_nor_a_ticket_already_in_review(
    machine: Bench,
) -> None:
    """The two guards: only a success is validated, only a ticket run from now on."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    waiting = machine.ticket("Déjà relu à moitié", "Rien.", project, status="review")
    machine.board.set(waiting, "Pull Request", "https://github.com/fake/repo/pull/99")
    broken = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    os.environ["FAKE_CLAUDE_FAIL"] = "la session a planté"

    machine.run()

    assert machine.status(broken) == "blocked", machine.status(broken)
    assert machine.status(waiting) == "review", machine.status(waiting)
    assert not machine.merges(), machine.merges()


@case
@runner_settings(force_validated_publication=True)
def a_publication_whose_validation_is_forced_goes_out_without_waiting(machine: Bench) -> None:
    """Force validated for Publication: prepared, then published, in one pass."""
    machine.typed()
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Annoncer la version 2", "Un post LinkedIn pour la v2.", project)
    machine.board.set(ticket, "Type", "Publication")

    results = machine.run()

    assert [result.get("kind") for result in results] == ["delivery"], results
    assert machine.status(ticket) == "done", machine.status(ticket)
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
def a_publication_whose_validation_is_forced_costs_its_two_sessions(machine: Bench) -> None:
    """Prepared, then published: two sessions paid, in the column and in the history."""
    machine.typed()
    project = machine.project("Lettre d'information", None)
    ticket = machine.ticket("Annoncer la version 2", "Un post LinkedIn pour la v2.", project)
    machine.board.set(ticket, "Type", "Publication")

    with _environ({"FAKE_CLAUDE_COST": ""}):
        results = machine.run()

    assert len(machine.sessions()) == 2, machine.sessions()
    assert machine.board.value(ticket, "Cost") == 0.04, machine.board.value(ticket, "Cost")
    assert results[0]["cost_usd"] == 0.04, results
    assert state.spent_today() == 0.04, state.spent_today()


@case
def a_ticket_with_no_model_runs_on_the_one_chosen_for_it_and_a_model_written_as_written(
    machine: Bench,
) -> None:
    project = machine.project("Notes", None)
    light = machine.ticket(
        "Retirer un paragraphe", "Le texte sous le titre ne sert à rien.", project
    )
    heavy = machine.ticket("Audit complet", "Audit de sécurité et de performance du site.", project)
    forced = machine.ticket("Retirer une ligne", "La dernière du pied de page.", project)
    machine.board.set(forced, "Model", "opus")

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
def a_ticket_on_an_openrouter_model_runs_on_openrouter_and_is_blocked_without_its_key(
    machine: Bench,
) -> None:
    project = machine.project("Notes", None)
    routed = machine.ticket("Écrire l'annonce", "Trois lignes.", project)
    machine.board.set(routed, "Model", "openai/gpt-5")

    # Without the key, the slug means nothing to the CLI: said as what it is.
    machine.run()
    assert machine.status(routed) == "blocked"
    assert "OpenRouter key is missing" in machine.board.said(routed)[-1], machine.board.said(routed)
    assert not machine.sessions(), "nothing ran on a model nobody can reach"

    with _environ({"OPENROUTER_API_KEY": "sk-or-functional-tests"}):
        machine.move(routed, "ready")
        machine.run()
    (entry,) = machine.sessions()
    assert entry["model"] == "openai/gpt-5"
    assert entry["base_url"].startswith("https://openrouter.ai"), entry
    assert machine.status(routed) != "blocked"
    assert machine.board.value(routed, "Model") == "openai/gpt-5", "the slug stays on the ticket"


@case
def a_ticket_the_runner_hesitates_over_is_blocked_and_nothing_runs(machine: Bench) -> None:
    """A doubt with a publication is a question, not a session — and a type
    somebody chose is never classified again, let alone overwritten."""
    machine.typed()
    project = machine.project("Lettre d'information", None)
    unsure = machine.ticket("La newsletter", "La newsletter d'octobre.", project)
    chosen = machine.ticket("L'édito", "Deux paragraphes.", project)
    machine.board.set(chosen, "Type", "Rédaction")
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
    assert machine.status(unsure) == "blocked"
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
def a_deleted_project_and_its_tickets_cost_no_session(machine: Bench) -> None:
    """In the trash, a project is out of every query — and a ticket still
    pointing at it is put back, not worked on with whatever the page held.

    The trash keeps a page in `ponos.db`, flagged, which is the thing to guard: the
    ready ticket below still names it, and without the check the runner would
    find the repository through the trashed page and spend a session on it.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    other = machine.project("Autre", machine.repository("autre"))
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    kept = machine.ticket("Un autre travail", "Ailleurs.", other)

    machine.board.trash(project)

    results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(kept, "done")], results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert "could not find its project" in machine.board.said(ticket)[-1], machine.board.said(
        ticket
    )
    assert all("Corriger l'entête" not in one["prompt"] for one in machine.sessions())
    assert not machine.worktrees(repository), "a deleted project got a worktree"
    assert repository.is_dir(), "the clone on the machine is never ours to remove"


@case
def a_session_that_fails_leaves_a_readable_ticket_and_no_worktree(machine: Bench) -> None:
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
    assert machine.status(ticket) == "blocked", machine.status(ticket)

    said = machine.board.said(ticket)
    assert said, "a ticket that failed was not told why"
    assert "rien à faire ici" in said[-1], said[-1]

    assert not machine.worktrees(repository), machine.worktrees(repository)
    worktrees = Path(os.environ["XDG_STATE_HOME"]) / "ponos" / "worktrees"
    assert not list(worktrees.glob("*")), "the worktree is still on disk"
    assert not machine.pull_requests(), "a failed session still opened a pull request"
    assert machine.branches(repository) == ["main"], machine.branches(repository)


@case
def an_external_action_that_commits_nothing_is_done_with_its_report(machine: Bench) -> None:
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
    assert machine.status(hesitant) == "done", machine.status(hesitant)
    assert not machine.pull_requests()

    # Typed as code by somebody, and done in Dokploy all the same.
    coded = machine.ticket("Ajouter la variable en prod", "SMTP_HOST manque.", project)
    machine.board.set(coded, "Type", "Code")
    report = "J'ai ajouté SMTP_HOST dans Dokploy et redéployé l'application."
    with _environ({"FAKE_CLAUDE_ELSEWHERE": report}):
        results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(coded, "done")], results
    assert machine.status(coded) == "done", machine.status(coded)
    assert report in machine.board.body(coded), machine.board.body(coded)
    assert "RESULT:" not in machine.board.body(coded), "the verdict is the status"
    assert not machine.pull_requests(), "nothing to review"
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_code_ticket_already_settled_on_main_is_sent_to_review_with_its_report(machine: Bench) -> None:
    """Nothing to commit, because a pull request the verdict names made the change."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger les clés i18n", "Deux clés manquent.", project)
    report = (
        "Je n'ai rien changé : le commit `327a1c6` a ajouté les deux clés dans "
        "`src/i18n/translationKeys.ts`.\nRESULT: ok — Aucun changement : les deux clés "
        "sont déjà corrigées sur main par #63."
    )
    with _environ({"FAKE_CLAUDE_ELSEWHERE": report}):
        results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(ticket, "done")], results
    assert machine.status(ticket) == "review", machine.status(ticket)
    assert "327a1c6" in machine.board.body(ticket), machine.board.body(ticket)
    assert not machine.pull_requests(), "nothing to merge"
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_code_ticket_that_changes_code_without_committing_it_is_still_blocked(machine: Bench) -> None:
    """The one case the commit is the deliverable, and it is not there."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    dirty = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    with _environ({"FAKE_CLAUDE_DIRTY": "1"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.status(dirty) == "blocked", machine.status(dirty)

    # Clean, but saying it changed the code, from a deployment ticket.
    claimed = machine.ticket("Corriger le déploiement", "Le build casse.", project)
    said = "J'ai corrigé le fichier docker/entrypoint.py puis redéployé dans Dokploy."
    with _environ({"FAKE_CLAUDE_ELSEWHERE": said}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.status(claimed) == "blocked", machine.status(claimed)
    assert len(machine.sessions()) == 1, "a session that concluded is not asked again"


@case
def a_session_that_stops_without_its_report_is_asked_for_it_once(machine: Bench) -> None:
    """Picked up in its own conversation, for the report and nothing else —
    blocked only when that fails too, and never asked twice for one ticket."""
    project = machine.project("Leadz", None)
    ticket = machine.ticket("Brancher le domaine", "leadz.ninja sur le serveur.", project)

    with _environ({"FAKE_CLAUDE_SILENT": "once", "FAKE_CLAUDE_COST": ""}):
        results = machine.run()

    assert results[0]["status"] == "done", results
    assert machine.status(ticket) == "done", machine.status(ticket)
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
    assert machine.status(silent) == "blocked", machine.status(silent)
    assert len(machine.sessions()) == 2, machine.sessions()

    # Back to ready: it already had its second chance.
    machine.move(silent, "ready")
    with _environ({"FAKE_CLAUDE_SILENT": "always"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert len(machine.sessions()) == 1, "not picked up a second time"


@case
def a_writing_ticket_blocked_on_a_question_is_not_said_to_have_written_nothing(
    machine: Bench,
) -> None:
    """A Rédaction session that stops on its question is a question for you.

    `session.no-answer` is kept for the one that wrote neither ANSWER.md nor a
    question: the two used to share it, and the board's « Blocage » column, and
    the counts by cause, could not tell a question from a silence.
    """
    machine.typed()
    project = machine.project("Lettre d'information", None)
    asking = machine.ticket("L'édito", "Deux paragraphes.", project)
    machine.board.set(asking, "Type", "Rédaction")
    asked = "Ton ou vous ?\nCATEGORY: question\nQUESTION: Tutoyer ou vouvoyer ?\nMODE: free"
    with _environ({"FAKE_CLAUDE_BLOCK": asked}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.board.value(asking, "Blocage") == "session.question"

    silent = machine.ticket("Le sommaire", "Trois titres.", project)
    machine.board.set(silent, "Type", "Rédaction")
    with _environ({"FAKE_CLAUDE_SILENT": "always"}):
        results = machine.run()
    assert results[0]["status"] == "blocked", results
    assert machine.board.value(silent, "Blocage") == "session.no-answer"


@case
def a_writing_ticket_its_session_says_is_code_is_made_code_and_run_again_once(
    machine: Bench,
) -> None:
    """`KIND: code` from a Rédaction session: Code in the column, one run as code.

    No question asked — the session said what somebody would have answered —
    and only once: a second claim on the same ticket ends as its session did.
    """
    machine.typed()
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Rattraper le concurrent", "Une PR qui ajoute l'export.", project)
    machine.board.set(ticket, "Type", "Rédaction")
    wrong = {"FAKE_CLAUDE_WRONG_KIND": "c'est un ticket de code"}

    with _environ(wrong):
        results = machine.run()
    assert [result["status"] for result in results] == ["requeued"], results
    assert machine.board.value(ticket, "Type") == "Code"
    assert machine.status(ticket) == "ready", machine.status(ticket)
    said = machine.board.said(ticket)[-1]
    assert "Code" in said and "?" not in said, said
    assert not machine.pull_requests(), "the first session changed nothing"

    with _environ(wrong):
        results = machine.run()
    assert [result["status"] for result in results] == ["done"], results
    # The sub-type is asked on the way, in a scratch directory: not a run.
    sessions = [one for one in machine.sessions() if "/scratch/subtype-" not in one["cwd"]]
    assert len(sessions) == 1, [one["cwd"] for one in sessions]
    assert "/worktrees/" in sessions[0]["cwd"], "run as code, in a worktree of its own"
    assert len(machine.pull_requests()) == 1, machine.pull_requests()

    # Typed back as a text and run again: the claim is not believed twice.
    machine.board.set(ticket, "Type", "Rédaction")
    machine.move(ticket, "ready")
    with _environ(wrong):
        results = machine.run()
    assert [result["status"] for result in results] == ["blocked"], results
    assert machine.board.value(ticket, "Type") == "Rédaction", "no second switch"
    assert machine.status(ticket) == "blocked", machine.status(ticket)


def _budget(machine: Bench, **limits: float) -> None:
    """The installation's `[budget]`, written into its configuration."""
    with open(machine.config, "a", encoding="utf-8") as handle:
        handle.write(
            "\n[budget]\n" + "".join(f"{key} = {value}\n" for key, value in limits.items())
        )


@case
def a_blocked_or_failed_session_has_its_cost_written_on_the_ticket(machine: Bench) -> None:
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
    assert machine.status(asking) == "blocked", machine.status(asking)
    assert machine.board.value(asking, "Cost") == 0.17, machine.board.value(asking, "Cost")


@case
def a_session_past_the_ticket_limit_stops_cleanly_and_blocks_the_ticket_with_the_reason() -> None:
    with bench() as machine:
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        _budget(machine, per_ticket_usd=2.5)
        ticket = machine.ticket("Une tâche sans fin", "Continue.", project)
        with _environ({"FAKE_CLAUDE_OVER_BUDGET": "1", "FAKE_CLAUDE_COST": "2.51"}):
            results = machine.run()

        assert machine.sessions()[0]["budget"] == "2.50", "the limit reaches the session itself"
        assert results[0]["status"] == "blocked", results
        assert machine.status(ticket) == "blocked", machine.status(ticket)
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
def past_the_daily_limit_nothing_new_is_started_and_the_ready_tickets_wait(machine: Bench) -> None:
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    _budget(machine, daily_usd=1.0)
    first = machine.ticket("Une tâche chère", "Fais-la.", project)
    with _environ({"FAKE_CLAUDE_BLOCK": "A ou B ?", "FAKE_CLAUDE_COST": "1.5"}):
        machine.run()
    assert machine.status(first) == "blocked", machine.status(first)

    second = machine.ticket("Une tâche qui attend", "Plus tard.", project)
    results = machine.run()
    assert machine.sessions() == [], "a session was started past the daily limit"
    assert machine.status(second) == "ready", machine.status(second)
    assert [result["status"] for result in results] == ["waiting"], results
    assert machine.board.value(second, "Waiting for credit") is True
    assert credits.held(what="budget") > time.time(), "the wait is written down for the runs after"


@case
@runner_settings(max_concurrent=1)
def a_claude_signed_out_puts_the_ticket_back_in_ready_and_waits_for_a_login(machine: Bench) -> None:
    """An expired sign-in is a quota nobody will refill by waiting: it needs you.

    Read as a session with no answer, it blocked one ticket after the other,
    each in ten seconds and for nothing. Here the ticket goes back to ready, the
    runner stops taking any, and your phone is told once to sign in again; the
    pass that finds `claude auth status` signed in again carries on by itself.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    first = machine.ticket("Une tâche", "Fais-la.", project)
    second = machine.ticket("Une autre tâche", "Fais-la aussi.", project)
    told: list[str] = []
    announce = base.Base._announce
    base.Base._announce = lambda self, title, body: told.append(f"{title} {body}")  # type: ignore[method-assign]
    try:
        with _environ({"FAKE_CLAUDE_SIGNED_OUT": "1"}):
            results = machine.run()
            assert len(machine.sessions()) == 1, (
                "another ticket was claimed past the expired sign-in"
            )
            assert results[0]["status"] == "waiting", results
            assert machine.status(first) == "ready", machine.status(first)
            assert machine.status(second) == "ready", machine.status(second)
            machine.run()
            assert machine.sessions() == [], "a session was started while signed out"
        assert len(told) == 1, told
        assert provider.LOGIN in told[0], told
        machine.run()
    finally:
        base.Base._announce = announce  # type: ignore[method-assign]
    assert len(machine.sessions()) == 2, "the pass signed in again did not carry on"
    assert machine.status(first) == "review", machine.status(first)
    assert machine.status(second) == "review", machine.status(second)


@case
def a_branch_is_replayed_on_a_base_that_moved_under_the_session() -> None:
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
            assert machine.status(ticket) == "review", machine.status(ticket)
            branch = results[0]["branch"]
            files = machine.files_on(repository, branch)
            assert "FAKE.md" in files, files
            assert ("OTHER.md" in files) is expected, (rebase, files)
            assert len(machine.pull_requests()) == 1, machine.pull_requests()
            said = machine.board.said(ticket)
            assert ("rejouée sur" in said[-1] or "replayed onto" in said[-1]) is expected, said[-1]


@case
def a_validated_merge_refused_for_being_behind_is_replayed_and_lands(machine: Bench) -> None:
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
    assert machine.status(ticket) == "review", machine.status(ticket)

    machine.land(repository, "OTHER.md")
    machine.move(ticket, "validated")

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "done", machine.status(ticket)
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
def a_validated_merge_that_conflicts_is_resolved_and_lands_with_both_changes(
    machine: Bench,
) -> None:
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
    machine.move(ticket, "validated")

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "done", machine.status(ticket)
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
def a_conflict_that_is_a_decision_blocks_the_ticket_with_the_question(machine: Bench) -> None:
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
    machine.move(ticket, "validated")

    with _environ({"FAKE_CLAUDE_RESOLVE": "blocked"}):
        results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    said = machine.board.said(ticket)[-1]
    assert "garder le texte du ticket ou celui de main" in said, said
    assert "FAKE.md" in said, said
    assert not machine.merges(), "a conflict nobody resolved was merged"
    assert machine.content(repository, branch, "FAKE.md") == pushed, "the branch was rewritten"
    assert machine.content(repository, "main", "FAKE.md") == "ce que l'autre ticket a écrit\n"
    assert not machine.worktrees(repository), machine.worktrees(repository)


def _validated_red(machine: Bench) -> tuple[Path, str, str]:
    """A pull request validated with a job red by its own fault, on a green base.

    The repository has a CI, so the runner reads the checks; `job 2` is red
    on the pull request and nothing is red on `main`. The board has its
    « Blocage » column. The repository, the ticket, and its branch.
    """
    repository = machine.repository("site")
    machine.with_ci(repository)
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    branch = str(machine.run()[0]["branch"])
    os.environ["FAKE_GH_CHECKS"] = _check_runs("SUCCESS", "FAILURE")
    machine.move(ticket, "validated")
    return repository, ticket, branch


def _repairs(machine: Bench) -> list[dict[str, Any]]:
    return [one for one in machine.sessions() if "You are repairing that" in one["prompt"]]


@case
def a_validated_pull_request_red_without_conflict_is_repaired_by_a_session_and_merged(
    machine: Bench,
) -> None:
    """Red after its rerun, green base, no conflict: a session repairs it, then the merge.

    What blocked #362 until a person pushed `npm run types` by hand: the merge
    was refused for a red job and nothing was sent after it, since `_mend` was
    only reached after a conflict.
    """
    repository, ticket, branch = _validated_red(machine)
    os.environ["FAKE_GH_GREEN_WITH"] = "FIXED.md"

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "done", machine.status(ticket)
    repairs = _repairs(machine)
    assert len(repairs) == 1, machine.sessions()
    assert "`job 2`" in repairs[0]["prompt"], repairs[0]["prompt"]
    assert "FIXED.md" in machine.files_on(repository, branch), "the repair was not pushed"
    assert "FIXED.md" in machine.files_on(repository, "main"), "the repair was not merged"
    said = machine.board.said(ticket)[-1]
    assert "for its red checks" in said and "in conflict" not in said, said
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_validated_pull_request_still_red_after_its_repair_is_blocked_and_never_repaired_twice(
    machine: Bench,
) -> None:
    """One repair, its commit pushed; still red, blocked — and validated again, no second one."""
    repository, ticket, branch = _validated_red(machine)

    results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "merge.checks-failed"
    assert len(_repairs(machine)) == 1, machine.sessions()
    assert "FIXED.md" in machine.files_on(repository, branch), "the repair was not pushed"
    assert not machine.merges(), "a red pull request was merged"
    said = machine.board.said(ticket)[-1]
    assert "still red after a repair session" in said, said

    # Validated again on the same commit: blocked at once, no session.
    machine.move(ticket, "validated")
    results = machine.run()

    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "merge.checks-failed"
    assert not _repairs(machine), machine.sessions()
    assert not machine.merges(), "a red pull request was merged"


def _in_conflict(machine: Bench) -> tuple[Path, str, str]:
    """A pull request validated after another ticket rewrote the file it writes.

    The board has its « Blocage » column, for the cases below to read the cause
    a resolution stopped on. The repository, the ticket, and its branch.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)
    branch = str(machine.run()[0]["branch"])
    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    machine.move(ticket, "validated")
    return repository, ticket, branch


@case
def a_branch_pushed_to_during_its_resolution_is_not_overwritten_and_asks_which_wins(
    machine: Bench,
) -> None:
    """Somebody pushed to the pull request's branch while its conflict was resolved.

    The lease the resolution is pushed on was taken on the commit the replay
    started from: the push is refused, their commit stays where it is, nothing
    is merged — and the ticket asks which of the two should win, with the
    resolution set aside on a branch of its own.
    """
    from ponos import git

    repository, ticket, branch = _in_conflict(machine)
    # `push_leased` hands back git's last line, which after a lease refused is
    # `error: failed to push some refs`, and `pushed_over` reads the line above
    # it, `! [rejected] … (stale info)`: the refusal is git's own, only that line
    # is the one handed back.
    leased = git.push_leased
    refusals: list[str] = []

    def push_leased(worktree: Path, name: str, was: str, accounts: Any = None) -> str:
        refused = leased(worktree, name, was, accounts)
        refusals.append(refused)
        return f" ! [rejected]        HEAD -> {name} (stale info)" if refused else ""

    git.push_leased = push_leased  # type: ignore[assignment]  # a doublure on the module
    try:
        with _environ({"FAKE_CLAUDE_PUSHES_OVER": "1"}):
            results = machine.run()
    finally:
        git.push_leased = leased

    assert refusals and refusals[0], refusals

    assert results and results[0]["status"] == "blocked", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "merge.pushed-over"
    said = machine.board.said(ticket)[-1]
    assert f"pushed to `{branch}` by someone else" in said, said
    assert not machine.merges(), "a branch somebody else pushed to was merged"
    tip = subprocess.run(
        ["git", "log", "-1", "--format=%s", branch],
        cwd=str(machine.root / "remotes" / "site.git"),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert tip.stdout.strip() == "Poussé par quelqu'un d'autre", tip.stdout
    aside = [name for name in machine.branches(repository) if name.startswith(f"{branch}-rebased-")]
    assert len(aside) == 1 and aside[0] in said, (machine.branches(repository), said)
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_resolution_whose_push_is_refused_fails_with_the_resolution_set_aside(
    machine: Bench,
) -> None:
    """The remote refuses the pull request's branch — a rule, a hook, a protection.

    Not somebody else's commits, so not a question about whose wins: the ticket
    fails on the refusal, with what git said and the resolution pushed to a
    branch the rule lets through.
    """
    repository, ticket, branch = _in_conflict(machine)
    hook = machine.root / "remotes" / "site.git" / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "while read old new ref; do\n"
        '  case "$ref" in *-rebased-*) ;; *) echo "branche protégée : $ref" >&2; exit 1 ;; esac\n'
        "done\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    results = machine.run()

    assert results and results[0]["status"] == "failed", results
    assert results[0]["code"] == "merge.push-refused", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "merge.push-refused"
    said = machine.board.said(ticket)[-1]
    assert "pushing them was refused" in said, said
    assert not machine.merges(), "a resolution that never reached the remote was merged"
    assert machine.content(repository, branch, "FAKE.md") == "the session was here\n"
    aside = [name for name in machine.branches(repository) if name.startswith(f"{branch}-rebased-")]
    assert len(aside) == 1 and aside[0] in said, (machine.branches(repository), said)
    assert not machine.worktrees(repository), machine.worktrees(repository)


@case
def a_base_that_moves_between_the_resolution_and_the_merge_is_caught_up_next_pass(
    machine: Bench,
) -> None:
    """Resolved and pushed, and `main` moved again before the merge was asked.

    GitHub refuses the merge of a branch that is behind: the ticket goes back
    to validated, says so, and the next pass — a replay with nothing left to
    resolve — lands it with all three changes.
    """
    repository, ticket, branch = _in_conflict(machine)

    with _environ({"FAKE_CLAUDE_MOVES_BASE": str(repository)}):
        results = machine.run()

    assert results and results[0]["status"] == "validated", results
    assert machine.status(ticket) == "validated", machine.status(ticket)
    assert not machine.board.value(ticket, "Blocage"), machine.board.value(ticket, "Blocage")
    said = machine.board.said(ticket)[-1]
    assert "the base moved again in the meantime" in said, said
    assert not machine.merges(), "a branch behind its base was merged"
    assert "<<<<<<<" not in machine.content(repository, branch, "FAKE.md")
    assert "OTHER.md" not in machine.files_on(repository, branch)

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "done", machine.status(ticket)
    landed = machine.files_on(repository, "main")
    assert "OTHER.md" in landed and "FAKE.md" in landed, landed
    assert "ce que l'autre ticket a écrit" in machine.content(repository, "main", "FAKE.md")


@case
def a_base_that_keeps_moving_under_the_resolutions_blocks_the_ticket(machine: Bench) -> None:
    """The same, once too often: past `MOST_REBASES`, the ticket asks.

    One replay is already counted against the ticket; the resolution makes the
    second, the base moves again under it, and chasing it a third time is the
    question the ticket asks instead.
    """
    repository, ticket, _branch = _in_conflict(machine)
    state.rebased(ticket)

    with _environ({"FAKE_CLAUDE_MOVES_BASE": str(repository)}):
        results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert machine.status(ticket) == "blocked", machine.status(ticket)
    assert machine.board.value(ticket, "Blocage") == "merge.base-moving"
    said = machine.board.said(ticket)[-1]
    assert "replayed onto `main` 2 times" in said, said
    assert state.rebases(ticket) == 0, "the count of a ticket that asks starts again"
    assert not machine.merges(), machine.merges()


@case
@runner_settings(resolve_conflicts_except="Site")
def a_project_left_out_of_resolution_blocks_on_its_conflict_as_before(machine: Bench) -> None:
    """`resolve_conflicts_except` names it: no session, the refusal as it came."""
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger l'entête", "Le titre est faux.", project)

    machine.run()
    machine.land(repository, "FAKE.md", "ce que l'autre ticket a écrit\n")
    machine.move(ticket, "validated")
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
def branches_differing_only_in_generated_files_and_the_changelog_merge_without_a_session(
    machine: Bench,
) -> None:
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
    assert machine.status(ticket) == "review", machine.status(ticket)

    _write(repository, _adding("b"), "Un autre ticket — b")
    machine.move(ticket, "validated")
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
def three_validated_pull_requests_on_one_repository_merge_one_after_the_other(
    machine: Bench,
) -> None:
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
    assert [machine.status(ticket) for ticket in tickets] == ["review"] * 3
    for ticket in tickets:
        machine.move(ticket, "validated")

    results = machine.run()

    assert [one["status"] for one in results] == ["done"] * 3, results
    assert [machine.status(ticket) for ticket in tickets] == ["done"] * 3
    assert len(machine.merges()) == 3, machine.merges()
    assert not machine.sessions(), machine.sessions()
    assert machine.content(repository, "main", "dist/bundle.js") == "zéro\na\nb\nc\n"
    changelog = machine.content(repository, "main", "CHANGELOG.md")
    assert all(f"- {part}" in changelog for part in "abc"), changelog
    for ticket in tickets:
        assert "moves faster" not in " ".join(machine.board.said(ticket)), ticket


@case
def a_conflict_in_code_is_resolved_by_a_session_that_is_not_told_about_generated_files(
    machine: Bench,
) -> None:
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
    machine.move(ticket, "validated")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    resolving = [one for one in machine.sessions() if "resolving that conflict" in one["prompt"]]
    assert len(resolving) == 1, machine.sessions()
    assert "- `FAKE.md`" in resolving[0]["prompt"]
    assert "- `dist/bundle.js`" not in resolving[0]["prompt"]
    assert "- `CHANGELOG.md`" not in resolving[0]["prompt"]
    assert machine.content(repository, "main", "dist/bundle.js") == "zéro\na\nb\n"


@case
def a_replay_over_a_new_route_regenerates_the_api_types_with_the_bundle(machine: Bench) -> None:
    """The types follow the routes of both sides, in the one regeneration commit.

    As `npm run types` writes `api-types.d.ts` from `web/answers.py`, the build
    here writes `api-types.d.ts` from it. A route lands on `main` under a pull
    request that adds another: the session keeps both routes, and the types the
    replay pushes are those of both — not the branch's, which the CI refuses.
    """
    repository = machine.repository("console")
    _write(
        repository,
        {
            ".ponos.toml": 'generated = ["dist/**", "api-types.d.ts"]\nbuild = "'
            "sed 's/^/type /' web/answers.py > api-types.d.ts"
            ' && mkdir -p dist && cat parts/*.txt > dist/bundle.js"\n',
            "web/answers.py": "route /api/health\n",
            "api-types.d.ts": "type route /api/health\n",
            "parts/0.txt": "zéro\n",
            "dist/bundle.js": "zéro\n",
        },
        "routes, types et bundle",
    )
    project = machine.project("Console", repository)
    ticket = machine.ticket("Ajouter a", "Ajoute la route a.", project)

    def route(name: str) -> dict[str, str]:
        return {
            "web/answers.py": f"route /api/health\nroute /api/{name}\n",
            "api-types.d.ts": f"type route /api/health\ntype route /api/{name}\n",
            f"parts/{name}.txt": f"{name}\n",
            "dist/bundle.js": f"zéro\n{name}\n",
        }

    with _environ({"FAKE_CLAUDE_ALSO": json.dumps({"la route a.": route("a")})}):
        machine.run()
    _write(repository, route("setup"), "Un autre ticket — /api/setup")
    machine.move(ticket, "validated")
    results = machine.run()

    assert results and results[0]["status"] == "done", results
    answers = machine.content(repository, "main", "web/answers.py")
    assert "/api/setup" in answers and "/api/a" in answers, answers
    types = machine.content(repository, "main", "api-types.d.ts")
    assert types.splitlines() == [f"type {line}" for line in answers.splitlines()], types
    tip = subprocess.run(
        ["git", "show", "--name-only", "--format=%s", "main"],
        cwd=str(machine.root / "remotes" / "console.git"),
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.split()
    assert tip[:4] == ["Regenerate", "the", "generated", "files"], tip
    assert "api-types.d.ts" in tip and "dist/bundle.js" in tip, tip


@case
def a_failing_build_stops_the_replay_and_nothing_is_pushed(machine: Bench) -> None:
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
    machine.move(ticket, "validated")
    results = machine.run()

    assert results and results[0]["status"] == "blocked", results
    assert not machine.merges()
    assert machine.content(repository, branch, "dist/bundle.js") == pushed, "the branch moved"


@case
def a_ticket_runs_in_the_repository_its_project_names(machine: Bench) -> None:
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
def a_new_version_restarts_the_daemon_which_takes_its_session_back_and_runs_the_next_on_it(
    machine: Bench,
) -> None:
    """What replaced `PASS_SPAN`: the daemon `exec`s itself onto a new version.

    Driven the way `ponos.service` drives it: the installed launcher, as a
    process of its own. A session is held in the middle of its ticket while a
    version lands whose two modules only work together (on 30 September 2026
    a pass that imported half of each died on `ImportError`); the `ponos run`s
    started meanwhile only wake the daemon. Once installed, the daemon is asked
    to restart (what the console's button does): it `exec`s onto the new code,
    takes the held session back, finishes its ticket — and the next ticket is
    run by the new version.
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

    def started(*arguments: str, out: Path | None = None) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [str(launcher), *arguments],
            stdout=out.open("w") if out else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    project = machine.project("Lettre d'information")
    ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes.", project, kind="writing")
    said = machine.root / "daemon.out"
    with _environ(environment):
        daemon = started("daemon", out=said)
        try:
            assert _waited(lambda: Path(f"{hold}.started").exists(), 60), said.read_text()

            # The incident's shape: a module that needs a name only the new
            # version of another one has.
            store_py = work / "src/ponos/store.py"
            store_py.write_text(store_py.read_text() + "\nHANDOVER = 'v2'\n")
            runner_py = work / "src/ponos/runner.py"
            runner_py.write_text(
                runner_py.read_text().replace(
                    "from .ticket import Job, Ticket\n",
                    "from .ticket import Job, Ticket\nfrom .store import HANDOVER  # noqa: F401\n",
                    1,
                )
            )
            init_py = work / "src/ponos/__init__.py"
            init_py.write_text(
                init_py.read_text().replace('__version__ = "', '__version__ = "9.', 1)
            )
            second = land("two")

            # Started while the update copies, resets and checks the new version.
            during: list[str] = []
            installing = threading.Thread(
                target=lambda: during.append(update.install(update.check(app, "main"), 600, app))
            )
            installing.start()
            meanwhile: list[subprocess.Popen[str]] = []
            while installing.is_alive():
                if sum(one.poll() is None for one in meanwhile) < 3:
                    meanwhile.append(started("run"))
                time.sleep(0.05)
            installing.join()
            assert during == [""], during
            assert app.resolve().name == f"app-{second[:12]}"
            for one in meanwhile:
                out = one.communicate(timeout=120)[0]
                assert one.returncode == 0 and "Error" not in out, out
                assert "looking at the board now" in out, "a run beside the daemon only wakes it"

            # The version the session started on is still whole on disk.
            previous = app.with_name(f"app-{first[:12]}")
            assert "HANDOVER" not in (previous / "src/ponos/store.py").read_text()

            # What the console's button does once the version is in place.
            daemon.send_signal(signal.SIGHUP)
            assert _waited(lambda: "ponos 9." in said.read_text(), 60), said.read_text()
            assert _waited(lambda: "taken back" in said.read_text(), 30), said.read_text()
            assert daemon.poll() is None, "the daemon restarted in place, same pid"
            hold.touch()
            assert _waited(lambda: machine.status(ticket) == "done", 60), (
                machine.status(ticket),
                said.read_text(),
            )
            assert len(machine.sessions()) == 1, "the held session was carried on, not redone"

            # The next ticket: the new version runs it.
            after = machine.ticket(
                "Relire l'édito", "Une passe de relecture.", project, kind="writing"
            )
            nudged = started("run")
            assert nudged.communicate(timeout=120)[0]
            assert _waited(lambda: machine.status(after) == "done", 60), said.read_text()
            text = said.read_text()
            assert "Error" not in text and "Traceback" not in text, text
        finally:
            daemon.send_signal(signal.SIGTERM)
            daemon.wait(timeout=120)


def _waited(condition: Callable[[], object], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return bool(condition())


@case
@runner_settings(max_concurrent=2, interval_seconds=3600)
def a_ticket_made_ready_beside_a_long_session_starts_in_the_free_place_within_seconds(
    machine: Bench,
) -> None:
    """6 November, 14:16: a place free, a ticket ready, and half an hour of nothing.

    Two places, one long session holding the first. A ticket made ready then
    starts in the second within seconds — not when the long one ends, nor at
    the next look of the safety net (an hour here).
    """
    from ponos import scheduler

    hold = machine.root / "hold"
    first_project = machine.project("Lettre d'information")
    second_project = machine.project("Blog")
    long = machine.ticket("Rédiger l'édito", "Deux paragraphes.", first_project, kind="writing")
    runner = Runner(C.load(machine.config), quiet=True)
    signals = scheduler.Signals()
    ended: list[str] = []
    with _environ({"FAKE_CLAUDE_HOLD": str(hold)}):
        serving = threading.Thread(
            target=lambda: ended.append(runner.serve(signals)), name="test-daemon", daemon=True
        )
        serving.start()
        try:
            assert _waited(lambda: len(machine.sessions()) == 1, 30), machine.sessions()
            assert machine.status(long) == "progress"
            began = time.monotonic()
            later = machine.ticket(
                "Annoncer l'édito", "Un billet court.", second_project, kind="writing"
            )
            # What the console, the MCP and `ponos run` do on a ticket made ready
            # (`daemon.nudge`, a SIGUSR1 that `daemon.listen` turns into this).
            signals.nudge()
            assert _waited(lambda: len(machine.sessions()) == 2, 15), "the free place stayed free"
            assert time.monotonic() - began < 10, time.monotonic() - began
            assert machine.status(later) == "progress"
            assert machine.status(long) == "progress", "the long session is still going"
            hold.touch()
            assert _waited(lambda: machine.status(long) == machine.status(later) == "done", 60), (
                machine.status(long),
                machine.status(later),
            )
        finally:
            signals.stop.set()
            serving.join(120)
    assert ended == ["stop"], ended


@case
def a_daemon_killed_under_a_session_is_started_again_and_the_session_is_carried_to_its_pr(
    machine: Bench,
) -> None:
    """Restarting the daemon never kills a session — and nothing of its ticket is lost.

    The daemon is killed outright (SIGKILL: no grace, no cleanup) in the middle
    of a code ticket's session. The session is not its child: it goes on. A new
    daemon finds it written down, follows it to its end, and the ticket comes
    back as it would have — a branch, a pull request, « review ».
    """
    hold = machine.root / "hold"
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket(
        "Corriger l'entête", "Le titre est faux, corrige-le.", project, kind="code", subtype="Bug"
    )
    environment = {
        "PONOS_CONFIG": str(machine.config),
        "FAKE_CLAUDE_HOLD": str(hold),
        "PYTHONPATH": str(ROOT / "src"),
    }
    outputs = [machine.root / "first.out", machine.root / "second.out"]

    def daemon(out: Path) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-m", "ponos", "daemon"],
            stdout=out.open("w"),
            stderr=subprocess.STDOUT,
            text=True,
        )

    with _environ(environment):
        first = daemon(outputs[0])
        try:
            assert _waited(lambda: Path(f"{hold}.started").exists(), 60), outputs[0].read_text()
            (row,) = state.sessions()
            tether = int(row["handle"]["pid"])
        finally:
            first.send_signal(signal.SIGKILL)
            first.wait(timeout=30)
        assert machine.status(ticket) == "progress", outputs[0].read_text()
        os.kill(tether, 0)  # the session outlived its daemon
        second = daemon(outputs[1])
        try:
            assert _waited(lambda: "taken back" in outputs[1].read_text(), 60), outputs[
                1
            ].read_text()
            hold.touch()
            assert _waited(lambda: machine.status(ticket) == "review", 60), (
                machine.status(ticket),
                outputs[1].read_text(),
            )
        finally:
            second.send_signal(signal.SIGTERM)
            second.wait(timeout=120)
    assert len(machine.sessions()) == 1, "the session was carried on, not started again"
    opened = machine.pull_requests()
    assert len(opened) == 1 and machine.board.value(ticket, "Pull Request") == opened[0]["url"]
    assert state.sessions() == [], "nothing left written down once it is done"
    runs = journal.runs(ticket)
    assert len(runs) == 1 and runs[0]["status"] == "done", runs
    assert "Traceback" not in outputs[1].read_text(), outputs[1].read_text()


def _worktree_of(machine: Bench) -> Path:
    """The one worktree a failed ticket left in the state directory."""
    (path,) = (Path(os.environ["XDG_STATE_HOME"]) / "ponos" / "worktrees").glob("*")
    return path


@case
@runner_settings(keep_worktree_on_failure=True)
def a_worktree_left_in_the_middle_of_a_rebase_is_saved_and_the_ticket_starts_again(
    machine: Bench,
) -> None:
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

    machine.move(ticket, "ready")
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
@runner_settings(keep_worktree_on_failure=True)
def a_ticket_renamed_between_two_attempts_carries_on_on_its_own_branch(machine: Bench) -> None:
    """Renamed after a failed attempt: the next one used to want a branch of the new title.

    The worktree, named after the ID, still held the first attempt's commit, and
    the ticket failed on it for good ("still holds work"). The branch is found
    by the ticket's ID, whatever the title now says: one branch, one pull request.
    """
    repository = machine.repository("site")
    project = machine.project("Site", repository)
    ticket = machine.ticket("Corriger le menu", "Fais-le.", project)
    with _environ({"FAKE_CLAUDE_FAIL": "la session a planté"}):
        machine.run()
    worktree = _worktree_of(machine)
    first = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
    ).stdout.strip()
    (worktree / "menu.txt").write_text("le menu corrigé\n", encoding="utf-8")
    _git(["add", "menu.txt"], worktree)
    _git(["commit", "-m", "le menu"], worktree)

    machine.board.set(ticket, "Name", "Corriger le menu du site, sur mobile aussi")
    machine.move(ticket, "ready")
    results = machine.run()

    assert results[0]["status"] == "done", (results, machine.board.said(ticket))
    opened = machine.pull_requests()
    assert [one["branch"] for one in opened] == [first], opened
    assert "menu.txt" in machine.files_on(repository, first), "the first attempt's commit was lost"
    assert [name for name in machine.branches(repository) if short_id(ticket) in name] == [first]


@case
def a_session_killed_is_resumed_once_and_blocked_as_killed_if_it_dies_again(machine: Bench) -> None:
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
    assert machine.status(again) == "blocked", machine.status(again)
    said = "\n".join(machine.board.said(again))
    assert "SIGKILL" in said, said
    assert not machine.worktrees(repository), "no worktree left behind"


def _with_an_on_prompt(machine: Bench, ticket: str, prompt: str) -> None:
    """A ticket given the prompt of its « On » column."""
    machine.board.set(ticket, "On", prompt)


@case
def a_status_that_moves_runs_the_on_prompt_once_and_a_restart_does_not_run_it_again(
    machine: Bench,
) -> None:
    """The prompt of a ticket, woken by a change and by nothing else.

    A fresh `Runner` for every pass is the restart: what keeps a change from
    running twice is not in the process. And the first reading of a ticket is a
    starting point — turning the feature on must not replay a board's past.
    """
    from ponos import transitions

    ticket = machine.ticket("Déployer le site", "Rien à faire ici.", status="paused")
    _with_an_on_prompt(machine, ticket, "Si on passe en Blocked, note-le dans le brief.")

    assert machine.run() == [] and not machine.sessions(), "a first sight is not a change"

    machine.move(ticket, "blocked")
    results = machine.run()
    assert [entry["status"] for entry in results] == ["on-ok"], results
    assert results[0]["transition"] == "paused → blocked", results
    sessions = machine.sessions()
    assert len(sessions) == 1, sessions
    prompt = sessions[0]["prompt"]
    assert "Old status: paused" in prompt and "New status: blocked" in prompt, prompt
    assert "Si on passe en Blocked, note-le dans le brief." in prompt
    assert "Déployer le site" in prompt, "the ticket reaches the prompt"
    assert sessions[0]["budget"] == "1.00", "an execution has a ceiling"

    # The log is emptied before each pass: a session here would be a second one.
    for _ in range(2):
        assert machine.run() == [] and not machine.sessions(), "one execution per change"

    machine.move(ticket, "paused")
    assert len(machine.run()) == 1 and len(machine.sessions()) == 1, "the next change runs it again"
    history = transitions.history(ticket)
    assert [(row["old"], row["new"], row["state"]) for row in history] == [
        ("blocked", "paused", "ok"),
        ("paused", "blocked", "ok"),
    ], history
    assert history[0]["cost_usd"], "what an execution cost is kept"
    assert machine.status(ticket) == "paused", "the prompt's own session moved nothing"


@case
def an_on_prompt_that_fails_says_so_on_the_ticket_and_leaves_its_status_alone(
    machine: Bench,
) -> None:
    from ponos import transitions

    ticket = machine.ticket("Fragile", "Rien.", status="paused")
    _with_an_on_prompt(machine, ticket, "Fais quelque chose.")
    machine.run()

    machine.move(ticket, "blocked")
    with _environ({"FAKE_CLAUDE_FAIL": "le réseau est tombé"}):
        results = machine.run()

    assert [entry["status"] for entry in results] == ["on-failed"], results
    assert machine.status(ticket) == "blocked", "an error never moves a status"
    said = machine.board.said(ticket)
    assert said and "« On »" in said[-1] and "paused → blocked" in said[-1], said
    assert transitions.history(ticket)[0]["state"] == "failed"
    assert machine.run() == [] and not machine.sessions(), "a failed change is not tried again"


@case
def an_on_prompt_is_not_run_when_the_feature_is_off_nor_for_an_empty_prompt() -> None:
    with bench(on=False) as machine:
        ticket = machine.ticket("Muet", "Rien.", status="paused")
        _with_an_on_prompt(machine, ticket, "Fais quelque chose.")
        machine.run()
        machine.move(ticket, "blocked")
        machine.run()
        assert not machine.sessions(), "runner.on = false runs nothing"

    with bench() as machine:
        ticket = machine.ticket("Sans prompt", "Rien.", status="paused")
        _with_an_on_prompt(machine, ticket, "")
        machine.run()
        machine.move(ticket, "blocked")
        machine.run()
        assert not machine.sessions(), "an empty prompt does nothing"


def main() -> int:
    return support.run(sys.argv[1:])


def _reviewer(login: str = "salva", kind: str = "User") -> dict[str, str]:
    return {"login": login, "type": kind}


def _line(number: int, body: str, review: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "id": number,
        "body": body,
        "path": "src/a.py",
        "line": 3,
        "diff_hunk": "@@ -1,2 +1,3 @@\n x = 1\n+y = 2",
        "pull_request_review_id": review,
        "user": _reviewer(),
        **extra,
    }


def _in_review(machine: Bench) -> tuple[Path, str, str]:
    """A code ticket delivered as a pull request, and read once by the runner."""
    repository = machine.repository("site")
    ticket = machine.ticket("Corriger l'entête", "Une phrase.", machine.project("Site", repository))
    machine.review()
    machine.run()
    assert machine.status(ticket) == "review", machine.status(ticket)
    assert len(machine.pull_requests()) == 1
    branch = machine.pull_requests()[0]["branch"]
    # The second reading is the first of its reviews: it only sets the marks.
    machine.run()
    assert machine.status(ticket) == "review", machine.status(ticket)
    return repository, ticket, branch


@case
def a_review_requesting_changes_reruns_the_ticket_and_answers_in_each_thread(
    machine: Bench,
) -> None:
    """Two line comments of a « Changes requested » review: one session, one commit, two replies."""
    repository, ticket, branch = _in_review(machine)
    machine.review(
        reviews=[
            {
                "id": 11,
                "state": "CHANGES_REQUESTED",
                "body": "",
                "user": _reviewer(),
            }
        ],
        comments=[_line(21, "Renomme ceci.", 11), _line(22, "Et ceci aussi.", 11, line=9)],
    )

    results = machine.run()

    assert results and results[0]["status"] == "done", results
    assert machine.status(ticket) == "review", machine.status(ticket)
    handed = [
        call for call in machine.sessions() if "Review comments left on GitHub" in call["prompt"]
    ]
    assert len(handed) == 1, machine.sessions()
    prompt = handed[0]["prompt"]
    assert "[21] @salva — src/a.py:3" in prompt and "[22] @salva — src/a.py:9" in prompt, prompt
    assert "+y = 2" in prompt and "Renomme ceci." in prompt, prompt
    assert "REVIEWED.md" in machine.files_on(repository, branch), "the review was not pushed"
    replies = machine.review()
    assert sorted(reply["to"] for reply in replies) == ["21", "22"], replies
    assert all("corrigé dans REVIEWED.md" in reply["body"] for reply in replies), replies
    assert all(reply["body"].startswith("<!-- ponos -->") for reply in replies), replies

    # The replies are the runner's own: read back, they wake nothing.
    machine.review(
        reviews=[{"id": 11, "state": "CHANGES_REQUESTED", "body": "", "user": _reviewer()}],
        comments=[
            _line(21, "Renomme ceci.", 11),
            _line(22, "Et ceci aussi.", 11, line=9),
            _line(23, "<!-- ponos -->\n@ponos corrigé", 0, in_reply_to_id=21),
        ],
    )
    machine.run()
    assert not machine.sessions(), machine.sessions()
    assert machine.status(ticket) == "review", machine.status(ticket)


@case
def a_comment_opening_on_the_mention_reruns_the_ticket_and_the_others_do_not(
    machine: Bench,
) -> None:
    """`@ponos` on a line wakes the ticket; a plain comment, a bot's, and a late mention do not."""
    _, ticket, _ = _in_review(machine)
    machine.review(
        comments=[
            _line(31, "Joli, merci."),
            _line(32, "@ponos-ci regarde", user=_reviewer("ci", "User")),
            _line(33, "@ponos corrige", user=_reviewer("copilot[bot]", "Bot")),
            _line(34, "Je pense à @ponos pour ça."),
        ]
    )

    machine.run()

    assert not machine.sessions(), machine.sessions()
    assert machine.status(ticket) == "review", machine.status(ticket)

    machine.review(comments=[_line(35, "@ponos Utilise une constante ici.")])
    machine.run()

    assert len(machine.sessions()) == 1, machine.sessions()
    assert "Utilise une constante ici." in machine.sessions()[-1]["prompt"]
    assert [reply["to"] for reply in machine.review()] == ["35"]
    assert machine.status(ticket) == "review", machine.status(ticket)


@case
def a_review_that_needs_no_change_is_answered_in_its_threads_without_a_commit(
    machine: Bench,
) -> None:
    """The session says why nothing changed: the threads hear it, the ticket stays in review."""
    _, ticket, _ = _in_review(machine)
    machine.review(comments=[_line(41, "@ponos pourquoi pas un dict ?")])
    os.environ["FAKE_CLAUDE_REVIEW_NOTHING"] = "1"

    machine.run()

    replies = machine.review()
    assert [reply["to"] for reply in replies] == ["41"], replies
    assert "rien à changer" in replies[0]["body"], replies
    assert machine.status(ticket) == "review", machine.status(ticket)


@case
@runner_settings(pr_review_comments=False)
def reviews_are_left_alone_when_the_setting_is_off(machine: Bench) -> None:
    _, ticket, _ = _in_review(machine)
    machine.review(comments=[_line(51, "@ponos corrige")])

    machine.run()

    assert not machine.sessions(), machine.sessions()
    assert machine.status(ticket) == "review", machine.status(ticket)


# -- Ponos's browser -------------------------------------------------------------


SITE_USER = "ada@hermez.test"
SITE_PASSWORD = "correct-horse-battery-staple-42"
SITE_CODE = "123456"

_FORM = (
    "<html><head><title>{title}</title></head><body><h1>{title}</h1>{error}"
    '<form method="post" action="{action}">{fields}<button type="submit">Entrer</button>'
    "</form></body></html>"
)
_SIGN_IN = (
    '<label>E-mail <input type="email" name="email" autocomplete="username"></label>'
    '<label>Mot de passe <input type="password" name="password"></label>'
)


class _SiteHandler(BaseHTTPRequestHandler):
    """A site to sign in to: a form, an optional second factor, and a page behind them."""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _page(self, body: str, status: int = 200, cookie: str = "") -> None:
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if cookie:
            self.send_header("Set-Cookie", f"sid={cookie}; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(encoded)

    def _go(self, where: str, cookie: str = "") -> None:
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        if cookie:
            self.send_header("Set-Cookie", f"sid={cookie}; Path=/; HttpOnly")
        self.end_headers()

    def _signed(self) -> bool:
        said = self.headers.get("Cookie", "")
        return any(part.strip() in self.server.sessions for part in said.split(";"))  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/login", "/otp-login"):
            self._page(_FORM.format(title="Connexion", error="", action=path, fields=_SIGN_IN))
        elif path == "/captcha-login":
            self._page(
                _FORM.format(
                    title="Connexion",
                    error='<div class="g-recaptcha" data-sitekey="x"></div>',
                    action="/login",
                    fields=_SIGN_IN,
                )
            )
        elif path == "/code":
            fields = '<label>Code de vérification <input name="code" autocomplete="one-time-code"></label>'
            self._page(
                _FORM.format(
                    title="Double authentification", error="", action="/code", fields=fields
                )
            )
        elif path == "/elsewhere":
            port = self.headers.get("Host", "").rsplit(":", 1)[-1]
            self._go(f"http://localhost:{port}/login")
        elif path.startswith("/private"):
            if not self._signed():
                self._go("/login")
                return
            self._page(
                "<html><head><title>Espace privé</title></head><body>"
                f"<h1>Espace privé</h1><p>Projets : alpha, beta</p><p>Page {path}</p>"
                f"<p>Connecté en tant que {SITE_USER}</p></body></html>"
            )
        else:
            self._page("<html><body>Accueil</body></html>")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        form = {
            key: values[0] for key, values in parse_qs(self.rfile.read(length).decode()).items()
        }
        if path in ("/login", "/otp-login"):
            if form.get("email") == SITE_USER and form.get("password") == SITE_PASSWORD:
                if path == "/otp-login":
                    self._go("/code")
                    return
                cookie = uuid.uuid4().hex
                self.server.sessions.add(f"sid={cookie}")  # type: ignore[attr-defined]
                self._go("/private", cookie)
                return
            error = '<p role="alert">Identifiants incorrects</p>'
            self._page(_FORM.format(title="Connexion", error=error, action=path, fields=_SIGN_IN))
        elif path == "/code" and form.get("code") == SITE_CODE:
            cookie = uuid.uuid4().hex
            self.server.sessions.add(f"sid={cookie}")  # type: ignore[attr-defined]
            self._go("/private", cookie)
        else:
            self._go("/code")


@contextmanager
def _site() -> Iterator[str]:
    """The sign-in site, on a loopback port: its address, as an entry of the vault names it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SiteHandler)
    server.sessions = set()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _browser_installed() -> None:
    from ponos import browser

    if why := browser.missing():
        raise support.Skip(f"Ponos's browser cannot start here: {why}")


def _keyring_free(machine: Bench) -> None:
    """A `secret-tool` that answers nothing: the vault's key goes to the bench's own file."""
    _script(machine.root / "bin" / "secret-tool", "raise SystemExit(1)\n")


def _login_entry(name: str, url: str, project: str = "Brevo") -> None:
    from ponos import vault_store

    vault_store.create(
        name,
        vault_store.LOGIN,
        {"user": SITE_USER, "password": SITE_PASSWORD},
        [project],
        url=url,
    )


def _everything_written(root: Path) -> Iterator[tuple[Path, str]]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix not in (".png", ".db", ".lock"):
            yield path, path.read_text(encoding="utf-8", errors="replace")


@case
def an_external_ticket_signs_in_with_the_vault_and_never_sees_the_password(machine: Bench) -> None:
    """`browser_login`, on a local site: the protected page is reached, the password said nowhere.

    The whole road of an external ticket in Ponos's browser: the runner gives
    the session `ponos-browser` instead of Claude in Chrome, the session signs
    in by the entry's name and reads the page behind the form. A value copied
    out of the environment is refused by `browser_type`, and a sign-in asked on
    another host than the entry's is refused too. Nothing written — the
    transcript, the log, the board, the profile — holds the password.
    """
    _browser_installed()
    _keyring_free(machine)
    machine.typed()
    with _site() as site:
        _login_entry("SITE", site + "/login")
        project = machine.project("Brevo")
        ticket = machine.ticket("Lire la liste des projets", "Ouvre le tableau de bord.", project)
        machine.board.set(ticket, "Type", "Action externe")
        steps = [
            ["browser_login", {"entry": "SITE"}],
            ["browser_read", {"what": "text"}],
            ["browser_type", {"label": "Mot de passe", "value": "$SITE_PASSWORD"}],
            [
                "browser_login",
                {"entry": "SITE", "url": site.replace("127.0.0.1", "localhost") + "/login"},
            ],
            ["browser_login", {"entry": "AUTRE"}],
            ["browser_screenshot", {}],
        ]
        with _environ({"FAKE_CLAUDE_BROWSE": json.dumps(steps)}):
            results = machine.run()

    assert [(result["id"], result["status"]) for result in results] == [(ticket, "done")], (
        results,
        machine.sessions(),
    )
    (call,) = machine.sessions()
    assert "browser_login" in call["prompt"] and "`SITE`" in call["prompt"], call["prompt"]
    body = machine.board.body(ticket)
    assert "browser_login: connected" in body, body
    assert "Projets : alpha, beta" in body, "the page behind the form was read"
    assert "browser_type: refused: that is a value of the vault" in body, body
    assert "browser_login: refused: localhost is not the site of SITE" in body, body
    assert "browser_login: refused: 'AUTRE' is not a login granted" in body, body
    assert "browser_screenshot: [image]" in body, body
    assert SITE_USER not in body, "the user is a value of the vault too"

    from ponos import browser, vault_store

    assert browser.sites(browser.load("Brevo")) == ["127.0.0.1"], "the sign-in stays in the profile"
    (entry,) = vault_store.listing()
    actions = [moment["action"] for moment in vault_store.history(entry["id"])]
    assert actions[:2] == ["login-refused", "login"], actions
    assert all(
        moment["ticket"] == ticket.replace("-", "") and moment["project"] == "Brevo"
        for moment in vault_store.history(entry["id"])[:2]
    )
    transcripts = list(Path(os.environ["XDG_STATE_HOME"]).rglob("*.jsonl"))
    assert any("mcp__ponos-browser__browser_login" in path.read_text() for path in transcripts)
    for path, text in _everything_written(machine.root):
        assert SITE_PASSWORD not in text, f"the password is written in {path}"


def _browse_directly(
    environment: dict[str, str], steps: list[tuple[str, dict[str, Any]]]
) -> list[str]:
    """`ponos-browser` driven over its standard input, as a session drives it: the texts it answered."""
    server = subprocess.Popen(
        [sys.executable, "-m", "ponos.browser_server"],
        env={**os.environ, **environment},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert server.stdin is not None and server.stdout is not None
    said: list[str] = []
    try:
        for number, (tool, arguments) in enumerate([("initialize", {}), *steps], start=1):
            method = "initialize" if tool == "initialize" else "tools/call"
            params = arguments if tool == "initialize" else {"name": tool, "arguments": arguments}
            server.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
                + "\n"
            )
            server.stdin.flush()
            reply = json.loads(server.stdout.readline())
            if method == "tools/call":
                said.append(str(reply["result"]["content"][0].get("text", "")))
    finally:
        server.stdin.close()
        server.wait(timeout=60)
    return said


def _session_environment(site: str, session: str, downloads: Path) -> dict[str, str]:
    from ponos import browser

    return {
        **browser.server_environment(
            project="Brevo",
            ticket="t1",
            session=session,
            headless=True,
            logins={
                "SITE": site + "/login",
                "CODE": site + "/otp-login",
                "ROBOT": site + "/captcha-login",
                "AILLEURS": site + "/elsewhere",
            },
            downloads=downloads,
        ),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }


@case
def two_sessions_browse_side_by_side_and_keep_one_profile(machine: Bench) -> None:
    """Two browsers of one project at once: each its own context, both signed in, one profile."""
    _browser_installed()
    _keyring_free(machine)
    with _site() as site:
        _login_entry("SITE", site + "/login")
        found: dict[str, list[str]] = {}

        def browse(name: str) -> None:
            found[name] = _browse_directly(
                _session_environment(site, name, machine.root / name),
                [
                    ("browser_login", {"entry": "SITE"}),
                    ("browser_navigate", {"url": f"{site}/private/{name}"}),
                    ("browser_read", {"what": "text"}),
                ],
            )

        threads = [threading.Thread(target=browse, args=(name,)) for name in ("one", "two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=180)

        for name in ("one", "two"):
            assert found[name][0].startswith("connected"), found[name]
            assert f"Page /private/{name}" in found[name][2], found[name]
            assert SITE_PASSWORD not in "".join(found[name])
        from ponos import browser

        state = browser.load("Brevo")
        # One cookie: the same name on the same site is one cookie, the last kept wins.
        assert state is not None and len(state["cookies"]) == 1, state

        # The next session starts signed in: the profile is the project's.
        again = _browse_directly(
            _session_environment(site, "three", machine.root / "three"),
            [("browser_navigate", {"url": f"{site}/private/again"})],
        )
        assert "Espace privé" in again[0], again


@case
def a_second_factor_stops_the_session_and_a_person_finishes_it_from_the_console(
    machine: Bench,
) -> None:
    """A one-time code is never answered by the browser: the person types it, the profile keeps it."""
    _browser_installed()
    _keyring_free(machine)
    from ponos import browser, vault_store

    with _site() as site:
        _login_entry("CODE", site + "/otp-login")
        _login_entry("ROBOT", site + "/captcha-login")
        _login_entry("AILLEURS", site + "/elsewhere")
        downloads = machine.root / "work"
        said = _browse_directly(
            _session_environment(site, "otp", downloads),
            [
                ("browser_login", {"entry": "CODE"}),
                ("browser_login", {"entry": "ROBOT"}),
                ("browser_login", {"entry": "AILLEURS"}),
            ],
        )
        assert said[2].startswith("refused: the sign-in page is on localhost"), said
        assert said[0].startswith("second factor requested: the site asks for a second factor"), (
            said
        )
        assert said[1].startswith("second factor requested: the site asks for a CAPTCHA"), said
        assert (downloads / "ponos-browser-sign-in.png").is_file(), "the session has its screenshot"
        entries = {entry["name"]: entry["id"] for entry in vault_store.listing()}
        assert vault_store.history(entries["CODE"])[0]["action"] == "login-second-factor"
        assert not browser.sites(browser.load("Brevo")), "nobody is signed in yet"

        # The person, from the console: a browser on the project's profile, the code typed.
        config = C.load(machine.config)
        identifier = browser.open_for_person(config, "Brevo", site + "/code")
        deadline = time.time() + 60
        while not any(item["id"] == identifier for item in browser.live()):
            assert time.time() < deadline, "the person's browser never showed its screen"
            time.sleep(0.2)
        assert browser.screen(identifier) is not None
        browser.send(identifier, {"action": "press", "key": "Tab"})
        browser.send(identifier, {"action": "type", "text": SITE_CODE})
        browser.send(identifier, {"action": "press", "key": "Enter"})
        while not browser.sites(browser.load("Brevo")):
            assert time.time() < deadline, "the code typed by the person was not kept"
            time.sleep(0.2)
        browser.send(identifier, {"action": "close"})
        while any(item["id"] == identifier for item in browser.live()):
            assert time.time() < deadline, "the person's browser did not close"
            time.sleep(0.2)

        again = _browse_directly(
            _session_environment(site, "resumed", downloads),
            [("browser_navigate", {"url": f"{site}/private"})],
        )
        assert "Espace privé" in again[0], again


if __name__ == "__main__":
    raise SystemExit(main())
