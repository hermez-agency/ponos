"""The console the browser tests open: a real `ponos service run`, on a board in a `ponos.db` of its own.

Real rather than a page with its API stubbed, because what these tests guard is
what the page does once the server has answered — how tall it is, whether it
scrolls — and a stub would be a second copy of every route to keep true. The
board is a `ponos.db` in a temporary directory, and `XDG_STATE_HOME` points
there too, so nothing reads the state of the
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
fresh installation serves, its first connection. Given `accounts`, a board of
its own for `accounts.spec.ts` — two tickets in review and a draft — in a
directory named after the port, so the test can read the comment a member left.

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

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import workbench  # noqa: E402

workbench.relaunch()

# The token the tests open the console with: a board of fixtures has nothing to guard.
TOKEN = "e2e"
LONG = "000000000000000000000000000abcde"
# Two drafts whose titles are far longer than a confirmation window is wide (bulk.spec.ts).
LONG_DRAFTS = {
    11: "Ticket 11 " + "blog-article-about-shipping-small-and-often-without-ever-breaking-the-build-" * 2,
    12: "Ticket 12 " + "another-extremely-long-title-with-no-space-to-wrap-on-for-the-launch-window-" * 2,
}
ASKING = "00000000000000000000000000000a5c"
# A writing ticket done: its post is its result, apart from its journal.
WRITTEN = ("0000000000000000000000000000b0a7", "Write a LinkedIn post")
# The same, for the test that retouches its result: the other reads it untouched.
RETOUCHED = ("0000000000000000000000000000b0a8", "Write another LinkedIn post")
POST = (
    "Three things shipping small taught me.\n\n"
    "1. **Small** pull requests get read.\n2. Often beats big.\n3. Alone is fine."
)
NEWER = "f" * 40
GESTURES = {
    "0000000000000000000000000000d0e0": ("A finished ticket", "done"),
    "0000000000000000000000000000fa11": ("A validated ticket", "validated"),
    "0000000000000000000000000000a51d": ("A ticket to set aside", "ready"),
    "0000000000000000000000000000c0de": ("A ticket to give up", "ready"),
    "0000000000000000000000000000c0ff": ("A ticket given up", "cancelled"),
    "0000000000000000000000000000d7a1": ("A card dragged by its title", "blocked"),
    "0000000000000000000000000000d7a2": ("A card dragged by its foot", "blocked"),
}
# Pull requests whose merge did not happen, and what their cards offer instead
# of a session: validated and waiting, and blocked on a red CI.
MERGES = {
    "00000000000000000000000000fe4901": ("A pull request waiting for its merge", "validated", ""),
    "00000000000000000000000000fe4902": (
        "A merge refused on a red CI",
        "blocked",
        "merge.checks-failed",
    ),
}
# Cards waiting on you, for a blocked ticket's discussion and the Decide tab:
# blocked on a report that names its kind of stop — one to read, and one for
# each gesture that moves it, one of them proposing to close the ticket — and
# one in review whose report says what to check. No project, so no count moves.
WAITING = {
    "00000000000000000000000000b10c01": ("Install Tailscale on the server", "blocked", "blocked"),
    "00000000000000000000000000b10c02": ("Choose the host", "blocked", "blocked"),
    "00000000000000000000000000b10c03": ("Close the duplicate", "blocked", "blocked"),
    "00000000000000000000000000b10c04": ("Move the old backups", "blocked", "blocked"),
    "00000000000000000000000000b10c05": ("Renew the certificate", "blocked", "blocked"),
    "00000000000000000000000000b10c06": ("Pick the header", "blocked", "blocked"),
    "00000000000000000000000000de1c01": ("Add the share button", "review", "review"),
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
STARTING = (
    "000000000000000000000000000057a1",
    "Warm up the engine",
    "qwen/qwen-2.5-coder-32b-instruct",
)
# A card in progress between two sessions: its pull request opened, its CI waited for.
WAITING_CI = ("0000000000000000000000000000c1a1", "Wait for the checks")
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
    "000000000000000000000000005e0001": ("Pick the colour", "blocked", "session.question", 30),
    "000000000000000000000000005e0002": (
        "Give the deploy key",
        "blocked",
        "access.credentials",
        90,
    ),
    "000000000000000000000000005e0003": ("Restart the build", "blocked", "session.killed", 99),
    "000000000000000000000000005e0004": ("Add the dark mode", "review", "", 50),
    "000000000000000000000000005e0005": ("Add the footer", "review", "", 50),
}
SERIES_PROJECT = ("000000000000000000000000005e0caf", "Studio", "🎨")
PAUSED = "00000000000000000000000000005ed1"
DUE = "00000000000000000000000000005ed2"
# Where Newsletter's clone is, once `main` has made it: the skills its repository holds.
CLONED: list[str] = []
PROJECTS = {
    "0000000000000000000000000000cafe": "Website",
    "0000000000000000000000000000beef": "Newsletter",
}
WRITING = ("0000000000000000000000000000f00d", "Journal", "📝")
# A ticket on a project that has an icon: what its card's foot shows.
FOOTED = ("00000000000000000000000000f007ed", "Write the journal entry")
# Two projects only the deleting tests touch — one from the list, one from its
# page — each with a ticket ready and one done, which a deletion must tell apart.
# Written only for the console given `doomed`: the other tests count projects.
DOOMED = {
    "0000000000000000000000000000d001": "Old shop",
    "0000000000000000000000000000d002": "Old blog",
}


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
                    {
                        "name": f"job-{number}",
                        "bucket": bucket,
                        "link": f"https://github.com/example/site/actions/runs/{number}",
                    }
                    for number, bucket in enumerate(buckets)
                ],
                "since": time.time(),
                "asked": time.time(),
            },
        )
    state.enter(WAITING_CI[0], "checks", pull_request(WAITING_CI[0]))
    db.close()


def board(seed: workbench.Seed, doomed: bool = False) -> None:
    brief = "\n\n".join(
        f"## Part {part}\n\n" + " ".join(["A line of the brief, long enough to wrap."] * 12)
        for part in range(1, 41)
    )
    long = {"id": LONG, "title": "A long ticket", "statut": "ready", "Priorité": 90}
    seed.write("tickets", long, brief)
    for id, title in (WRITTEN, RETOUCHED):
        page = {"id": id, "title": title, "statut": "done", "Type": "Rédaction"}
        seed.write("tickets", page, "A post about shipping small, for LinkedIn.")
        _result_of(id, POST, "**Result:** ✅ post written\n\nI read it twice before handing it back.")
    asking = {
        "id": ASKING,
        "title": "A ticket with a question",
        "statut": "blocked",
        "Blocage": "session.question",
    }
    seed.write("tickets", asking, "Put the logo in the header.")
    seed.say(ASKING, "🙋 Question\nWhich header, the dashboard's or the site's?")
    for id, title in NAMES.items():
        page = {"id": id, "title": title, "statut": "review", "Pull Request": pull_request(id)}
        if id in SUBTYPED:
            page.update({"Type": "Code", "Sous-type": SUBTYPED[id]})
        seed.write("tickets", page, "A short brief.")
    for id, (title, status, column) in WAITING.items():
        page = {"id": id, "title": title, "statut": status}
        if id in CHECKED:
            page["Pull Request"] = pull_request(id)
            # What it cost: the foot of its card has more to say than its checks.
            page["Cost"] = 7.28
            page["created"] = "2026-10-15T10:00:00+00:00"
        seed.write("tickets", page, "A short brief.")
        seed.say(id, REPORTS.get(id, STUCK) if column == "blocked" else DELIVERED)
    id, title = WAITING_CI
    page = {"id": id, "title": title, "statut": "progress", "Pull Request": pull_request(id)}
    seed.write("tickets", page, "A short brief.")
    id, title, model = STARTING
    page = {"id": id, "title": title, "statut": "progress", "Model": model}
    seed.write("tickets", page, "A short brief.")
    for number in range(1, 13):
        title = LONG_DRAFTS.get(number, f"Ticket {number}")
        page = {"id": f"{number:032d}", "title": title, "statut": "draft"}
        seed.write("tickets", page, "A short brief.")
    for id, (title, status) in GESTURES.items():
        page = {"id": id, "title": title, "statut": status}
        seed.write("tickets", page, "A short brief.")
    for id, (title, status, code) in MERGES.items():
        page = {"id": id, "title": title, "statut": status, "Pull Request": pull_request(id)}
        if code:
            page["Blocage"] = code
        seed.write("tickets", page, "A short brief.")
    for id, name in PROJECTS.items():
        page = {"id": id, "title": name, "Repository": f"example/{name.lower()}"}
        if name == "Newsletter" and CLONED:
            page["Path"] = CLONED[0]
        seed.write("projects", page, f"The brief of {name}.")
    for number, (id, name) in enumerate(DOOMED.items() if doomed else ()):
        page = {"id": id, "title": name, "Repository": f"example/{name.lower().replace(' ', '-')}"}
        seed.write("projects", page, f"The brief of {name}.")
        for status in ("ready", "done"):
            ticket = f"{number * 2 + (status == 'done') + 1:030d}0{number + 1}"
            title = f"{name} work, {status.lower()}"
            page = {"id": ticket, "title": title, "statut": status, "Project": [id]}
            seed.write("tickets", page, "A short brief.")
    id, name, icon = WRITING
    page = {"id": id, "title": name, "icon": icon}
    seed.write("projects", page, f"The brief of {name}.")
    # A ticket on that project, for the card's foot: its icon, and its link.
    page = {"id": FOOTED[0], "title": FOOTED[1], "statut": "ready", "Project": [WRITING[0]]}
    seed.write("tickets", page, "A short brief.")
    # Two schedules whose `Next` is weeks behind: one turned off since, which
    # will not fire, and one on, which fires on the next pass. Neither may show
    # a date in the past.
    for id, name, active in ((PAUSED, "Test email", False), (DUE, "Weekly digest", True)):
        page = {
            "id": id,
            "title": name,
            "Cadence": "Hourly",
            "At": "00:00",
            "Active": active,
            "Next": "2026-09-09T21:00:00+02:00",
        }
        # The turned-off one did fire, a minute ago: the calendar's only past.
        if not active:
            page["Last"] = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(
                timespec="minutes"
            )
        seed.write("schedules", page, "Send it.")


def _result_of(ticket: str, result: str, journal: str) -> None:
    """A ticket's result, kept as a session keeps it, and its journal — see results.py."""
    from ponos import tickets

    tickets.update(ticket, journal=journal)
    tickets.set_result(ticket, result)


