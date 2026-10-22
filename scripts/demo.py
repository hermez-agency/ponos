#!/usr/bin/env python3
"""A console to work on the interface with: a real `ponos serve`, on a board made up.

    python3 scripts/demo.py [port]        # 8791, and the token is "demo"
    cd frontend && npm run dev:demo       # the page, hot reloaded, on that console

Working on the console used to take a real installation — Notion, repositories,
paid sessions — or the server of the browser tests, whose board is cut for them:
one ticket per gesture to check, a single run in the journal, a handful of
notifications. A page drawn against that is drawn empty. This board is cut to be
looked at: eight projects, sixty-odd tickets in every column, six weeks of
sessions, costs, stops of every family, recurrences, ideas, a bell, conversations.

**It does not share data with `frontend/e2e/console.py`, only the harness**
(`workbench.py`). Making the demo richer must never move a test, and a test
must never be what the demo is made of.

**Deterministic, and dated from now.** Every identifier comes from a hash of its
name and every choice from one generator seeded here, so two starts write the same
board; every date is a number of days before the moment of the start, so the
board never looks old. What differs between two starts is those dates and nothing else.

**Nothing is real, and nothing leaves the machine**: the configuration, the state
(`ponos.db`), HOME and the board live in a temporary directory, removed when the
console stops, and the `claude`, `gh` and `systemctl` first in the PATH answer for
themselves. The local state is written through `ponos`'s own modules (`journal`,
`state`, `ideas`, `notifications`, `chats`), not through SQL of ours, so that a
migration of a table moves the demo with it — dates aside, which a module stamps
with the present and the demo moves back into the past.
"""

from __future__ import annotations

import hashlib
import random
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workbench  # noqa: E402

workbench.relaunch()

from ponos import files, schedules  # noqa: E402

PORT = "8791"
TOKEN = "demo"
SEED = 20261022

NOW = datetime.now(UTC).replace(microsecond=0)

REPORT_AUTHOR = "ponos"

# -- the projects --------------------------------------------------------------

# key: (name, icon, repository, what it is). Two have no repository: their
# tickets produce documents, and one of those has no icon.
PROJECTS = {
    "website": (
        "Acme Website",
        "🌐",
        "acme/website",
        "The marketing site: Astro, MDX, a blog and the pricing pages.",
    ),
    "ponos": (
        "Ponos",
        "🤖",
        "acme/ponos",
        "The runner that works the tickets, and its console.",
    ),
    "app": (
        "Northwind App",
        "🐾",
        "acme/northwind-app",
        "The mobile app for pet owners: React Native, a Node API, Postgres.",
    ),
    "leadz": (
        "Leadz",
        "🎯",
        "acme/leadz",
        "Prospecting: find companies, write to them, follow the replies.",
    ),
    "brand": (
        "Brand Assets",
        "🎨",
        "acme/brand-assets",
        "Logos, tokens and the scripts that export them for every product.",
    ),
    "trader": (
        "Trader IA",
        "📈",
        "acme/trader-ia",
        "Backtests and alerts for a handful of strategies.",
    ),
    "newsletter": (
        "Newsletter",
        "✉️",
        "",
        "The monthly letter: written on the board, published from Notion.",
    ),
    "handbook": (
        "Team Handbook",
        "",
        "",
        "How the team works — policies, checklists, the release process.",
    ),
}

AGENTS = {
    "reviewer": (
        "Reviewer",
        "opus",
        "Reads a diff the way a maintainer would: what breaks, what is missing.",
    ),
    "writer": ("Technical writer", "sonnet", "Writes for the person who has never seen the code."),
    "release": ("Release manager", "haiku", "Prepares the changelog, the tag and the notes."),
}

# -- the tickets ---------------------------------------------------------------

CODE, WRITING, EXTERNAL, PUBLICATION = "Code", "Writing", "External action", "Publication"

