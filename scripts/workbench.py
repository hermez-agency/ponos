"""What the two consoles made of fixtures have in common: a real `ponos serve`, on nothing real.

`frontend/e2e/console.py` is the console the browser tests open, and
`scripts/demo.py` the one you open to work on the interface. Their data differ —
one ticket per gesture to check against a board drawn to be looked at — and
must stay apart, or a prettier demo would move a test. What does not differ is
everything around the data, and it is here once: the board of files under a
configuration of its own, a `XDG_STATE_HOME` and a `HOME` in a temporary
directory so that nothing reads the state of the console you run for yourself,
and a `claude`, a `gh` and a `systemctl` first in the PATH, so that nothing
reaches a session, GitHub or the machine's timer.

The caller writes the board and the local state (the journal, the bell) between
`stage` and `serve`, because those are written through `ponos` itself, and
`ponos` reads where its state is from the environment `stage` sets.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The console is served by FastAPI (web/app.py), which the machine's python3 may
# not have: the checkout's environment does, once `uv sync` has made it.
VENV = ROOT / ".venv" / "bin" / "python"


def relaunch() -> None:
    """Start again under the checkout's `.venv` when `python3` has no FastAPI."""
    if (
        importlib.util.find_spec("fastapi") is None
        and VENV.is_file()
        and Path(sys.prefix).resolve() != VENV.parents[1].resolve()
    ):
        os.execv(VENV, [str(VENV), *sys.argv])


# The session a message to the workspace starts: what it does, said the way
# Claude Code's stream-json says it.
CLAUDE = """#!{python}
import json, os, pathlib, sys, time

args = sys.argv[1:]
# What the health band at the top of the dashboard asks: a Claude Code that is
# there, recent enough and signed in — nothing to fix on a board of fixtures.
if args == ["--version"]:
    print("2.1.0 (Claude Code)")
    sys.exit(0)
# Signed in, except for the first connection's console, whose test is about the
# sign-in it asks for.
if args[:2] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": {signed}, "authMethod": "claude.ai", "email": "ada@example.com"}}))
    sys.exit(0)
resumed = "--resume" in args
session = args[args.index("--resume" if resumed else "--session-id") + 1]
filed = pathlib.Path.home() / ".claude" / "projects" / "-e2e" / f"{{session}}.jsonl"
filed.parent.mkdir(parents=True, exist_ok=True)
filed.touch()
prompt = sys.stdin.read()

def say(event):
    print(json.dumps(event), flush=True)
    time.sleep(0.6)

if "proposing ideas" in prompt:
    # A batch of ten for the ideas deck: other words every time it is asked,
    # so that none is dropped as one already proposed.
    counter = pathlib.Path.home() / "ideas-asked"
    asked = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(asked + 1))
    nouns = ["calendar", "invoice", "gallery", "newsletter", "dashboard", "inventory", "booking",
             "referral", "changelog", "playlist", "quotation", "timeline", "wishlist", "forum",
             "podcast", "glossary", "roadmap", "checkout", "sitemap", "feedback"]
    teams = ["sales", "support", "finance", "marketing", "legal"]
    batch = [
        {{"title": f"Build the {{nouns[n + 10 * (asked % 2)]}} module for {{teams[asked % 5]}}",
          "description": f"Because the {{nouns[n + 10 * (asked % 2)]}} is what people ask for.",
          "kind": "project" if n % 2 else "ticket", "where": "The web app.",
          "category": ["ux", "feature", "security", "technical"][n % 4],
          "score": [35, 88, 52, 71, 12, 64, 95, 40, 69, None][n],
          "score_reason": "Worth it for the people who asked.",
          "done": ["It works."], "out": ["Nothing else."]}}
        for n in range(10)
    ]
    time.sleep(1)
    say({{"type": "result", "result": json.dumps(batch), "session_id": session, "total_cost_usd": 0.01, "num_turns": 1}})
    sys.exit(0)

if "You are scoring ideas" in prompt:
    # An idea written by hand, scored by the light model: 75 each, green.
    import re
    numbers = [int(found) for found in re.findall(r"^(\\d+)\\. ", prompt.split("# Ideas to score", 1)[1], re.M)]
    scores = [{{"id": number, "score": 75, "score_reason": "Small and asked for."}} for number in numbers]
    say({{"type": "result", "result": json.dumps(scores), "session_id": session, "total_cost_usd": 0.001, "num_turns": 1}})
    sys.exit(0)

def use(name, **given):
    say({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": name, "input": given}}]}}}})

say({{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "Let me look."}}]}}}})
use("Read", file_path="/home/me/app/src/api.py")
use("Bash", command="python3 -m app.check")
say({{"type": "user", "message": {{"content": [{{"type": "tool_result", "is_error": True,
    "content": "Exit code 1\\nTraceback (most recent call last): boom"}}]}}}})
if "slowly" in prompt:
    use("Bash", command="sleep 600")
    time.sleep(600)
if "hold-the-line" in prompt:
    time.sleep(4)
answer = ("Resumed, and done." if resumed else "Done.") + " The board has 13 tickets."
say({{"type": "result", "result": answer, "session_id": session, "total_cost_usd": 0.0123, "num_turns": 3}})
"""


