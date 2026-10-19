"""Reading and validating ~/.config/ponos/config.toml.

The file is the single source of truth, and a missing value is reported at
install time rather than in the middle of a ticket — for everything but its
secrets. A token or a password is not read from `config.toml`, ever: that file
is one you open in an editor, paste into a ticket, copy into an image or onto a
shared volume, and a secret has no business going wherever it goes. They live in
the environment, or in `secrets.env` beside it — `NAME=value` lines, created
`0600` and written by the console the way it writes everything else (`SECRETS`
says which names). A secret still found in `config.toml` is ignored, moved out
by the next launch (`move_secrets`), and said so on stderr.

Which of the two wins depends on who wrote it last. The console writes
`secrets.env`, and a key somebody has just typed and checked must not lose to
one a compose file was started with weeks ago: the file wins. The console's
sign-in goes the other way round — `PONOS_WEB_EMAIL` and `PONOS_WEB_PASSWORD`
are how a unit file or a container claims a console before anybody arrives, and
the environment wins over the file; that is what makes it worth setting.
"""

from __future__ import annotations

import os
import re
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The two vocabularies of `[storage]`, kept where the interface is declared —
# `store.py` imports nothing from here, so this direction is the safe one.
from . import disk, models, passwords, subtypes, vault
from .store import CONFLICTS, MODES

PLACEHOLDER = "ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Where the console's sign-in may be written instead of in the file.
WEB_EMAIL_ENV = "PONOS_WEB_EMAIL"
WEB_PASSWORD_ENV = "PONOS_WEB_PASSWORD"

# Where a provider's key may come from — the names every tool already reads, so
# a container is given them once.
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"

# Every secret the configuration knows: where `config.toml` used to hold it, and
# the variable that holds it now — in the environment, or in `secrets.env`.
SECRETS: dict[tuple[str, str], str] = {
    ("notion", "token"): "PONOS_NOTION_TOKEN",
    ("web", "token"): "PONOS_WEB_TOKEN",
    ("web", "password"): WEB_PASSWORD_ENV,
    ("notify.telegram", "token"): "PONOS_TELEGRAM_TOKEN",
    ("notify.slack", "token"): "PONOS_SLACK_TOKEN",
    ("claude", "api_key"): ANTHROPIC_KEY_ENV,
    ("openrouter", "key"): OPENROUTER_KEY_ENV,
}

# The ones the environment wins for — see the module's docstring.
_ENVIRONMENT_FIRST = (WEB_PASSWORD_ENV,)

# The language the reports are written in, when the file names none: what a
# container is given once, in a compose file or a Dokploy template, before
# anybody opens the console. The file wins — a language picked in Settings is a
# decision taken later than the deployment.
LANGUAGE_ENV = "PONOS_LANGUAGE"

# Where the secrets file is, when it is not beside the configuration.
SECRETS_PATH_ENV = "PONOS_SECRETS"

# Set by the image (see the Dockerfile): this process runs in a container, where
# there is no systemd, no desktop and no install directory to move — a new
# version is a new image. Read, never guessed from `/.dockerenv`: a machine that
# happens to run its own installation inside a container still has the
# install.sh layout, and is not this case.
CONTAINER_ENV = "PONOS_CONTAINER"


def in_container() -> bool:
    return os.environ.get(CONTAINER_ENV, "").strip().lower() in ("1", "true", "yes")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ponos"


class RealStateRefused(Exception):
    """Ponos runs from a repository, and was not told which state to write."""


def checkout() -> Path | None:
    """The repository these sources run from, when they are not an installation.

    `install.sh` puts them under ~/.local/share/ponos — a clone, so with a
    `.git` — and the image says it is one; a copy has no `.git` at all. What is
    left is a checkout or a worktree, run with `PYTHONPATH=src`.
    """
    here = Path(__file__).resolve().parents[2]
    if in_container() or not (here / ".git").exists():
        return None
    if here.parent == (Path.home() / ".local" / "share" / "ponos").resolve():
        return None
    return here


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "ponos"


def refuse_real_state() -> None:
    """Raise RealStateRefused when a checkout is about to write the real state.

    The real `ponos.db` was once migrated by a branch's code, from a worktree:
    its migrations, not yet rebased, did not match main's, and every run's
    journal stopped on it until it was repaired by hand. A checkout that does
    not set `XDG_STATE_HOME` is refused instead — the tests set it, and so does
    whoever means it. Only where the state is written: a path shown is no harm.
    """
    if os.environ.get("XDG_STATE_HOME"):
        return
    repository = checkout()
    if repository is not None:
        raise RealStateRefused(
            f"ponos runs from the repository {repository}, not from its installation, "
            "and would write the real state in ~/.local/state/ponos — set XDG_STATE_HOME: "
            "XDG_STATE_HOME=$(mktemp -d) for a state of its own, "
            "or XDG_STATE_HOME=~/.local/state to really use the installation's"
        )


def config_path() -> Path:
    override = os.environ.get("PONOS_CONFIG")
    return Path(override) if override else config_dir() / "config.toml"


def secrets_path(config: Path | None = None) -> Path:
    """`secrets.env`, beside the configuration it goes with.

    Beside rather than under the configuration directory: a test, or a second
    installation started with `PONOS_CONFIG`, gets its own secrets with its own
    file, and never reads the real ones.
    """
    override = os.environ.get(SECRETS_PATH_ENV)
    if override:
        return Path(override)
    return (config or config_path()).parent / "secrets.env"


class ConfigError(Exception):
    """Configuration missing, unreadable or incomplete."""


@dataclass
class Notion:
    token: str = ""
    workspace: str = ""
    tickets_database: str = ""
    # How you call it when you want it to answer rather than to work. Its own
    # name, as Notion writes it when you @-mention the integration, is always
    # understood too — this is for the word you would actually type.
    mention: str = ""
    pages: dict[str, str] = field(default_factory=dict)
    properties: dict[str, str] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    # How the board spells the four types of ticket — see kinds.py. Not merged
    # with the defaults, for the same reason as `pages`: `kind_names()` needs to
    # know which ones the file names, to try the other spellings only when it
    # names none.
    types: dict[str, str] = field(default_factory=dict)

    def prop(self, key: str) -> str:
        return self.properties.get(key, _DEFAULT_PROPERTIES[key])

    def kind(self, key: str) -> str:
        """The option a type of ticket is written as on the board."""
        return self.types.get(key, _DEFAULT_TYPES[key])

    def kind_names(self, key: str) -> tuple[str, ...]:
        """Every spelling that option may carry: the configured one, then the others.

        The same rule as `page_aliases`: a name written in the file is the name
        meant, and nothing else is tried past it. A file that says nothing gets
        the English default and the French one — a board built by hand in French
        says “Rédaction”, and reading it as no type at all would have the runner
        classify, again and again, a ticket somebody already typed.
        """
        if key in self.types:
            return (self.types[key],)
        return (_DEFAULT_TYPES[key], *_TYPE_ALIASES.get(key, ()))

    def kind_of(self, value: str) -> str:
        """The type a board option means, or "" for one that is none of the four."""
        wanted = str(value or "").strip().casefold()
        if not wanted:
            return ""
        for key in _DEFAULT_TYPES:
            if wanted in (name.strip().casefold() for name in self.kind_names(key)):
                return key
        return ""

    def page(self, key: str) -> str:
        """The title of the workspace row holding that database or page."""
        return self.pages.get(key, _DEFAULT_PAGES[key])

    def page_aliases(self, key: str) -> tuple[str, ...]:
        """Every title that row may carry: the configured one, then the old ones.

        Only when the configuration does not name it: someone who wrote the
        title down meant that title, and guessing past it would find the wrong
        row on a board that has both.
        """
        if key in self.pages:
            return (self.pages[key],)
        return (_DEFAULT_PAGES[key], *_LEGACY_PAGES.get(key, ()))

    def state(self, key: str) -> str:
        # "blocked" is optional, and only *against a named `failed`*: a file that
        # says where failures go but not where questions go meant one column for
        # both. A file that names neither gets the defaults, which are two —
        # telling "the agent asked you something" from "something broke" is the
        # whole reason the runner distinguishes them.
        if key == "blocked" and "blocked" not in self.status and "failed" in self.status:
            return self.state("failed")
        # "review" reads the same way, against a named `done`: a file that says
        # where a finished ticket goes but not where it waits for its pull
        # request has one column for both, and nothing to watch for a merge. A
        # file that names neither gets the defaults, which are two — the pull
        # request being open and it being merged are not the same day.
        if key == "review" and "review" not in self.status and "done" in self.status:
            return self.state("done")
        # "validated" reads the same way, against a named `review` or `done`: a
        # file that says where a ticket waits to be looked at, or where it goes
        # once it is, and nothing about where you accept it, described a board
        # that ends at the pull request. It falls back on `review`, which is
        # where the ticket already sits, and the runner reads a `validated` that
        # is `review` as "this board has no such gesture". Renaming some other
        # column is not a statement about this one: a file that names only
        # `ready` still gets the default, and the board decides from there.
        if key == "validated" and "validated" not in self.status:
            if "review" in self.status or "done" in self.status:
                return self.state("review")
        # "draft" has no default at all: it names an option the board already
        # has for tickets still being written, and a board without one keeps
        # them with no status, as before. Unnamed, it is "", which no ticket
        # is ever read as — the runner itself never asks for it.
        if key == "draft":
            return self.status.get("draft", "")
        return self.status.get(key, _DEFAULT_STATUS[key])