# (project, title, type, sub-type, status, flag). The flag is the block code of a
# ticket that stopped, or `ci:<state>` for a pull request in review. The order is
# the order the generator draws in: change it and the whole board is another one.
TICKETS = [
    ("website", "Add a FAQ to the pricing page", CODE, "Feature", "Done", ""),
    ("website", "Fix the contact form on Safari", CODE, "Bug", "Done", ""),
    ("website", "Speed up the hero image on mobile", CODE, "Perf", "In review", "ci:passed"),
    ("website", "Migrate the blog to MDX", CODE, "Refactor", "In progress", ""),
    ("website", "The cookie banner is shown twice", CODE, "Bug", "Blocked", "merge.checks-failed"),
    ("website", "Translate the legal pages into Spanish", WRITING, "", "Ready", ""),
    ("website", "Add structured data to the product pages", CODE, "Feature", "Backlog", ""),
    ("website", "Upgrade Astro to the next major", CODE, "Chore", "Done", ""),
    ("website", "Case study: the Northwind launch", WRITING, "", "In review", ""),
    ("ponos", "Show the cost of a ticket on its card", CODE, "Feature", "Done", ""),
    ("ponos", "Retry a failed merge from the card", CODE, "Amélioration", "Validated", ""),
    ("ponos", "Redact tokens in the session log", CODE, "Sécurité", "Done", ""),
    ("ponos", "Split runner.py by chapter", CODE, "Refactor", "Done", ""),
    ("ponos", "Document the vault in the README", CODE, "Docs", "Done", ""),
    (
        "ponos",
        "Merge conflict on the config schema",
        CODE,
        "Bug",
        "Blocked",
        "merge.conflict-decision",
    ),
    (
        "ponos",
        "Ring the bell when a session asks a question",
        CODE,
        "Feature",
        "In review",
        "ci:failed",
    ),
    ("ponos", "Dark mode for the statistics page", CODE, "Feature", "Ready", ""),
    ("ponos", "Keep the project index between two passes", CODE, "Perf", "Backlog", ""),
    ("ponos", "Release 0.9: changelog and tag", PUBLICATION, "", "Backlog", ""),
    ("app", "Add the vaccination calendar", CODE, "Feature", "In progress", ""),
    ("app", "Push notifications for lost pets", CODE, "Feature", "Blocked", "session.question"),
    ("app", "Crash when uploading a PNG over 10 MB", CODE, "Bug", "Done", ""),
    ("app", "Rewrite the onboarding copy", WRITING, "", "Ready", ""),
    ("app", "Remove the legacy API v1 endpoints", CODE, "Chore", "Backlog", ""),
    (
        "app",
        "Audit the vulnerable dependencies",
        CODE,
        "Sécurité",
        "Blocked",
        "session.over-budget",
    ),
    ("app", "The dashboard is slow with 10 000 pets", CODE, "Perf", "Failed", "runner.crashed"),
    ("app", "Open the Play Store beta", EXTERNAL, "", "Blocked", "access.credentials"),
    ("leadz", "Export the contacts as CSV", CODE, "Feature", "Done", ""),
    ("leadz", "Deduplicate the companies by domain", CODE, "Amélioration", "Done", ""),
    ("leadz", "Rate limit the search endpoint", CODE, "Sécurité", "In review", "ci:pending"),
    ("leadz", "A health score for each folder", CODE, "Feature", "Ready", ""),
    ("leadz", "Fix the SMS campaign preview", CODE, "Bug", "Done", ""),
    (
        "leadz",
        "Replies are missed when the mail was forwarded",
        CODE,
        "Bug",
        "Blocked",
        "session.no-commit",
    ),
    ("leadz", "Install the Brevo webhook on the server", EXTERNAL, "", "Blocked", "access.sudo"),
    ("leadz", "Archive the old campaigns", CODE, "Chore", "Backlog", ""),
    ("brand", "Generate the favicons of every product", CODE, "Feature", "Done", ""),
    ("brand", "Document the colour tokens", CODE, "Docs", "Done", ""),
    ("brand", "Dark variants of the logos", CODE, "Feature", "In review", "ci:none"),
    ("brand", "Speed up the SVG export script", CODE, "Perf", "Cancelled", ""),
    ("brand", "Clean up a worktree left behind", CODE, "Chore", "Blocked", "worktree.residue"),
    ("trader", "Backtest the momentum strategy", CODE, "Feature", "Done", ""),
    ("trader", "Fix the timezone of the daily candles", CODE, "Bug", "Done", ""),
    ("trader", "Alert when the API quota reaches 80 %", CODE, "Amélioration", "Ready", ""),
    ("trader", "Refactor the broker adapters", CODE, "Refactor", "Backlog", ""),
    ("trader", "Write the weekly report to Notion", WRITING, "", "Blocked", "notion.write-failed"),
    ("newsletter", "Issue 41: autumn product news", WRITING, "", "Done", ""),
    ("newsletter", "Issue 42: customer stories", WRITING, "", "In progress", ""),
    ("newsletter", "Subject lines to test for issue 43", WRITING, "", "Ready", ""),
    ("newsletter", "Publish issue 42 on the blog", PUBLICATION, "", "Backlog", ""),
    ("newsletter", "Ask the guest author of issue 44", EXTERNAL, "", "Backlog", ""),
    ("handbook", "Write the onboarding checklist", WRITING, "", "Done", ""),
    ("handbook", "Update the holiday policy", WRITING, "", "In review", ""),
    ("handbook", "Describe the release process", WRITING, "", "Done", ""),
    ("handbook", "Which tools do we pay for?", WRITING, "", "Blocked", "ticket.empty"),
    ("handbook", "Plan the quarterly retrospective", WRITING, "", "Cancelled", ""),
]

# The tickets the recurrences were born of: done, week after week.
RECURRING = {
    "Weekly dependency review": ("ponos", CODE, "Chore", 6),
    "Weekly digest": ("newsletter", WRITING, "", 4),
    "Monthly cost report": ("handbook", WRITING, "", 1),
}

# What each family of stop says on the ticket, in the words a report uses. The
# category is the one `decisions.py` reads back to offer what fits.
STOPS = {
    "merge.checks-failed": (
        "Failing checks",
        "the checks still fail once the conflicts are resolved: `lint` is red on the rebased branch",
        "Should I fix the lint errors, or is this one for you?",
        "1. Fix them and push again · 2. I will look at it myself",
    ),
    "merge.conflict-decision": (
        "Conflict",
        "the base changed the same function in two different ways, and both are plausible",
        "Which of the two behaviours should win?",
        "1. Keep the base's version · 2. Keep the ticket's version · 3. Merge both options",
    ),
    "session.question": (
        "A decision to make",
        "the brief does not say which pets get a notification",
        "Notify only the owner, or everybody within five kilometres?",
        "1. Only the owner · 2. Everybody nearby",
    ),
    "session.over-budget": (
        "Out of credit",
        "the session spent its $8 ceiling reading the dependency tree before finding anything",
        "Raise the ceiling for this ticket?",
        "1. Raise it to $15 · 2. Narrow the audit to the API package",
    ),
    "session.no-commit": (
        "Stuck",
        "the session ended well and committed nothing: the forwarded mails use a header it could not reproduce",
        "Can you forward me one such mail as a sample?",
        "",
    ),
    "worktree.residue": (
        "Stuck",
        "a worktree of an earlier run is still there, with files nobody committed",
        "Clean it up, or do you want to look at what is in it first?",
        "1. Clean it up · 2. Leave it, I will look",
    ),
    "notion.write-failed": (
        "Stuck",
        "Notion refused the page: the integration cannot see the Reports database any more",
        "Share the Reports database with the integration, then say done.",
        "",
    ),
    "access.sudo": (
        "Something to do by hand",
        "installing the webhook needs root on the server, which a session never has",
        "Run the command below on the server, then answer done.",
        "",
    ),
    "access.credentials": (
        "Missing access",
        "the Play Console asks for a sign-in with a code sent by e-mail",
        "Sign in to the Play Console, then answer done.",
        "",
    ),
    "ticket.empty": (
        "A decision to make",
        "the ticket has a title and no brief",
        "What do you want the list to contain: the subscriptions, the tools, or both?",
        "1. Subscriptions only · 2. Tools and subscriptions",
    ),
    "runner.crashed": (
        "Stuck",
        "the runner stopped while the session was working: the machine went to sleep",
        "",
        "",
    ),
}