def series_board(seed: workbench.Seed) -> None:
    """The board of `series.spec.ts`: nothing but the cards its series go through."""
    id, name, icon = SERIES_PROJECT
    page = {"id": id, "title": name, "icon": icon}
    seed.write("projects", page, f"The brief of {name}.")
    for number, (id, (title, status, code, priority)) in enumerate(SERIES.items()):
        page = {
            "id": id,
            "title": title,
            "statut": status,
            "Priorité": priority,
            "Project": [SERIES_PROJECT[0]],
            "created": f"2026-10-{10 + number}T10:00:00+00:00",
        }
        if code:
            page["Blocage"] = code
        seed.write("tickets", page, "A short brief.")
        report = DELIVERED if status == "review" else STUCK
        seed.say(id, report)


# The board of `accounts.spec.ts`: what a reader looks at, and what a member validates.
ACCOUNTS = {
    "000000000000000000000000acc0de01": ("A ticket a member validates", "review"),
    "000000000000000000000000acc0de02": ("A ticket a reader looks at", "review"),
    "000000000000000000000000acc0de03": ("A draft nobody may launch", "draft"),
}
# No pull request in it: the panel asks GitHub nothing.
SHARED = "✅ To review — 2 commits · 4 minutes\nAdds a share button under each article."


def accounts_board(seed: workbench.Seed) -> None:
    """The board of `accounts.spec.ts`: nothing but the cards its two people look at."""
    for id, (title, status) in ACCOUNTS.items():
        page = {"id": id, "title": title, "statut": status}
        seed.write("tickets", page, "A short brief.")
        if status == "review":
            seed.say(id, SHARED)


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
    first.event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": "make: *** No rule to make target",
                    }
                ]
            },
        }
    )
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
    now = datetime.now(UTC).replace(microsecond=0)
    for run, begun, minutes in ((first, 130, 10), (second, 60, 5)):
        start = now - timedelta(minutes=begun)
        with db.transaction() as connection:
            connection.execute(
                "UPDATE runs SET started_at = ?, ended_at = ? WHERE id = ?",
                (start.isoformat(), (start + timedelta(minutes=minutes)).isoformat(), run.id),
            )
    db.close()