@dataclass
class Runner:
    workspace_root: Path = Path.home() / "workspace"
    interval_seconds: int = 1800
    max_concurrent: int = 2
    # How many of those places one project may hold: pull requests of one
    # repository written side by side touch the same files, and each one that
    # lands makes the others conflict. See runner.py.
    max_concurrent_per_project: int = 2
    timeout_minutes: int = 30
    # A session killed from outside (SIGKILL, SIGTERM) is carried on once, after
    # this many seconds and only if the network answers. See resources.py.
    relaunch_delay_seconds: int = 15
    # No session is started while less memory than this is available, in MB;
    # zero turns the guard off. Eight sessions with `tsc` and a test suite each
    # is how the kernel ends up killing one of them.
    min_free_memory_mb: int = 2048
    # Same guard for the disk the state directory is on, in MB: below it, a
    # tidy runs before anything is started, and if that does not bring it back
    # the ticket stays in Ready. A full disk fails every ticket at once. See
    # cleanup.py; zero turns the guard off.
    min_free_disk_mb: int = 5120
    # What to do when the subscription's quota is spent: wait for the window to
    # roll over rather than fail every ticket it touches. Off is the old
    # behaviour — an exhausted quota is reported as the session failure it looks
    # like. See credits.py.
    wait_for_credits: bool = True
    # How much of the window to leave alone, as a percentage. The runner starts
    # nothing new past `100 - this`, so there is still a subscription left to
    # open a terminal with — a runner that spends the last of it is a runner you
    # end up turning off. Capped at 50: past that it is not a reserve, it is a
    # decision to halve the machine.
    credit_reserve_percent: int = 5
    model: str = ""
    # The language the runner writes its reports in, and the one it asks a
    # session to answer in. Empty is English, and it is more than that: a file
    # that says nothing leaves each session with the rule its prompt already
    # carries — answer in the language you were written to. See voice.py.
    language: str = ""
    # The language the console opens in — and the one the pages it serves before
    # you are in are written in. Empty follows `language`; both empty leave the
    # browser to say, as it always did. See `interface_language`.
    app_language: str = ""
    permission_mode: str = "bypassPermissions"
    branch_prefix: str = "ticket/"
    base_branch: str = ""
    fetch: bool = True
    push: bool = True
    open_pull_request: bool = True
    # Replay the ticket's branch on top of its base before the pull request is
    # opened, and again when a validated merge is refused for being behind. A
    # board that sends ten tickets at one repository is a base branch that moves
    # under every one of them: without this, the first merge makes the nine
    # others conflict. See execution.py and delivery.py.
    rebase: bool = True
    # Skip the review, one type of ticket at a time: what moving a ticket to
    # validated would set off is done as soon as its session has succeeded —
    # the pull request merged, the publication sent — and the ticket goes to
    # done. Off, all four, which is the board as it always was: nothing leaves
    # this machine for good without somebody having read it. A session that
    # did not succeed is never validated, whatever these say. Writing and
    # external action already end in done, with nothing waiting to be
    # validated — see delivery.py.
    force_validated_code: bool = False
    force_validated_writing: bool = False
    force_validated_external: bool = False
    force_validated_publication: bool = False
    # How a validated pull request is merged. `gh` has to be told which of the
    # three it is, and the runner will not pick for you at the last moment: a
    # board that squashes wants every ticket squashed.
    merge_method: str = "squash"
    # A validated merge that conflicts: replayed all the same, the conflicts
    # resolved by a session, checked, pushed with a lease and merged — see
    # delivery.py. Off, or for a project named in `resolve_conflicts_except`
    # (comma-separated), a conflict blocks the ticket as it always did.
    resolve_conflicts: bool = True
    resolve_conflicts_except: str = ""
    # The model that resolves. Empty: the ticket's own, as its session had it.
    resolve_model: str = ""
    # How long a resolved pull request's CI is waited for before the merge is
    # asked. Zero does not wait: GitHub still refuses a merge a required check
    # has not passed.
    checks_timeout_minutes: int = 20
    keep_worktree_on_failure: bool = True
    attach_sessions: bool = True
    session_host: str = ""
    notify: bool = True
    # The steps of a running session, written into its ticket as they happen.
    progress: bool = True
    progress_interval_seconds: int = 10
    # Answering in the comments: a ticket as somewhere to talk, not only
    # somewhere to ask. See conversation.py for what wakes an answer.
    reply: bool = True
    # A person wrote the comment and a person is waiting for the answer, so a
    # minute is soon enough — and the scan costs one request per page.
    reply_interval_seconds: int = 60
    reply_scan: int = 20
    reply_timeout_minutes: int = 10
    # `plan` is the guardrail, not the prompt: a conversation that quietly
    # edited a repository is the one thing nobody would expect of it.
    reply_permission_mode: str = "plan"
    # The « On » column: a prompt run at every change of a ticket's status — see
    # transitions.py. The board is read at most this often, the prompt may spend
    # `budget.on_usd` per execution, and a ticket born of an execution may
    # itself run its prompt only `on_max_depth` generations down.
    on: bool = True
    on_interval_seconds: int = 30
    on_max_depth: int = 3
    on_timeout_minutes: int = 10
    # Empty: the mode tickets run under, since the prompt is there to act.
    on_permission_mode: str = ""
    # Looking again at what is blocked, and moving back to ready what no longer
    # is — see unblocking.py. Off by default: it spends a session per ticket.
    unblock: bool = False
    unblock_interval_seconds: int = 6 * 3600
    # What comes back on its own: the Schedules database, read in the same pass
    # that reads the board. One line to turn every schedule off at once, without
    # unticking a single row — see schedules.py.
    schedule: bool = True
    auto_update: bool = True
    # What an update follows. "release": the newest `vX.Y.Z` tag, and nothing
    # in between — a commit pushed to `main` is not yet something every
    # installation runs. "main": every commit of the branch installed from, as
    # soon as it lands. See update.py.
    update_channel: str = "release"
    update_interval_seconds: int = 3600
    log_retention_days: int = 14
    # Once a day, the worktrees and scratch directories of tickets done for
    # `log_retention_days` go too — see cleanup.py.
    clean_done_worktrees: bool = True
    # A worktree nobody has touched for this many days goes too, whatever its
    # ticket's status — unless the ticket is in progress, or the worktree holds
    # changes or commits that are nowhere else. Zero turns it off.
    stale_worktree_days: int = 30
    # Paths left out of every worktree (a sparse checkout), for the big media
    # files a ticket almost never touches. A ticket that needs one runs
    # `git sparse-checkout disable`. Empty checks everything out.
    worktree_exclude: str = ""

    dry_run: bool = False
    prompt_file: str = ""
    document_prompt_file: str = ""
    delivery_prompt_file: str = ""
    # Telling a ticket's type when nobody wrote it: a short session, on the
    # lightest model, before anything runs — see kinds.py. Off, a ticket with no
    # Type is run the way the runner always ran it, by what its project holds.
    classify: bool = True
    classify_model: str = "haiku"
    # The least confidence a guess is acted on with. Below it, the ticket is
    # blocked with the question rather than run on a guess.
    classify_confidence: str = "medium"
    # Finding ideas — ten per batch, in one short session — see ideas.py. A
    # light model is enough to propose; it is the person swiping who chooses.
    ideas_model: str = "haiku"
    # Choosing the model of a ticket whose Model is empty, by rules read off the
    # ticket — its type, its size, its words, its priority — rather than giving
    # every one `model`. See models.py. Off, `model` for all of them, as before.
    # A Model written on the ticket, or on its agent, is always taken as written.
    auto_model: bool = True
    # Which model answers each of the four levels…
    auto_model_light: str = "haiku"
    auto_model_standard: str = "sonnet"
    auto_model_heavy: str = "opus"
    auto_model_heaviest: str = "fable"
    # …and the level each type starts from, before its size and its words move it.
    auto_model_code: str = "standard"
    auto_model_writing: str = "light"
    auto_model_external: str = "standard"
    auto_model_publication: str = "standard"
    # …and how a code ticket's sub-type moves that start: `lower`, `same` or
    # `higher`, by sub-type — see subtypes.py. A sub-type the file says nothing
    # about moves it by the table's own default.
    auto_model_subtypes: dict[str, str] = field(default_factory=dict)
    # A ticket chosen for and failed comes back one level up, once.
    auto_model_escalate: bool = True
    # Fable at all. Off, nothing the runner starts runs on it — a level, an
    # escalation, a Model on a ticket or an agent: Opus instead. See models.py.
    use_fable: bool = False

    def allowed(self, model: str) -> str:
        """The model a session is given — Opus for a Fable `use_fable` refuses."""
        return models.allowed(model, self.use_fable)

    def model_grid(self) -> models.Grid:
        """The levels and the types' starting points, as models.py reads them."""
        return models.Grid(
            models={
                level: self.allowed(getattr(self, f"auto_model_{level}"))
                for level in models.LEVELS
            },
            starts={
                kind: getattr(self, f"auto_model_{kind}")
                for kind in ("code", "writing", "external", "publication")
            },
            shifts={key: subtypes.shift(key, self.auto_model_subtypes) for key in subtypes.KEYS},
        )

    def subtype_shift(self, key: str) -> str:
        """How the file has a sub-type move the start: `lower`, `same` or `higher`."""
        return self.auto_model_subtypes.get(key) or subtypes.BY_KEY[key].shift

    def interface_language(self) -> str:
        """The language the console opens in, as the file says it — or nothing.

        `app_language`, and when that says nothing the reports' own: one line is
        enough for somebody who reads French everywhere, and two are there for
        whoever wants their tickets answered in one language and the console in
        another. Empty when neither says anything, and the console then asks the
        browser. Read down to a language by `voice.understood`.
        """
        return self.app_language or self.language

    def forces_validation(self, kind: str) -> bool:
        """Is a ticket of that type validated without waiting for anybody?"""
        return bool(getattr(self, f"force_validated_{kind}", False)) if kind else False

    def resolves_conflicts(self, project: str) -> bool:
        """Is a conflict on that project's pull requests resolved by a session?"""
        left_alone = {
            name.strip().casefold() for name in self.resolve_conflicts_except.split(",")
        }
        return self.resolve_conflicts and project.strip().casefold() not in left_alone