# The stops of the past: sessions that stopped, were answered, and went on. They
# are what the statistics count per family and per week.
PAST_STOPS = [
    "merge.checks-failed",
    "session.question",
    "merge.conflict-decision",
    "session.no-answer",
    "session.question",
    "worktree.interrupted",
    "merge.base-red",
    "session.over-budget",
    "access.credentials",
    "session.killed",
    "merge.pushed-over",
    "session.question",
    "notion.read-failed",
    "merge.checks-failed",
]

CAVEATS = [
    "not tried on Safari",
    "the screenshots on mobile are missing",
    "the migration was run on an empty database only",
    "I could not run the end-to-end tests here",
    "the French translation was not proofread",
    "no one has measured it on a slow connection",
]

SUMMARIES = [
    "Adds the page and its tests; the old route redirects to it.",
    "The fix is a one-line change in the parser, with a test that fails without it.",
    "Moves the logic out of the component, and keeps its public props as they were.",
    "Updates the dependency and the three call sites its release notes warn about.",
    "Writes the section, with an example for each case the brief lists.",
    "Adds the option behind a setting that is off by default.",
]

CONTEXT = [
    "People have been asking for this for a few weeks, and support answers by hand each time.",
    "The current behaviour is a quick fix from last quarter that nobody has looked at since.",
    "It is in the way of the next release, so a small change that can be reviewed beats a perfect one.",
    "A customer reported it twice this month, and the second time they were not kind about it.",
    "It is a good moment: the module was touched last week and is fresh in everybody's mind.",
]
TASKS = [
    "Read the code around the feature before changing anything, and say what you found.",
    "Write the test first, and check that it fails for the reason you expect.",
    "Keep the change inside the module: no drive-by cleanups.",
    "Update the documentation where it describes the old behaviour.",
    "Handle the empty case and the case with a very long value.",
    "Check the mobile layout at 375 px and the desktop one at 1440 px.",
    "Leave the public names alone; other projects import them.",
    "Mention in the report anything you could not verify.",
]
DONE_WHEN = [
    "The new behaviour is covered by a test that was red before.",
    "The existing suite is green, and the linter has nothing to say.",
    "The pull request explains what changed and why, in a few lines.",
    "Nothing outside the scope of the ticket is modified.",
]
NOTES = (
    "```sh\n"
    "# to reproduce\n"
    "git checkout main && make setup\n"
    "make test -- -k regression\n"
    "```\n\n"
    "| Case | Today | Expected |\n"
    "| --- | --- | --- |\n"
    "| empty value | error 500 | a clear message |\n"
    "| very long value | cut silently | cut with an ellipsis |\n"
    "| unknown option | ignored | refused, with the list of options |\n"
)

# What the sessions read and run, per project: the files a step names.
FILES = {
    "website": [
        "src/pages/pricing.astro",
        "src/components/Faq.astro",
        "src/content/blog/index.mdx",
    ],
    "ponos": [
        "src/ponos/board.py",
        "src/ponos/web/routes.py",
        "frontend/src/components/console/card.tsx",
    ],
    "app": ["app/screens/Calendar.tsx", "api/src/pets/routes.ts", "api/src/db/queries.ts"],
    "leadz": ["backend/search/service.py", "backend/campaigns/preview.py", "web/src/folders.tsx"],
    "brand": ["scripts/export.mjs", "tokens/colors.json", "logos/dark/index.svg"],
    "trader": ["strategies/momentum.py", "data/candles.py", "brokers/adapter.py"],
    "newsletter": ["issues/41.md", "issues/42.md"],
    "handbook": ["handbook/onboarding.md", "handbook/release.md"],
}
COMMANDS = {
    "website": "npm test",
    "ponos": "uv run python tests/run.py",
    "app": "npm run test -- --watchAll=false",
    "leadz": "pytest -q",
    "brand": "node scripts/export.mjs --check",
    "trader": "pytest -q tests/",
    "newsletter": "grep -c '' issues/*.md",
    "handbook": "markdownlint handbook/",
}
MODELS = {
    "opus": "claude-opus-4-1-20250805",
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
}

SCHEDULES = [
    # name, project, cadence, at, day, active, type, sub-type, model, brief
    (
        "Weekly dependency review",
        "ponos",
        "Weekly",
        "09:00",
        "Monday",
        True,
        CODE,
        "Chore",
        "haiku",
        "List the outdated dependencies, update the safe ones, and open one pull request.",
    ),
    (
        "Weekly digest",
        "newsletter",
        "Weekly",
        "17:00",
        "Friday",
        True,
        WRITING,
        "",
        "sonnet",
        "Write the digest of what shipped this week, from the merged pull requests.",
    ),
    (
        "Monthly cost report",
        "handbook",
        "Monthly",
        "08:30",
        "1",
        True,
        WRITING,
        "",
        "sonnet",
        "Add up what the sessions cost last month, per project, and say what stands out.",
    ),
    (
        "Nightly backup check",
        "app",
        "Daily",
        "03:00",
        "",
        True,
        CODE,
        "Chore",
        "haiku",
        "Check that last night's database backup exists, is not empty, and restores.",
    ),
    (
        "Hourly uptime probe",
        "website",
        "Hourly",
        "00:00",
        "",
        False,
        CODE,
        "Bug",
        "haiku",
        "Fetch the ten main pages and report the ones that answer slowly or not at all.",
    ),
]

