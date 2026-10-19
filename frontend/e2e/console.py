"""The console the browser tests open: a real `ponos serve`, on a board of files.

Real rather than a page with its API stubbed, because what these tests guard is
what the page does once the server has answered — how tall it is, whether it
scrolls — and a stub would be a second copy of every route to keep true. The
board is Markdown in a temporary directory (`files.py`), so nothing reaches
Notion, and `XDG_STATE_HOME` points there too, so nothing reads the state of the
console you run for yourself.

    python3 e2e/console.py 8790

One ticket is written long on purpose: a brief several screens tall, which is
the page that stopped scrolling. One is blocked on a question a run asked, for
the discussion its page opens on and the mark its card wears. Two more blocked
on a report that names its kind of stop, three more on the same report for
the Unblock gestures that move a ticket, and one in review with points to
check, for the Unblock and Decide tabs. Three projects, for the list whose cards
open them: two with a repository, and one without, an emoji for its icon. Five tickets for the gestures a card offers — one Done, one
Validated, one Ready to be set aside and made ready again, one Ready to be
given up, and one Cancelled to be reopened. Two schedules a pass
last read weeks ago, one of them turned off. And a check that found a newer
version than this checkout, for the version at the top right to offer it — a
commit that exists nowhere, so that a click on "Update now" could only ever fail;
the console's own checks are off, so that it stays the one found.
The blocked ticket has two runs in the local journal, for the session tab that
reads them.

Given `doomed`, the same console with two more projects, for the tests that
delete them. Given `unclaimed`, the same console with no token and no sign-in: what a
fresh installation serves, its first connection.

And a `claude` of its own, first in the PATH, for the conversation with the
workspace: it reads a file, runs a command that fails, and answers — or, told
to take its time, starts a command that would run for ten minutes, for Stop to
end. It files its session where Claude Code would, under a HOME of its own, so
a stopped conversation is one that can be resumed. And a `gh` that answers who
it is signed in as — no picture, so nothing is fetched — for the name an idea
written by hand is signed with.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ponos import files  # noqa: E402

# The token the tests open the console with: a board of fixtures has nothing to guard.
TOKEN = "e2e"
LONG = "000000000000000000000000000abcde"
ASKING = "00000000000000000000000000000a5c"
NEWER = "f" * 40
GESTURES = {
    "0000000000000000000000000000d0e0": ("A finished ticket", "Done"),
    "0000000000000000000000000000fa11": ("A validated ticket", "Validated"),
    "0000000000000000000000000000a51d": ("A ticket to set aside", "Ready"),
    "0000000000000000000000000000c0de": ("A ticket to give up", "Ready"),
    "0000000000000000000000000000c0ff": ("A ticket given up", "Cancelled"),
}
# Cards waiting on you, for a blocked ticket's discussion and the Decide tab:
# blocked on a report that names its kind of stop — one to read, and one for
# each gesture that moves it, one of them proposing to close the ticket — and
# one in review whose report says what to check. No project, so no count moves.
WAITING = {
    "00000000000000000000000000b10c01": ("Install Tailscale on the server", "Blocked", "blocked"),
    "00000000000000000000000000b10c02": ("Choose the host", "Blocked", "blocked"),
    "00000000000000000000000000b10c03": ("Close the duplicate", "Blocked", "blocked"),
    "00000000000000000000000000b10c04": ("Move the old backups", "Blocked", "blocked"),
    "00000000000000000000000000b10c05": ("Renew the certificate", "Blocked", "blocked"),
    "00000000000000000000000000b10c06": ("Pick the header", "Blocked", "blocked"),
    "00000000000000000000000000de1c01": ("Add the share button", "In review", "review"),
}
# Pull requests in review, and what the runner last read of their checks: one
# red, one running, one green, and one that has no check at all — drawn with
# nothing. The first is the review ticket above.
CHECKED = {
    "00000000000000000000000000de1c01": ("failed", ["pass", "fail", "pending"]),
    "00000000000000000000000000c1c102": ("pending", ["pass", "pending"]),
    "00000000000000000000000000c1c103": ("passed", ["pass", "skipping"]),
    "00000000000000000000000000c1c104": ("", []),
}
NAMES = {
    "00000000000000000000000000c1c102": "Speed up the search",
    "00000000000000000000000000c1c103": "Fix the footer",
    "00000000000000000000000000c1c104": "Rename the options",
}
# A card in progress that no session has written a step for yet, on a model
# whose name is longer than the card is wide.
STARTING = ("000000000000000000000000000057a1", "Warm up the engine", "qwen/qwen-2.5-coder-32b-instruct")
# Code tickets with a sub-type, written as the board writes it: the card wears
# its badge, and the search filters on it.
SUBTYPED = {
    "00000000000000000000000000c1c102": "Sécurité",
    "00000000000000000000000000c1c103": "Bug",
}
STUCK = (
    "🙋 Stuck — branch `ticket/tailscale` ready\n"
    "Missing access: I have no SSH access to the server\n"
    "Which way do you prefer?\n"
    "1. Give me an SSH key · 2. Install it yourself and tell me"
)
# The one card whose session proposes to close it rather than to work on it.
CLOSING = (
    "🙋 Stuck — nothing done\n"
    "A decision to make: the same change was merged last week\n"
    "It is a duplicate of “Open the firewall”: close it? → yes / no"
)
REPORTS = {"00000000000000000000000000b10c03": CLOSING}
DELIVERED = (
    "✅ To review — PR #12 · 3 commits · 9 minutes\n"
    "Adds a share button under each article.\n"
    "https://github.com/example/website/pull/12\n"
    "To check: not tried on Safari\n"
    "To check: the screenshots on mobile are missing"
)
PAUSED = "00000000000000000000000000005ed1"
DUE = "00000000000000000000000000005ed2"
PROJECTS = {"0000000000000000000000000000cafe": "Website", "0000000000000000000000000000beef": "Newsletter"}
WRITING = ("0000000000000000000000000000f00d", "Journal", "📝")
# A ticket on a project that has an icon: what its card's foot shows.
FOOTED = ("00000000000000000000000000f007ed", "Write the journal entry")
# Two projects only the deleting tests touch — one from the list, one from its
# page — each with a ticket ready and one done, which a deletion must tell apart.
# Written only for the console given `doomed`: the other tests count projects.
DOOMED = {"0000000000000000000000000000d001": "Old shop", "0000000000000000000000000000d002": "Old blog"}


def pull_request(id: str) -> str:
    return f"https://github.com/example/site/pull/{int(id[-3:], 16)}"


def checks_of() -> None:
    """What the runner last read of each pull request's checks, in the local state."""
    import time

    from ponos import db, state

    for id, (verdict, buckets) in CHECKED.items():
        state.keep_ci(
            id,
            {
                "url": pull_request(id),
                "head": "abc123",
                "state": verdict,
                "checks": [
                    {"name": f"job-{number}", "bucket": bucket, "link": f"https://github.com/example/site/actions/runs/{number}"}
                    for number, bucket in enumerate(buckets)
                ],
                "since": time.time(),
                "asked": time.time(),
            },
        )
    db.close()