# What an installation may follow when it updates itself — see `Runner`.
UPDATE_CHANNELS = ("release", "main")


# What `gh pr merge` accepts, and the whole of it: anything else is a typo, and
# a typo here would only be discovered by GitHub refusing the one merge you were
# watching.
MERGE_METHODS = ("squash", "merge", "rebase")


# How sure a classification says it is, from the least to the most. Three words
# rather than a number: a model asked for a probability invents a precision it
# does not have, and a threshold of 0.72 would be read as one.
CONFIDENCES = ("low", "medium", "high")


# The most of the subscription a reserve may hold back. Half is already an
# extreme setting — the runner would then stop at 50 % of every window — and
# anything past it describes a runner you meant to switch off instead.
MOST_RESERVED = 50


# The three moments worth a message. `blocked` is the one that matters: it is
# the only one that expects something back from you.
EVENTS = ("blocked", "failed", "done")


@dataclass
class Notify:
    """Where the runner reaches you, and whether it listens for an answer.

    Desktop notifications are the old behaviour and stay the default; a channel
    exists only if its two values are filled in. `replies` is the half that
    makes a notification a question: without it the runner still writes to
    Telegram or Slack, it just never reads what you write back.
    """

    desktop: bool = True
    replies: bool = True
    events: tuple[str, ...] = EVENTS
    telegram: dict[str, str] = field(default_factory=dict)
    slack: dict[str, str] = field(default_factory=dict)

    def wants(self, event: str) -> bool:
        return event in self.events

    @property
    def remote(self) -> bool:
        """Is there anywhere to write to besides this machine's screen?"""
        return bool(
            (self.telegram.get("token") and self.telegram.get("chat"))
            or (self.slack.get("token") and self.slack.get("channel"))
        )


@dataclass
class Web:
    """The console: a board, a command line and a chat, in one page.

    Loopback by default, and that is not a placeholder. Behind this port sits a
    runner that starts Claude Code sessions with `bypassPermissions` — so the
    port is arbitrary code execution on this machine, and anything reachable
    from elsewhere has to be a decision somebody took on purpose. `serve`
    refuses a non-loopback host unless a token is configured; the way to reach
    the console from another machine is an ssh tunnel, not a wider bind.
    """

    host: str = "127.0.0.1"
    port: int = 8787
    token: str = ""
    # The address the console is reached at from elsewhere — `https://ponos.
    # example.com` behind Traefik or a tunnel. What the MCP connector's OAuth
    # addresses are built on, as Leadz builds them on its own: a proxy that
    # does not say it served HTTPS would otherwise have them all in `http://`,
    # and claude.ai refuses those. Empty: read from each request.
    url: str = ""
    # Who opens the console, and what they type. Both set, the page asks for
    # them instead of for the token — which is the difference between a console
    # you open from a bookmark and one you open by pasting a secret. The token
    # is still what a script carries; it just stops being what *you* carry. Both
    # are also read from the environment, see the module's docstring.
    email: str = ""
    password: str = ""
    # How often the console asks Notion what the board looks like — and only
    # while a browser is actually watching. Nobody is watching most of the time,
    # and a poll nobody reads spends the integration's rate limit for nothing.
    poll_seconds: int = 15
    # A chat turn is a Claude session like any other, and wants the same kind of
    # ceiling. Shorter than a ticket's: somebody is sitting in front of it.
    chat_timeout_minutes: int = 20
    # The model a new conversation of the console starts on. Empty: the runner's
    # own default model. Each conversation then keeps the one it was given.
    chat_model: str = ""
    # What a message to the workspace may carry. A file is refused past this
    # size rather than read and then regretted: a phone video is a gigabyte,
    # and the session would read none of it anyway.
    attachment_max_mb: int = 25
    # How long a conversation's files are kept when nobody starts a new one.
    # They are copies of what you dropped on the page, not the originals.
    attachment_days: int = 7
    # Whether a dictated message goes as soon as it is transcribed, rather than
    # waiting in the field to be read over. Off: a transcription is a draft.
    send_after_transcription: bool = False


# Where an OpenRouter key is spent, unless the file names somewhere else. It is
# the only endpoint that key works against, so it is a default rather than a
# question — the line exists for a gateway of your own that speaks the same API.
OPENROUTER_URL = "https://openrouter.ai/api/v1"


@dataclass
class OpenRouter:
    """One key, and every model behind it. See openrouter.py.

    Empty is the whole of the old behaviour: no key, nothing added to a session's
    environment, Claude Code talking to Anthropic as it always did.
    """

    key: str = ""
    base_url: str = OPENROUTER_URL
    # Whether the sessions themselves run on it, rather than the key merely
    # being *available* to the work. Off by default, and deliberately: it
    # changes which company answers the agent, what a model name means, and who
    # bills you. See openrouter.py for what goes with it.
    route_sessions: bool = False
    # What a dictated message is transcribed with, as an OpenRouter slug.
    transcription_model: str = "openai/whisper-1"


# Who answers a session. `cli` is Claude Code signed in as you (`claude login`),
# which is the subscription, Claude in Chrome and the wait for credits. `api_key`
# is an Anthropic key, billed by the token. `openrouter` is the key of
# `[openrouter]`, and the sessions run there when `route_sessions` says so.
PROVIDERS = ("cli", "api_key", "openrouter")


@dataclass
class Claude:
    """Which account the sessions run on. See provider.py.

    `provider` empty is a file written before the key existed, and it reads the
    way that file always worked: OpenRouter when its sessions were routed there,
    the CLI's own sign-in otherwise. Nothing changes until somebody chooses.
    """

    provider: str = ""
    api_key: str = ""


@dataclass
class Budget:
    """What the runner agrees to spend, in dollars. Zero is no limit.

    Two lines, and they stop different things. `daily_usd` is read before a
    session is *started*: past it nothing new begins until midnight, and what is
    in flight is left to finish. `per_ticket_usd` is handed to the session
    itself, so that one ticket cannot eat the day on its own. Neither does
    anything on a subscription, where the CLI reports no cost to count.
    """

    daily_usd: float = 0.0
    per_ticket_usd: float = 0.0
    # One execution of a ticket's « On » prompt (see transitions.py). Unlike the
    # other two it has a default: a prompt acts on its own, on a change nobody
    # was watching for, and no limit is the wrong thing to start from.
    on_usd: float = 1.0


# What a session does without asking, and what it never does without Salva's
# word. Written as sentences, because a model reads them as such — and in the
# list rather than in the prompt, so that the page can show them and change them.
ALLOWED = (
    "redéployer un service sur les Dokploy de Salva (dokploy.cardona.digital et le "
    "Dokploy d'Animalink), lire leurs logs, ajouter une variable d'environnement non "
    "secrète ou générer un secret aléatoire propre au service",
    "taguer et publier une release d'un dépôt de SalvadorCardona ou de hermez-agency, "
    "après fusion sur main",
    "cloner un dépôt de SalvadorCardona ou de hermez-agency manquant dans le workspace "
    "et lui créer un projet Ponos",
    "relancer une CI",
    "fusionner une PR validée",
)
ASK = (
    "publier sur un registre public (npm, PyPI…)",
    "ouvrir une PR ou une issue sur un dépôt tiers",
    "toute action qui envoie un e-mail ou un message à quelqu'un d'autre que Salva",
    "supprimer des données de production",
    "modifier un DNS",
    "toute dépense",
)


@dataclass
class Permissions:
    """What a session may do alone, and what it must ask first. See prompt.py.

    Both lists have a default and the file only has to say what it changes: a
    list written empty is a real answer — nothing is allowed alone — and is not
    the same as a list the file does not carry.
    """

    allowed: tuple[str, ...] = ALLOWED
    ask: tuple[str, ...] = ASK


@dataclass
class Vault:
    """Which keys each project's sessions are given, and where they are read. See vault.py.

    `projects` is `project → {VARIABLE: item}`: the variable the session sees,
    and the item the provider holds it under — prefixed with another provider
    (`pass:hermez/npm`) when that one key lives elsewhere. A project the table
    does not name is given nothing. `problems` is what the file asked for and
    cannot have, said by `ponos doctor` rather than discovered in a ticket.
    """

    provider: str = "env"
    projects: dict[str, dict[str, str]] = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    def granted(self, project: str) -> dict[str, str]:
        """The variables that project may have — matched however the board spells it."""
        wanted = project.strip().casefold()
        for name, secrets in self.projects.items():
            if name.strip().casefold() == wanted:
                return dict(secrets)
        return {}