# kind, category, score, title, description, where, done, out — the ideas of the
# workspace, then those of three projects. The score is the one the grid gives.
GLOBAL_IDEAS = [
    (
        "project",
        "feature",
        91,
        "A public status page for every product",
        "Customers ask whether it is down before they write to support.",
    ),
    (
        "project",
        "feature",
        78,
        "A shared library of prompts",
        "The same instructions are retyped in six projects.",
    ),
    (
        "project",
        "technical",
        64,
        "A staging environment that sleeps",
        "Cheap to keep, and it ends the tests made on production.",
    ),
    (
        "project",
        "ux",
        52,
        "A one-page client portal",
        "Invoices, files and the state of the work, without an e-mail.",
    ),
    (
        "project",
        "feature",
        33,
        "A marketplace for templates",
        "Interesting, but nobody asked for it yet.",
    ),
    (
        "ticket",
        "security",
        88,
        "Rotate every API key from one place",
        "Today it takes an afternoon and a checklist.",
    ),
    (
        "ticket",
        "technical",
        73,
        "One logging format across the products",
        "Searching the logs would stop needing four different greps.",
    ),
    (
        "ticket",
        "ux",
        69,
        "Keyboard shortcuts on every list",
        "The people who use the tools all day ask for them.",
    ),
    ("ticket", "feature", 45, "Export a project as a zip", "Useful for hand-overs, rarely needed."),
    (
        "ticket",
        "technical",
        22,
        "Move the CI to self-hosted runners",
        "Saves little at the current volume.",
    ),
    (
        "ticket",
        "ux",
        81,
        "Show the cost of the day in the header",
        "The number people look for first.",
    ),
    (
        "ticket",
        "security",
        58,
        "Expire the sign-in sessions after thirty days",
        "A long-lived cookie is a long-lived risk.",
    ),
]
PROJECT_IDEAS = {
    "website": [
        (
            "feature",
            84,
            "A comparison table on the pricing page",
            "Visitors ask what the plans do not include.",
        ),
        ("ux", 71, "Lazy-load the testimonials", "They are below the fold and weigh 400 kB."),
        (
            "technical",
            57,
            "Generate the sitemap at build time",
            "The hand-written one is two months behind.",
        ),
        (
            "security",
            37,
            "Add a Content-Security-Policy header",
            "Needs a pass over the inline scripts first.",
        ),
    ],
    "app": [
        (
            "feature",
            90,
            "Remind the owner of the next vaccine",
            "The single feature the reviews mention most.",
        ),
        ("ux", 76, "Offline mode for the pet's record", "Vets have bad reception."),
        (
            "technical",
            49,
            "Replace the hand-made date helpers",
            "Three of them disagree about time zones.",
        ),
    ],
    "ponos": [
        (
            "ux",
            86,
            "Group the notifications by ticket",
            "Three bells for the same card are one too many.",
        ),
        (
            "technical",
            62,
            "Show the steps of a run as a timeline",
            "Easier to read than a long list.",
        ),
        ("feature", 41, "Export the statistics as CSV", "Asked for once, for an invoice."),
    ],
}

# Conversations with the workspace, the Sessions page: (title, model, project,
# days ago, [(you, workspace)]).
CHATS = [
    (
        "What is waiting for me?",
        "",
        "",
        0,
        [
            (
                "What is waiting for me?",
                "Three tickets are waiting on you:\n\n- **Push notifications for lost pets** asks who should be notified.\n"
                "- **Merge conflict on the config schema** needs a choice between two behaviours.\n"
                "- **Add the share button** has two points to check before it is merged.\n\n"
                "The others are working or ready.",
            ),
        ],
    ),
    (
        "Why did the dashboard ticket fail?",
        "opus",
        "Northwind App",
        1,
        [
            (
                "Why did the dashboard ticket fail?",
                "The runner stopped while the session was reading the query plans: the machine went to sleep "
                "at 02:14. Nothing was lost; the branch has two commits. Move the ticket back to Ready and it "
                "will start from them.",
            ),
            ("Do that, and raise its priority.", "Done: it is Ready again, at priority 80."),
        ],
    ),
    (
        "Summarise last week's merged work",
        "sonnet",
        "",
        4,
        [
            (
                "Summarise last week's merged work",
                "Eleven pull requests were merged, nine of them code:\n\n1. The FAQ on the pricing page\n"
                "2. The Safari fix of the contact form\n3. CSV export of the contacts\n\n"
                "The most expensive was the Astro upgrade, at $7.40.",
            ),
        ],
    ),
    (
        "Draft the brief for the client portal",
        "opus",
        "",
        9,
        [
            (
                "Draft the brief for the client portal",
                "# Client portal\n\nOne page per client, no account to create: a signed link.\n\n"
                "## It shows\n\n- the invoices, newest first\n- the files they sent and received\n"
                "- the state of each piece of work\n\n## It does not\n\nChat, comments, or notifications.",
            ),
        ],
    ),
    (
        "How much did Leadz cost this month?",
        "haiku",
        "Leadz",
        15,
        [
            (
                "How much did Leadz cost this month?",
                "$41.20 over nineteen sessions, which is $2.17 on average. The CSV export is the most "
                "expensive ticket, at $6.80.",
            ),
        ],
    ),
]