def board(root: Path, doomed: bool = False) -> None:
    tickets = root / "tickets"
    tickets.mkdir(parents=True)
    brief = "\n\n".join(
        f"## Part {part}\n\n" + " ".join(["A line of the brief, long enough to wrap."] * 12)
        for part in range(1, 41)
    )
    long = {"id": LONG, "title": "A long ticket", "Status": "Ready", "Priority": 90}
    (tickets / f"a-long-ticket-{LONG[-8:]}.md").write_text(files.render(long, brief), encoding="utf-8")
    asking = {
        "id": ASKING,
        "title": "A ticket with a question",
        "Status": "Blocked",
        "Blocage": "session.question",
    }
    (tickets / f"a-ticket-with-a-question-{ASKING[-8:]}.md").write_text(
        files.render(asking, "Put the logo in the header."), encoding="utf-8"
    )
    comments = root / "comments"
    comments.mkdir()
    question = {"id": "q1", "at": "2026-09-30T10:00:00+00:00", "by": "ponos", "discussion": "q1"}
    (comments / f"{ASKING}.md").write_text(
        files.render(question, "🙋 Question\nWhich header, the dashboard's or the site's?"), encoding="utf-8"
    )
    for id, title in NAMES.items():
        page = {"id": id, "title": title, "Status": "In review", "Pull Request": pull_request(id)}
        if id in SUBTYPED:
            page.update({"Type": "Code", "Sous-type": SUBTYPED[id]})
        (tickets / f"{title.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
            files.render(page, "A short brief."), encoding="utf-8"
        )
    for id, (title, status, column) in WAITING.items():
        page = {"id": id, "title": title, "Status": status}
        if id in CHECKED:
            page["Pull Request"] = pull_request(id)
            # What it cost: the foot of its card has more to say than its checks.
            page["Cost"] = 7.28
            page["created"] = "2026-10-15T10:00:00+00:00"
        (tickets / f"{title.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
            files.render(page, "A short brief."), encoding="utf-8"
        )
        said = {"id": f"r{id[-4:]}", "at": "2026-10-01T10:00:00+00:00", "by": "ponos",
                "discussion": f"r{id[-4:]}"}
        (comments / f"{id}.md").write_text(
            files.render(said, REPORTS.get(id, STUCK) if column == "blocked" else DELIVERED), encoding="utf-8"
        )
    id, title, model = STARTING
    page = {"id": id, "title": title, "Status": "In progress", "Model": model}
    (tickets / f"{title.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
        files.render(page, "A short brief."), encoding="utf-8"
    )
    for number in range(1, 13):
        page = {"id": f"{number:032d}", "title": f"Ticket {number}", "Status": "Backlog"}
        (tickets / f"ticket-{number}-{page['id'][-8:]}.md").write_text(
            files.render(page, "A short brief."), encoding="utf-8"
        )
    for id, (title, status) in GESTURES.items():
        page = {"id": id, "title": title, "Status": status}
        (tickets / f"{title.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
            files.render(page, "A short brief."), encoding="utf-8"
        )
    projects = root / "projects"
    projects.mkdir()
    for id, name in PROJECTS.items():
        page = {"id": id, "title": name, "Repository": f"example/{name.lower()}"}
        (projects / f"{name.lower()}-{id[-8:]}.md").write_text(
            files.render(page, f"The brief of {name}."), encoding="utf-8"
        )
    for number, (id, name) in enumerate(DOOMED.items() if doomed else ()):
        page = {"id": id, "title": name, "Repository": f"example/{name.lower().replace(' ', '-')}"}
        (projects / f"{name.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
            files.render(page, f"The brief of {name}."), encoding="utf-8"
        )
        for status in ("Ready", "Done"):
            ticket = f"{number * 2 + (status == 'Done') + 1:030d}0{number + 1}"
            title = f"{name} work, {status.lower()}"
            page = {"id": ticket, "title": title, "Status": status, "Project": [id]}
            (tickets / f"{title.lower().replace(' ', '-').replace(',', '')}-{ticket[-8:]}.md").write_text(
                files.render(page, "A short brief."), encoding="utf-8"
            )
    id, name, icon = WRITING
    page = {"id": id, "title": name, "icon": icon}
    (projects / f"{name.lower()}-{id[-8:]}.md").write_text(
        files.render(page, f"The brief of {name}."), encoding="utf-8"
    )
    # A ticket on that project, for the card's foot: its icon, and its link.
    page = {"id": FOOTED[0], "title": FOOTED[1], "Status": "Ready", "Project": [WRITING[0]]}
    (tickets / f"footed-{FOOTED[0][-8:]}.md").write_text(files.render(page, "A short brief."), encoding="utf-8")
    # Two schedules whose `Next` is weeks behind: one turned off since, which
    # will not fire, and one on, which fires on the next pass. Neither may show
    # a date in the past.
    schedules = root / "schedules"
    schedules.mkdir()
    for id, name, active in ((PAUSED, "Test email", False), (DUE, "Weekly digest", True)):
        page = {"id": id, "title": name, "Cadence": "Hourly", "At": "00:00",
                "Active": active, "Next": "2026-09-09T21:00:00+02:00"}
        # The turned-off one did fire, a minute ago: the calendar's only past.
        if not active:
            page["Last"] = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="minutes")
        (schedules / f"{name.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
            files.render(page, "Send it."), encoding="utf-8"
        )


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


