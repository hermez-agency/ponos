"""The console the browser tests open: a real `ponos serve`, on a board of files.

Real rather than a page with its API stubbed, because what these tests guard is
what the page does once the server has answered — how tall it is, whether it
scrolls — and a stub would be a second copy of every route to keep true. The
board is Markdown in a temporary directory (`files.py`), so nothing reaches
Notion, and `XDG_STATE_HOME` points there too, so nothing reads the state of the
console you run for yourself.

    python3 e2e/console.py 8790

Under the checkout's `.venv` when `python3` has no FastAPI: `uv sync` makes it.

One ticket is written long on purpose: a brief several screens tall, which is
the page that stopped scrolling. One is blocked on a question a run asked, for
the discussion its page opens on and the mark its card wears. Two more blocked
on a report that names its kind of stop, three more on the same report for
the Unblock gestures that move a ticket, and one in review with points to
check, for the Unblock and Decide tabs. Three projects, for the list whose cards
open them: two with a repository, and one without, an emoji for its icon. Seven tickets for the gestures a card offers — one Done, one
Validated, one Ready to be set aside and made ready again, one Ready to be
given up, one Cancelled to be reopened, and two Blocked to be dragged to Ready. Two schedules a pass
last read weeks ago, one of them turned off. And a check that found a newer
version than this checkout, for the version at the top right to offer it — a
commit that exists nowhere, so that a click on "Update now" could only ever fail;
the console's own checks are off, so that it stays the one found.
The blocked ticket has two runs in the local journal, for the session tab that
reads them.

Given `doomed`, the same console with two more projects, for the tests that
delete them. Given `series`, a board of its own: three blocked tickets, each on
another kind of stop, and two in review — the columns the series of
`series.spec.ts` goes through whole, which no other test may move a card of. Given `unclaimed`, the same console with no token and no sign-in: what a
fresh installation serves, its first connection.

The harness around the board — the stand-in `claude`, `gh` and `systemctl`, the state in a temporary
directory — is `scripts/workbench.py`, shared with `scripts/demo.py`, whose data are its own.

And a `claude` of its own, first in the PATH, for the conversation with the
workspace: it reads a file, runs a command that fails, and answers — or, told
to take its time, starts a command that would run for ten minutes, for Stop to
end. It files its session where Claude Code would, under a HOME of its own, so
a stopped conversation is one that can be resumed. And a `gh` that answers who
it is signed in as — no picture, so nothing is fetched — for the name an idea
written by hand is signed with.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import workbench  # noqa: E402

workbench.relaunch()

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
    "0000000000000000000000000000d7a1": ("A card dragged by its title", "Blocked"),
    "0000000000000000000000000000d7a2": ("A card dragged by its foot", "Blocked"),
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
# The board of the series: blocked on a question, on an access and on a stop
# Ponos tries again by itself — the order the series takes them in, whatever
# their priority — and two in review. One project, with an icon.
SERIES = {
    "000000000000000000000000005e0001": ("Pick the colour", "Blocked", "session.question", 30),
    "000000000000000000000000005e0002": ("Give the deploy key", "Blocked", "access.credentials", 90),
    "000000000000000000000000005e0003": ("Restart the build", "Blocked", "session.killed", 99),
    "000000000000000000000000005e0004": ("Add the dark mode", "In review", "", 50),
    "000000000000000000000000005e0005": ("Add the footer", "In review", "", 50),
}
SERIES_PROJECT = ("000000000000000000000000005e0caf", "Studio", "🎨")
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


def series_board(root: Path) -> None:
    """The board of `series.spec.ts`: nothing but the cards its series go through."""
    tickets = root / "tickets"
    tickets.mkdir(parents=True)
    comments = root / "comments"
    comments.mkdir()
    projects = root / "projects"
    projects.mkdir()
    id, name, icon = SERIES_PROJECT
    page = {"id": id, "title": name, "icon": icon}
    (projects / f"{name.lower()}-{id[-8:]}.md").write_text(files.render(page, f"The brief of {name}."), encoding="utf-8")
    for number, (id, (title, status, code, priority)) in enumerate(SERIES.items()):
        page = {"id": id, "title": title, "Status": status, "Priority": priority, "Project": [SERIES_PROJECT[0]],
                "created": f"2026-10-{10 + number}T10:00:00+00:00"}
        if code:
            page["Blocage"] = code
        (tickets / f"{title.lower().replace(' ', '-')}-{id[-8:]}.md").write_text(
            files.render(page, "A short brief."), encoding="utf-8"
        )
        said = {"id": f"r{id[-4:]}", "at": "2026-10-01T10:00:00+00:00", "by": "ponos", "discussion": f"r{id[-4:]}"}
        report = DELIVERED if status == "In review" else STUCK
        (comments / f"{id}.md").write_text(files.render(said, report), encoding="utf-8")


def journal_of(ticket: str) -> None:
    """Two runs of the blocked ticket in the local journal, the second long.

    The first failed after three steps; the second asked its question after
    two hundred and fifty — more than one page, for the button that reads
    further back.
    """
    from ponos import db, journal

    first = journal.Run.start(ticket=ticket, title="A ticket that asked", session="first")
    first.event({"type": "system", "subtype": "init", "model": "claude-sonnet-4-5-20250929"})
    first.event(workbench.said("I read the brief first."))
    first.event(workbench.tool("Bash", {"command": "make test"}))
    first.event({"type": "user", "message": {"content": [
        {"type": "tool_result", "is_error": True, "content": "make: *** No rule to make target"}
    ]}})
    first.event({"type": "result", "total_cost_usd": 0.12})
    first.end("failed", "the session ended badly")
    second = journal.Run.start(ticket=ticket, title="A ticket that asked", session="second")
    second.event({"type": "system", "subtype": "init", "model": "claude-opus-4-1-20250805"})
    second.event(workbench.said("Starting again, from the start."))
    for index in range(1, 249):
        second.event(workbench.tool("Read", {"file_path": f"/repo/src/part-{index}.py"}))
    second.event(workbench.said("Which header — the dashboard's, or the public site's?"))
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
    """Four notifications on the bell, two of them for tickets that have moved on since.

    A failure on the long ticket, now Ready again, and a pull request to read on
    the finished one, rung ten minutes ago: the console's first board read lets
    go of both. A pull request still in review and the question the blocked
    ticket asked are what is left unread.
    """
    from ponos import db, notifications

    notifications.add("failed", LONG, "A long ticket")
    notifications.add("review", "0000000000000000000000000000d0e0", "A finished ticket")
    rung = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        connection.execute("UPDATE notifications SET at = ?", (rung,))
    notifications.add("review", "00000000000000000000000000c1c102", "Speed up the search")
    notifications.add("question", ASKING, "A ticket with a question")
    db.close()


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "8790"
    # `unclaimed`: no token and no sign-in, for the first connection's steps.
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    unclaimed = mode == "unclaimed"
    here = Path(tempfile.mkdtemp(prefix="ponos-e2e-"))
    if mode == "series":
        series_board(here / "board")
    else:
        board(here / "board", doomed=mode == "doomed")
    workbench.stage(here, here / "board", token=None if unclaimed else TOKEN, signed=not unclaimed, newer=NEWER)
    journal_of(ASKING)
    bell_of()
    checks_of()
    workbench.serve(port)


if __name__ == "__main__":
    main()