def ident(kind: str, name: str) -> str:
    """Thirty-two hexadecimal characters, the same for the same name at every start."""
    return hashlib.md5(f"demo/{kind}/{name}".encode()).hexdigest()


def ago(days: float = 0.0) -> datetime:
    return NOW - timedelta(days=days)


def stamp(moment: datetime) -> str:
    return moment.isoformat()


def sentence_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def brief(rng: random.Random, title: str, size: str) -> str:
    """The text of a ticket: a line, a page, or several screens."""
    if size == "short":
        return f"{title}. Keep the change small, and follow the conventions of the code around it."
    context = rng.sample(CONTEXT, 5)
    parts = [
        " ".join(context[:2]),
        "## What to do\n\n" + sentence_list(rng.sample(TASKS, 4)),
        "## Done when\n\n" + sentence_list(rng.sample(DONE_WHEN, 3)),
    ]
    if size == "long":
        parts.insert(1, "## Background\n\n" + "\n\n".join(context[2:]))
        parts.insert(3, "## Notes\n\n" + NOTES)
        parts.append("## Out of scope\n\n" + sentence_list(rng.sample(TASKS, 3)))
    return "\n\n".join(parts)


def write_page(directory: Path, title: str, front: dict[str, Any], body: str) -> None:
    name = f"{files.slug(title)}-{front['id'][-8:]}.md"
    (directory / name).write_text(files.render({"title": title, **front}, body), encoding="utf-8")


class Ticket:
    """What the board and the local state both need to know about one ticket."""

    def __init__(self, project: str, title: str, kind: str, subtype: str, status: str, flag: str):
        self.project, self.title, self.kind, self.subtype = project, title, kind, subtype
        self.status, self.flag = status, flag
        self.id = ident("ticket", title)
        self.model = ""
        self.cost: float | None = None
        self.minutes: float | None = None
        self.pull_request = ""
        self.created = NOW
        self.edited = NOW
        self.closed: datetime | None = None
        self.runs: list[dict[str, Any]] = []
        # For the tickets a recurrence was born of: every how many days, and the
        # occurrence counted back from the last one.
        self.every = 0
        self.back = 0

    @property
    def repository(self) -> str:
        return PROJECTS[self.project][2]


def tickets_of(rng: random.Random) -> list[Ticket]:
    """The board's tickets, each with a life: when it was written, taken, closed, and what it cost."""
    found = [Ticket(*row) for row in TICKETS]
    for name, (project, kind, subtype, count) in RECURRING.items():
        for back in range(count, 0, -1):
            ticket = Ticket(
                project, f"{name} #{count - back + 1}", kind, subtype, "Done", "recurring"
            )
            ticket.every, ticket.back = (30 if "Monthly" in name else 7), back
            found.append(ticket)
    for ticket in found:
        ticket.model = rng.choices(["sonnet", "opus", "haiku"], [60, 25, 15])[0]
        if ticket.subtype in ("Docs", "Chore"):
            ticket.model = "haiku"
        if ticket.subtype in ("Sécurité", "Refactor"):
            ticket.model = "opus"
        bounds = {
            "Backlog": (1, 20),
            "Ready": (0.3, 6),
            "In progress": (0.1, 1),
            "In review": (0.3, 4),
            "Validated": (0.5, 3),
            "Done": (2, 40),
            "Failed": (0.5, 3),
            "Blocked": (1, 12),
            "Cancelled": (8, 25),
        }[ticket.status]
        ticket.created = ago(rng.uniform(*bounds))
        if ticket.every:
            ticket.created = ago(ticket.every * ticket.back - rng.uniform(0, 0.3))
        if ticket.status not in ("Backlog", "Ready", "Cancelled"):
            spent = rng.uniform(0.4, 3.0) if ticket.model == "haiku" else rng.uniform(1.0, 9.0)
            ticket.cost = round(spent, 2)
            ticket.minutes = round(rng.uniform(4, 55), 1)
        if ticket.status in ("In review", "Validated", "Done") and ticket.repository:
            ticket.pull_request = (
                f"https://github.com/{ticket.repository}/pull/{rng.randint(20, 480)}"
            )
        ticket.edited = ticket.created + timedelta(days=rng.uniform(0.02, 1.5))
        if ticket.status == "Done":
            ticket.closed = min(ticket.created + timedelta(days=rng.uniform(0.2, 4)), ago(0.05))
            if ticket.every:
                ticket.closed = min(ticket.created + timedelta(hours=rng.uniform(1, 6)), ago(0.05))
            ticket.edited = ticket.closed
        if ticket.edited > NOW:
            ticket.edited = NOW - timedelta(minutes=rng.randint(2, 50))
        if ticket.status in ("Backlog", "Ready", "Cancelled"):
            ticket.edited = ticket.created
    return found