def board_dir() -> Path:
    """Where a Markdown board lives when the file does not say.

    Under the state directory, beside the worktrees and the logs, because that
    is where this tool already keeps what it made rather than what you wrote.
    Anybody who would rather have it in a repository of their own says so —
    which is most of the point of a board made of files.
    """
    return state_dir() / "board"


@dataclass
class Storage:
    """Where the board is kept, and what to do when two copies disagree.

    `notion` is the default and the whole of the old behaviour: one board, in
    Notion, and not a line of this module is felt. `markdown` is the same board
    as files on disk, and never touches the network — no token is read, nothing
    is resolved, `ponos doctor` stops asking Notion who you are.
    `both` keeps the two in step: a pass reconciles them before it reads the
    queue, and `conflict` says who wins when the same page moved on both sides.
    """

    mode: str = "notion"
    path: Path = field(default_factory=board_dir)
    # "newest": the later `last_edited_time` wins, and the loser is journalled
    # rather than dropped quietly. The only rule there is, and named so that the
    # day there is a second one the file can say which.
    conflict: str = "newest"
    # Whether a pass reconciles the two before it does anything else. Off is for
    # somebody who would rather run `ponos sync` when it suits them.
    on_every_pass: bool = True

    @property
    def notion(self) -> bool:
        """Does this installation talk to Notion at all?"""
        return self.mode in ("notion", "both")

    @property
    def markdown(self) -> bool:
        return self.mode in ("markdown", "both")


@dataclass
class Config:
    notion: Notion
    runner: Runner
    projects: dict[str, str]
    path: Path
    web: Web = field(default_factory=Web)
    notify: Notify = field(default_factory=Notify)
    openrouter: OpenRouter = field(default_factory=OpenRouter)
    claude: Claude = field(default_factory=Claude)
    budget: Budget = field(default_factory=Budget)
    permissions: Permissions = field(default_factory=Permissions)
    storage: Storage = field(default_factory=Storage)
    vault: Vault = field(default_factory=Vault)
    # `[github]`: which of your GitHub accounts each owner is worked under, as
    # `owner = "the gh account"`. Empty is a machine with one account, which is
    # every machine until it is not — see `git.token_for`.
    github: dict[str, str] = field(default_factory=dict)
    # The secrets `config.toml` still holds, as `table.key` — ignored, and said
    # so: see `move_secrets`.
    exposed: tuple[str, ...] = ()

    def require_usable(self) -> None:
        """Raise ConfigError if the file is not complete enough to run."""
        if not self.storage.notion:
            # A Markdown board needs nothing named and nothing shared: the
            # directory is made the first time something is written into it.
            return
        missing = []
        if not self.notion.token or self.notion.token == PLACEHOLDER:
            # Named twice: the key everybody knows it by, and where it goes now.
            missing.append(
                f"notion.token ({SECRETS[('notion', 'token')]}, "
                f"in {secrets_path(self.path)} or the environment)"
            )
        # Either way of naming the tickets database will do: the workspace page
        # that holds it, or the database itself.
        if not self.notion.workspace and not self.notion.tickets_database:
            missing.append(f"notion.workspace (or notion.tickets_database) in {self.path}")
        if missing:
            raise ConfigError(
                f"{', '.join(missing)} must be set\n"
                "  ponos init <page-url>   builds the databases and fills this in\n"
                "  ponos config            opens the file in your editor\n"
                "  storage.mode = \"markdown\"       runs the whole thing without Notion"
            )


_DEFAULT_PROPERTIES = {
    "status": "Status",
    "project": "Project",
    # Which machine took the ticket, as ponos@host. Not to be confused
    # with `role` below: this one is a runner, that one is a craft.
    "agent": "Runner",
    "pull_request": "Pull Request",
    "session": "Session",
    # Optional. A database without them behaves exactly as before: the runner
    # skips a property the schema does not declare.
    "model": "Model",          # per-ticket model, overrides runner.model
    "priority": "Priority",    # a score from 0 to 100: which ready ticket goes first
    "cost": "Cost",            # written back, in dollars
    "duration": "Duration",    # written back, in minutes
    # What the session is doing right now, rewritten every few seconds while it
    # runs and cleared when it ends. The board's live column.
    "progress": "Progress",
    # A date here holds the ticket until that moment. It is a start gate, not a
    # deadline — "Due Date" said the opposite of what the runner does with it.
    "due": "Scheduled",
    # Ticked while the subscription's window is spent under a ticket. A checkbox
    # and not an eighth column: what happened to that ticket is that *nothing*
    # happened to it, which is not a moment of its life — it is still ready, or
    # still validated, with a note saying why nobody has got to it yet. A column
    # would have said it left the board, and would have had to be typed into
    # Notion by hand on top of that, since the API cannot widen a `status`.
    "waiting": "Waiting for credit",  # checkbox: ticked while the credit is out
    # What kind of work the ticket is — Code, Writing, External action or
    # Publication — which decides the road it takes. Optional, and empty is an
    # answer too: the runner works it out before running the ticket.
    "type": "Type",
    # What kind of change a code ticket is — Bug, Feature, Amélioration… — as a
    # select, ignored on the other types. Empty, the runner fills it before the
    # ticket runs: from the title's prefix, or by asking. See subtypes.py.
    "subtype": "Sous-type",
    # A prompt run at every change of the ticket's status, whoever made it. Text,
    # optional, and empty means nothing happens: see transitions.py.
    "on": "On",
    # Why a blocked or failed ticket stopped: a code of blocks.py, as a select a
    # Notion view filters on. Written when it stops, emptied when it leaves.
    "block": "Blocage",
    # The state of the pull request's checks while the ticket is in review: a
    # select with three options (see ci.py), emptied for a repository without CI.
    "ci": "CI",
    # Relation to the Agents database. It carries the same word as the database
    # it points at, because it is the same thing.
    "role": "Agent",
    # The Schedules database, for what comes back on its own. The first four are
    # what you fill in; the last three are what a pass writes back. A workspace
    # without that database never reads any of them.
    "cadence": "Cadence",          # select: Hourly, Daily, Weekly, Monthly
    "at": "At",                    # text: "09:00"
    "day": "Day",                  # text: "Monday", or "1".."31"
    "active": "Active",            # checkbox: unticked stops everything
    "next_run": "Next",            # date: when the next ticket is born
    "last_run": "Last",            # date: when the last one was
    "last_ticket": "Last ticket",  # relation → the tickets database
}

# The rows the runner looks for in the workspace database, by their title.
# Only `tickets` is required; the others change nothing by their absence.
_DEFAULT_PAGES = {
    "tickets": "Tickets",
    "projects": "Projects",
    "agents": "Agents",
    "context": "Context",
    "schedules": "Schedules",
}

# What those rows used to be called, or are called on a board built by hand. A
# row is looked up under its current name first, then under these — as long as
# the configuration itself names none, since a title someone typed is a title
# they meant. Nothing to rename, nothing to re-provision.
_LEGACY_PAGES = {
    "tickets": ("Master Tickets",),
    "projects": ("Master project", "Master Projects"),
    "agents": ("Master Agents",),
    "context": ("Soul",),
    "schedules": ("Master Scheduler", "Master Scheluder"),
}

# The four types of ticket, told apart by the road they take rather than by what
# they are about — see kinds.py. The keys are what the code says; the values are
# the options of the board's Type column.
_DEFAULT_TYPES = {
    "code": "Code",
    "writing": "Writing",
    "external": "External action",
    "publication": "Publication",
}

# The other spellings an option is recognised by, as long as the file names
# none: the words a French board was written with.
_TYPE_ALIASES = {
    "writing": ("Rédaction", "Redaction"),
    "external": ("Action externe",),
}

# The columns of the board, and they are meant to be read in that order.
#
# "In review" rather than "Done": nothing is done when the runner lets go of a
# ticket — a pull request is waiting for a human, and calling that Done is how a
# board stops being believed. And `failed` and `blocked` are two columns, not
# one: the agent asking a question is waiting for *you*, a session that crashed
# is waiting for someone to read a log. The runner tells them apart; the board
# used to put both in "Draft" and throw that away.
#
# "Validated" is the answer to the question "In review" asks. Reviewing ends in
# a gesture — merge this, publish this — and that gesture is the one thing a
# board cannot do for you and the runner should not decide alone. So you move
# the ticket one column to the right, and the runner does the gesture: it
# merges the pull request, or it publishes what the ticket holds, and only then
# is anything Done. A board that does not offer the column has no such moment,
# and nothing changes: you merge by hand, as before.
#
# There is no column for "the credit ran out": a ticket nothing was started for
# has not moved, so nothing on the board should say it did. It stays where it
# was and is ticked — see `waiting` in `_DEFAULT_PROPERTIES`.
#
# "Cancelled" is the other end of a ticket, beside Done: given up on, not
# finished. Terminal like it — the runner never runs it, never takes it back —
# and apart from it, because a board that files the tickets nobody wanted any
# more under Done is a board whose Done stops meaning "this got done".
_DEFAULT_STATUS = {
    "ready": "Ready",
    "running": "In progress",
    "review": "In review",
    "validated": "Validated",
    "done": "Done",
    "failed": "Failed",
    "blocked": "Blocked",
    "cancelled": "Cancelled",
}


