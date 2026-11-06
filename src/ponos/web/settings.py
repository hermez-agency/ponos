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
from typing import Any

from .. import config as config_module
from .. import local_ci, voice
from ..config import (
    DIGESTS,
    EVENTS,
    IDEAS_SCHEDULES,
    IDEAS_SCOPES,
    MERGE_METHODS,
    UPDATE_CHANNELS,
    WEEKDAYS,
    Config,
)

# The three accounts a session may run on, said as what each of them is.
PROVIDER_OPTIONS = (
    ("cli", "Claude Code CLI — your subscription (claude login)"),
    ("api_key", "Anthropic API key — billed by the token"),
    ("openrouter", "OpenRouter — the key of the OpenRouter section"),
)

# The two ways GitHub is reached, said as what each of them is.
GITHUB_ACCESS_OPTIONS = (
    ("app", "GitHub App — installed on the repositories you pick"),
    ("token", "Access token — a fine-grained token you create"),
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
    # What this machine must have for the switch to be turned on — "docker" —
    # said rather than hidden: the field is drawn greyed, with the reason,
    # while it is missing. See `_unavailable`.
    needs: str = ""

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
        "general",
        "General",
        "The runner itself: its languages, its updates, this console, and the room it takes.",
    ),
    Group(
        "source",
        "Ticket source",
        "Where your tickets live, and how the runner finds its way in your Notion board.",
    ),
    Group(
        "execution",
        "Execution",
        "How tickets are picked up, what a session may do, and when your review is skipped.",
    ),
    Group(
        "models",
        "Models and costs",
        "Who answers the sessions, which model works each ticket, and how much may be spent.",
    ),
    Group(
        "code",
        "Code and repositories",
        "What a Code ticket turns into: a branch, a pull request, and the merge once you "
        "validate it.",
    ),
    Group(
        "communication",
        "Communication",
        "How the runner reaches you, what a ticket shows while it runs, and its answers in "
        "comments.",
    ),
)