def board(root: Path, rng: random.Random, tickets: list[Ticket]) -> None:
    """The board in Markdown files: projects, agents, tickets, comments and recurrences."""
    folders = {
        name: root / name for name in ("tickets", "projects", "agents", "schedules", "comments")
    }
    for folder in folders.values():
        folder.mkdir(parents=True)
    (root / "context.md").write_text(
        "We are a small agency. Write plainly, in the language of the ticket, and say what you "
        "could not check.\n\nPull requests are small and say why. Nothing is merged on a red build.\n",
        encoding="utf-8",
    )
    for key, (name, icon, repository, about) in PROJECTS.items():
        front: dict[str, Any] = {"id": ident("project", key), "created": stamp(ago(60))}
        if icon:
            front["icon"] = icon
        if repository:
            front["Repository"] = repository
        write_page(
            folders["projects"],
            name,
            front,
            f"{about}\n\n## Conventions\n\n{sentence_list(TASKS[:3])}",
        )
    for key, (name, model, role) in AGENTS.items():
        write_page(
            folders["agents"],
            name,
            {"id": ident("agent", key), "Model": model, "created": stamp(ago(45))},
            role,
        )
    for number, ticket in enumerate(tickets):
        front: dict[str, Any] = {
            "id": ticket.id,
            "created": stamp(ticket.created),
            "edited": stamp(ticket.edited),
            "Status": ticket.status,
            "Project": [ident("project", ticket.project)],
            "Type": ticket.kind,
            "Priority": rng.choice([10, 25, 40, 50, 60, 75, 90, 95]),
            "Model": ticket.model,
        }
        if ticket.subtype:
            front["Sous-type"] = ticket.subtype
        if ticket.cost is not None:
            front["Cost"] = ticket.cost
            front["Duration"] = ticket.minutes
        if ticket.pull_request:
            front["Pull Request"] = ticket.pull_request
        if number % 7 == 3:
            front["Agent"] = [ident("agent", rng.choice(list(AGENTS)))]
        if ticket.status == "In progress":
            front["Runner"] = "ponos@devbox"
            front["Progress"] = f"Editing {rng.choice(FILES[ticket.project])}"
        if ticket.status in ("Blocked", "Failed"):
            front["Blocage"] = ticket.flag
        if ticket.status == "Ready" and number % 3 == 0:
            front["Scheduled"] = stamp(ago(-0.2))
        if ticket.title == "Dark mode for the statistics page":
            front["Waiting for credit"] = True
        size = ("short", "medium", "long", "medium")[number % 4]
        body = "" if ticket.flag == "ticket.empty" else brief(rng, ticket.title, size)
        write_page(folders["tickets"], ticket.title, front, body)
        said = report_of(rng, ticket)
        if said:
            comment = {
                "id": ident("comment", ticket.title),
                "at": stamp(ticket.edited),
                "by": REPORT_AUTHOR,
                "discussion": ident("comment", ticket.title),
            }
            (folders["comments"] / f"{ticket.id}.md").write_text(
                files.render(comment, said), encoding="utf-8"
            )
    for name, project, cadence, at, weekday, active, kind, subtype, model, text in SCHEDULES:
        front = {
            "id": ident("schedule", name),
            "created": stamp(ago(50)),
            "Cadence": cadence,
            "At": at,
            "Active": active,
            "Type": kind,
            "Model": model,
            "Priority": 50,
            "Project": [ident("project", project)],
        }
        if weekday:
            front["Day"] = weekday
        if subtype:
            front["Sous-type"] = subtype
        # Next from the rule itself, and the last one an occurrence before it.
        local = NOW.astimezone().replace(tzinfo=None)
        following = schedules.next_occurrence(cadence, at, weekday, after=local)
        assert following is not None
        front["Next"] = following.astimezone().isoformat(timespec="minutes")
        gap = {"Hourly": 1 / 24, "Daily": 1, "Weekly": 7, "Monthly": 30}[cadence]
        front["Last"] = ago(gap * rng.uniform(0.2, 0.9)).astimezone().isoformat(timespec="minutes")
        born = [t for t in tickets if t.flag == "recurring" and t.title.startswith(name)]
        if born:
            front["Last ticket"] = [born[-1].id]
        write_page(folders["schedules"], name, front, text)


def report_of(rng: random.Random, ticket: Ticket) -> str:
    """What Ponos wrote on the ticket when it stopped, or when it handed the work over."""
    if ticket.status in ("Blocked", "Failed") and ticket.flag in STOPS:
        category, why, ask, options = STOPS[ticket.flag]
        lines = [
            f"🙋 Stuck — branch `ticket/{files.slug(ticket.title)[:30]}` ready",
            f"{category}: {why}",
        ]
        if ask:
            lines.append(ask)
        if options:
            lines.append(options)
        if ticket.flag == "access.sudo":
            lines.append("`sudo systemctl enable --now brevo-webhook`")
        return "\n".join(lines)
    if ticket.status in ("In review", "Validated", "Done") and ticket.pull_request:
        lines = [
            f"✅ To review — PR #{ticket.pull_request.rsplit('/', 1)[-1]} · {rng.randint(1, 6)} commits"
            f" · {round(ticket.minutes or 0)} minutes",
            rng.choice(SUMMARIES),
            ticket.pull_request,
        ]
        if ticket.status == "In review":
            lines += [f"To check: {text}" for text in rng.sample(CAVEATS, rng.choice([0, 1, 2, 2]))]
        return "\n".join(lines)
    if ticket.status == "In review":
        return "✅ To review\nThe text is on the page, ready to read.\nTo check: the tone of the second paragraph"
    return ""


def runs_of(rng: random.Random, tickets: list[Ticket]) -> None:
    """The sessions each ticket went through, as the journal and the history will tell them."""
    for ticket in tickets:
        if ticket.status in ("Backlog", "Ready", "Cancelled"):
            continue
        end = ticket.closed or ticket.edited
        attempts = 2 if ticket.status == "Done" and rng.random() < 0.25 else 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            minutes = (ticket.minutes or 10) / attempts
            finish = end if last else end - timedelta(hours=rng.uniform(2, 20))
            status = {
                "Done": "done",
                "In review": "done",
                "Validated": "done",
                "Blocked": "blocked",
                "Failed": "failed",
                "In progress": "",
            }[ticket.status]
            code = ticket.flag if ticket.status in ("Blocked", "Failed") else ""
            if not last:
                status, code = "blocked", rng.choice(PAST_STOPS)
            ticket.runs.append(
                {
                    "start": finish - timedelta(minutes=minutes),
                    "end": finish if status else None,
                    "status": status,
                    "code": code,
                    "cost": round((ticket.cost or 1.0) / attempts, 3),
                    "steps": rng.randint(5, 12),
                }
            )
        if ticket.status == "In progress":
            ticket.runs[-1]["start"] = NOW - timedelta(minutes=rng.randint(6, 14))
            ticket.runs[-1]["end"] = None