def _database_id(raw: str) -> str:
    """Normalise whatever the user pasted into something resolvable.

    A bare ID, a dashed ID and a full Notion URL all reduce to the 32-character
    identifier. Anything else is handed back untouched — it is most likely the
    database's name, which the client can look up by search.
    """
    raw = raw.strip()
    if not raw:
        return ""
    candidate = raw
    if "://" in candidate:
        candidate = candidate.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        candidate = candidate.rsplit("-", 1)[-1]
    candidate = candidate.replace("-", "")
    return candidate if is_identifier(candidate) else raw


def identifier(raw: str) -> str:
    """The 32-character ID inside whatever was pasted — a URL, or an ID.

    Named for what the caller has in hand rather than for what it points at:
    `init` is given the link of a page, not of a database.
    """
    return _database_id(raw)


def write_notion_value(path: Path, key: str, value: str) -> bool:
    """Set one key of the [notion] table. See `write_value`."""
    return write_value(path, "notion", key, value)


# A TOML key that needs no quotes. Anything else — a project called "Site
# vitrine", a status column with an accent — is written quoted, and looked up
# under both spellings: the file may have been typed by hand.
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

_ESCAPES = (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t"))


def _literal(value: object) -> str:
    """One TOML right-hand side, in the four shapes this file holds.

    A string is escaped rather than interpolated: a token with a quote in it
    used to write a line that stopped the file from parsing, and the next thing
    anybody saw was "configuration not found".
    """
    if isinstance(value, bool):  # before int: a bool *is* an int in Python
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_literal(str(item)) for item in value) + "]"
    text = str(value)
    for raw, encoded in _ESCAPES:
        text = text.replace(raw, encoded)
    text = "".join(character if character >= " " else "" for character in text)
    return f'"{text}"'


def write_value(path: Path, table: str, key: str, value: object) -> bool:
    """Set — or, with `value=None`, remove — one key of one table, in place.

    A TOML writer is not in the standard library and this file is one the user
    reads and edits by hand — rewriting it from a parsed tree would cost every
    comment in it, which is most of its value. So the line is edited, or added
    under the table header if it is not there.

    Removing rather than emptying is deliberate: a key the file does not carry
    is a key the loader fills in itself, and that is what the console means when
    a field is left blank. The comments around it survive, so the line comes
    back documented if it is ever set again.

    `table` is written as it appears between the brackets, dots included:
    "notify.telegram" finds `[notify.telegram]`.

    Returns whether the file changed.
    """
    text = path.read_text(encoding="utf-8")
    written = key if _BARE_KEY.match(key) else _literal(key)
    line = "" if value is None else f"{written} = {_literal(value)}"
    section = re.search(rf"^\[{re.escape(table)}\]\s*$", text, flags=re.M)
    if not section:
        if not line:
            return False
        path.write_text(f"{text.rstrip()}\n\n[{table}]\n{line}\n", encoding="utf-8")
        return True

    start = section.end()
    following = re.search(r"^\[", text[start:], flags=re.M)
    end = start + (following.start() if following else len(text) - start)
    body = text[start:end]

    spellings = "|".join({re.escape(key), re.escape(_literal(key))})
    existing = re.search(rf"^(?:{spellings})\s*=.*$", body, flags=re.M)
    if existing:
        if line:
            if existing.group(0).strip() == line:
                return False
            body = body[: existing.start()] + line + body[existing.end():]
        else:
            stop = existing.end() + (1 if body[existing.end() : existing.end() + 1] == "\n" else 0)
            body = body[: existing.start()] + body[stop:]
    elif line:
        body = "\n" + line + body
    else:
        return False

    path.write_text(text[:start] + body + text[end:], encoding="utf-8")
    return True


def edit(path: Path, changes: list[tuple[str, str, object]]) -> list[str]:
    """Apply a set of changes to the file — all of them, or none at all.

    This is what the console saves through, and it is the one writer that does
    not trust its caller. A configuration is not a form: half of it applied is a
    runner that claims tickets it cannot finish. So the edits are made on a copy
    beside the file, the copy is *loaded* — if it will not parse, or would leave
    a working installation unable to run, nothing moves — and only then does it
    take the file's place, in one `os.replace` and with its permissions.

    A secret is not the file's: it goes to `secrets.env`, by the same copy and
    the same replace, and whatever line `config.toml` still had for it goes.

    The file it displaces is kept as `config.toml.bak`, which is what you want
    the first time a save turns out to have been the wrong idea.

    Returns the names of the keys that actually changed, `table.key` each.
    """
    original = path.read_text(encoding="utf-8")
    try:
        load(path).require_usable()
        was_usable = True
    except ConfigError:
        was_usable = False

    secrets_file = secrets_path(path)
    try:
        secrets_text = secrets_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        secrets_text = ""
    pending = secrets_text
    touched: list[str] = []
    file_changes: list[tuple[str, str, object]] = []
    for table, key, value in changes:
        if (table, key) not in SECRETS:
            file_changes.append((table, key, value))
            continue
        name = SECRETS[(table, key)]
        if name == WEB_PASSWORD_ENV and value is not None and str(value).strip():
            # Written as a digest from its first line: see `passwords`.
            value = _password_digest(str(value))
        updated = _set_secret(pending, name, None if value is None else str(value))
        if read_secrets_text(updated).get(name) != read_secrets_text(pending).get(name):
            touched.append(f"{table}.{key}")
        pending = updated
        file_changes.append((table, key, None))

    # Named per call: two saves at once — two browser tabs, a tab and the CLI —
    # would otherwise edit the same copy and the loser would win.
    suffix = f"saving.{os.getpid()}.{threading.get_ident()}"
    scratch = path.parent / f".{path.name}.{suffix}"
    secrets_scratch = secrets_file.parent / f".{secrets_file.name}.{suffix}"
    # Created private rather than tightened afterwards: this copy may hold every
    # token the file does, and a chmod after the write leaves a moment in which
    # the umask decides who reads them.
    disk.write_private(scratch, original)
    try:
        written = [
            f"{table}.{key}"
            for table, key, value in file_changes
            if write_value(scratch, table, key, value)
        ]
        touched += [name for name in written if name not in touched]
        if not touched:
            return []
        if pending != secrets_text:
            disk.write_private(secrets_scratch, pending)
        try:
            fresh = load(
                scratch, secrets=secrets_scratch if pending != secrets_text else secrets_file
            )
            if was_usable:
                fresh.require_usable()
        # Broad on purpose: the loader coerces as it reads, and anything it
        # refuses to read — a port that is not a number, a path that is not one
        # — has to come back as "not saved" rather than as a traceback and half
        # a file. The scratch copy is what took it, so there is nothing to undo.
        except Exception as error:  # noqa: BLE001
            raise ConfigError(
                f"that would leave the configuration unusable — "
                f"{str(error).splitlines()[0].replace(str(scratch), str(path))}"
            ) from error
        if pending != secrets_text:
            os.replace(secrets_scratch, secrets_file)
        if written:
            try:
                mode = path.stat().st_mode & 0o777
            except OSError:
                mode = 0o600
            backup = path.parent / f"{path.name}.bak"
            # What the backup keeps is the file as it was, less its secrets:
            # yesterday's copy is no place for one either.
            disk.write_private(backup, original)
            _scrub(backup, exposed(read_raw(backup)))
            scratch.chmod(mode)
            os.replace(scratch, path)
    finally:
        for leftover in (scratch, secrets_scratch):
            if leftover.exists():
                leftover.unlink()
    return touched


def read_raw(path: Path) -> dict:
    """The file as it is written, with nothing filled in.

    `load` is the runner's view: every default applied, every floor enforced.
    This is the file's own, and the console needs it to tell "you chose the
    default" from "you said nothing and the default answered".
    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _section(raw: dict, table: str) -> dict:
    """One table of a parsed file, dots followed: "notify.telegram" too."""
    node: object = raw
    for part in table.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def exposed(raw: dict) -> list[tuple[str, str]]:
    """The secrets a parsed `config.toml` still holds — which `load` ignores.

    An empty value is no secret, and nor is the example's placeholder: both are
    only where one used to go.
    """
    return [
        (table, key)
        for table, key in SECRETS
        if (value := str(_section(raw, table).get(key, "") or "").strip())
        and value != PLACEHOLDER
    ]


# One line of `secrets.env`. The shape compose's `env_file`, systemd's
# `EnvironmentFile` and a shell's `source` all read, so one file serves them all.
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
# A value written as it is. Anything else is double-quoted, with what a shell or
# systemd would interpret inside the quotes escaped.
_BARE_VALUE = re.compile(r"^[A-Za-z0-9_\-.:/+@=,%~^]*$")


def read_secrets(path: Path) -> dict[str, str]:
    """`secrets.env` as `NAME → value`; nothing at all when there is no file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return read_secrets_text(text)


