"""Reading and validating ~/.config/ponos/config.toml.

The file is the single source of truth, and a missing value is reported at
install time rather than in the middle of a ticket — for everything but its
secrets. A token or a password is not read from `config.toml`, ever: that file
is one you open in an editor, paste into a ticket, copy into an image or onto a
shared volume, and a secret has no business going wherever it goes. They live in
Ponos's own vault (vault_store.py: `vault.db`, sealed, the table `own`), where
the console writes them, or in the environment (`SECRETS` says which names). A
secret still found in `config.toml` is ignored, moved into the vault by the next
launch (`move_secrets`), and said so on stderr — and so is what a `secrets.env`
from before the vault still held in clear, the file deleted once it is.

Which of the two wins depends on who wrote it last. The console writes the
vault, and a key somebody has just typed and checked must not lose to one a
compose file was started with weeks ago: the vault wins. The console's sign-in
goes the other way round — `PONOS_WEB_EMAIL` and `PONOS_WEB_PASSWORD` are how a
unit file or a container claims a console before anybody arrives, and the
environment wins over the vault; that is what makes it worth setting.
"""

from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import sys
import threading
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import disk, models, passwords, subtypes, vault

if TYPE_CHECKING:
    # Imported by `load`, not here: see schema.py.
    from . import schema

# Where the console's sign-in may be written instead of in the file.
WEB_EMAIL_ENV = "PONOS_WEB_EMAIL"
WEB_PASSWORD_ENV = "PONOS_WEB_PASSWORD"

# Where a provider's key may come from — the names every tool already reads, so
# a container is given them once.
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
GITHUB_TOKEN_ENV = "PONOS_GITHUB_TOKEN"

# Every secret the configuration knows: where `config.toml` used to hold it, and
# the name it holds now — in the environment, or in Ponos's own vault.
SECRETS: dict[tuple[str, str], str] = {
    ("web", "token"): "PONOS_WEB_TOKEN",
    ("web", "password"): WEB_PASSWORD_ENV,
    ("notify.telegram", "token"): "PONOS_TELEGRAM_TOKEN",
    ("notify.slack", "token"): "PONOS_SLACK_TOKEN",
    ("claude", "api_key"): ANTHROPIC_KEY_ENV,
    ("openrouter", "key"): OPENROUTER_KEY_ENV,
    ("github_access", "token"): GITHUB_TOKEN_ENV,
}

# The ones the environment wins for — see the module's docstring.
_ENVIRONMENT_FIRST = (WEB_PASSWORD_ENV,)

# The language the reports are written in, when the file names none: what a
# container is given once, in a compose file or a Dokploy template, before
# anybody opens the console. The file wins — a language picked in Settings is a
# decision taken later than the deployment.
LANGUAGE_ENV = "PONOS_LANGUAGE"

# The proxies the console believes about whom they relay, when the file names
# none: what a container is given in its compose file, beside Traefik — whose
# address only the deployment knows. Comma-separated; the file wins.
TRUSTED_PROXIES_ENV = "PONOS_WEB_TRUSTED_PROXIES"

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


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "ponos"


def private_state() -> None:
    """Close the state directory, and the folders at its top, to other accounts.

    Everything a ticket or a conversation leaves sits there — transcripts,
    screenshots pasted in the chat, what a session captured — and was written
    over the years with the umask. A closed directory keeps what is under it
    from being read, whatever its own mode, so this is enough at each launch
    and cheap: one level, no walk. The files themselves `ponos doctor` reports,
    and tightens when asked.
    """
    root = state_dir()
    try:
        disk.private_dir(root)
        folders = [path for path in root.iterdir() if path.is_dir() and not path.is_symlink()]
    except OSError:
        return  # a read-only home, a path that is not ours: what writes there will say so
    for folder in folders:
        disk.tighten(folder)


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


def legacy_secrets_path(config: Path | None = None) -> Path:
    """`secrets.env`, where the secrets were kept in clear before the vault.

    Read once more by `move_secrets`, which empties it into the vault and
    deletes it — never as a source of secrets any more.
    """
    return (config or config_path()).parent / "secrets.env"


class ConfigError(Exception):
    """Configuration missing, unreadable or incomplete."""