def journal_of(ticket: str) -> None:
    """Two runs of the blocked ticket in the local journal, the second long.

    The first failed after three steps; the second asked its question after
    two hundred and fifty — more than one page, for the button that reads
    further back.
    """
    from ponos import db, journal

    first = journal.Run.start(ticket=ticket, title="A ticket that asked", session="first")
    first.event({"type": "system", "subtype": "init", "model": "claude-sonnet-4-5-20250929"})
    first.event(_said("I read the brief first."))
    first.event(_tool("Bash", {"command": "make test"}))
    first.event({"type": "user", "message": {"content": [
        {"type": "tool_result", "is_error": True, "content": "make: *** No rule to make target"}
    ]}})
    first.event({"type": "result", "total_cost_usd": 0.12})
    first.end("failed", "the session ended badly")
    second = journal.Run.start(ticket=ticket, title="A ticket that asked", session="second")
    second.event({"type": "system", "subtype": "init", "model": "claude-opus-4-1-20250805"})
    second.event(_said("Starting again, from the start."))
    for index in range(1, 249):
        second.event(_tool("Read", {"file_path": f"/repo/src/part-{index}.py"}))
    second.event(_said("Which header — the dashboard's, or the public site's?"))
    second.event({"type": "result", "total_cost_usd": 0.5})
    second.end("blocked", "which header", "session.question")
    # Fifteen minutes of work in all — ten, then five — and the hour between
    # them waited on, for the time the Brief adds up and the card wears.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for run, begun, minutes in ((first, 130, 10), (second, 60, 5)):
        start = now - timedelta(minutes=begun)
        with db.transaction() as connection:
            connection.execute(
                "UPDATE runs SET started_at = ?, ended_at = ? WHERE id = ?",
                (start.isoformat(), (start + timedelta(minutes=minutes)).isoformat(), run.id),
            )
    db.close()