def read_secrets_text(text: str) -> dict[str, str]:
    """The same, from a text already in hand."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        elif len(value) >= 2 and value[0] == value[-1] == '"':
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        found[match.group(1)] = value
    return found


def _secret_line(name: str, value: str) -> str:
    # No line breaks and no control characters: a value is one line, or it is
    # the next variable's name.
    value = "".join(character for character in value.strip() if character >= " ")
    if _BARE_VALUE.match(value):
        return f"{name}={value}"
    for raw in ("\\", '"', "$", "`"):
        value = value.replace(raw, "\\" + raw)
    return f'{name}="{value}"'


_SECRETS_HEADER = (
    "# Ponos's secrets, one NAME=value a line. Kept 0600, and never in config.toml:\n"
    "# see config.example.toml for the names. The environment holds them as well.\n"
)


def _set_secret(text: str, name: str, value: str | None) -> str:
    """A secrets file's text with one variable set — or removed, for `None`."""
    lines = text.splitlines()
    at = [
        index
        for index, line in enumerate(lines)
        if (match := _ASSIGNMENT.match(line)) and match.group(1) == name
    ]
    if value is None or not str(value).strip():
        lines = [line for index, line in enumerate(lines) if index not in at]
    elif at:
        lines[at[0]] = _secret_line(name, str(value))
        lines = [line for index, line in enumerate(lines) if index not in at[1:]]
    else:
        if not lines:
            lines = _SECRETS_HEADER.splitlines()
        lines.append(_secret_line(name, str(value)))
    return "\n".join(lines) + "\n" if lines else ""


def write_secrets(path: Path, values: dict[str, str | None]) -> list[str]:
    """Set — or, with `None`, remove — variables of a secrets file, in one write.

    The file's other lines stay where they are, comments included, and it is
    replaced whole and private from its first byte (`disk.write_atomic`).
    Returns the names whose value actually changed.
    """
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    before = read_secrets(path)
    text = original
    for name, value in values.items():
        text = _set_secret(text, name, value)
    if text == original:
        return []
    disk.write_atomic(path, text)
    after = read_secrets(path)
    return [name for name in values if before.get(name) != after.get(name)]


def _scrub(target: Path, keys: list[tuple[str, str]]) -> None:
    """Remove those keys from a TOML file, in one replace and with its mode."""
    if not keys:
        return
    mode = target.stat().st_mode & 0o777
    scratch = target.parent / f".{target.name}.scrubbing.{os.getpid()}.{threading.get_ident()}"
    disk.write_private(scratch, target.read_text(encoding="utf-8"))
    try:
        for table, key in keys:
            write_value(scratch, table, key, None)
        scratch.chmod(mode)
        os.replace(scratch, target)
    finally:
        if scratch.exists():
            scratch.unlink()


def move_secrets(path: Path) -> list[str]:
    """Take every secret out of `config.toml` and into `secrets.env`.

    What a launch does before anything else (see `__main__`), because the file
    was where the installer, `ponos init` and the console used to write them,
    and an installation that updates itself must not wake up without its token.
    Moved rather than copied: a secret left in the file is the very thing this
    is about. A variable `secrets.env` already holds is not overwritten — it was
    put there later than the line the file kept.

    `config.toml.bak` is scrubbed too, being yesterday's copy of the same file.

    Returns the keys moved, `table.key` each; raises OSError when the files
    cannot be written, and then the file is left as it was.
    """
    raw = read_raw(path)
    found = exposed(raw)
    if not found:
        return []
    file = secrets_path(path)
    stored = read_secrets(file)
    write_secrets(
        file,
        {
            SECRETS[(table, key)]: str(_section(raw, table)[key]).strip()
            for table, key in found
            if SECRETS[(table, key)] not in stored
        },
    )
    _scrub(path, found)
    backup = path.parent / f"{path.name}.bak"
    if backup.exists():
        _scrub(backup, exposed(read_raw(backup)))
    # A line `write_value` cannot reach — an inline table — stays, and `load`
    # keeps saying so: only what actually left is reported as moved.
    left = set(exposed(read_raw(path)))
    return [f"{table}.{key}" for table, key in found if (table, key) not in left]


def _password_digest(value: str) -> str:
    """The console's password as `secrets.env` keeps it — a digest already stays one.

    Stripped first, as `secret` strips what it reads back: the password that
    was compared in clear was the stripped one, and the digest has to be of it.
    """
    value = value.strip()
    return value if passwords.is_digest(value) else passwords.digest(value)


def hash_password(path: Path) -> bool:
    """Replace a password `secrets.env` keeps in clear by its digest.

    What a launch does after `move_secrets` — which may just have brought one
    over from `config.toml` — so that an installation from before digests keeps
    its password, the one people type, and stops keeping it readable. Nobody is
    asked to type it again: the digest is of the very value that was there.

    The environment's is left alone, being the unit's or the compose file's to
    keep; the console digests it in memory (`web.server.sign_in`).

    Returns whether anything was written; raises OSError when the file cannot be.
    """
    file = secrets_path(path)
    kept = read_secrets(file).get(WEB_PASSWORD_ENV, "").strip()
    if not kept or passwords.is_digest(kept):
        return False
    write_secrets(file, {WEB_PASSWORD_ENV: _password_digest(kept)})
    return True


def secret(stored: dict[str, str], table: str, key: str) -> str:
    """One secret, from `secrets.env` or the environment — see the docstring."""
    name = SECRETS[(table, key)]
    environment = os.environ.get(name, "").strip()
    written = stored.get(name, "").strip()
    if name in _ENVIRONMENT_FIRST:
        return environment or written
    return written or environment


def defaults(table: str) -> dict[str, str]:
    """The names the runner falls back on, for one of the four naming tables.

    `properties`, `status`, `pages`, `types` — the four places where a board that spells
    a column its own way says so. Public because the console draws a field per
    key, and a key it did not know about would be a setting nobody can reach.
    """
    return dict(
        {
            "properties": _DEFAULT_PROPERTIES,
            "status": _DEFAULT_STATUS,
            "pages": _DEFAULT_PAGES,
            "types": _DEFAULT_TYPES,
        }[table]
    )


def is_identifier(value: str) -> bool:
    """A Notion ID is 32 hexadecimal characters, once the dashes are gone."""
    stripped = value.replace("-", "")
    return len(stripped) == 32 and all(char in "0123456789abcdefABCDEF" for char in stripped)


def load(path: Path | None = None, *, secrets: Path | None = None) -> Config:
    """The runner's reading of the file — and of its secrets, which are elsewhere.

    `secrets` names the secrets file when it is not the one beside `path`: the
    copy `edit` checks before it replaces anything.
    """
    target = path or config_path()
    raw = _read_toml(target)
    stored = read_secrets(secrets or secrets_path(target))
    runner = _runner(raw.get("runner", {}))

    projects = {
        str(name): os.path.expanduser(str(value))
        for name, value in raw.get("projects", {}).items()
    }

    # Lowercased on the way in: GitHub does not care how an owner is spelled,
    # and a line that says `Animalink` must answer for `animalink/site`.
    github = {
        str(name).strip().lower(): str(value).strip()
        for name, value in raw.get("github", {}).items()
        if str(value).strip()
    }

    return Config(
        notion=_notion(raw.get("notion", {}), stored),
        runner=runner,
        projects=projects,
        path=target,
        web=_web(raw.get("web", {}), stored),
        notify=_notify(raw.get("notify", {}), stored, runner),
        openrouter=_openrouter(raw.get("openrouter", {}), stored),
        claude=_claude(raw.get("claude", {}), stored),
        budget=_budget(raw.get("budget", {})),
        permissions=_permissions(raw.get("permissions", {})),
        storage=_storage(raw.get("storage", {})),
        vault=_vault(raw.get("vault")),
        github=github,
        exposed=tuple(f"{table}.{key}" for table, key in exposed(raw)),
    )


def _read_toml(target: Path) -> dict:
    """The file as TOML says it — or a ConfigError that names it."""
    if not target.exists():
        raise ConfigError(
            f"configuration not found: {target}\n"
            "  reinstall with install.sh, or copy config.example.toml"
        )
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{target} is not valid TOML: {error}") from error
    return raw


def _notion(notion_raw: dict, stored: dict[str, str]) -> Notion:
    return Notion(
        token=secret(stored, "notion", "token"),
        workspace=_database_id(str(notion_raw.get("workspace", ""))),
        mention=str(notion_raw.get("mention", "")).strip(),
        tickets_database=_database_id(str(notion_raw.get("tickets_database", ""))),
        # Not merged with the defaults, for the same reason as `status` below:
        # `page_aliases()` needs to know which titles the file actually names, to
        # tell "the user calls it this" from "nobody said, so try the old names".
        pages=dict(notion_raw.get("pages", {})),
        properties={**_DEFAULT_PROPERTIES, **notion_raw.get("properties", {})},
        # Not merged with the defaults: `state()` needs to know which keys the
        # file actually sets, to let "blocked" fall back on "failed".
        status=dict(notion_raw.get("status", {})),
        types=dict(notion_raw.get("types", {})),
    )


def _runner(runner_raw: dict) -> Runner:
    """`[runner]`, read a part at a time: the table holds most of the keys there are."""
    defaults = Runner()
    return Runner(
        **_runner_pace(runner_raw, defaults),
        **_runner_work(runner_raw, defaults),
        **_runner_conversation(runner_raw, defaults),
        **_runner_upkeep(runner_raw, defaults),
        **_runner_models(runner_raw, defaults),
    )