@dataclass
class BoardNames:
    # The names of the board — its columns, its statuses, its types — are not
    # the file's to choose: see `PROPERTIES`. These read them, and nothing else.

    def prop(self, key: str) -> str:
        return PROPERTIES[key]

    def kind(self, key: str) -> str:
        """The option a type of ticket is written as on the board."""
        return TYPES[key]

    def kind_names(self, key: str) -> tuple[str, ...]:
        """Every spelling that option may carry: the board's, then the older ones.

        A ticket typed before the names were fixed says “Writing” where the
        board now says “Rédaction”: read as no type at all, the runner would
        classify, again and again, a ticket somebody already typed.
        """
        return (TYPES[key], *_TYPE_ALIASES.get(key, ()))

    def kind_of(self, value: str) -> str:
        """The type a board option means, or "" for one that is none of the four."""
        wanted = str(value or "").strip().casefold()
        if not wanted:
            return ""
        for key in TYPES:
            if wanted in (name.strip().casefold() for name in self.kind_names(key)):
                return key
        return ""

    def state(self, key: str) -> str:
        return STATUS[key]


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
    # No session is started while the load over the last minute is above this
    # many times the cores: a saturated machine stretches every session already
    # running, and its tests time out. Zero turns the guard off.
    max_load_per_core: float = 1.5
    # How many workers the tests of one session may take — Vitest, Playwright,
    # pytest-xdist, Jest — exported to its environment and said in its prompt.
    # Zero is its part of the cores: `nproc // max_concurrent`, one at least.
    # See resources.share.
    session_workers: int = 0
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
    # Run the project's CI on this machine before the pull request is opened,
    # in Docker — a red CI found here is fixed by the same session, rather than
    # by another one once GitHub has said it. Off, nothing changes; a project
    # may say otherwise for itself. See local_ci.py.
    local_ci: bool = False
    # How many times the CI is run before the ticket is blocked on it — the
    # first run included, every other one after the session has fixed it.
    local_ci_attempts: int = 3
    # How many local CIs this machine runs at once, whatever the number of
    # tickets in flight: each one is a set of containers.
    local_ci_concurrent: int = 1
    # Before the push, a short session reads the branch's diff against the
    # ticket — its done criterion first — in plan mode, and the ticket's own
    # session is picked up once on what it finds blocking. The pull request
    # opens whatever it says. A project may say otherwise for itself. See review.py.
    self_review: bool = True
    # The model that reads. Empty: the ticket's own.
    review_model: str = "sonnet"
    # How long a project's setup command may run in a fresh worktree, before
    # the session starts. Past it the command is killed and the ticket blocked.
    # See worktree_setup.py.
    setup_timeout_minutes: int = 10
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
    # The reviews and the line comments of GitHub on a ticket's pull request, as
    # work: a « Changes requested », or a comment that opens on the mention,
    # puts the ticket back in ready. See reviews.py.
    pr_review_comments: bool = True
    pr_review_mention: str = "@ponos"
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
    # The most `logs/` may hold, in megabytes, service journal included: past
    # it the oldest session logs go, down to 90 % of it — see rotation.py.
    log_max_mb: int = 4096
    # Once a day, the worktrees and scratch directories of tickets done for
    # `log_retention_days` go too — see cleanup.py.
    clean_done_worktrees: bool = True
    # A worktree nobody has touched for this many days goes too, whatever its
    # ticket's status — unless the ticket is in progress, or the worktree holds
    # changes or commits that are nowhere else. Zero turns it off.
    stale_worktree_days: int = 30
    # Each session works with a TMPDIR of its own, under `cache_dir()/tmp`,
    # removed when it ends. What is still there after this many hours (a
    # session killed, a crash) goes in the daily tidy, and so does what the
    # sessions and the tests of old left in `~/.cache/tmp*` and `~/tmp*` once
    # untouched for two. 0 turns it off.
    tmp_retention_hours: int = 24
    # Also once a day: `docker image prune -a`, `docker builder prune` and
    # `docker volume prune` — what no container, running or stopped, refers to.
    docker_prune: bool = True
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
    # Finding them without being asked — see idea_schedule.py. Off, only the
    # button does; the rest of the keys say when, for which projects, and how
    # much a pass may do and spend.
    ideas_schedule: str = "off"
    ideas_at: str = "09:00"
    ideas_day: str = "Monday"
    ideas_every_hours: int = 6
    ideas_cron: str = ""
    ideas_scope: str = "all"
    ideas_projects: str = ""
    ideas_workspace: bool = False
    ideas_per_batch: int = 10
    ideas_skip_above: int = 20
    ideas_budget_usd: float = 0.0
    ideas_notify: bool = False
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
    # An investigation reads a lot and concludes in tickets other sessions will
    # follow to the letter: it starts where the hard work does.
    auto_model_diagnostic: str = "heavy"
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
                level: self.allowed(getattr(self, f"auto_model_{level}")) for level in models.LEVELS
            },
            starts={
                kind: getattr(self, f"auto_model_{kind}")
                for kind in ("code", "writing", "external", "publication", "diagnostic")
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
        left_alone = {name.strip().casefold() for name in self.resolve_conflicts_except.split(",")}
        return self.resolve_conflicts and project.strip().casefold() not in left_alone


# How often ideas are found on their own, and for which projects — see `Runner`.
IDEAS_SCHEDULES = ("off", "every_4h", "daily", "weekly", "hours", "cron")
IDEAS_SCOPES = ("all", "selected")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

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

# How often the digest goes out, and the days a weekly one can be set to: the
# order is `datetime.weekday()`'s, so a name's rank is its day.
DIGESTS = ("off", "daily", "weekly")
DIGEST_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


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
    digest: str = "off"
    digest_day: str = "monday"
    digest_hour: int = 9
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
    # Who may say, in `X-Forwarded-For`, whom it relays — addresses or networks.
    # Everyone else is counted by its own address when it gets the door wrong
    # (see web/attempts.py): this machine by default, where `tailscale serve`
    # relays from; Traefik in front of a container is declared, by its address.
    trusted_proxies: tuple[str, ...] = ("127.0.0.1", "::1")
    # Who opens the console, and what they type. Both set, the page asks for
    # them instead of for the token — which is the difference between a console
    # you open from a bookmark and one you open by pasting a secret. The token
    # is still what a script carries; it just stops being what *you* carry. Both
    # are also read from the environment, see the module's docstring.
    email: str = ""
    password: str = ""
    # How often the console asks what the board looks like — and only while a
    # browser is actually watching. Nobody is watching most of the time.
    poll_seconds: int = 15
    # A chat turn is a Claude session like any other, and wants the same kind of
    # ceiling. Shorter than a ticket's: somebody is sitting in front of it.
    chat_timeout_minutes: int = 20
    # How many conversations may be answering at once. Each turn is a Claude
    # session, and they spend the same subscription: past this, a message waits
    # in its conversation until a place is free.
    chat_max_turns: int = 3
    # The model a new conversation of the console starts on. Empty: the runner's
    # own default model. Each conversation then keeps the one it was given.
    chat_model: str = ""
    # What a message to the workspace may carry. A file is refused past this
    # size rather than read and then regretted: a phone video is a gigabyte,
    # and the session would read none of it anyway.
    attachment_max_mb: int = 25
    # The most a file of the library (Context → Library) may weigh. Those files
    # are kept for good and read by sessions, not dropped for one message.
    library_max_mb: int = 50
    # Whether the console's assistant, and any MCP client allowed to write, may
    # put a ticket in Ready (`launch_task`, web/mcp.py) — once it has shown what
    # it would cost and been told yes. Off: what it creates waits as a draft
    # for a person to launch from the console, as before.
    assistant_launches: bool = True
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


# The voices Piper speaks with, by the language of the reply. See speech.py.
DEFAULT_VOICE_FR = "fr_FR-siwis-medium"
DEFAULT_VOICE_EN = "en_US-lessac-medium"


@dataclass
class Speech:
    """`[speech]`: the console reading its answers aloud, with Piper. See speech.py.

    On by default: it costs nothing until Piper is installed and somebody presses
    the button, and the console says why it is greyed out until then.
    """

    enabled: bool = True
    voice_fr: str = DEFAULT_VOICE_FR
    voice_en: str = DEFAULT_VOICE_EN
    # Percent of the voice's own pace: 100 is normal, 150 a third faster.
    speed: int = 100


# Which browser the sessions of external tickets act in: Ponos's own (Chromium
# driven by Playwright, see browser.py) or Claude in Chrome, the user's Chrome.
BROWSERS = ("ponos", "chrome")


@dataclass
class Browser:
    """`[browser]`: the browser external tickets use. See browser.py.

    `default` is the word of every project that does not say its own (Settings
    of a project), and a ticket may still name the other one in its body.
    `headless` false shows the window, to watch a session or debug one.
    """

    default: str = "ponos"
    headless: bool = True


# How GitHub is reached. Empty is the whole of the old behaviour: a GitHub App
# when one is connected, the `gh` accounts otherwise — and a token, when one is
# given, only in the place of `gh`. `app` and `token` say which of the two wins.
GITHUB_MODES = ("app", "token")


@dataclass
class GithubAccess:
    """`[github_access]`: the GitHub App or a personal access token. See github_token.py.

    The token itself is never a key of the file: `token` is read from
    Ponos's vault or the environment (`SECRETS`), and `token_item` names where a
    vault keeps it instead (`pass:ponos/github`, `keyring:ponos-github`).
    """

    mode: str = ""
    token: str = ""
    token_item: str = ""


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
    # Whether the sessions sign their commits and pull requests as Claude —
    # Claude Code's own `Co-Authored-By` trailer and « Generated with Claude
    # Code » line. Off: every session is launched without them, whatever the
    # machine's `~/.claude/settings.json` says, its prompt asks for none, and
    # what slips through is taken out of the pull request (git.unsigned).
    attribution: bool = False


@dataclass
class Review:
    """`[review]`: what Ponos does by itself with a pull request left in review.

    `ci_retries` is how many times a ticket whose CI is red, or whose pull
    request conflicts, is put back in ready with the instruction to repair it
    (see ci.py). Past it the ticket is blocked and asks. Zero is never retried.
    """

    ci_retries: int = 5


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


# What a session does without asking, and what it never does without the user's
# word. Written as sentences, because a model reads them as such — and in the
# list rather than in the prompt, so that the page can show them and change them.
# Every installation starts from these: they name no one, no host and no owner.
ALLOWED = (
    "taguer et publier une release d'un dépôt du projet, après fusion sur main",
    "cloner un dépôt du propriétaire GitHub du projet, ou d'un propriétaire que "
    "[github] nomme, manquant dans le workspace et lui créer un projet Ponos",
    "relancer une CI",
    "fusionner une PR validée",
)
ASK = (
    "publier sur un registre public (npm, PyPI…)",
    "ouvrir une PR ou une issue sur un dépôt tiers",
    "toute action qui envoie un e-mail ou un message à quelqu'un d'autre que l'utilisateur",
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
    """Where a project's keys are read. See vault.py.

    Which keys each project's sessions are given is the project's own, in
    `ponos.db` (`project_settings.vault`). `problems` is what the file asked
    for and cannot have, said by `ponos doctor` rather than discovered in a ticket.
    """

    provider: str = "env"
    problems: tuple[str, ...] = ()


@dataclass
class Install:
    """`[install]`: the extras of `pyproject.toml` each version's environment is built with.

    Declared rather than guessed: an environment is made anew for every version,
    and what was added to the one before by hand would be gone. See environment.py.
    """

    extras: tuple[str, ...] = ()


@dataclass
class Config:
    runner: Runner
    path: Path
    web: Web = field(default_factory=Web)
    notify: Notify = field(default_factory=Notify)
    openrouter: OpenRouter = field(default_factory=OpenRouter)
    speech: Speech = field(default_factory=Speech)
    browser: Browser = field(default_factory=Browser)
    claude: Claude = field(default_factory=Claude)
    budget: Budget = field(default_factory=Budget)
    review: Review = field(default_factory=Review)
    permissions: Permissions = field(default_factory=Permissions)
    vault: Vault = field(default_factory=Vault)
    install: Install = field(default_factory=Install)
    # The board's vocabulary — its columns, statuses and types: see `PROPERTIES`.
    board: BoardNames = field(default_factory=BoardNames)
    # `[github]`: which of your GitHub accounts each owner is worked under, as
    # `owner = "the gh account"`. Empty is a machine with one account, which is
    # every machine until it is not — see `git.token_for`.
    github: dict[str, str] = field(default_factory=dict)
    github_access: GithubAccess = field(default_factory=GithubAccess)
    # The secrets `config.toml` still holds, as `table.key` — ignored, and said
    # so: see `move_secrets`.
    exposed: tuple[str, ...] = ()

    @property
    def console_url(self) -> str:
        """Where the console is reached, for the links Ponos writes: `web.url`, else this machine's."""
        if self.web.url:
            return self.web.url.rstrip("/")
        host = "127.0.0.1" if self.web.host in ("", "0.0.0.0", "::") else self.web.host  # noqa: S104
        return f"http://{host}:{self.web.port}"


# The board's columns, as `ponos.db` keeps them and every pass reads them.
#
# Fixed, and not a setting: a name somebody could change was a name every
# check, every fallback and every test had to read through a setting, for one
# spelling. The options of the selects are French where they are words —
# Rédaction, Amélioration, réussi — because that is the language the board is
# written in; the statuses are the board's short lowercase keywords.
PROPERTIES = {
    "status": "statut",
    "project": "Project",
    # Which machine took the ticket, as ponos@host. Not to be confused
    # with `role` below: this one is a runner, that one is a craft.
    "agent": "Agent",
    "pull_request": "Pull Request",
    "session": "Session",
    # Optional. A database without them behaves exactly as before: the runner
    # skips a property the schema does not declare.
    "model": "Model",  # per-ticket model, overrides runner.model
    "priority": "Priorité",  # a score from 0 to 100: which ready ticket goes first
    "cost": "Cost",  # written back, in dollars
    "duration": "Duration",  # written back, in minutes
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
    # would have said it left the board.
    "waiting": "Waiting for credit",  # checkbox: ticked while the credit is out
    # Ticked, the ticket's first session only plans, and the work waits for a
    # yes — see planning.py. An attribute too, for the same reason: the ticket
    # runs and asks like any other, and only what its session may do changes.
    "plan": "Plan d'abord",  # checkbox: plan first, then wait for a yes
    # What kind of work the ticket is — Code, Rédaction, Action externe or
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
    # Why a blocked ticket stopped: a code of blocks.py, as a select the
    # console filters on. Written when it stops, emptied when it leaves.
    "block": "Blocage",
    # The state of the pull request's checks while the ticket is in review: a
    # select with three options (see ci.py), emptied for a repository without CI.
    "ci": "CI",
    # Relation to the Agents database: the role a ticket is handled with.
    # Optional, like the goal — and not « Agent », which is the machine's.
    "role": "Rôle",
    # Relation to the Objectifs database: what the ticket is for. Named in the
    # singular for the same reason, and only its first page is read.
    "goal": "Objectif",
    # Relation to the tickets database itself: the tickets this one comes after.
    # It is not started while one of them is anything but done — see
    # dependencies.py. Optional, like the goal: a board without it runs as before.
    "after": "Après",
    # The Schedules database, for what comes back on its own. The first four are
    # what you fill in; the last three are what a pass writes back. A workspace
    # without that database never reads any of them.
    "cadence": "Cadence",  # select: Hourly, Daily, Weekly, Monthly
    "at": "At",  # text: "09:00"
    "day": "Day",  # text: "Monday", or "1".."31"
    "active": "Active",  # checkbox: unticked stops everything
    "next_run": "Next",  # date: when the next ticket is born
    "last_run": "Last",  # date: when the last one was
    "last_ticket": "Last ticket",  # relation → the tickets database
}

# The five types of ticket, told apart by the road they take rather than by what
# they are about — see kinds.py. The keys are what the code says; the values are
# the options of the board's Type column.
TYPES = {
    "code": "Code",
    "writing": "Rédaction",
    "external": "Action externe",
    "publication": "Publication",
    "diagnostic": "Diagnostic",
}

# The types `runner.force_validated` may name. A diagnostic is not one of them:
# it closes by itself once its fix tickets are written, and nothing of it waits
# for a review.
VALIDATED = tuple(kind for kind in TYPES if kind != "diagnostic")

# The other spellings an option is still recognised by: the English words a
# board was typed with before the names were fixed, and one without its accent.
_TYPE_ALIASES = {
    "writing": ("Writing", "Redaction"),
    "external": ("External action",),
}

# The statuses of the board, and they are meant to be read in that order.
#
# "review" rather than "done": nothing is done when the runner lets go of a
# ticket — a pull request is waiting for a human, and calling that done is how a
# board stops being believed.
#
# One status for a ticket that stopped, "blocked", whether the agent asked a
# question or a session crashed: the board has one column for both, and the
# block cause (`Blocage`, see blocks.py) is what tells them apart. A `failed`
# status beside it pointed at the same column for as long as there was a board.
#
# "validated" is the answer to the question "review" asks. Reviewing ends in a
# gesture — merge this, publish this — and that gesture is the one thing a
# board cannot do for you and the runner should not decide alone. So you move
# the ticket one column to the right, and the runner does the gesture: it
# merges the pull request, or it publishes what the ticket holds, and only then
# is anything done.
#
# There is no status for "the credit ran out": a ticket nothing was started for
# has not moved, so nothing on the board should say it did. It stays where it
# was and is ticked — see `waiting` in `PROPERTIES`.
#
# "paused" is a ticket you stopped on purpose, with its worktree and its branch
# kept: the runner never takes it back by itself, and only moving it to ready
# runs it again — from the work already there, as any ticket that has run before.
#
# "cancelled" is the other end of a ticket, beside done: given up on, not
# finished. Terminal like it — the runner never runs it, never takes it back —
# and apart from it, because a board that files the tickets nobody wanted any
# more under done is a board whose done stops meaning "this got done".
#
# "draft" is a ticket still being written: the runner never reads nor writes it,
# and never picks it up.
STATUS = {
    "ready": "ready",
    "running": "progress",
    "review": "review",
    "validated": "validated",
    "done": "done",
    "blocked": "blocked",
    "paused": "paused",
    "cancelled": "cancelled",
    "draft": "draft",
}


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
    """Set — or, with `value=None`, remove — one key of one table of the file.

    The CLI's way in (`ponos notify pair`), and the console's
    one: through `edit`, so that the real file is only ever replaced whole and
    under its lock — written in place, a process killed between the truncation
    and the write left a configuration that no longer parsed. See `_write_line`
    for what the edit itself keeps of the file.

    Returns whether anything changed.
    """
    return bool(edit(path, [(table, key, value)]))


def _write_line(path: Path, table: str, key: str, value: object) -> bool:
    """Set — or, with `value=None`, remove — one key of one table, in place.

    In place, so only ever on a copy (`edit`, `_scrub`): never on the file itself.

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
            body = body[: existing.start()] + line + body[existing.end() :]
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

    A secret is not the file's: it goes to Ponos's vault (`keep_secrets`), once
    the copy has been loaded with it, and whatever line `config.toml` still had
    for it goes.

    The file it displaces is kept as `config.toml.bak`, which is what you want
    the first time a save turns out to have been the wrong idea.

    Two saves at once — two tabs, a tab and the CLI — take turns, under
    `_locked`: each read the file, then replaced it with its copy, and the copy
    of the second was made from the file as it was before the first.

    Returns the names of the keys that actually changed, `table.key` each.
    """
    with _locked(path):
        return _edit(path, changes)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """An exclusive flock beside the file, for as long as it is read and replaced.

    Not on the file itself: `os.replace` puts another inode in its place, and a
    save waiting on the old one would wake holding a lock nobody else asks for.
    The lock file stays — removed, the next save would lock a fresh one beside
    a save still holding the old (see `state.lock`).
    """
    lock = path.parent / f".{path.name}.lock"
    with open(lock, "a", encoding="utf-8", opener=disk.opener()) as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _edit(path: Path, changes: list[tuple[str, str, object]]) -> list[str]:
    """`edit`, once the lock is held."""
    original = path.read_text(encoding="utf-8")

    kept = kept_secrets()
    pending = dict(kept)
    secrets: dict[str, str | None] = {}
    touched: list[str] = []
    file_changes: list[tuple[str, str, object]] = []
    for table, key, value in changes:
        if (table, key) not in SECRETS:
            file_changes.append((table, key, value))
            continue
        name = SECRETS[(table, key)]
        typed = "" if value is None else str(value).strip()
        if name == WEB_PASSWORD_ENV and typed:
            # Kept as a digest from the first: see `passwords`.
            typed = _password_digest(typed)
        if typed != pending.get(name, ""):
            touched.append(f"{table}.{key}")
        secrets[name] = typed or None
        if typed:
            pending[name] = typed
        else:
            pending.pop(name, None)
        file_changes.append((table, key, None))

    # Named per call: two saves at once — two browser tabs, a tab and the CLI —
    # would otherwise edit the same copy and the loser would win.
    suffix = f"saving.{os.getpid()}.{threading.get_ident()}"
    scratch = path.parent / f".{path.name}.{suffix}"
    # Created private rather than tightened afterwards: a file from before the
    # vault may still hold a token, and a chmod after the write leaves a moment
    # in which the umask decides who reads it.
    disk.write_private(scratch, original)
    try:
        written = [
            f"{table}.{key}"
            for table, key, value in file_changes
            if _write_line(scratch, table, key, value)
        ]
        touched += [name for name in written if name not in touched]
        if not touched:
            return []
        try:
            load(scratch, secrets=pending)
        # Broad on purpose: the loader coerces as it reads, and anything it
        # refuses to read — a port that is not a number, a path that is not one
        # — has to come back as "not saved" rather than as a traceback and half
        # a file. The scratch copy is what took it, so there is nothing to undo.
        except Exception as error:
            raise ConfigError(
                f"that would leave the configuration unusable — "
                f"{str(error).splitlines()[0].replace(str(scratch), str(path))}"
            ) from error
        if pending != kept:
            try:
                keep_secrets(secrets)
            except (vault.VaultError, sqlite3.Error) as error:
                raise ConfigError(
                    f"the secret could not be kept in Ponos's vault — {error}"
                ) from error
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
        if scratch.exists():
            scratch.unlink()
    return touched


def read_raw(path: Path) -> dict[str, Any]:
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


def _section(raw: dict[str, Any], table: str) -> dict[str, Any]:
    """One table of a parsed file, dots followed: "notify.telegram" too."""
    node: object = raw
    for part in table.split("."):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def exposed(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """The secrets a parsed `config.toml` still holds — which `load` ignores.

    An empty value is no secret, and nor is the example's placeholder: both are
    only where one used to go.
    """
    return [
        (table, key)
        for table, key in SECRETS
        if str(_section(raw, table).get(key, "") or "").strip()
    ]


# One line of a `secrets.env` from before the vault — the shape compose's
# `env_file`, systemd's `EnvironmentFile` and a shell's `source` all read.
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_secrets(path: Path) -> dict[str, str]:
    """A `secrets.env` as `NAME → value`; nothing at all when there is no file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
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


def kept_secrets() -> dict[str, str]:
    """Ponos's own secrets as its vault keeps them, `NAME → value`.

    Nothing when the vault cannot be opened — its key gone, the file refused:
    the environment still answers, and `ponos doctor` says why the vault does
    not (`vault_store.problem`).
    """
    from . import vault_store

    try:
        return vault_store.own()
    except (vault.VaultError, sqlite3.Error, OSError):
        return {}


def keep_secrets(values: dict[str, str | None]) -> list[str]:
    """Set — or, with `None`, remove — some of Ponos's own secrets in its vault.

    Returns the names whose value actually changed; raises `vault.VaultError`
    when the vault cannot be opened or written.
    """
    from . import vault_store

    return vault_store.keep_own(values)


def _scrub(target: Path, keys: list[tuple[str, str]]) -> None:
    """Remove those keys from a TOML file, in one replace and with its mode."""
    if not keys:
        return
    mode = target.stat().st_mode & 0o777
    scratch = target.parent / f".{target.name}.scrubbing.{os.getpid()}.{threading.get_ident()}"
    disk.write_private(scratch, target.read_text(encoding="utf-8"))
    try:
        for table, key in keys:
            _write_line(scratch, table, key, None)
        scratch.chmod(mode)
        os.replace(scratch, target)
    finally:
        if scratch.exists():
            scratch.unlink()


def move_secrets(path: Path) -> list[str]:
    """Take every secret out of `config.toml` and of `secrets.env`, into Ponos's vault.

    What a launch does before anything else (see `__main__`), because those
    two files were where the installer and the console used to write them, and
    an installation that updates itself must not wake up without its token.
    Moved rather than copied: a secret left in clear is the very thing this is
    about. A name the vault already holds is not overwritten — it was put there
    later than the line either file kept — and `secrets.env` wins over
    `config.toml`, for the same reason.

    `config.toml.bak` is scrubbed too, being yesterday's copy of the same file;
    `secrets.env` is deleted once every line of it is in the vault, those of
    `[vault] provider = "env"` included (`vault.Environment` reads them there).

    Returns what was moved, `table.key` for a line of `config.toml` and the
    name for one of `secrets.env`; raises OSError or `vault.VaultError` when
    the move cannot be made, and then both files are left as they were.
    """
    with _locked(path):
        return _move_secrets(path)


def _move_secrets(path: Path) -> list[str]:
    """`move_secrets`, under the lock a save takes too."""
    raw = read_raw(path)
    found = exposed(raw)
    legacy = legacy_secrets_path(path)
    lines = read_secrets(legacy)
    if not found and not legacy.exists():
        return []
    from . import vault_store

    held = set(vault_store.own_names()) if (found or lines) else set()
    moving: dict[str, str | None] = {}
    for table, key in found:
        name = SECRETS[(table, key)]
        if name not in held:
            moving[name] = str(_section(raw, table)[key]).strip()
    for name, value in lines.items():
        if name not in held and value.strip():
            moving[name] = value
    if moving.get(WEB_PASSWORD_ENV):
        moving[WEB_PASSWORD_ENV] = _password_digest(str(moving[WEB_PASSWORD_ENV]))
    if moving:
        keep_secrets(moving)
    _scrub(path, found)
    backup = path.parent / f"{path.name}.bak"
    if backup.exists():
        _scrub(backup, exposed(read_raw(backup)))
    legacy.unlink(missing_ok=True)
    # A line `write_value` cannot reach — an inline table — stays, and `load`
    # keeps saying so: only what actually left is reported as moved.
    left = set(exposed(read_raw(path)))
    return [f"{table}.{key}" for table, key in found if (table, key) not in left] + sorted(
        name for name in lines if name in moving
    )


def _password_digest(value: str) -> str:
    """The console's password as the vault keeps it — a digest already stays one.

    Stripped first, as `secret` strips what it reads back: the password that
    was compared in clear was the stripped one, and the digest has to be of it.
    """
    value = value.strip()
    return value if passwords.is_digest(value) else passwords.digest(value)


def hash_password() -> bool:
    """Replace a password the vault keeps in clear by its digest.

    The console writes a digest from the first; this is for a password put in
    the vault some other way. Nobody is asked to type it again: the digest is
    of the very value that was there. The environment's is left alone, being
    the unit's or the compose file's to keep; the console digests it in memory
    (`web.server.sign_in`).

    Returns whether anything was written; raises `vault.VaultError` when the
    vault cannot be written.
    """
    kept = kept_secrets().get(WEB_PASSWORD_ENV, "").strip()
    if not kept or passwords.is_digest(kept):
        return False
    keep_secrets({WEB_PASSWORD_ENV: _password_digest(kept)})
    return True


def secret(stored: dict[str, str], table: str, key: str) -> str:
    """One secret, from Ponos's vault (`stored`) or the environment — see the docstring.

    Both remembered, to be masked wherever the runner writes (see vault.py):
    the one that loses is no less a secret for it.
    """
    name = SECRETS[(table, key)]
    environment = os.environ.get(name, "").strip()
    written = stored.get(name, "").strip()
    vault.remember(environment)
    vault.remember(written)
    if name in _ENVIRONMENT_FIRST:
        return environment or written
    return written or environment


def load(path: Path | None = None, *, secrets: dict[str, str] | None = None) -> Config:
    """The runner's reading of the file — and of its secrets, which are elsewhere.

    `secrets` are the secrets when they are not the vault's: those `edit`
    checks before it keeps anything. What each key may hold is
    schema.py's; what is put together here is what the file does not say — the
    secrets, the environment, the defaults that depend on where this runs.
    """
    target = path or config_path()
    raw, file = _validated(target)
    stored = kept_secrets() if secrets is None else secrets
    runner = _runner(file.runner)
    return Config(
        runner=runner,
        path=target,
        web=_web(file.web, stored),
        notify=_notify(file.notify, stored, runner),
        # The sessions run on OpenRouter exactly when that is the provider chosen:
        # `route_sessions` is no key of the file any more.
        openrouter=OpenRouter(
            key=secret(stored, "openrouter", "key"),
            route_sessions=file.claude.provider == "openrouter",
        ),
        speech=Speech(),
        browser=Browser(),
        claude=Claude(
            provider=file.claude.provider,
            api_key=secret(stored, "claude", "api_key"),
            attribution=file.claude.attribution,
        ),
        budget=Budget(**file.budget.model_dump()),
        review=Review(),
        permissions=Permissions(**file.permissions.model_dump()),
        vault=_vault(file.vault),
        install=Install(extras=file.install.extras),
        github=dict(file.github),
        github_access=_github_access(file.github_access, stored),
        exposed=tuple(f"{table}.{key}" for table, key in exposed(raw)),
    )


class MissingLibrary(ConfigError):
    """This Python has no pydantic, and the file is not read without it.

    The machine's own Python, running a version an older one installed before
    it had an environment: see `readable` and `__main__.command_run`.
    """


def readable() -> bool:
    """Can this Python read the file — is pydantic installed for it?"""
    try:
        from . import schema  # noqa: F401
    except ImportError:
        return False
    return True


def _validated(target: Path) -> tuple[dict[str, Any], schema.File]:
    """The file as TOML says it, and read against schema.py.

    Or a ConfigError naming what is wrong — a key no table reads included.
    """
    if not target.exists():
        raise ConfigError(
            f"configuration not found: {target}\n"
            "  reinstall with install.sh, or copy config.example.toml"
        )
    text = target.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{target} is not valid TOML: {error}") from error
    try:
        from . import schema
    except ImportError as error:
        raise MissingLibrary(
            f"{target} cannot be read by {sys.executable}: it has no {error.name or 'pydantic'}. "
            "This version's environment is missing it — ponos update --environment makes it, "
            "and so does the next run"
        ) from error
    return raw, schema.read(raw, text, target)


def _runner(table: schema.RunnerTable) -> Runner:
    """The runner the file describes: its ~16 keys, every other setting the constant it was."""
    forced = table.force_validated
    read = table.model_dump(exclude={"force_validated"})
    return Runner(
        **{
            **read,
            "workspace_root": Path(os.path.expanduser(table.workspace_root)),
            # The file first: a language picked in Settings is a decision taken
            # later than the deployment that set the environment.
            "language": table.language or os.environ.get(LANGUAGE_ENV, "").strip(),
            **{f"force_validated_{kind}": kind in forced for kind in VALIDATED},
        }
    )


def _web(table: schema.WebTable, stored: dict[str, str]) -> Web:
    return Web(
        **{
            **table.model_dump(),
            "token": secret(stored, "web", "token"),
            # The environment first, so a unit file or a container can hold the
            # credentials rather than the file. Stripped like every other secret
            # here: a password read out of a file would otherwise carry the
            # newline that file ends with, and lock you out of your own console.
            "email": (os.environ.get(WEB_EMAIL_ENV) or table.email).strip(),
            "password": secret(stored, "web", "password"),
            "trusted_proxies": _trusted_proxies(),
        }
    )


def _trusted_proxies() -> tuple[str, ...]:
    """The proxies whose forwarded address is believed: the environment's, or the default.

    No longer a key of the file — a unit file or a container holds it, as it
    already could.
    """
    written = os.environ.get(TRUSTED_PROXIES_ENV, "")
    found = tuple(entry for entry in (part.strip() for part in written.split(",")) if entry)
    return found or Web.trusted_proxies


def _notify(table: schema.NotifyTable, stored: dict[str, str], runner: Runner) -> Notify:
    # `runner.notify` came first and said "one desktop notification per ticket".
    # It keeps saying exactly that: the new table only has to name what it
    # changes, and a file written before any of this existed behaves as it did.
    return Notify(
        desktop=runner.notify if table.desktop is None else table.desktop,
        events=table.events,
        digest=table.digest,
        telegram=_channel(table.telegram, secret(stored, "notify.telegram", "token")),
        slack=_channel(table.slack, secret(stored, "notify.slack", "token")),
    )


def _channel(table: schema.TelegramTable | schema.SlackTable, token: str) -> dict[str, str]:
    """One [notify.<channel>] table, as the strings it says — and its token.

    The keys the file writes, and only those. The bot's token is put in from
    where secrets live, and a `token` the table still carries is left out.
    """
    read: dict[str, str] = table.model_dump(exclude_unset=True)
    if token:
        read["token"] = token
    return read


def read_github_access(raw: dict[str, Any], stored: dict[str, str]) -> GithubAccess:
    """`[github_access]` and its token, read again — the console writes them as it runs.

    Read leniently, as a table that does not validate says nothing.
    """
    from . import schema

    try:
        table = schema.GithubAccessTable.model_validate(
            _section(schema.without_secrets(raw), "github_access")
        )
    except ValueError:  # pydantic's ValidationError
        table = schema.GithubAccessTable()
    return _github_access(table, stored)


def _github_access(table: schema.GithubAccessTable, stored: dict[str, str]) -> GithubAccess:
    return GithubAccess(
        mode=table.mode,
        token=secret(stored, "github_access", "token"),
        token_item=table.token_item,
    )


# The key Ponos's own vault is opened with, when the environment gives it (vault_store.py).
VAULT_KEY_ENV = "PONOS_VAULT_KEY"


def reserved_variables() -> set[str]:
    """The variables that are the runner's own: never a project's, from any vault."""
    return set(SECRETS.values()) | {"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", VAULT_KEY_ENV}


def _vault(table: schema.VaultTable) -> Vault:
    """`[vault]`, checked: a provider Ponos does not know is said."""
    found: list[str] = []
    if table.provider not in vault.PROVIDERS:
        found.append(f"vault.provider = {table.provider!r} is none of {', '.join(vault.PROVIDERS)}")
    return Vault(provider=table.provider, problems=tuple(found))