# The runner's systemd timer, which the dashboard's health band reads: a board of
# fixtures arms none, and on a machine with systemd but no timer (GitHub's
# runners) the band would push the charts down and fail the tests that point at
# them.
SYSTEMCTL = """#!{python}
import sys

args = sys.argv[1:]
if "is-enabled" in args:
    print("enabled")
elif "show" in args:
    print("SubState=waiting")
    print("NextElapseUSecRealtime=Mon 2099-01-01 00:00:00 UTC")
    print("NextElapseUSecMonotonic=infinity")
elif "list-timers" in args:
    print("NEXT LEFT LAST PASSED UNIT ACTIVATES")
    print("Mon 2099-01-01 00:00:00 UTC 1h left n/a n/a ponos.timer ponos.service")
"""

# Who `gh api user` says it is; anything else it is asked fails, as a gh signed out would.
GH = """#!{python}
import json, sys

if sys.argv[1:3] == ["auth", "status"]:
    sys.exit(0)
if sys.argv[1:3] == ["api", "user"]:
    print(json.dumps({{"login": "ada", "name": "Ada Lovelace", "avatar_url": ""}}))
    sys.exit(0)
sys.exit(1)
"""


def said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def tool(name: str, payload: dict) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": payload}]},
    }


def stage(
    here: Path, board: Path, *, token: str | None, signed: bool = True, newer: str = ""
) -> None:
    """Everything a console needs around its board, in `here`, and the environment that points at it.

    `token` None is a console nobody has claimed. `newer` is a commit the
    update check found, for the version at the top right to offer; empty, the
    checkout is the newest there is. Either way the console's own checks are
    off, so that nothing asks a remote.
    """
    config = here / "config.toml"
    config.write_text(
        f'[storage]\nmode = "markdown"\npath = "{board}"\n\n[runner]\nauto_update = false\n',
        encoding="utf-8",
    )
    if token is not None:
        # Beside the file, where a secret lives — config.toml holds none.
        (here / "secrets.env").write_text(f"PONOS_WEB_TOKEN={token}\n", encoding="utf-8")
        (here / "secrets.env").chmod(0o600)
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    stamp = here / "state" / "ponos" / "update.json"
    stamp.parent.mkdir(parents=True)
    stamp.write_text(
        json.dumps(
            {
                "checked_at": 0,
                "current": head,
                "latest": newer or head,
                "tag": "",
                "behind": 2 if newer else 0,
                "commits": ["A second change", "A first change"] if newer else [],
            }
        )
    )
    bin = here / "bin"
    bin.mkdir()
    for name, script in (("claude", CLAUDE), ("gh", GH), ("systemctl", SYSTEMCTL)):
        (bin / name).write_text(
            script.format(python=sys.executable, signed=signed), encoding="utf-8"
        )
        (bin / name).chmod(0o755)
    (here / "home").mkdir()
    os.environ.update(
        PATH=f"{bin}{os.pathsep}{os.environ.get('PATH', '')}",
        HOME=str(here / "home"),
        PONOS_CONFIG=str(config),
        XDG_STATE_HOME=str(here / "state"),
        PYTHONPATH=str(ROOT / "src"),
    )


def serve(port: str) -> None:
    os.execvp(sys.executable, [sys.executable, "-m", "ponos", "serve", "--port", port])