def _runner_pace(runner_raw: dict, defaults: Runner) -> dict:
    """Where the work is, how often and how much of it at once, and what holds it back."""
    return dict(
        workspace_root=Path(
            os.path.expanduser(
                str(runner_raw.get("workspace_root", defaults.workspace_root))
            )
        ),
        # systemd refuses a zero interval, and anything below a second would
        # only spin: one second is the floor that means anything here.
        interval_seconds=max(1, int(runner_raw.get("interval_seconds", defaults.interval_seconds))),
        max_concurrent=max(1, int(runner_raw.get("max_concurrent", defaults.max_concurrent))),
        max_concurrent_per_project=max(
            1,
            int(runner_raw.get("max_concurrent_per_project", defaults.max_concurrent_per_project)),
        ),
        timeout_minutes=max(1, int(runner_raw.get("timeout_minutes", defaults.timeout_minutes))),
        relaunch_delay_seconds=max(
            0, int(runner_raw.get("relaunch_delay_seconds", defaults.relaunch_delay_seconds))
        ),
        min_free_memory_mb=max(
            0, int(runner_raw.get("min_free_memory_mb", defaults.min_free_memory_mb))
        ),
        min_free_disk_mb=max(
            0, int(runner_raw.get("min_free_disk_mb", defaults.min_free_disk_mb))
        ),
        wait_for_credits=bool(
            runner_raw.get("wait_for_credits", defaults.wait_for_credits)
        ),
        # Both ends clamped rather than refused: a file saying 150 meant "keep
        # plenty", not "never run again", and a negative reserve is a typo for
        # none at all.
        credit_reserve_percent=max(
            0,
            min(
                MOST_RESERVED,
                int(runner_raw.get("credit_reserve_percent", defaults.credit_reserve_percent)),
            ),
        ),
    )


def _runner_work(runner_raw: dict, defaults: Runner) -> dict:
    """How a ticket is worked: its session, its branch, and how far it goes on its own."""
    return dict(
        model=str(runner_raw.get("model", defaults.model)).strip(),
        # Kept as the file wrote it: `voice` reads it down to a language it
        # speaks, and the difference between "nothing was said" and "English was
        # asked for" is one the loader must not flatten.
        language=str(
            runner_raw.get("language", defaults.language) or os.environ.get(LANGUAGE_ENV, "")
        ).strip(),
        app_language=str(runner_raw.get("app_language", defaults.app_language)).strip(),
        permission_mode=str(runner_raw.get("permission_mode", defaults.permission_mode)).strip(),
        branch_prefix=str(runner_raw.get("branch_prefix", defaults.branch_prefix)),
        base_branch=str(runner_raw.get("base_branch", defaults.base_branch)).strip(),
        fetch=bool(runner_raw.get("fetch", defaults.fetch)),
        push=bool(runner_raw.get("push", defaults.push)),
        open_pull_request=bool(
            runner_raw.get("open_pull_request", defaults.open_pull_request)
        ),
        rebase=bool(runner_raw.get("rebase", defaults.rebase)),
        force_validated_code=bool(
            runner_raw.get("force_validated_code", defaults.force_validated_code)
        ),
        force_validated_writing=bool(
            runner_raw.get("force_validated_writing", defaults.force_validated_writing)
        ),
        force_validated_external=bool(
            runner_raw.get("force_validated_external", defaults.force_validated_external)
        ),
        force_validated_publication=bool(
            runner_raw.get("force_validated_publication", defaults.force_validated_publication)
        ),
        merge_method=(
            str(runner_raw.get("merge_method", "")).strip().lower()
            if str(runner_raw.get("merge_method", "")).strip().lower() in MERGE_METHODS
            else defaults.merge_method
        ),
        resolve_conflicts=bool(runner_raw.get("resolve_conflicts", defaults.resolve_conflicts)),
        # A list in the file reads as well as the comma-separated line the
        # console writes: both are a handful of project names.
        resolve_conflicts_except=(
            ", ".join(str(name).strip() for name in raw_except)
            if isinstance(raw_except := runner_raw.get("resolve_conflicts_except", ""), list)
            else str(raw_except).strip()
        ),
        resolve_model=str(runner_raw.get("resolve_model", defaults.resolve_model)).strip(),
        checks_timeout_minutes=max(
            0, int(runner_raw.get("checks_timeout_minutes", defaults.checks_timeout_minutes))
        ),
        keep_worktree_on_failure=bool(
            runner_raw.get("keep_worktree_on_failure", defaults.keep_worktree_on_failure)
        ),
        attach_sessions=bool(runner_raw.get("attach_sessions", defaults.attach_sessions)),
        session_host=str(runner_raw.get("session_host", defaults.session_host)).strip(),
        dry_run=bool(runner_raw.get("dry_run", defaults.dry_run)),
        prompt_file=str(runner_raw.get("prompt_file", defaults.prompt_file)).strip(),
        document_prompt_file=str(
            runner_raw.get("document_prompt_file", defaults.document_prompt_file)
        ).strip(),
        delivery_prompt_file=str(
            runner_raw.get("delivery_prompt_file", defaults.delivery_prompt_file)
        ).strip(),
    )


def _runner_conversation(runner_raw: dict, defaults: Runner) -> dict:
    """What it says on a ticket, and when it answers, reacts or looks again."""
    return dict(
        notify=bool(runner_raw.get("notify", defaults.notify)),
        progress=bool(runner_raw.get("progress", defaults.progress)),
        # Ten seconds reads as live and costs three writes a ticket per tick.
        # The floor is five: below that, two tickets running at once would spend
        # the integration's rate limit on saying what they are about to do.
        progress_interval_seconds=max(
            5,
            int(runner_raw.get("progress_interval_seconds", defaults.progress_interval_seconds)),
        ),
        reply=bool(runner_raw.get("reply", defaults.reply)),
        # The floor is ten seconds, which is the fastest a run itself goes: a
        # zero here would turn every pass into a full scan of the board.
        reply_interval_seconds=max(
            10, int(runner_raw.get("reply_interval_seconds", defaults.reply_interval_seconds))
        ),
        reply_scan=max(1, int(runner_raw.get("reply_scan", defaults.reply_scan))),
        reply_timeout_minutes=max(
            1, int(runner_raw.get("reply_timeout_minutes", defaults.reply_timeout_minutes))
        ),
        reply_permission_mode=str(
            runner_raw.get("reply_permission_mode", defaults.reply_permission_mode)
        ).strip()
        or defaults.reply_permission_mode,
        on=bool(runner_raw.get("on", defaults.on)),
        on_interval_seconds=max(
            10, int(runner_raw.get("on_interval_seconds", defaults.on_interval_seconds))
        ),
        on_max_depth=max(0, int(runner_raw.get("on_max_depth", defaults.on_max_depth))),
        on_timeout_minutes=max(
            1, int(runner_raw.get("on_timeout_minutes", defaults.on_timeout_minutes))
        ),
        on_permission_mode=str(
            runner_raw.get("on_permission_mode", defaults.on_permission_mode)
        ).strip(),
        unblock=bool(runner_raw.get("unblock", defaults.unblock)),
        # A ticket is looked at once in this long, and a session is spent each
        # time: ten minutes is the floor.
        unblock_interval_seconds=max(
            600, int(runner_raw.get("unblock_interval_seconds", defaults.unblock_interval_seconds))
        ),
        schedule=bool(runner_raw.get("schedule", defaults.schedule)),
    )


def _runner_upkeep(runner_raw: dict, defaults: Runner) -> dict:
    """Keeping itself up to date, and tidying up after itself."""
    return dict(
        auto_update=bool(runner_raw.get("auto_update", defaults.auto_update)),
        # Filtered rather than trusted: a typo here must not quietly put an
        # installation on every commit of `main`. Anything unknown is the
        # careful answer.
        update_channel=(
            str(runner_raw.get("update_channel", "")).strip().lower()
            if str(runner_raw.get("update_channel", "")).strip().lower() in UPDATE_CHANNELS
            else defaults.update_channel
        ),
        # A run asks the remote at most once per this interval. The floor is a
        # minute: at a ten-second cadence, an unbounded value would turn into a
        # `git fetch` six times a minute, forever.
        update_interval_seconds=max(
            60, int(runner_raw.get("update_interval_seconds", defaults.update_interval_seconds))
        ),
        log_retention_days=max(
            0, int(runner_raw.get("log_retention_days", defaults.log_retention_days))
        ),
        clean_done_worktrees=bool(
            runner_raw.get("clean_done_worktrees", defaults.clean_done_worktrees)
        ),
        stale_worktree_days=max(
            0, int(runner_raw.get("stale_worktree_days", defaults.stale_worktree_days))
        ),
        # A list in the file reads as well as the comma-separated line the
        # console writes, as `resolve_conflicts_except` does.
        worktree_exclude=(
            ", ".join(str(path).strip() for path in raw_exclude)
            if isinstance(raw_exclude := runner_raw.get("worktree_exclude", ""), list)
            else str(raw_exclude).strip()
        ),
    )


