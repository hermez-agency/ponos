"""The configuration file, described well enough for a browser to draw it.

`config.toml` is the single source of truth and stays a file you can open in an
editor. What this module adds is a *description* of it — one entry per key, with
the label, the sentence of help and the type — so the console can offer the same
settings without a second idea of what a setting is.

Three rules hold the whole thing together.

- **The file's own words, not the loader's.** A field shows what the file says;
  the value the runner would use when the file says nothing is shown beside it,
  greyed, as a placeholder. That is the difference between "you chose thirty
  minutes" and "nobody said, so thirty minutes it is" — and it is why clearing a
  field *removes the line* rather than writing an empty one.
- **A secret is never sent to the browser.** A token goes out as "set, ending in
  …f3a2" and comes back only when you type a new one. Clearing one is a gesture
  of its own, so that an empty field can keep meaning "leave it alone". Nor is
  it written to `config.toml`: `config.edit` puts it in `secrets.env`.
- **Nothing the browser says is trusted.** Every value is checked here against
  the same rules the loader applies — the floors, the three merge methods, the
  three events — and the file itself is loaded before the save is allowed to
  stand. See `config.edit`.

Adding a setting to `config.py` and not here is caught by the test suite: a key
the console cannot reach is a key that quietly stops existing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import config as config_module
from .. import models, subtypes, voice
from ..config import CONFIDENCES, EVENTS, MERGE_METHODS, UPDATE_CHANNELS, Config
from ..store import CONFLICTS, MODES

# What Claude Code accepts, and what each of them means for a runner nobody is
# watching. `bypassPermissions` is the working default: a session that stops to
# ask permission at three in the morning is a session that times out.
PERMISSION_MODES = ("bypassPermissions", "acceptEdits", "default", "plan")

# The same four, said as what they let a session do. The file's own word stays
# in brackets: it is what somebody reading `config.toml` will find there.
PERMISSION_OPTIONS = (
    ("bypassPermissions", "Everything, without asking (bypassPermissions)"),
    ("acceptEdits", "Edit files, no commands (acceptEdits)"),
    ("default", "Ask each time (default)"),
    ("plan", "Read only (plan)"),
)

# The three accounts a session may run on, said as what each of them is.
PROVIDER_OPTIONS = (
    ("cli", "Claude Code CLI — your subscription (claude login)"),
    ("api_key", "Anthropic API key — billed by the token"),
    ("openrouter", "OpenRouter — the key of the OpenRouter section"),
)

# How a code ticket's sub-type moves the level its type starts it at.
SHIFT_OPTIONS = (
    ("lower", "One level lower"),
    ("same", "Same as Code"),
    ("higher", "One level higher"),
)

# The four levels a model is chosen among, said as what they are for.
LEVEL_OPTIONS = (
    ("light", "Light work"),
    ("standard", "Standard work"),
    ("heavy", "Heavy work"),
    ("heaviest", "Heaviest work"),
)


@dataclass(frozen=True)
class Field:
    """One key of one table, and everything the console needs to draw it."""

    table: str
    key: str
    kind: str  # text · secret · path · bool · int · choice · events · lines
    label: str
    help: str = ""
    choices: tuple[str, ...] = ()
    minimum: int = 0
    # Zero is "no ceiling", which is what almost every number here wants: a
    # timeout or an interval is bounded by what you meant, not by the loader.
    maximum: int = 0
    # What has to happen for a change to count. Most of it is read again on the
    # next run and needs nothing; the exceptions say so rather than looking like
    # they worked.
    after: str = ""
    # A value of `choices` and the words it is shown in. The file keeps saying
    # `squash`; the page says what squash does to your history.
    options: tuple[tuple[str, str], ...] = ()
    # Folded under "advanced settings" until asked for. Not less true, only
    # less often needed: a field somebody setting up their first board has to
    # read past is a field that hides the three that matter.
    advanced: bool = False
    # What a number counts — "seconds", "minutes" — drawn beside the box rather
    # than in brackets after the label, where it was read as part of the name.
    unit: str = ""
    # What an empty box says when the runner has no default to show: an
    # example of what goes there, rather than "not set" about everything.
    placeholder: str = ""
    # A variable of the environment that wins over the file, for the page to
    # say so when it is set. A secret's own variable is `config.SECRETS`'.
    environment: str = ""
    # A cell of the model table rather than a line of its own: `level` is the
    # model a level runs on, `type` the level a type of ticket starts at,
    # `subtype` how a code ticket's sub-type moves that start, and `short` the
    # word heading its row or its column. See `Section.layout`.
    grid: str = ""
    short: str = ""

    @property
    def name(self) -> str:
        return f"{self.table}.{self.key}"


@dataclass(frozen=True)
class Section:
    """One card of a group: a few keys that answer the same question."""

    key: str
    title: str
    blurb: str
    fields: tuple[Field, ...] = ()
    # The sections that are not lists of known keys: `[projects]` and
    # `[github]` are mappings you add rows to, and the console draws them as
    # such. The name of the table is the name of the list `describe` sends.
    pairs: str = ""
    # The page this card is on — one of `GROUPS`.
    group: str = ""
    # The folded block it sits in, if any — one of `FOLDS`. A card there is
    # only opened by somebody who came looking for it.
    fold: str = ""
    # How the card is drawn when a column of fields would not say it: `grid`
    # is the model table, levels down the side and types across.
    layout: str = ""


@dataclass(frozen=True)
class Group:
    """One page of the settings, and the question it answers."""

    key: str
    title: str
    blurb: str


# Six pages rather than one per table of the file. The file is organised the way
# the loader reads it; the page the way somebody looks for a setting — "where do
# my tickets come from", "which model", "how do I hear about it". A field keeps
# its key wherever it is drawn: the group is the page's idea, the table is the
# file's, and `config.toml` did not move for any of this.
GROUPS: tuple[Group, ...] = (
    Group(
        "general", "General",
        "The runner itself: its languages, its updates, this console, and the room it takes.",
    ),
    Group(
        "source", "Ticket source",
        "Where your tickets live, and how the runner finds its way in your Notion board.",
    ),
    Group(
        "execution", "Execution",
        "How tickets are picked up, what a session may do, and when your review is skipped.",
    ),
    Group(
        "models", "Models and costs",
        "Who answers the sessions, which model works each ticket, and how much may be spent.",
    ),
    Group(
        "code", "Code and repositories",
        "What a Code ticket turns into: a branch, a pull request, and the merge once you "
        "validate it.",
    ),
    Group(
        "communication", "Communication",
        "How the runner reaches you, what a ticket shows while it runs, and its answers in "
        "comments.",
    ),
)

# The folded blocks a group may end on. One today: the names a board that was not
# built by `init` may spell differently — forty keys almost nobody changes, which
# used to be three pages of their own at the same rank as the token.
FOLDS: dict[str, tuple[str, str]] = {
    "mapping": (
        "Advanced mapping",
        "Only for a board whose names differ from the ones `ponos init` creates: its "
        "columns, its properties, its databases and its types.",
    ),
}

# Keys the file still reads but the page no longer draws, and the field that
# says the same thing now. Saving that field removes the old line, so a file
# moves to the new key the first time somebody touches it — and one that is
# never touched keeps working as it did. See `save`.
LEGACY: dict[str, str] = {
    # `runner.notify` came first and said "one desktop notification per ticket";
    # `notify.desktop` falls back on it, and is the one the page shows.
    "runner.notify": "notify.desktop",
}


def _naming(
    table: str, words: dict[str, tuple[str, str]], advanced: bool = False
) -> tuple[Field, ...]:
    """A field per key of one of the four naming tables.

    Generated from the defaults rather than listed again: a property the runner
    learns to read is a field the console offers the same day — under its key,
    until somebody gives it a label of its own here.
    """
    return tuple(
        Field(
            table=f"notion.{table}",
            key=key,
            kind="text",
            label=words.get(key, (key.replace("_", " "), ""))[0],
            help=words.get(key, ("", ""))[1],
            advanced=advanced,
        )
        for key in config_module.defaults(table)
    )


_MODEL = "e.g. `sonnet`"

# Within a group, the order is the order of need: the card somebody setting up
# a board fills in first, then the ones they come back to. Within a card, the
# same — and what is rarely touched is folded under its advanced settings.
SECTIONS: tuple[Section, ...] = (
    # -- general -------------------------------------------------------------
    Section(
        key="languages",
        group="general",
        title="Languages",
        blurb="What the runner writes in, and what this console opens in: the language "
        "picked in a browser comes first, the default is for every browser that has not "
        "picked one.",
        fields=(
            Field(
                "runner", "app_language", "choice", "Language of the console, by default for all",
                "The language the console opens in on every browser that has not picked its "
                "own above. Not set: the language of the reports, or else the browser's.",
                choices=voice.LANGUAGES,
                options=(("en", "English"), ("fr", "French")),
            ),
            Field(
                "runner", "language", "choice", "Language of the reports",
                "What the runner writes on tickets and sends to your phone, and the language "
                "sessions are asked to answer in. Not set: reports in English, and each "
                "session answers in the ticket's language.",
                choices=voice.LANGUAGES,
                options=(("en", "English"), ("fr", "French")),
            ),
        ),
    ),
    Section(
        key="test",
        group="general",
        title="Test mode",
        blurb="Try a configuration out without the runner touching anything.",
        fields=(
            Field(
                "runner", "dry_run", "bool", "Test mode (changes nothing)",
                "The runner says what it would do and does none of it: no branch, no commit, "
                "no write to the board. Useful while you set things up.",
            ),
        ),
    ),
    Section(
        key="update",
        group="general",
        title="Updates",
        blurb="The runner can update itself between two checks of the board.",
        fields=(
            Field("runner", "auto_update", "bool", "Update automatically",
                  "Installs the newest version as soon as there is one."),
            Field("runner", "update_channel", "choice", "Follow",
                  "Releases are versions that were tested; the branch brings every change as "
                  "soon as it lands.",
                  choices=UPDATE_CHANNELS,
                  options=(
                      ("release", "Releases (vX.Y.Z tags)"),
                      ("main", "Every commit of the installed branch"),
                  )),
            Field("runner", "update_interval_seconds", "int", "Look for an update every",
                  "3600 is an hour. 60 at the least.",
                  minimum=60,
                  unit="seconds",
                  advanced=True),
        ),
    ),
    Section(
        key="web",
        group="general",
        title="Web console access",
        blurb=(
            "The server behind this page. It can run code on this machine as you, so it "
            "only listens to this machine unless you set a token or a sign-in."
        ),
        fields=(
            Field("web", "host", "text", "Listen address",
                  "`127.0.0.1`: this machine only. Any other address needs a token, or an "
                  "email and a password, below. Safer still: an ssh tunnel, `ssh -L "
                  "8787:127.0.0.1:8787 <this machine>`.",
                  after="the console has to be restarted"),
            Field("web", "port", "int", "Port",
                  "The console is then at `http://127.0.0.1:<port>`.",
                  minimum=1,
                  after="the console has to be restarted"),
            Field("web", "token", "secret", "Console token",
                  "Empty: one is drawn once and kept in "
                  "`~/.local/state/ponos/web/token`. Needed to listen beyond this "
                  "machine.",
                  after="the console has to be restarted, and this page reopened with the new token"),
            Field("web", "url", "text", "Public address",
                  "Where the console is reached from elsewhere, `https://…` behind a proxy "
                  "or a tunnel. The Claude connector is this address followed by `/mcp`."),
            Field("web", "email", "text", "Sign-in email",
                  "With a password, the console asks for the two instead of the token. "
                  "`PONOS_WEB_EMAIL` wins over it.",
                  after="the console has to be restarted",
                  placeholder="e.g. you@example.com",
                  environment=config_module.WEB_EMAIL_ENV),
            Field("web", "password", "secret", "Sign-in password",
                  "`PONOS_WEB_PASSWORD` wins over it. Changing it signs every browser "
                  "out; the token keeps working, for scripts.",
                  after="the console has to be restarted"),
            Field("web", "send_after_transcription", "bool", "Send a dictated message right away",
                  "Off: the transcription waits in the field, to be read over first. "
                  "Dictation needs the OpenRouter key."),
            Field("web", "poll_seconds", "int", "Refresh the board every",
                  "Only while this page is open. 5 at the least.",
                  minimum=5,
                  unit="seconds",
                  advanced=True),
            Field("web", "chat_timeout_minutes", "int", "Time limit per discussion reply",
                  "For the discussion with the workspace, in this console.",
                  minimum=1,
                  unit="minutes",
                  advanced=True),
            Field("web", "attachment_max_mb", "int", "Largest attached file",
                  "Per file sent in the discussion. A larger one is refused, with the reason.",
                  minimum=1,
                  unit="MB",
                  advanced=True),
            Field("web", "attachment_days", "int", "Keep attached files",
                  "Copies of what you sent in the discussion, deleted after this or with "
                  "“new conversation”.",
                  minimum=1,
                  unit="days",
                  advanced=True),
        ),
    ),
    Section(
        key="logs",
        group="general",
        title="Logs and clean-up",
        blurb="How long what the sessions leave behind stays on this machine.",
        fields=(
            Field(
                "runner", "log_retention_days", "int", "Keep session logs",
                "How long each session's log stays on this machine. 0 keeps them forever.",
                unit="days",
            ),
            Field(
                "runner", "clean_done_worktrees", "bool", "Clean up after done tickets",
                "Once a day, delete the working copies of tickets done for as many days as "
                "the logs are kept. A blocked or in-review ticket keeps its own.",
            ),
            Field(
                "runner", "stale_worktree_days", "int", "Drop forgotten working copies after",
                "A working copy untouched for this many days is deleted, whatever its ticket, "
                "unless the ticket is in progress or the copy holds work that is not pushed. "
                "0 turns it off.",
                minimum=0,
                unit="days",
            ),
            Field(
                "runner", "worktree_exclude", "text", "Leave out of working copies",
                "Comma-separated folders (docs/media, for instance) that new working copies are "
                "made without, to spare the disk. A ticket that needs one runs "
                "git sparse-checkout disable.",
            ),
        ),
    ),
    # -- source --------------------------------------------------------------
    Section(
        key="storage",
        group="source",
        title="Where the board lives",
        blurb=(
            "Where your tickets live: in Notion (the default), as Markdown files on this "
            "machine, or in both, kept in sync."
        ),
        fields=(
            Field(
                "storage", "mode", "choice", "Board kept in",
                "Markdown files need no Notion token and no network. Both writes to the two "
                "and reconciles them.",
                choices=MODES,
                options=(
                    ("notion", "Notion"),
                    ("markdown", "Markdown files"),
                    ("both", "Both, kept in sync"),
                ),
                after="the console has to be restarted",
            ),
            Field(
                "storage", "path", "path", "Markdown folder",
                "The folder holding `tickets/`, `projects/`, `agents/`, `schedules/` and "
                "`context.md`. You can put it under git.",
                after="the console has to be restarted",
            ),
            Field(
                "storage", "conflict", "choice", "When both sides changed",
                "A page edited in Notion and in the files since the last sync: the most "
                "recent edit wins, the other is kept in the sync journal.",
                choices=CONFLICTS,
                options=(("newest", "Keep the most recent"),),
                advanced=True,
            ),
            Field(
                "storage", "on_every_pass", "bool", "Sync before every check of the board",
                "Only for Both. Off: the two only sync when you run `ponos sync`.",
                advanced=True,
            ),
        ),
    ),
    Section(
        key="notion",
        group="source",
        title="Notion",
        blurb=(
            "The integration that reads and writes your board. `ponos init <page-url>` "
            "fills this in for you."
        ),
        fields=(
            Field(
                "notion", "token", "secret", "Integration token",
                "The secret starting with `ntn_`, from notion.so/profile/integrations. "
                "Share your workspace page with the integration too: a token alone sees "
                "nothing.",
            ),
            Field(
                "notion", "workspace", "text", "Workspace page",
                "The Notion page that holds the Tickets, Projects, Agents and Context "
                "databases. Paste its URL: only the identifier is kept.",
                placeholder="https://www.notion.so/…",
            ),
            Field(
                "notion", "tickets_database", "text", "Tickets database (without a workspace page)",
                "Only if the workspace page is empty: the tickets database on its own, by "
                "URL or identifier.",
                placeholder="its URL or its identifier",
                advanced=True,
            ),
        ),
    ),
    Section(
        key="status",
        group="source",
        fold="mapping",
        title="Names of the board's columns",
        blurb=(
            "Change these only if your board's columns are named differently. Leaving "
            "Blocked empty while renaming Failed means one column for both."
        ),
        fields=_naming(
            "status",
            {
                "ready": ("Ready", "The tickets the runner picks up."),
                "running": ("In progress", "Where a ticket goes while it is worked on."),
                "review": ("In review", "Work done, waiting for your review."),
                "validated": ("Validated", "You accepted it: the runner merges, or publishes."),
                "done": ("Done", "Finished and closed."),
                "failed": ("Failed", "Something broke; a log says what."),
                "blocked": ("Blocked", "The runner asked you a question and is waiting."),
                "cancelled": ("Cancelled", "Given up on: never run, counted neither done nor open."),
            },
        )
        + (
            Field(
                "notion.status", "draft", "text", "Draft",
                "Optional: the option your board already has for tickets still being "
                "written. Never picked up. Empty: a draft has no status.",
            ),
        ),
    ),
    Section(
        key="properties",
        group="source",
        fold="mapping",
        title="Names of the ticket properties",
        blurb=(
            "Change these only if your Notion properties are named differently. An optional "
            "one may be missing: what it would hold is simply not written."
        ),
        fields=_naming(
            "properties",
            {
                "status": ("Status", "Required."),
                "project": ("Project", "Relation to the Projects database."),
                "agent": ("Machine", "Written by the runner: which machine took the ticket."),
                "pull_request": ("Pull request", "Written by the runner when one is opened."),
                "session": ("Session", "Written by the runner: the link that reopens the session."),
                "model": ("Model", "This ticket's model, over the default one."),
                "priority": ("Priority", "Which Ready ticket goes first."),
                "cost": ("Cost", "Written by the runner, in dollars."),
                "duration": ("Duration", "Written by the runner, in minutes."),
                "progress": ("Progress", "Written by the runner: what the session is doing."),
                "due": ("Scheduled for", "A date here holds the ticket until then."),
                "waiting": ("Waiting for credit", "Ticked while the subscription limit is reached."),
                "role": ("Agent", "Relation to the Agents database: who handles the ticket."),
                "type": ("Type", "Code, Writing, External action or Publication; empty, it is guessed."),
                "block": ("Block cause", "Written by the runner: why a stopped ticket stopped, as a code."),
                "ci": ("CI", "Written by the runner: the state of the pull request's checks while it is in review."),
                "subtype": ("Sub-type", "Bug, Feature, Amélioration… on a code ticket; empty, it is deduced."),
                "on": ("Prompt on status change", "A prompt run at every change of the ticket's status; empty, nothing runs."),
                "cadence": ("Schedule: cadence", "Hourly, Daily, Weekly or Monthly."),
                "at": ("Schedule: time", "The hour, written 09:00."),
                "day": ("Schedule: day", "Monday… or 1 to 31."),
                "active": ("Schedule: active", "Unticked: paused, nothing deleted."),
                "next_run": ("Schedule: next run", "Written by the runner."),
                "last_run": ("Schedule: last run", "Written by the runner."),
                "last_ticket": (
                    "Schedule: last ticket",
                    "Written by the runner: what the last occurrence created.",
                ),
            },
        ),
    ),
    Section(
        key="pages",
        group="source",
        fold="mapping",
        title="Names of the Notion databases",
        blurb=(
            "The titles the runner looks for under your workspace page. Only Tickets is "
            "required; the others change nothing by their absence."
        ),
        fields=_naming(
            "pages",
            {
                "tickets": ("Tickets database", "Required."),
                "projects": ("Projects database", "Where a ticket's repository is found."),
                "agents": ("Agents database", "The roles a ticket can be handled by."),
                "context": ("Context page", "Who the work is for, read by every session."),
                "schedules": ("Schedules database", "Recurring tickets; absent, nothing recurs."),
            },
        ),
    ),
    Section(
        key="type_names",
        group="source",
        fold="mapping",
        title="Names of the ticket types",
        blurb="The four types, as your Type column spells them.",
        fields=_naming(
            "types",
            {
                "code": ("Name of the Code type", "As written in your Type column."),
                "writing": ("Name of the Writing type", "As written in your Type column."),
                "external": (
                    "Name of the External action type",
                    "As written in your Type column.",
                ),
                "publication": (
                    "Name of the Publication type",
                    "As written in your Type column.",
                ),
            },
        ),
    ),
    # -- execution -----------------------------------------------------------
    Section(
        key="pace",
        group="execution",
        title="Pace",
        blurb=(
            "How often the board is checked, how many tickets run at once, and how long "
            "each one may take."
        ),
        fields=(
            Field(
                "runner", "interval_seconds", "int", "Check the board every",
                "The delay between two looks for Ready tickets. 10 starts a ticket within "
                "ten seconds; a look that finds nothing costs one request.",
                minimum=1,
                unit="seconds",
                after="`ponos enable` writes it into the systemd timer",
            ),
            Field(
                "runner", "max_concurrent", "int", "Tickets in parallel",
                "How many Claude sessions run at the same time. Each is a full session: 2 "
                "suits a laptop.",
                minimum=1,
            ),
            Field(
                "runner", "max_concurrent_per_project", "int", "Tickets in parallel per project",
                "How many of those sessions may work on the same project at once. Pull requests "
                "written side by side on one repository touch the same files and conflict when "
                "the first one lands: 2 keeps that rare.",
                minimum=1,
            ),
            Field(
                "runner", "timeout_minutes", "int", "Time limit per ticket",
                "Past it, the session is stopped and the ticket fails, with the reason.",
                minimum=1,
                unit="minutes",
            ),
            Field(
                "runner", "min_free_memory_mb", "int", "Memory to keep free",
                "No session is started while less memory than this is available; the ticket "
                "waits in Ready. 0 turns the guard off.",
                minimum=0,
                unit="MB",
            ),
            Field(
                "runner", "min_free_disk_mb", "int", "Disk space to keep free",
                "Under it, old working copies are tidied first; if the space is still short, "
                "no ticket is started and it waits in Ready. 0 turns the guard off.",
                minimum=0,
                unit="MB",
            ),
            Field(
                "runner", "relaunch_delay_seconds", "int", "Wait before resuming a killed session",
                "A session killed from outside is resumed once after this delay, if the network "
                "answers.",
                minimum=0,
                unit="seconds",
            ),
        ),
    ),
    Section(
        key="permissions",
        group="execution",
        title="Permissions",
        blurb="Nobody is there to approve: what a session may do on its own.",
        fields=(
            Field(
                "runner", "permission_mode", "choice", "What a session may do without asking",
                "Nobody is there to approve: anything but “Everything” leaves a session "
                "waiting until it times out.",
                choices=PERMISSION_MODES,
                options=PERMISSION_OPTIONS,
            ),
            Field("runner", "reply_permission_mode", "choice", "What an answer may do",
                  "“Read only” is the guardrail: an answer that quietly changed a repository "
                  "is the last thing anybody expects.",
                  choices=PERMISSION_MODES,
                  options=PERMISSION_OPTIONS),
        ),
    ),
    Section(
        key="types",
        group="execution",
        title="Types and classification",
        blurb=(
            "A ticket's type decides how it is worked. An empty type is guessed before the "
            "ticket runs; a type you chose is never changed."
        ),
        fields=(
            Field("runner", "classify", "bool", "Guess the type when it is empty",
                  "A short session reads the ticket, writes the type in its column and the "
                  "reason in a comment. Off: a ticket without a type is worked as before, "
                  "from what its project holds."),
            Field("runner", "classify_confidence", "choice", "Least confidence to act on a guess",
                  "Below it, the ticket is blocked and asks you for its type. A doubt "
                  "between Code and another type takes the other one; any other doubt "
                  "involving Publication or External action blocks.",
                  choices=CONFIDENCES,
                  options=(("low", "Low"), ("medium", "Medium"), ("high", "High"))),
        ),
    ),
    Section(
        key="validation",
        group="execution",
        title="Automatic validation",
        blurb=(
            "Skip your review for some types of ticket: once the session succeeds, the "
            "runner validates it itself and says so. A failed or blocked ticket never is."
        ),
        fields=(
            Field("runner", "force_validated_code", "bool", "Code tickets",
                  "The pull request is opened, its CI waited for, then merged. A merge GitHub "
                  "refuses leaves the ticket in review, with the reason."),
            Field("runner", "force_validated_publication", "bool", "Publication tickets",
                  "What was prepared is published straight away, without waiting for your "
                  "review."),
            Field("runner", "force_validated_writing", "bool", "Writing tickets",
                  "No effect today: a Writing ticket already ends in Done."),
            Field("runner", "force_validated_external", "bool", "External action tickets",
                  "No effect today: an External action ticket already ends in Done."),
        ),
    ),
    Section(
        key="prompts",
        group="execution",
        title="Custom instructions",
        blurb=(
            "The instructions each session is given, each replaceable by a file of your "
            "own. Empty: the built-in ones."
        ),
        fields=(
            Field("runner", "prompt_file", "path", "Instructions for a ticket with a repository",
                  "The path to a Markdown or text file."),
            Field("runner", "document_prompt_file", "path", "Instructions for a ticket without one",
                  "The path to a Markdown or text file."),
            Field("runner", "delivery_prompt_file", "path", "Instructions for publishing a validated ticket",
                  "The path to a Markdown or text file."),
        ),
    ),
    Section(
        key="schedules",
        group="execution",
        title="Recurring tickets",
        blurb=(
            "Tickets created on their own from the Schedules database — hourly, daily, "
            "weekly or monthly. After the machine was off, one occurrence is created, never "
            "every one it missed."
        ),
        fields=(
            Field("runner", "schedule", "bool", "Create recurring tickets",
                  "Off: the Schedules database is ignored, and none of its rows is touched."),
        ),
    ),
    Section(
        key="autonomy",
        group="execution",
        title="What a session may do alone",
        blurb=(
            "Read by every session. What it does without asking, and what always waits for "
            "your word — so it stops asking the same question twice. One rule per line."
        ),
        fields=(
            Field("permissions", "allowed", "lines", "Done without asking",
                  "One action per line, in your own words. Cleared: the session asks about "
                  "everything that is not in the ticket."),
            Field("permissions", "ask", "lines", "Always asks you first",
                  "One action per line. A session that reaches one stops and asks you."),
        ),
    ),
    # -- models --------------------------------------------------------------
    Section(
        key="claude",
        group="models",
        title="Provider and default model",
        blurb=(
            "Who answers the sessions: Claude Code signed in as you, an Anthropic key, or "
            "OpenRouter. The first connection asks, and checks the answer works."
        ),
        fields=(
            Field(
                "claude", "provider", "choice", "Provider",
                "Only the CLI keeps Claude in Chrome and the wait for credits. Empty: "
                "OpenRouter when its sessions are routed there, the CLI otherwise.",
                choices=config_module.PROVIDERS,
                options=PROVIDER_OPTIONS,
            ),
            Field(
                "claude", "api_key", "secret", "Anthropic API key",
                "From console.anthropic.com. Used only when the provider is the key; "
                "empty, `ANTHROPIC_API_KEY` from the environment is.",
            ),
            Field(
                "runner", "model", "text", "Default model",
                "`opus`, `sonnet` or `haiku`, for instance. Empty: Claude Code's own default. "
                "A ticket's Model column wins over it.",
                placeholder="Claude Code's own default",
            ),
            Field("web", "chat_model", "text", "Model of a new session",
                  "`opus`, `sonnet`, `haiku`, `fable`, or an OpenRouter model such as "
                  "`openai/gpt-5`. Empty: the model above.",
                  placeholder="The model above"),
        ),
    ),
    Section(
        key="auto_model",
        group="models",
        layout="grid",
        title="Automatic model choice",
        blurb=(
            "Each type of ticket starts at a level, its size and wording move it, and each "
            "level runs on its model. A Model on the ticket or its agent is always kept."
        ),
        fields=(
            Field(
                "runner", "auto_model", "bool", "Choose the model when it is empty",
                "From the ticket's type, size, wording and priority: a small change runs on "
                "a light model, an audit on a heavy one. The model and the reason go in a "
                "comment. Off: the default model for every ticket. A Model on the ticket or "
                "its agent is always kept.",
            ),
            Field(
                "runner", "use_fable", "bool", "Use Claude Fable",
                "Off by default: Fable costs far more than Opus. Off, every session runs on "
                "Opus instead — the heaviest level, an escalation, a Model written on a ticket.",
            ),
            Field(
                "runner", "auto_model_escalate", "bool", "One level up after a failure",
                "A ticket whose chosen model failed runs one level higher the next time, "
                "once, and says so.",
            ),
            *(
                Field("runner", f"auto_model_{level}", "text", label, help,
                      grid="level", short=short, placeholder=_MODEL)
                for level, short, label, help in (
                    ("light", "Light work", "Model for light work", "A text to remove, a label "
                     "to rename. Empty: the nearest level below or above."),
                    ("standard", "Standard work", "Model for standard work", "A bug or a "
                     "feature in one pull request."),
                    ("heavy", "Heavy work", "Model for heavy work", "An audit, a refactor, a "
                     "migration, a hard bug."),
                    ("heaviest", "Heaviest work", "Model for the heaviest work", "A long "
                     "request full of heavy work."),
                )
            ),
            *(
                Field("runner", f"auto_model_{kind}", "choice", label,
                      "The level it starts from, before its size and its wording move it.",
                      choices=models.LEVELS, options=LEVEL_OPTIONS, grid="type", short=short)
                for kind, short, label in (
                    ("code", "Code", "Code tickets start at"),
                    ("writing", "Writing", "Writing tickets start at"),
                    ("external", "External action", "External action tickets start at"),
                    ("publication", "Publication", "Publication tickets start at"),
                )
            ),
            # One per sub-type, read off the table: a sub-type added there is a
            # column here without a line more.
            *(
                Field("runner", f"auto_model_subtype_{subtype.key}", "choice",
                      f"{subtype.label} tickets start",
                      "Where a code ticket of this sub-type starts, from the level of Code.",
                      choices=tuple(subtypes.SHIFTS), options=SHIFT_OPTIONS, grid="subtype",
                      short=subtype.label)
                for subtype in subtypes.SUBTYPES
            ),
        ),
    ),
    Section(
        key="credits",
        group="models",
        title="Credits",
        blurb="How much of your subscription the runner may spend, and what it does at the limit.",
        fields=(
            Field(
                "runner", "wait_for_credits", "bool", "Pause when the subscription limit is reached",
                "On: the ticket waits, ticked Waiting for credit, and starts again when the "
                "usage window resets. Off: every ticket fails until then.",
            ),
            Field(
                "runner", "credit_reserve_percent", "int", "Share kept for your own use",
                "At 5, no new ticket starts past 95 % of the session or weekly limit, so you "
                "still have Claude for yourself. Running tickets finish. From 0 (use it all) "
                "to 50.",
                minimum=0,
                maximum=config_module.MOST_RESERVED,
                unit="%",
            ),
        ),
    ),
    Section(
        key="openrouter",
        group="models",
        title="OpenRouter (other models)",
        blurb=(
            "One key for every other AI provider — a GPT, images, transcription. Sessions "
            "get it as `OPENROUTER_API_KEY`, and this console dictates with it."
        ),
        fields=(
            Field(
                "openrouter", "key", "secret", "OpenRouter key",
                "Starts with `sk-or-`, from openrouter.ai/keys. On its own it is only handed "
                "to the sessions; nothing about the runner changes.",
            ),
            Field(
                "openrouter", "route_sessions", "bool", "Run the sessions through OpenRouter",
                "Claude Code then talks to OpenRouter instead of Anthropic: models are named "
                "the OpenRouter way (`openai/gpt-5`), the bill is OpenRouter's rather than "
                "your subscription's, and Claude in Chrome no longer loads.",
            ),
            Field(
                "openrouter", "base_url", "text", "API address",
                "Only for a gateway of your own that speaks the same API.",
                advanced=True,
            ),
        ),
    ),
    Section(
        key="specialised",
        group="models",
        title="Specialised models",
        blurb="The short jobs that are not a ticket's own work, each on a model of its own.",
        fields=(
            Field("runner", "resolve_model", "text", "Model that resolves conflicts",
                  "Empty: the model the ticket was worked with.",
                  placeholder="the ticket's own model"),
            Field("runner", "classify_model", "text", "Model that guesses the type",
                  "A light one is enough, e.g. `haiku`. Empty: Claude Code's own default."),
            Field("runner", "ideas_model", "text", "Model that finds ideas",
                  "Ten ideas per batch, in one short session. A light one is enough, "
                  "e.g. `haiku`. Empty: Claude Code's own default."),
            Field(
                "openrouter", "transcription_model", "text", "Dictation model",
                "Turns a message dictated in the console into text.",
            ),
        ),
    ),
    # -- code ----------------------------------------------------------------
    Section(
        key="repositories",
        group="code",
        title="Repositories",
        blurb="Where your git repositories are found — and cloned, when one is missing.",
        fields=(
            Field(
                "runner", "workspace_root", "path", "Repositories folder",
                "Where your git repositories are, e.g. `~/workspace`. A project's repository "
                "is looked for here — and cloned here when it is missing.",
            ),
        ),
    ),
    Section(
        key="projects",
        group="code",
        title="Project folders",
        blurb=(
            "Which folder on this machine holds a Notion project's repository. Only needed "
            "when it is not found on its own: a `path` or `github` property on the project "
            "page does the same, for every machine."
        ),
        pairs="projects",
    ),
    Section(
        key="github",
        group="code",
        title="GitHub accounts",
        blurb=(
            "Which `gh` account works for each GitHub owner, when this machine uses several "
            "— yours and a client's. Left, the owner as in the repository's URL; right, the "
            "account as `gh auth status` lists it. Sign each one in once with `gh auth "
            "login`. An owner not listed here is worked under the active account."
        ),
        pairs="github",
    ),
    Section(
        key="branches",
        group="code",
        title="Branches and pull requests",
        blurb="From the branch a ticket starts on to the merge of its pull request.",
        fields=(
            Field("runner", "base_branch", "text", "Base branch",
                  "The branch a ticket's branch starts from, e.g. `main`. Empty: the "
                  "repository's default branch.",
                  placeholder="the repository's default branch"),
            Field("runner", "push", "bool", "Push the branch",
                  "Send the ticket's branch to the remote once it has commits. Off: the work "
                  "stays on this machine."),
            Field("runner", "open_pull_request", "bool", "Open a pull request",
                  "Once the session succeeds, on GitHub — needs `gh` installed and signed in. "
                  "Opening one merges nothing."),
            Field("runner", "merge_method", "choice", "Merge a validated pull request as",
                  "Applied when you move a ticket to Validated.",
                  choices=MERGE_METHODS,
                  options=(
                      ("squash", "One commit (squash)"),
                      ("merge", "A merge commit (merge)"),
                      ("rebase", "Commits replayed (rebase)"),
                  )),
            Field("runner", "branch_prefix", "text", "Branch name prefix",
                  "`ticket/` gives `ticket/1a2b3c4d-remove-the-header`.",
                  advanced=True),
            Field("runner", "fetch", "bool", "Fetch the remote before branching",
                  "So a ticket starts from the latest code rather than last week's.",
                  advanced=True),
            Field("runner", "rebase", "bool", "Rebase on the base branch before pushing",
                  "The base branch moves while a session works: the branch is replayed on top "
                  "of it before the push, and a merge refused for being behind is retried once.",
                  advanced=True),
            Field("runner", "checks_timeout_minutes", "int", "Wait for CI before merging",
                  "After a resolved conflict, or with automatic validation. 0 does not wait — "
                  "GitHub still refuses a merge a required check has not passed.",
                  unit="minutes",
                  advanced=True),
        ),
    ),
    Section(
        key="conflicts",
        group="code",
        title="Conflicts",
        blurb="When a validated pull request no longer merges cleanly.",
        fields=(
            Field("runner", "resolve_conflicts", "bool", "Resolve merge conflicts automatically",
                  "When a validated pull request conflicts, a session resolves it, runs the "
                  "project's checks, then merges. A conflict that needs a decision blocks the "
                  "ticket with the question."),
            Field("runner", "resolve_conflicts_except", "text", "Projects whose conflicts are left to you",
                  "Project names, separated by commas. A conflict there blocks the ticket "
                  "instead of being resolved.",
                  placeholder="e.g. Website, Newsletter"),
        ),
    ),
    Section(
        key="worktrees",
        group="code",
        title="Worktrees",
        blurb="Each ticket works in a copy of its repository of its own, thrown away after.",
        fields=(
            Field("runner", "keep_worktree_on_failure", "bool", "Keep a failed ticket's work folder",
                  "Its worktree stays as the session left it, for you to look at. "
                  "`ponos clean --force` removes them."),
        ),
    ),
    # -- communication -------------------------------------------------------
    Section(
        key="notify",
        group="communication",
        title="Notifications",
        blurb=(
            "How the runner reaches you: this computer's screen, Telegram or Slack. A reply "
            "on Telegram or Slack becomes a comment on the ticket — which is what restarts "
            "a blocked one."
        ),
        fields=(
            Field("notify", "events", "events", "Send a message when a ticket is",
                  "Blocked: it asks you a question. Done: its work waits for your review. "
                  "Failed: there is a log to read.",
                  choices=EVENTS,
                  options=(("blocked", "Blocked"), ("failed", "Failed"), ("done", "Done"))),
            Field("notify", "desktop", "bool", "Notify on this computer's screen",
                  "A desktop notification when a ticket finishes."),
            Field("notify", "replies", "bool", "Read your replies",
                  "Your replies on Telegram or Slack become comments on the ticket. Off: "
                  "messages are sent, replies are ignored."),
        ),
    ),
    Section(
        key="telegram",
        group="communication",
        title="Telegram",
        blurb="A bot that writes to you, and reads what you answer.",
        fields=(
            Field("notify.telegram", "token", "secret", "Telegram bot token",
                  "From @BotFather (/newbot). `ponos notify --pair` then finds the "
                  "chat ID."),
            Field("notify.telegram", "chat", "text", "Telegram chat ID",
                  "Only this chat is read: anybody can write to a bot.",
                  placeholder="found by `ponos notify --pair`"),
        ),
    ),
    Section(
        key="slack",
        group="communication",
        title="Slack",
        blurb="A bot in a channel of yours, which writes there and reads the thread.",
        fields=(
            Field("notify.slack", "token", "secret", "Slack bot token",
                  "The `xoxb-…` one. Scopes: `chat:write`, and `channels:history` "
                  "(`groups:history`, `im:history`) to read your replies."),
            Field("notify.slack", "channel", "text", "Slack channel ID",
                  "In Slack, ··· → View channel details, at the bottom. Then `/invite "
                  "@your-bot` in the channel — the step everyone forgets.",
                  placeholder="e.g. C0123456789"),
        ),
    ),
    Section(
        key="live",
        group="communication",
        title="Live progress",
        blurb="What a ticket shows while its session is running, and where the session goes after.",
        fields=(
            Field("runner", "progress", "bool", "Show progress on the ticket",
                  "The session's steps are written on the ticket's page, the latest one in "
                  "its Progress column."),
            Field("runner", "attach_sessions", "bool", "File sessions under their project",
                  "A finished session is moved under the project's folder, so `claude "
                  "--resume` there finds it. Off: it can only be resumed by its ID."),
            Field("runner", "progress_interval_seconds", "int", "Update progress every",
                  "10 reads as live. 5 at the least, so two tickets at once do not spend "
                  "Notion's rate limit on it.",
                  minimum=5,
                  unit="seconds",
                  advanced=True),
            Field("runner", "session_host", "text", "Machine the sessions run on (ssh)",
                  "Only when the runner lives on a server, e.g. `me@server.example.com`: the "
                  "ticket's Session link then opens the session over ssh.",
                  placeholder="this machine",
                  advanced=True),
        ),
    ),
    Section(
        key="on",
        group="execution",
        title="Prompt on status change",
        blurb=(
            "A ticket whose « On » column holds a prompt runs it at every change of its "
            "status — yours or the runner's — with the old status, the new one and the ticket."
        ),
        fields=(
            Field("runner", "on", "bool", "Run the « On » prompt of a ticket",
                  "A ticket whose « On » column holds a prompt runs it, in a session of its own, "
                  "at every change of its status. Off: no prompt runs."),
            Field("runner", "on_interval_seconds", "int", "Look for moved statuses every",
                  "10 at the least; one request per hundred tickets that carry a prompt.",
                  minimum=10,
                  unit="seconds",
                  advanced=True),
            Field("runner", "on_max_depth", "int", "Generations of tickets created in a chain",
                  "A ticket created by a prompt runs its own prompt only this many generations "
                  "down. 0 stops the chain at once.",
                  minimum=0,
                  advanced=True),
            Field("runner", "on_timeout_minutes", "int", "Time limit per prompt",
                  "The session is stopped after this long.",
                  minimum=1,
                  unit="minutes",
                  advanced=True),
            Field("runner", "on_permission_mode", "choice", "What a prompt may do",
                  "Empty: the same as a ticket's session, since a prompt is there to act.",
                  choices=("", *PERMISSION_MODES),
                  options=(("", "Like a ticket"), *PERMISSION_OPTIONS),
                  advanced=True),
        ),
    ),
    Section(
        key="replies",
        group="communication",
        title="Answers in comments",
        blurb=(
            "Reply under one of the runner's reports, or name it, and it answers in the "
            "thread — having read the ticket and the repository, and changing nothing."
        ),
        fields=(
            Field("runner", "reply", "bool", "Answer comments",
                  "Off: comments get no answer. Answering a blocked ticket's question still "
                  "starts it again."),
            Field(
                "notion", "mention", "text", "Word that asks for an answer",
                "Write it in a ticket's comment — `@claude what is blocking?` — and the "
                "runner answers in the thread instead of working. The integration's own "
                "name works too.",
            ),
            Field("runner", "reply_interval_seconds", "int", "Look for new comments every",
                  "10 at the least.",
                  minimum=10,
                  unit="seconds",
                  advanced=True),
            Field("runner", "reply_scan", "int", "Tickets looked at each time",
                  "One request each; the next ones are looked at the time after.",
                  minimum=1,
                  advanced=True),
            Field("runner", "unblock", "bool", "Look again at blocked tickets",
                  "A session reads why each blocked ticket stopped and whether that still "
                  "holds. Only a ticket whose cause is gone goes back to ready; the reason "
                  "is written on it either way. It costs a session per ticket."),
            Field("runner", "unblock_interval_seconds", "int", "Look at a blocked ticket every",
                  "600 at the least.",
                  minimum=600,
                  unit="seconds",
                  advanced=True),
            Field("runner", "reply_timeout_minutes", "int", "Time limit per answer",
                  "Somebody is waiting for it: keep it short.",
                  minimum=1,
                  unit="minutes",
                  advanced=True),
        ),
    ),
)

FIELDS: dict[str, Field] = {
    entry.name: entry for section in SECTIONS for entry in section.fields
}


def _table(raw: dict, table: str) -> dict:
    """One `[a.b]` table of the parsed file, or an empty one."""
    node: object = raw
    for part in table.split("."):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


def _fallback(config: Config, entry: Field) -> object:
    """What the runner uses when the file says nothing about this key.

    Read off the loaded configuration rather than written down again, so the
    placeholder cannot drift from the default it claims to show.
    """
    if entry.name == "claude.provider":
        # What the sessions run on today, which a file that names none still has.
        from .. import provider

        return provider.chosen(config)
    if entry.table == "notion.status":
        return config_module.defaults("status").get(entry.key, "")
    if entry.table == "notion.properties":
        return config_module.defaults("properties")[entry.key]
    if entry.table == "notion.pages":
        return config_module.defaults("pages")[entry.key]
    if entry.table == "notion.types":
        return config_module.defaults("types")[entry.key]
    if entry.key.startswith("auto_model_subtype_"):
        return config.runner.subtype_shift(entry.key.removeprefix("auto_model_subtype_"))
    holder = {
        "notion": config.notion,
        "runner": config.runner,
        "notify": config.notify,
        "web": config.web,
        "openrouter": config.openrouter,
        "claude": config.claude,
        "permissions": config.permissions,
        "storage": config.storage,
    }.get(entry.table)
    if holder is None:  # a channel table: nothing is defaulted into it
        return ""
    value = getattr(holder, entry.key, "")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _preview(secret: str) -> str:
    """Enough of a token to recognise it by, and not enough to use it.

    The example value `config.example.toml` ships with is no token at all: it
    is where one goes. Saying "set · ends …xxxx" about it told somebody with a
    fresh file that Notion was configured, which `doctor` would then deny.
    """
    secret = secret.strip()
    if not secret or secret == config_module.PLACEHOLDER or "xxxx" in secret:
        return ""
    return f"…{secret[-4:]}" if len(secret) > 8 else "set"


def _from_environment(entry: Field, stored: dict[str, str]) -> str:
    """The variable the runner takes this value from instead of the file, if any.

    Said on the page because a field the environment overrides is a field you
    can retype all day: the runner keeps reading the variable. A secret counts
    only when the variable is what it actually uses — `secrets.env` wins for
    most of them, see `config.secret`.
    """
    if entry.kind == "secret":
        name = config_module.SECRETS[(entry.table, entry.key)]
        if not os.environ.get(name, "").strip():
            return ""
        used = config_module.secret(stored, entry.table, entry.key)
        return name if used == os.environ[name].strip() else ""
    if entry.environment and os.environ.get(entry.environment, "").strip():
        return entry.environment
    return ""


def describe(config: Config) -> dict:
    """Every setting, as the console draws it. No secret leaves in here."""
    raw = config_module.read_raw(config.path)
    stored = config_module.read_secrets(config_module.secrets_path(config.path))
    sections = []
    for section in SECTIONS:
        drawn = {
            "key": section.key,
            "title": section.title,
            "blurb": section.blurb,
            "pairs": section.pairs,
            "group": section.group,
            "fold": section.fold,
            "layout": section.layout,
            "fields": [],
        }
        for entry in section.fields:
            stated = _table(raw, entry.table).get(entry.key)
            if entry.kind == "secret":
                # Never the file's: what `secrets.env` holds is what was stated.
                stated = stored.get(config_module.SECRETS[(entry.table, entry.key)])
            shown: dict = {
                "name": entry.name,
                "kind": entry.kind,
                "label": entry.label,
                "help": entry.help,
                "choices": list(entry.choices),
                "options": dict(entry.options),
                "advanced": entry.advanced,
                "fallback": _fallback(config, entry),
                "after": entry.after,
                "stated": stated is not None,
                "unit": entry.unit,
                "placeholder": entry.placeholder,
                "grid": entry.grid,
                "short": entry.short,
                "environment": _from_environment(entry, stored),
            }
            if entry.kind == "secret":
                # Not `_fallback`: for a secret that is the value itself, and
                # the placeholder would carry out the very thing it exists to
                # keep in. A token has no default worth showing anyway.
                shown["value"] = ""
                shown["fallback"] = ""
                # The one the runner uses, even when the environment gave it.
                shown["preview"] = _preview(config_module.secret(stored, entry.table, entry.key))
                shown["variable"] = config_module.SECRETS[(entry.table, entry.key)]
            elif entry.kind in ("events", "lines"):
                shown["value"] = [str(item) for item in stated] if isinstance(stated, list) else None
            elif entry.kind == "bool":
                shown["value"] = bool(stated) if stated is not None else None
            elif entry.kind == "int":
                shown["value"] = int(stated) if isinstance(stated, int) else None
            else:
                shown["value"] = str(stated) if stated is not None else ""
            drawn["fields"].append(shown)
        sections.append(drawn)

    problem = ""
    try:
        config.require_usable()
    except config_module.ConfigError as error:
        problem = str(error).splitlines()[0]

    return {
        "path": str(config.path),
        "usable": not problem,
        "problem": problem,
        "groups": [
            {"key": group.key, "title": group.title, "blurb": group.blurb} for group in GROUPS
        ],
        "folds": [
            {"key": key, "title": title, "blurb": blurb} for key, (title, blurb) in FOLDS.items()
        ],
        "sections": sections,
        "projects": [
            {"name": name, "value": str(path)}
            for name, path in sorted(_table(raw, "projects").items())
        ],
        "github": [
            {"name": owner, "value": str(account)}
            for owner, account in sorted(_table(raw, "github").items())
        ],
    }


# How many entries a folder is listed with: a picker, not a file manager. A
# folder of node_modules is a folder somebody types the rest of.
MOST_LISTED = 200


def folder(typed: str) -> dict:
    """What is in the folder a path field points at, for the page to pick from.

    A browser's own file picker hands back a file's name and never its path, and
    a path on *this* machine is what the file wants — so the page asks here. Names
    only, never what is in them: it is the list `ls` would give you, from the
    account that already runs every session. Hidden entries stay hidden unless
    what was typed asks for one.
    """
    path = Path(typed.strip() or "~").expanduser()
    if not path.is_dir():
        path = path.parent
    if not path.is_dir():
        path = Path.home()
    try:
        listed = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError as error:
        raise ValueError(f"{path}: {error.strerror or error}") from None
    hidden = Path(typed.strip()).name.startswith(".")
    entries = [
        {"name": item.name, "folder": item.is_dir()}
        for item in listed
        if hidden or not item.name.startswith(".")
    ]
    return {
        "folder": str(path),
        "parent": str(path.parent) if path.parent != path else "",
        "entries": entries[:MOST_LISTED],
        "more": max(0, len(entries) - MOST_LISTED),
    }


def _value(entry: Field, offered: object) -> object:
    """One value from the browser, as the file may hold it — or `None` to unset.

    Everything the loader would silently repair is refused here instead. A floor
    the loader raises quietly is a field that saves, comes back changed and
    tells nobody why.
    """
    if offered is None:
        return None
    if entry.kind == "bool":
        if not isinstance(offered, bool):
            raise ValueError(f"{entry.label}: yes or no")
        return offered
    if entry.kind == "int":
        if isinstance(offered, bool) or not isinstance(offered, (int, str)):
            raise ValueError(f"{entry.label}: a number")
        try:
            number = int(str(offered).strip())
        except ValueError:
            raise ValueError(f"{entry.label}: “{offered}” is not a number") from None
        if number < max(entry.minimum, 0):
            raise ValueError(f"{entry.label}: {entry.minimum} at the least")
        if entry.maximum and number > entry.maximum:
            raise ValueError(f"{entry.label}: {entry.maximum} at the most")
        return number
    if entry.kind == "events":
        if not isinstance(offered, list):
            raise ValueError(f"{entry.label}: a list")
        chosen = [str(item).strip().lower() for item in offered]
        unknown = [name for name in chosen if name not in EVENTS]
        if unknown:
            raise ValueError(f"{entry.label}: no such moment “{unknown[0]}”")
        # An empty list is a real answer — "tell me nothing" — so it is written
        # rather than removed, which would bring the three back.
        return sorted(set(chosen), key=EVENTS.index)
    if entry.kind == "lines":
        if not isinstance(offered, list):
            raise ValueError(f"{entry.label}: a list")
        # An empty list is a real answer — "nothing is allowed alone" — so it is
        # written rather than removed, which would bring the defaults back.
        return [line for item in offered if (line := " ".join(str(item).split()))]
    text = str(offered).strip()
    if entry.kind == "choice":
        if text and text not in entry.choices:
            raise ValueError(f"{entry.label}: one of {', '.join(entry.choices)}")
    # Blank means "say nothing about it", which is how the default comes back.
    return text or None


def _pairs(raw: dict, table: str, offered: object) -> list[tuple[str, str, object]]:
    """One `name = value` table as the browser now has it, against what is there.

    The two the file holds: `[projects]`, a Notion name and a path, and
    `[github]`, an owner and the account it is worked under. Both are mappings
    you add rows to rather than lists of known keys, so both are saved by what
    the browser sends *in full* — a row that is no longer there is a line that
    goes away.
    """
    if not isinstance(offered, list):
        raise ValueError(f"{table}: a list of {{name, value}}")
    wanted: dict[str, str] = {}
    for row in offered:
        if not isinstance(row, dict):
            raise ValueError(f"{table}: a list of {{name, value}}")
        name = str(row.get("name", "")).strip()
        value = str(row.get("value", "")).strip()
        if not name and not value:
            continue  # a row somebody started and left
        if not name:
            raise ValueError(f"a {table} row set to {value} has no name")
        if not value:
            raise ValueError(f"“{name}” maps to nothing — fill it in, or remove the row")
        if name in wanted:
            raise ValueError(f"“{name}” is named twice")
        wanted[name] = value
    changes: list[tuple[str, str, object]] = [
        (table, name, None) for name in _table(raw, table) if name not in wanted
    ]
    changes += [(table, name, value) for name, value in wanted.items()]
    return changes


def save(config: Config, payload: dict) -> dict:
    """Apply what the console sent. Nothing, or all of it — see `config.edit`.

    Only the keys the browser actually names are touched: a field left alone is
    a line the file keeps, comment and all. That is also what makes a secret
    safe to leave blank — blank was never sent.
    """
    offered = payload.get("settings")
    if offered is not None and not isinstance(offered, dict):
        raise ValueError("settings: a table of name → value")

    changes: list[tuple[str, str, object]] = []
    touched: list[Field] = []
    for name, value in (offered or {}).items():
        entry = FIELDS.get(str(name))
        if entry is None:
            raise ValueError(f"no such setting: {name}")
        changes.append((entry.table, entry.key, _value(entry, value)))
        touched.append(entry)
        # The key it replaces goes with it: one line in the file says it, not two
        # that might disagree. See `LEGACY`.
        for old, new in LEGACY.items():
            if new == entry.name:
                table, _, key = old.rpartition(".")
                changes.append((table, key, None))

    raw = config_module.read_raw(config.path)
    for table in ("projects", "github"):
        if table in payload:
            changes += _pairs(raw, table, payload[table])

    if not changes:
        return {"saved": [], "after": []}

    written = config_module.edit(config.path, changes)
    return {
        "saved": written,
        # Said once each, and only for what actually moved: a notice about a
        # restart you do not need is a notice you stop reading.
        "after": sorted(
            {entry.after for entry in touched if entry.after and entry.name in written}
        ),
    }