def bell_of() -> None:
    """Four tickets on the bell, two of them moved on since.

    A failure on the long ticket, now Ready again, and a pull request to read on
    the finished one, rung ten minutes ago: the console's first board read lets
    go of both. A pull request still in review and the question the blocked
    ticket asked are what is left unread — its second question, the first one
    answered already: one line for the two.
    """
    from ponos import db, notifications

    notifications.add("failed", LONG, "A long ticket")
    notifications.add("review", "0000000000000000000000000000d0e0", "A finished ticket")
    rung = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        connection.execute("UPDATE notifications SET at = ?", (rung,))
    notifications.add("review", "00000000000000000000000000c1c102", "Speed up the search")
    notifications.add("question", ASKING, "A ticket with a question")
    with db.transaction() as connection:
        connection.execute("UPDATE notifications SET read_at = at WHERE ticket = ?", (ASKING,))
    notifications.add("question", ASKING, "A ticket with a question")
    db.close()


def cloned_repository(here: Path) -> str:
    """A clone for Newsletter that holds one skill of its own: the read-only list's row, and a clash."""
    import subprocess

    repository = here / "newsletter"
    folder = repository / ".claude" / "skills" / "revue"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: revue\ndescription: Reviews a pull request the way Newsletter does.\n---\n\nReview.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    return str(repository)