def history_of(rng: random.Random, tickets: list[Ticket]) -> None:
    """The runner's history: one line per session, and one per closing, with what it cost."""
    from ponos import state

    for ticket in tickets:
        name = PROJECTS[ticket.project][0]
        for run in ticket.runs:
            if not run["status"]:
                continue
            line: dict[str, Any] = {
                "at": stamp(run["end"]),
                "ticket": ticket.title,
                "id": ticket.id,
                "status": run["status"],
                "project": name,
                "seconds": round((run["end"] - run["start"]).total_seconds(), 1),
                "cost_usd": run["cost"],
            }
            if run["code"]:
                line["code"] = run["code"]
                line["reason"] = (
                    STOPS[run["code"]][1] if run["code"] in STOPS else "the session stopped"
                )
            elif ticket.pull_request:
                line["pull_request"] = ticket.pull_request
                line["branch"] = f"ticket/{files.slug(ticket.title)[:30]}"
                line["commits"] = rng.randint(1, 6)
            elif ticket.kind != CODE:
                line["kind"] = "publication" if ticket.kind == PUBLICATION else "document"
            state.record(line)
        if ticket.status == "Done" and ticket.closed:
            closing: dict[str, Any] = {
                "at": stamp(ticket.closed),
                "ticket": ticket.title,
                "id": ticket.id,
                "status": "done",
                "project": name,
            }
            if ticket.pull_request:
                closing.update(kind="delivery", merged=ticket.pull_request)
            state.record(closing)


def journal_of(rng: random.Random, tickets: list[Ticket]) -> None:
    """Each run in the local journal: its steps, dated through the run, and its end."""
    from ponos import db, journal

    for ticket in tickets:
        for run in ticket.runs:
            files_read = FILES[ticket.project]
            opened = journal.Run.start(
                ticket=ticket.id,
                title=ticket.title,
                kind=ticket.kind,
                project=PROJECTS[ticket.project][0],
                session=ident("session", f"{ticket.title}/{run['start'].isoformat()}")[:24],
                model=ticket.model,
                chosen=rng.random() < 0.5,
            )
            opened.event({"type": "system", "subtype": "init", "model": MODELS[ticket.model]})
            opened.event(
                workbench.said("I read the brief and the code it points at, then started.")
            )
            for number in range(run["steps"]):
                path = files_read[number % len(files_read)]
                kind = number % 4
                if kind == 0:
                    opened.event(workbench.tool("Read", {"file_path": path}))
                elif kind == 1:
                    opened.event(
                        workbench.tool(
                            "Grep", {"pattern": rng.choice(["TODO", "export", "def ", "props"])}
                        )
                    )
                elif kind == 2:
                    opened.event(workbench.tool("Edit", {"file_path": path}))
                else:
                    opened.event(workbench.tool("Bash", {"command": COMMANDS[ticket.project]}))
            if run["status"] == "failed":
                opened.event(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {"type": "tool_result", "is_error": True, "content": "Killed"}
                            ]
                        },
                    }
                )
            opened.event(
                workbench.said(f"That is {ticket.title.lower()}, as far as I can take it.")
            )
            opened.event({"type": "result", "total_cost_usd": run["cost"]})
            if run["status"]:
                opened.end(run["status"], run["code"] or ticket.pull_request, run["code"])
            if opened.id is None:
                continue
            start, end = run["start"], run["end"] or NOW
            span = (end - start) / (run["steps"] + 4)
            with db.transaction() as connection:
                connection.execute(
                    "UPDATE runs SET started_at = ?, ended_at = ? WHERE id = ?",
                    (stamp(start), stamp(end) if run["end"] else None, opened.id),
                )
                connection.executemany(
                    "UPDATE steps SET at = ? WHERE run = ? AND position = ?",
                    [
                        (stamp(start + span * position), opened.id, position)
                        for position in range(1, run["steps"] + 5)
                    ],
                )


def checks_of(tickets: list[Ticket]) -> None:
    """What the runner last read of the checks of each pull request in review."""
    import time

    from ponos import state

    buckets = {
        "passed": ["pass", "pass", "skipping"],
        "failed": ["pass", "fail", "pending"],
        "pending": ["pass", "pending"],
    }
    for ticket in tickets:
        verdict = ticket.flag.removeprefix("ci:") if ticket.flag.startswith("ci:") else ""
        if not verdict or not ticket.pull_request or verdict == "none":
            continue
        state.keep_ci(
            ticket.id,
            {
                "url": ticket.pull_request,
                "head": ident("head", ticket.title)[:7],
                "state": verdict,
                "checks": [
                    {
                        "name": name,
                        "bucket": bucket,
                        "link": f"{ticket.pull_request}/checks",
                    }
                    for name, bucket in zip(
                        ("lint", "test", "build"), buckets[verdict], strict=False
                    )
                ],
                "since": time.time(),
                "asked": time.time(),
            },
        )