def bell_of() -> None:
    """Three notifications on the bell: the question the blocked ticket asked, and two on the long one."""
    from ponos import db, notifications

    notifications.add("failed", LONG, "A long ticket")
    notifications.add("review", LONG, "A long ticket")
    notifications.add("question", ASKING, "A ticket with a question")
    db.close()


def _said(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _tool(name: str, payload: dict) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": payload}]}}


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "8790"
    # `unclaimed`: no token and no sign-in, for the first connection's steps.
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    unclaimed = mode == "unclaimed"
    here = Path(tempfile.mkdtemp(prefix="ponos-e2e-"))
    board(here / "board", doomed=mode == "doomed")
    config = here / "config.toml"
    # No update checks of the console's own: they would ask the remote of this
    # checkout and write over the stamp below.
    config.write_text(
        f'[storage]\nmode = "markdown"\npath = "{here / "board"}"\n'
        "\n[runner]\nauto_update = false\n",
        encoding="utf-8",
    )
    if not unclaimed:
        # Beside the file, where a secret lives — config.toml holds none.
        (here / "secrets.env").write_text(f"PONOS_WEB_TOKEN={TOKEN}\n", encoding="utf-8")
        (here / "secrets.env").chmod(0o600)
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    stamp = here / "state" / "ponos" / "update.json"
    stamp.parent.mkdir(parents=True)
    stamp.write_text(json.dumps({
        "checked_at": 0, "current": head, "latest": NEWER, "tag": "",
        "behind": 2, "commits": ["A second change", "A first change"],
    }))
    bin = here / "bin"
    bin.mkdir()
    (bin / "claude").write_text(CLAUDE.format(python=sys.executable, signed=not unclaimed), encoding="utf-8")
    (bin / "claude").chmod(0o755)
    (bin / "gh").write_text(GH.format(python=sys.executable), encoding="utf-8")
    (bin / "gh").chmod(0o755)
    (bin / "systemctl").write_text(SYSTEMCTL.format(python=sys.executable), encoding="utf-8")
    (bin / "systemctl").chmod(0o755)
    (here / "home").mkdir()
    os.environ.update(
        PATH=f"{bin}{os.pathsep}{os.environ.get('PATH', '')}",
        HOME=str(here / "home"),
        PONOS_CONFIG=str(config),
        XDG_STATE_HOME=str(here / "state"),
        PYTHONPATH=str(ROOT / "src"),
    )
    journal_of(ASKING)
    bell_of()
    checks_of()
    os.execvp(sys.executable, [sys.executable, "-m", "ponos", "serve", "--port", port])


if __name__ == "__main__":
    main()