# The folded blocks a group may end on. One today: the titles of the databases,
# for a workspace whose rows were not named by `init`. The board's columns,
# statuses and types have no such block: their names are fixed (see
# `config.PROPERTIES`).
FOLDS: dict[str, tuple[str, str]] = {
    "mapping": (
        "Advanced mapping",
        "Only for a workspace whose rows differ from the ones `ponos init` creates: the "
        "titles of its databases.",
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
    """A field per title of `[notion.pages]`.

    Generated from the defaults rather than listed again: a database the runner
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
        for key in config_module.page_titles()
    )


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
                "runner",
                "app_language",
                "choice",
                "Language of the console, by default for all",
                "The language the console opens in on every browser that has not picked its "
                "own above. Not set: the language of the reports, or else the browser's.",
                choices=voice.LANGUAGES,
                options=(("en", "English"), ("fr", "French")),
            ),
            Field(
                "runner",
                "language",
                "choice",
                "Language of the reports",
                "What the runner writes on tickets and sends to your phone, and the language "
                "sessions are asked to answer in. Not set: reports in English, and each "
                "session answers in the ticket's language.",
                choices=voice.LANGUAGES,
                options=(("en", "English"), ("fr", "French")),
            ),
        ),
    ),
    Section(
        key="update",
        group="general",
        title="Updates",
        blurb="The runner can update itself between two checks of the board.",
        fields=(
            Field(
                "runner",
                "auto_update",
                "bool",
                "Update automatically",
                "Installs the newest version as soon as there is one.",
            ),
            Field(
                "runner",
                "update_channel",
                "choice",
                "Follow",
                "Releases are versions that were tested; the branch brings every change as "
                "soon as it lands.",
                choices=UPDATE_CHANNELS,
                options=(
                    ("release", "Releases (vX.Y.Z tags)"),
                    ("main", "Every commit of the installed branch"),
                ),
            ),
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
            Field(
                "web",
                "host",
                "text",
                "Listen address",
                "`127.0.0.1`: this machine only. Any other address needs a token, or an "
                "email and a password, below. Safer still: an ssh tunnel, `ssh -L "
                "8787:127.0.0.1:8787 <this machine>`.",
                after="the console has to be restarted",
            ),
            Field(
                "web",
                "port",
                "int",
                "Port",
                "The console is then at `http://127.0.0.1:<port>`.",
                minimum=1,
                after="the console has to be restarted",
            ),
            Field(
                "web",
                "token",
                "secret",
                "Console token",
                "Empty: one is drawn once and kept in "
                "`~/.local/state/ponos/web/token`. Needed to listen beyond this "
                "machine.",
                after="the console has to be restarted, and this page reopened with the new token",
            ),
            Field(
                "web",
                "url",
                "text",
                "Public address",
                "Where the console is reached from elsewhere, `https://…` behind a proxy "
                "or a tunnel. The Claude connector is this address followed by `/mcp`.",
            ),
            Field(
                "web",
                "email",
                "text",
                "Sign-in email",
                "With a password, the console asks for the two instead of the token. "
                "`PONOS_WEB_EMAIL` wins over it.",
                after="the console has to be restarted",
                placeholder="e.g. you@example.com",
                environment=config_module.WEB_EMAIL_ENV,
            ),
            Field(
                "web",
                "password",
                "secret",
                "Sign-in password",
                "`PONOS_WEB_PASSWORD` wins over it. Changing it signs every browser "
                "out; the token keeps working, for scripts.",
                after="the console has to be restarted",
            ),
        ),
    ),
    # -- source --------------------------------------------------------------
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
                "notion",
                "token",
                "secret",
                "Integration token",
                "The secret starting with `ntn_`, from notion.so/profile/integrations. "
                "Share your workspace page with the integration too: a token alone sees "
                "nothing.",
            ),
            Field(
                "notion",
                "workspace",
                "text",
                "Workspace page",
                "The Notion page that holds the Tickets, Projects, Agents and Context "
                "databases. Paste its URL: only the identifier is kept.",
                placeholder="https://www.notion.so/…",
            ),
            Field(
                "notion",
                "tickets_database",
                "text",
                "Tickets database (without a workspace page)",
                "Only if the workspace page is empty: the tickets database on its own, by "
                "URL or identifier.",
                placeholder="its URL or its identifier",
                advanced=True,
            ),
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
                "goals": ("Goals database", "What a ticket is for, read into its prompt."),
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
                "runner",
                "interval_seconds",
                "int",
                "Check the board every",
                "The delay between two looks for Ready tickets. 10 starts a ticket within "
                "ten seconds; a look that finds nothing costs one request.",
                minimum=1,
                unit="seconds",
                after="`ponos service on` writes it into the systemd timer",
            ),
            Field(
                "runner",
                "max_concurrent",
                "int",
                "Tickets in parallel",
                "How many Claude sessions run at the same time. Each is a full session: 2 "
                "suits a laptop.",
                minimum=1,
            ),
            Field(
                "runner",
                "timeout_minutes",
                "int",
                "Time limit per ticket",
                "Past it, the session is stopped and the ticket fails, with the reason.",
                minimum=1,
                unit="minutes",
            ),
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
            Field(
                "runner",
                "force_validated_code",
                "bool",
                "Code tickets",
                "The pull request is opened, its CI waited for, then merged. A merge GitHub "
                "refuses leaves the ticket in review, with the reason.",
            ),
            Field(
                "runner",
                "force_validated_publication",
                "bool",
                "Publication tickets",
                "What was prepared is published straight away, without waiting for your review.",
            ),
            Field(
                "runner",
                "force_validated_writing",
                "bool",
                "Writing tickets",
                "No effect today: a Writing ticket already ends in Done.",
            ),
            Field(
                "runner",
                "force_validated_external",
                "bool",
                "External action tickets",
                "No effect today: an External action ticket already ends in Done.",
            ),
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
            Field(
                "permissions",
                "allowed",
                "lines",
                "Done without asking",
                "One action per line, in your own words. Cleared: the session asks about "
                "everything that is not in the ticket.",
            ),
            Field(
                "permissions",
                "ask",
                "lines",
                "Always asks you first",
                "One action per line. A session that reaches one stops and asks you.",
            ),
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
                "claude",
                "provider",
                "choice",
                "Provider",
                "Only the CLI keeps Claude in Chrome and the wait for credits. Empty: "
                "OpenRouter when its sessions are routed there, the CLI otherwise.",
                choices=config_module.PROVIDERS,
                options=PROVIDER_OPTIONS,
            ),
            Field(
                "claude",
                "api_key",
                "secret",
                "Anthropic API key",
                "From console.anthropic.com. Used only when the provider is the key; "
                "empty, `ANTHROPIC_API_KEY` from the environment is.",
            ),
            Field(
                "runner",
                "model",
                "text",
                "Default model",
                "`opus`, `sonnet` or `haiku`, for instance. Empty: Claude Code's own default. "
                "A ticket's Model column wins over it.",
                placeholder="Claude Code's own default",
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
                "runner",
                "wait_for_credits",
                "bool",
                "Pause when the subscription limit is reached",
                "On: the ticket waits, ticked Waiting for credit, and starts again when the "
                "usage window resets. Off: every ticket fails until then.",
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
                "openrouter",
                "key",
                "secret",
                "OpenRouter key",
                "Starts with `sk-or-`, from openrouter.ai/keys. On its own it is only handed "
                "to the sessions; nothing about the runner changes.",
            ),
        ),
    ),
    # -- code ----------------------------------------------------------------
    Section(
        key="ideas",
        group="models",
        title="Finding ideas on a schedule",
        blurb=(
            "Ponos proposes ideas without being asked, while the console runs. The button "
            "on the Ideas page keeps working whatever is set here; the same settings are "
            "in its Settings window."
        ),
        fields=(
            Field(
                "runner",
                "ideas_model",
                "text",
                "Model that finds ideas",
                "Ten ideas per batch, in one short session. A light one is enough, "
                "e.g. `haiku`. Empty: Claude Code's own default.",
            ),
            Field(
                "runner",
                "ideas_schedule",
                "choice",
                "How often",
                "Off: only the button finds ideas.",
                choices=IDEAS_SCHEDULES,
                options=(
                    ("off", "Never — only when asked"),
                    ("every_4h", "Every 4 hours"),
                    ("daily", "Every day"),
                    ("weekly", "Every week"),
                    ("hours", "Every N hours"),
                    ("cron", "A cron expression"),
                ),
            ),
            Field(
                "runner",
                "ideas_at",
                "text",
                "At what time",
                "For every day and every week, in this machine's timezone: 09:00.",
                placeholder="09:00",
            ),
            Field(
                "runner",
                "ideas_day",
                "choice",
                "On which day",
                "For every week.",
                choices=WEEKDAYS,
            ),
            Field(
                "runner",
                "ideas_every_hours",
                "int",
                "Every",
                "For “Every N hours”: counted from the last pass.",
                minimum=1,
                unit="hours",
            ),
            Field(
                "runner",
                "ideas_cron",
                "text",
                "Cron expression",
                "Five fields — minute hour day month weekday — with `*`, lists, ranges and "
                "steps: `0 9 * * 1-5` is weekdays at nine.",
                placeholder="0 9 * * 1-5",
            ),
            Field(
                "runner",
                "ideas_scope",
                "choice",
                "Which projects",
                "All of them includes the ones added later. A project's own page can still "
                "turn it off, or on.",
                choices=IDEAS_SCOPES,
                options=(
                    ("all", "All projects"),
                    ("selected", "Selected projects"),
                ),
            ),
            Field(
                "runner",
                "ideas_projects",
                "text",
                "The selected projects",
                "Project ids or names, separated by commas. The Ideas page's window "
                "lists them with check boxes.",
                placeholder="e.g. Website, Newsletter",
            ),
            Field(
                "runner",
                "ideas_workspace",
                "bool",
                "Ideas for the workspace",
                "Ideas that belong to no project, and may propose a project of its own.",
            ),
            Field(
                "runner",
                "ideas_per_batch",
                "int",
                "Ideas per pass and per project",
                "Ten by default, twenty at the most.",
                minimum=1,
                maximum=20,
            ),
            Field(
                "runner",
                "ideas_skip_above",
                "int",
                "Skip a project that has this many new ideas",
                "New ideas nobody has sorted yet. The skip is written in the journal. "
                "0: never skipped.",
                minimum=0,
            ),
            Field(
                "runner",
                "ideas_budget_usd",
                "text",
                "Most a pass may spend",
                "In dollars, read between two projects. Empty: no ceiling.",
                placeholder="e.g. 1.50",
            ),
            Field(
                "runner",
                "ideas_notify",
                "bool",
                "Tell me about new ideas",
                "One message on your channels after a pass that found some.",
            ),
        ),
    ),
    Section(
        key="repositories",
        group="code",
        title="Repositories",
        blurb="Where your git repositories are found — and cloned, when one is missing.",
        fields=(
            Field(
                "runner",
                "workspace_root",
                "path",
                "Repositories folder",
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
        key="github-access",
        group="code",
        title="GitHub access",
        blurb=(
            "How clones, pushes and pull requests reach GitHub: a GitHub App, or a personal "
            "access token. The token itself is pasted in the GitHub tab, which checks it; "
            "it is never kept in this file."
        ),
        fields=(
            Field(
                "github_access",
                "mode",
                "choice",
                "Reach GitHub with",
                "Empty: the App when one is connected and reaches the repository, then the "
                "token, then the `gh` accounts. Choosing one puts it first.",
                choices=config_module.GITHUB_MODES,
                options=GITHUB_ACCESS_OPTIONS,
            ),
            Field(
                "github_access",
                "token",
                "secret",
                "Access token",
                "A fine-grained token with Contents and Pull requests on read and write. "
                "The GitHub tab checks it before keeping it; here it is kept as typed. "
                "Empty, `PONOS_GITHUB_TOKEN` from the environment is used.",
            ),
            Field(
                "github_access",
                "token_item",
                "text",
                "Keep the token in a vault",
                "Instead of `secrets.env`: where your vault holds it, e.g. `pass:ponos/github` "
                "or `keyring:ponos-github`. The token can also come from "
                "`PONOS_GITHUB_TOKEN` in the environment.",
                placeholder="pass:ponos/github",
                advanced=True,
            ),
        ),
    ),
    Section(
        key="branches",
        group="code",
        title="Branches and pull requests",
        blurb="From the branch a ticket starts on to the merge of its pull request.",
        fields=(
            Field(
                "runner",
                "base_branch",
                "text",
                "Base branch",
                "The branch a ticket's branch starts from, e.g. `main`. Empty: the "
                "repository's default branch.",
                placeholder="the repository's default branch",
            ),
            Field(
                "runner",
                "merge_method",
                "choice",
                "Merge a validated pull request as",
                "Applied when you move a ticket to Validated.",
                choices=MERGE_METHODS,
                options=(
                    ("squash", "One commit (squash)"),
                    ("merge", "A merge commit (merge)"),
                    ("rebase", "Commits replayed (rebase)"),
                ),
            ),
        ),
    ),
    Section(
        key="local_ci",
        group="code",
        title="Local CI before pull request",
        blurb="Run the project's CI on this machine, in Docker, before the pull request is "
        "opened: a red one goes back to the same session to be fixed. The CI on GitHub still "
        "runs, and stays the check that counts.",
        fields=(
            Field(
                "runner",
                "local_ci",
                "bool",
                "Local CI before pull request",
                "Once the session has committed, the command the project declares in its "
                "Settings tab runs — or its GitHub workflows, through `act` — and the session "
                "fixes what fails before anything is pushed. A project can turn it on or off "
                "for itself. Off: nothing changes.",
                needs="docker",
            ),
        ),
    ),
    Section(
        key="self_review",
        group="code",
        title="Self-review before pull request",
        blurb="A short session reads the branch's diff against the ticket before the push, and "
        "the ticket's session is picked up once on what it finds blocking.",
        fields=(
            Field(
                "runner",
                "self_review",
                "bool",
                "Self-review before pull request",
                "Once the session has committed, a session in plan mode reads the diff against "
                "the ticket's done criterion and the project's CLAUDE.md. What it finds blocking "
                "goes back to the ticket's session once; then the pull request opens and says "
                "what was fixed and what was left. Its cost is added to the ticket's. A project "
                "can turn it on or off for itself.",
            ),
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
            Field(
                "notify",
                "events",
                "events",
                "Send a message when a ticket is",
                "Blocked: it asks you a question. Done: its work waits for your review. "
                "Failed: there is a log to read.",
                choices=EVENTS,
                options=(("blocked", "Blocked"), ("failed", "Failed"), ("done", "Done")),
            ),
            Field(
                "notify",
                "desktop",
                "bool",
                "Notify on this computer's screen",
                "A desktop notification when a ticket finishes.",
            ),
            Field(
                "notify",
                "digest",
                "choice",
                "Send a digest",
                "The period's delivered tickets, cost, merge rate, stops and tickets waiting "
                "for you, in one message on Telegram or Slack. No Claude session, no cost.",
                choices=DIGESTS,
                options=(("off", "Never"), ("daily", "Every day"), ("weekly", "Every week")),
            ),
        ),
    ),
    Section(
        key="telegram",
        group="communication",
        title="Telegram",
        blurb="A bot that writes to you, and reads what you answer.",
        fields=(
            Field(
                "notify.telegram",
                "token",
                "secret",
                "Telegram bot token",
                "From @BotFather (/newbot). `ponos notify --pair` then finds the chat ID.",
            ),
            Field(
                "notify.telegram",
                "chat",
                "text",
                "Telegram chat ID",
                "Only this chat is read: anybody can write to a bot.",
                placeholder="found by `ponos notify --pair`",
            ),
        ),
    ),
    Section(
        key="slack",
        group="communication",
        title="Slack",
        blurb="A bot in a channel of yours, which writes there and reads the thread.",
        fields=(
            Field(
                "notify.slack",
                "token",
                "secret",
                "Slack bot token",
                "The `xoxb-…` one. Scopes: `chat:write`, and `channels:history` "
                "(`groups:history`, `im:history`) to read your replies.",
            ),
            Field(
                "notify.slack",
                "channel",
                "text",
                "Slack channel ID",
                "In Slack, ··· → View channel details, at the bottom. Then `/invite "
                "@your-bot` in the channel — the step everyone forgets.",
                placeholder="e.g. C0123456789",
            ),
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
            Field(
                "notion",
                "mention",
                "text",
                "Word that asks for an answer",
                "Write it in a ticket's comment — `@claude what is blocking?` — and the "
                "runner answers in the thread instead of working. The integration's own "
                "name works too.",
            ),
            Field(
                "runner",
                "unblock",
                "bool",
                "Look again at blocked tickets",
                "A session reads why each blocked ticket stopped and whether that still "
                "holds. Only a ticket whose cause is gone goes back to ready; the reason "
                "is written on it either way. It costs a session per ticket.",
            ),
        ),
    ),
)

FIELDS: dict[str, Field] = {entry.name: entry for section in SECTIONS for entry in section.fields}


def _table(raw: dict[str, Any], table: str) -> dict[str, Any]:
    """One `[a.b]` table of the parsed file, or an empty one."""
    node: object = raw
    for part in table.split("."):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


# The four switches of the validation card are one key of the file, the list
# `runner.force_validated`: the page keeps drawing one switch per type, and these
# two read and write the list from them. A file that still has the old booleans
# is read as they say (see `config._runner`) and loses them on its first save.
FORCED = "force_validated_"


def _forced(raw: dict[str, Any], kind: str) -> bool | None:
    """Is this type in the file's list — or, for an older file, its own boolean; None if unsaid."""
    table = _table(raw, "runner")
    if isinstance(table.get("force_validated"), list):
        return kind in [str(item).strip().lower() for item in table["force_validated"]]
    old = table.get(f"{FORCED}{kind}")
    return old if isinstance(old, bool) else None


def _forced_changes(
    config: Config, raw: dict[str, Any], given: dict[str, object]
) -> list[tuple[str, str, object]]:
    """The one list the switches make, and the old booleans that go.

    What a switch left alone says is what the runner does today, so touching
    one never turns another on or off.
    """
    now = {kind: config.runner.forces_validation(kind) for kind in config_module.TYPES}
    for kind, value in given.items():
        now[kind] = bool(value)
    held = _table(raw, "runner")
    present = [
        ("runner", f"{FORCED}{kind}", None)
        for kind in config_module.TYPES
        if f"{FORCED}{kind}" in held
    ]
    chosen = [kind for kind in config_module.TYPES if now[kind]]
    return [*present, ("runner", "force_validated", chosen)]


def _fallback(config: Config, entry: Field) -> object:
    """What the runner uses when the file says nothing about this key.

    Read off the loaded configuration rather than written down again, so the
    placeholder cannot drift from the default it claims to show.
    """
    if entry.name == "claude.provider":
        # What the sessions run on today, which a file that names none still has.
        from .. import provider

        return provider.chosen(config)
    if entry.table == "notion.pages":
        return config_module.page_titles()[entry.key]
    holder = {
        "notion": config.notion,
        "runner": config.runner,
        "notify": config.notify,
        "web": config.web,
        "openrouter": config.openrouter,
        "speech": config.speech,
        "browser": config.browser,
        "claude": config.claude,
        "permissions": config.permissions,
        "github_access": config.github_access,
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


def _unavailable(entry: Field, docker: local_ci.Docker) -> str:
    """Why a field cannot be turned on here, or "" when it can."""
    return unavailable_for(entry.needs, docker)


def unavailable_for(needs: str, docker: local_ci.Docker) -> str:
    """Why what needs `needs` cannot be turned on here — also said by a project's own settings."""
    if needs == "docker" and not docker.available:
        return (
            "Docker is installed, but its daemon does not answer: start it to turn this on."
            if docker.installed
            else "Docker is not installed on this machine: this cannot be turned on without it."
        )
    return ""


def describe(config: Config) -> dict[str, Any]:
    """Every setting, as the console draws it. No secret leaves in here."""
    raw = config_module.read_raw(config.path)
    stored = config_module.read_secrets(config_module.secrets_path(config.path))
    docker = local_ci.docker()
    sections = []
    for section in SECTIONS:
        drawn: dict[str, Any] = {
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
            if entry.key.startswith(FORCED):
                stated = _forced(raw, entry.key.removeprefix(FORCED))
            if entry.kind == "secret":
                # Never the file's: what `secrets.env` holds is what was stated.
                stated = stored.get(config_module.SECRETS[(entry.table, entry.key)])
            shown: dict[str, Any] = {
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
                "unavailable": _unavailable(entry, docker),
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
                shown["value"] = (
                    [str(item) for item in stated] if isinstance(stated, list) else None
                )
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
        "docker": {"available": docker.available, "installed": docker.installed},
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


def folder(typed: str) -> dict[str, Any]:
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


def _pairs(raw: dict[str, Any], table: str, offered: object) -> list[tuple[str, str, object]]:
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


def save(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
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
    forced: dict[str, object] = {}
    for name, value in (offered or {}).items():
        entry = FIELDS.get(str(name))
        if entry is None:
            raise ValueError(f"no such setting: {name}")
        given = _value(entry, value)
        if given is True and (why := _unavailable(entry, local_ci.docker())):
            raise ValueError(f"{name}: {why}")
        touched.append(entry)
        if entry.key.startswith(FORCED):
            forced[entry.key.removeprefix(FORCED)] = given
            continue
        changes.append((entry.table, entry.key, given))
        # The key it replaces goes with it: one line in the file says it, not two
        # that might disagree. See `LEGACY`.
        for old, new in LEGACY.items():
            if new == entry.name:
                table, _, key = old.rpartition(".")
                changes.append((table, key, None))

    raw = config_module.read_raw(config.path)
    if forced:
        changes += _forced_changes(config, raw, forced)
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