def bell_of(tickets: list[Ticket]) -> None:
    """The bell: what rang for the tickets that wait on you, and what you have read since."""
    from ponos import db, notifications

    rows: list[tuple[str, Ticket, float, bool]] = []
    waiting = [t for t in tickets if t.status in ("Blocked", "Failed", "In review")]
    for number, ticket in enumerate(waiting):
        if ticket.status == "In review":
            kind = "ci" if ticket.flag == "ci:failed" else "review"
        elif ticket.status == "Failed":
            kind = "failed"
        else:
            kind = notifications.kind_of("blocked", ticket.flag)
        rows.append((kind, ticket, 0.03 + 0.4 * number, number >= 5))
    # Older ones, read: tickets that were answered or merged since.
    for number, ticket in enumerate([t for t in tickets if t.status == "Done"][:8]):
        rows.append(("review", ticket, 2 + 1.7 * number, True))
    with db.transaction() as connection:
        for kind, ticket, days, read in rows:
            at = stamp(ago(days).replace(microsecond=0))
            connection.execute(
                "INSERT INTO notifications (kind, ticket, title, at, read_at) VALUES (?, ?, ?, ?, ?)",
                (kind, ticket.id, ticket.title, at, at if read else ""),
            )


def ideas_of(rng: random.Random, tickets: list[Ticket]) -> None:
    """The ideas deck: batches over the weeks, kept, thrown away or made into tickets."""
    from ponos import db, ideas

    # The tickets an idea became are tickets of the board: the ones not yet taken.
    open_ones = [t.id for t in tickets if t.status in ("Backlog", "Ready")]

    def batch(project: str, rows: list[tuple], days: float, model: str) -> None:
        proposals = [
            {
                "kind": row[0] if project == "" else "ticket",
                "category": row[1] if project == "" else row[0],
                "score": row[2] if project == "" else row[1],
                "title": row[3] if project == "" else row[2],
                "description": row[4] if project == "" else row[3],
                "detail": {
                    "where": "The web app." if project else "The workspace.",
                    "done": ["It works, and a test says so."],
                    "out": ["Anything not named above."],
                    "score_reason": "Worth it for the people who asked.",
                },
            }
            for row in rows
        ]
        number, stored = ideas.record(project, model, round(rng.uniform(0.04, 0.2), 3), proposals)
        moved = stamp(ago(days))
        with db.transaction() as connection:
            connection.execute(
                "UPDATE idea_batches SET created_at = ? WHERE id = ?", (moved, number)
            )
            connection.execute(
                "UPDATE ideas SET created_at = ?, changed_at = ? WHERE batch = ?",
                (moved, moved, number),
            )
        for position, idea in enumerate(stored):
            outcome = position % 5
            if outcome == 3:
                ideas.decide(idea.id, "discarded")
            elif outcome == 4:
                ideas.decide(idea.id, "ticket", ticket=open_ones[idea.id % len(open_ones)])
            elif outcome == 2 and days > 3:
                ideas.decide(idea.id, "kept")

    batch("", GLOBAL_IDEAS[:6], 12, "sonnet")
    batch("", GLOBAL_IDEAS[6:], 2, "sonnet")
    for key, rows in PROJECT_IDEAS.items():
        batch(ident("project", key), rows, 5, "sonnet")
    ideas.written(
        "",
        "Let a client approve a pull request by e-mail",
        "Some clients will never open GitHub.",
        kind="project",
        category="ux",
        author="Salva",
    )
    ideas.written(
        ident("project", "app"),
        "Dark mode",
        "Every review asks for it.\nThe palette is already there.",
        category="ux",
        author="Salva",
    )


def chats_of() -> None:
    """The conversations of the Sessions page, the latest first."""
    from ponos.web import chats

    for number, (title, model, project, days, turns) in enumerate(CHATS):
        moment = ago(days + 0.02 * number)
        messages = []
        for turn, (said, answer) in enumerate(turns):
            at = stamp(moment + timedelta(minutes=turn * 2))
            messages.append({"role": "you", "text": said, "at": at})
            messages.append({"role": "workspace", "text": answer, "at": at})
        chats.save(
            {
                "id": ident("chat", title),
                "title": title,
                "model": model,
                "project": project,
                "claude": ident("claude", title),
                "turns": len(turns),
                "created": stamp(moment),
                "updated": messages[-1]["at"],
                "messages": messages,
            }
        )


def build(here: Path) -> None:
    """Everything: the board, then the local state the console reads beside it."""
    rng = random.Random(SEED)
    tickets = tickets_of(rng)
    board(here / "board", rng, tickets)
    workbench.stage(here, here / "board", token=TOKEN)
    runs_of(rng, tickets)
    history_of(rng, tickets)
    journal_of(rng, tickets)
    checks_of(tickets)
    bell_of(tickets)
    ideas_of(rng, tickets)
    chats_of()
    from ponos import db

    db.close()


def main(argv: list[str]) -> int:
    port = argv[0] if argv else PORT
    here = Path(tempfile.mkdtemp(prefix="ponos-demo-"))
    try:
        build(here)
        print("Ponos demo: a console on made-up data — no Notion, no network, nothing of yours.")
        print(f"  open  http://127.0.0.1:{port}/?token={TOKEN}")
        print(
            f"  dev   cd frontend && npm run dev:demo   (PONOS_ORIGIN=http://127.0.0.1:{port} npm run dev)"
        )
        print("  stop  Ctrl-C — the temporary state is removed\n", flush=True)
        # A child rather than an exec, so that the state is removed when it stops.
        child = subprocess.Popen([sys.executable, "-m", "ponos", "serve", "--port", port])
        signal.signal(signal.SIGTERM, lambda *_: child.terminate())
        try:
            return child.wait()
        except KeyboardInterrupt:
            # Ctrl-C reached the child as well; a signal sent to this process alone did not.
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
            child.wait()
            return 0
    finally:
        shutil.rmtree(here, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