def memory_of() -> None:
    """What Ponos remembers: one kept fact, and two proposals waiting.

    One proposal comes from a ticket (its link leads there), the other from a
    conversation of the MCP, which has no page to lead to.
    """
    from ponos import db, memory

    memory.add("Prefers short reports.", "preference")
    memory.propose("The client signs off on Fridays.", "project", "", "ticket", ASKING)
    memory.propose("The owner is an early riser.", "person", "", "chat")
    db.close()


# A one-pixel PNG and a one-page PDF: real files, so that the previews have
# something to draw.
PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082"
)
PAGE = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def library_of() -> None:
    """The library: a charter for the Website project only, and a logo for every project."""
    import io

    from ponos import db, library

    library.save(
        "charter.pdf",
        io.BytesIO(PAGE),
        len(PAGE),
        1 << 20,
        description="The brand charter",
        tag_list=["brand", "client"],
        project_list=["0000000000000000000000000000cafe"],
    )
    library.save(
        "logo.png",
        io.BytesIO(PIXEL),
        len(PIXEL),
        1 << 20,
        description="The logo, on white",
        tag_list=["brand"],
    )
    db.close()


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "8790"
    # `unclaimed`: no token and no sign-in, for the first connection's steps.
    mode = sys.argv[2] if len(sys.argv) > 2 else ""
    # `fresh`: unclaimed too, and on no board at all — what an installation
    # serves before anything is written: nothing in `ponos.db`.
    fresh = mode == "fresh"
    unclaimed = mode == "unclaimed" or fresh
    here = Path(tempfile.mkdtemp(prefix="ponos-e2e-"))
    if mode == "accounts":
        # Where the test finds it again: `accounts.spec.ts` reads its comments.
        here = Path(tempfile.gettempdir()) / f"ponos-e2e-accounts-{port}"
        shutil.rmtree(here, ignore_errors=True)
        here.mkdir()
    workbench.stage(
        here,
        token=None if unclaimed else TOKEN,
        signed=not unclaimed,
        newer=NEWER,
    )
    if not fresh:
        seed = workbench.Seed()
        CLONED.append(cloned_repository(here))
        if mode == "accounts":
            accounts_board(seed)
        elif mode == "series":
            series_board(seed)
        else:
            board(seed, doomed=mode == "doomed")
        from ponos import db

        db.close()
        journal_of(ASKING)
        bell_of()
        checks_of()
        memory_of()
        library_of()
    workbench.serve(port)


if __name__ == "__main__":
    main()