def _runner_models(runner_raw: dict, defaults: Runner) -> dict:
    """Which model a ticket gets, and which one sorts it first."""
    return dict(
        classify=bool(runner_raw.get("classify", defaults.classify)),
        # Empty is the CLI's own model, which is a choice too: a runner routed
        # through OpenRouter has no `haiku` to be given.
        classify_model=str(runner_raw.get("classify_model", defaults.classify_model)).strip(),
        ideas_model=str(runner_raw.get("ideas_model", defaults.ideas_model)).strip(),
        # Filtered rather than trusted, like the channel: a typo must not turn
        # into a threshold nothing reaches, which would block every ticket.
        classify_confidence=(
            str(runner_raw.get("classify_confidence", "")).strip().lower()
            if str(runner_raw.get("classify_confidence", "")).strip().lower() in CONFIDENCES
            else defaults.classify_confidence
        ),
        auto_model=bool(runner_raw.get("auto_model", defaults.auto_model)),
        # Empty is allowed: a level that names no model borrows the nearest one
        # that does — see `models.Grid.model`.
        **{
            f"auto_model_{level}": str(
                runner_raw.get(f"auto_model_{level}", getattr(defaults, f"auto_model_{level}"))
            ).strip()
            for level in models.LEVELS
        },
        # Filtered rather than trusted: a typo is the type's default level, not
        # a level nothing answers.
        **{
            f"auto_model_{kind}": (
                str(runner_raw.get(f"auto_model_{kind}", "")).strip().lower()
                if str(runner_raw.get(f"auto_model_{kind}", "")).strip().lower() in models.LEVELS
                else getattr(defaults, f"auto_model_{kind}")
            )
            for kind in ("code", "writing", "external", "publication")
        },
        # Filtered like the types: a word that is none of the three is the
        # sub-type's own default, not a level nothing answers.
        auto_model_subtypes={
            key: str(runner_raw.get(f"auto_model_subtype_{key}", "")).strip().lower()
            for key in subtypes.KEYS
            if str(runner_raw.get(f"auto_model_subtype_{key}", "")).strip().lower() in subtypes.SHIFTS
        },
        auto_model_escalate=bool(
            runner_raw.get("auto_model_escalate", defaults.auto_model_escalate)
        ),
        use_fable=bool(runner_raw.get("use_fable", defaults.use_fable)),
    )


def _web(web_raw: dict, stored: dict[str, str]) -> Web:
    web_defaults = Web()
    return Web(
        host=str(web_raw.get("host", web_defaults.host)).strip() or web_defaults.host,
        port=int(web_raw.get("port", web_defaults.port)),
        token=secret(stored, "web", "token"),
        url=str(web_raw.get("url", web_defaults.url)).strip().rstrip("/"),
        # The environment first, so a unit file or a container can hold the
        # credentials rather than the file. Stripped like every other secret
        # here: a password read out of a file would otherwise carry the
        # newline that file ends with, and lock you out of your own console.
        email=(
            os.environ.get(WEB_EMAIL_ENV) or str(web_raw.get("email", web_defaults.email))
        ).strip(),
        password=secret(stored, "web", "password"),
        # Five seconds is the floor for the same reason as the live report's:
        # below that, a page left open in a tab becomes a second full-time
        # reader of the board.
        poll_seconds=max(5, int(web_raw.get("poll_seconds", web_defaults.poll_seconds))),
        chat_timeout_minutes=max(
            1, int(web_raw.get("chat_timeout_minutes", web_defaults.chat_timeout_minutes))
        ),
        chat_model=str(web_raw.get("chat_model", web_defaults.chat_model)).strip(),
        attachment_max_mb=max(
            1, int(web_raw.get("attachment_max_mb", web_defaults.attachment_max_mb))
        ),
        attachment_days=max(
            1, int(web_raw.get("attachment_days", web_defaults.attachment_days))
        ),
        send_after_transcription=bool(
            web_raw.get("send_after_transcription", web_defaults.send_after_transcription)
        ),
    )


def _openrouter(router_raw: dict, stored: dict[str, str]) -> OpenRouter:
    router_defaults = OpenRouter()
    return OpenRouter(
        key=secret(stored, "openrouter", "key"),
        # A trailing slash here would produce `…/v1//messages`, which some
        # gateways answer and others refuse. Emptied, the default answers.
        base_url=str(router_raw.get("base_url", "")).strip().rstrip("/")
        or router_defaults.base_url,
        route_sessions=bool(router_raw.get("route_sessions", router_defaults.route_sessions)),
        transcription_model=str(router_raw.get("transcription_model", "")).strip()
        or router_defaults.transcription_model,
    )


def _claude(claude_raw: dict, stored: dict[str, str]) -> Claude:
    # Filtered rather than trusted: a typo must not leave the sessions on an
    # account nobody chose. An unknown word is the file that says nothing.
    chosen = str(claude_raw.get("provider", "")).strip().lower()
    return Claude(
        provider=chosen if chosen in PROVIDERS else "",
        api_key=secret(stored, "claude", "api_key"),
    )


def _budget(budget_raw: dict) -> Budget:
    return Budget(
        daily_usd=_dollars(budget_raw.get("daily_usd")),
        per_ticket_usd=_dollars(budget_raw.get("per_ticket_usd")),
        on_usd=_dollars(budget_raw.get("on_usd", Budget.on_usd)),
    )


def _permissions(permissions_raw: dict) -> Permissions:
    permissions_defaults = Permissions()
    return Permissions(
        **{
            name: _sentences(permissions_raw.get(name), getattr(permissions_defaults, name))
            for name in ("allowed", "ask")
        }
    )


def _storage(storage_raw: dict) -> Storage:
    storage_defaults = Storage()
    # Filtered rather than trusted, and for once that is not paranoia: a typo
    # here would silently decide where the board lives. An unknown word falls
    # back on Notion, which is what a file that says nothing already gets.
    mode = str(storage_raw.get("mode", storage_defaults.mode)).strip().lower()
    conflict = str(storage_raw.get("conflict", storage_defaults.conflict)).strip().lower()
    return Storage(
        mode=mode if mode in MODES else storage_defaults.mode,
        path=Path(os.path.expanduser(str(storage_raw.get("path", "")))) if storage_raw.get("path")
        else storage_defaults.path,
        conflict=conflict if conflict in CONFLICTS else storage_defaults.conflict,
        on_every_pass=bool(
            storage_raw.get("on_every_pass", storage_defaults.on_every_pass)
        ),
    )


def _notify(notify_raw: dict, stored: dict[str, str], runner: Runner) -> Notify:
    # `runner.notify` came first and said "one desktop notification per ticket".
    # It keeps saying exactly that: the new table only has to name what it
    # changes, and a file written before any of this existed behaves as it did.
    events = notify_raw.get("events", EVENTS)
    return Notify(
        desktop=bool(notify_raw.get("desktop", runner.notify)),
        replies=bool(notify_raw.get("replies", True)),
        # Filtered rather than trusted: a typo in this list would otherwise
        # silence a moment without ever saying so.
        events=tuple(
            name
            for name in (str(value).strip().lower() for value in events)
            if name in EVENTS
        ),
        telegram=_channel(notify_raw.get("telegram"), secret(stored, "notify.telegram", "token")),
        slack=_channel(notify_raw.get("slack"), secret(stored, "notify.slack", "token")),
    )


def _dollars(raw: object) -> float:
    """An amount, or 0.0 for a limit that is empty, negative or not a number.

    Empty is the line left blank in the file, and it must read as "no limit"
    rather than as a ceiling of nothing that stops every session.
    """
    try:
        return max(0.0, float(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _sentences(raw: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """A list of sentences as the file wrote it, or the default when it wrote none.

    A key that is absent, or not a list, is the default; a list — even an empty
    one — is the answer. Blank entries are dropped, not kept as empty rules.
    """
    if not isinstance(raw, list):
        return default
    return tuple(text for item in raw if (text := str(item).strip()))


def _vault(raw: object) -> Vault:
    """`[vault]`, read leniently and checked: what cannot be handed over is said.

    A project's secrets are written either as a table — `NPM_TOKEN =
    "hermez/npm"`, the variable and the item it is read from — or as a list of
    names, each read under its own name. An entry that is no variable name, or
    that would take the place of one of the runner's own keys, is left out and
    named in `problems`: a session must never be handed a project's
    `ANTHROPIC_API_KEY` in place of the one the runner chose.
    """
    table = raw if isinstance(raw, dict) else {}
    found: list[str] = []
    chosen = str(table.get("provider", "env")).strip().lower() or "env"
    if chosen not in vault.PROVIDERS:
        found.append(f"vault.provider = {chosen!r} is none of {', '.join(vault.PROVIDERS)}")
    reserved = set(SECRETS.values()) | {"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"}
    projects: dict[str, dict[str, str]] = {}
    listed = table.get("projects", {})
    for project, entries in (listed.items() if isinstance(listed, dict) else ()):
        if isinstance(entries, dict):
            pairs = [(str(name).strip(), str(item).strip()) for name, item in entries.items()]
        elif isinstance(entries, (list, tuple)):
            pairs = [(str(name).strip(), str(name).strip()) for name in entries]
        else:
            found.append(f"vault.projects.{project} is neither a table nor a list")
            continue
        kept: dict[str, str] = {}
        for variable, item in pairs:
            why = vault.problems(variable, item, reserved)
            if why:
                found.append(f"vault.projects.{project}: {why}")
                continue
            kept[variable] = item
        projects[str(project)] = kept
    return Vault(provider=chosen, projects=projects, problems=tuple(found))


def _channel(raw: object, token: str) -> dict[str, str]:
    """One [notify.<channel>] table, as strings — a chat id is not a number.

    Telegram's chat ids are integers, negative for a group, and TOML will hand
    them over as such. Everything downstream compares them to what the API
    returns in JSON, where they are strings. The bot's token is put in from
    where secrets live, and a `token` the table still carries is left out.
    """
    table = raw if isinstance(raw, dict) else {}
    read = {
        # A list — `allowed_users` — is kept as one comma-separated string, so
        # the table stays the flat mapping every reader of it expects.
        str(key): (
            ",".join(str(item).strip() for item in value)
            if isinstance(value, (list, tuple))
            else str(value)
        ).strip()
        for key, value in table.items()
        # Never the file's own: see `SECRETS`.
        if key != "token"
    }
    if token:
        read["token"] = token
    return read
