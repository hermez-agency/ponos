"""What every test file of the core shares, and what makes them run without pytest.

The suite is cut into one file per module — `test_update.py` for `update.py`,
`test_web_server.py` for `web/server.py` — so that two tickets touching two
modules touch two files. What more than one of those files needs lives here:
the doubles of a session, of a board, and the fixtures.

A fixture is written once, as a generator that receives the case it serves,
and both runners use it: `conftest.py` hands it to pytest under its name, and
`call` below opens it for `python3 tests/run.py` by reading the names of a
case's parameters — the one thing pytest does that the suite needs, done in a
dozen lines, so that running it still needs nothing installed beyond the
runner's own `requirements.txt`.
"""

from __future__ import annotations

import argparse
import contextlib
import inspect
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ponos import (
    channels,
    conversation,
    db,
    environment,
    github_app,
    github_checks,
    github_token,
    images,
    ledger,
    leftovers,
    log,
    pages,
    projects,
    provider,
    session,
    store,
    workspace,
)
from ponos import config as C
from ponos import git as git_module
from ponos import http as http_module
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import api as web_api
from ponos.web import board as web_board
from ponos.web import live as web_live
from ponos.web import settings as web_settings

if TYPE_CHECKING:
    from ponos.web import app as web_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


# A case takes its fixtures by name, and a fixture is handed the case it serves.
Case = TypeVar("Case", bound=Callable[..., None])
Fixture = TypeVar("Fixture", bound=Callable[[Callable[..., None]], Iterator[Any]])

CASES: list[Callable[..., None]] = []
FIXTURES: dict[str, Callable[[Callable[..., None]], Iterator[Any]]] = {}


def case(function: Case) -> Case:
    CASES.append(function)
    return function


class Skip(Exception):
    """A case that cannot run here — `raise Skip(reason)`: reported, not failed."""


def fixture(function: Fixture) -> Fixture:
    """A fixture both runners know, by its name: `function(case)` yields its value."""
    FIXTURES[function.__name__] = function
    return function


def call(function: Callable[..., None]) -> None:
    """Run one case the way pytest would, its fixtures opened and closed around it."""
    with fresh_vault(), contextlib.ExitStack() as stack:
        values = {
            name: stack.enter_context(contextmanager(FIXTURES[name])(function))
            for name in inspect.signature(function).parameters
        }
        function(**values)


def _outcome(index: int) -> tuple[str, str, str]:
    """One case, in a worker: its name, its traceback when it failed, its reason when skipped."""
    function = CASES[index]
    try:
        call(function)
    except Skip as skipped:
        return function.__name__, "", str(skipped)
    except Exception:  # noqa: BLE001 — a test runner reports, it does not raise
        return function.__name__, traceback.format_exc(), ""
    return function.__name__, "", ""


def run(argv: list[str]) -> int:
    """What `python3 tests/run.py` and `python3 tests/functional.py` do with `CASES`.

    The cases are shared among one process per core, as `pytest -n auto` shares
    them: forked once every file is imported, each worker `isolate`s itself
    and is handed the cases one by one, so that none can lean on another having
    run before it. `-j 1` runs them in this process, in order. As `-n auto`,
    the default heeds `PYTEST_XDIST_AUTO_NUM_WORKERS`: a ticket's session is
    handed its share of the cores in it (session.WORKERS).
    """
    parser = argparse.ArgumentParser()
    share = os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", "")
    default = int(share) if share.isdigit() and int(share) > 0 else os.cpu_count() or 1
    parser.add_argument("-j", "--jobs", type=int, default=default)
    jobs = parser.parse_args(argv).jobs
    started = time.monotonic()
    failures = skips = 0
    if jobs > 1 and "fork" in multiprocessing.get_all_start_methods():
        pool = multiprocessing.get_context("fork").Pool(jobs, initializer=isolate)
    else:
        isolate()
        pool = None
    with pool or contextlib.nullcontext():
        outcomes = (pool.imap if pool else map)(_outcome, range(len(CASES)))
        for name, failure, skipped in outcomes:
            if failure:
                failures += 1
                print(f"  ✗ {name}")
                print("".join("      " + line for line in failure.splitlines(True)))
            elif skipped:
                skips += 1
                print(f"  - {name} (skipped: {skipped})")
            else:
                print(f"  ✓ {name}")
    total = len(CASES) - skips
    print(
        f"\n{total - failures}/{total} passed"
        + (f", {skips} skipped" if skips else "")
        + f" in {time.monotonic() - started:.1f}s"
    )
    return 1 if failures else 0


@contextmanager
def fresh_vault() -> Iterator[None]:
    """Around each case: the vault of the worker's state, and its key, gone after it.

    Ponos's own secrets live in `vault.db`, under `XDG_STATE_HOME` — which a
    worker shares between every case it runs — and not beside a case's own
    `config.toml`: a token one case saves would otherwise be read by the next.
    """
    from ponos import vault_store

    try:
        yield
    finally:
        for leftover in (vault_store.path(), vault_store.key_path(), vault_store._pending_path()):
            leftover.unlink(missing_ok=True)
        vault_store._own_kept = None


# A tidy prunes Docker, and this machine's Docker is not the test's to prune.
# The one case that checks what is asked of it puts the real one back.
REAL_PRUNE = leftovers.prune_docker
leftovers.prune_docker = lambda: False


@fixture
def state_home(case: Callable[..., None]) -> Iterator[Path]:
    """A throwaway XDG_STATE_HOME: what the runner keeps between two runs, the case's alone."""
    with _state_home() as path:
        yield path


@fixture
def vault_home(case: Callable[..., None]) -> Iterator[Path]:
    """A vault of Ponos of the case's own: its state, its `vault.key`, and no keyring.

    The keyring is the machine's: a case that wants one puts a `secret-tool`
    of its own in front of the `PATH` and says so (`vault_store.keyring_usable`).
    """
    from ponos import vault, vault_store

    config = os.environ.get("XDG_CONFIG_HOME")
    usable = vault_store.keyring_usable
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    vault_store.keyring_usable = lambda: False
    vault.forget()
    try:
        with _state_home() as path:
            yield path
    finally:
        vault.forget()
        vault_store.keyring_usable = usable
        os.environ.pop(C.VAULT_KEY_ENV, None)
        if config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = config


@fixture
def installation(
    case: Callable[..., None],
) -> Iterator[tuple[Callable[..., str], Path, str]]:
    """An installation of this very runner: `(commit, app, first)`, see `_installable`."""
    with _installable() as installed:
        yield installed


# The variables a machine may export that the runner reads for GitHub, or to
# choose who answers a session — none of which a case may inherit.
MACHINE = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GIT_CONFIG_COUNT",
    C.GITHUB_TOKEN_ENV,
    github_app.APPS_ENV,
    github_app.WEB_ENV,
    "PONOS_GITHUB_OWNER",
    "PONOS_GITHUB_LAPSES",
    C.OPENROUTER_KEY_ENV,
    C.ANTHROPIC_KEY_ENV,
    provider.OAUTH_TOKEN_ENV,
    C.VAULT_KEY_ENV,
)


def isolate() -> None:
    """What the whole suite runs under, whoever starts it: `main` or pytest."""
    # Claude Code's own store, pointed at an empty directory for the whole
    # suite. Everything here is pure, and "how much of this machine's
    # subscription is spent" is the least pure fact there is: a laptop at 96 %
    # would otherwise park tickets in a test about something else entirely, and
    # a CI runner with no store at all would take a different road again. The
    # tests that are *about* the reading say so themselves — see `_usage`.
    os.environ["CLAUDE_CONFIG_DIR"] = tempfile.mkdtemp()
    # The runner's own state, for two reasons: a test that runs a session writes
    # its run into the local journal, and opening the real `ponos.db` would
    # migrate it and set aside the JSON files the installed runner still reads.
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    # And its configuration directory, where the vault's key is written when
    # the keyring does not take it — never the machine's `vault.key`, nor its
    # keyring: Ponos's own secrets are in that vault (see `fresh_vault`).
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    from ponos import vault_store

    vault_store.keyring_usable = lambda: False
    # GitHub, for a machine that has connected an app: an address nothing
    # listens on, so a test that reaches `git.token_for` falls back on `gh` at
    # once rather than asking the real GitHub for a token. The tests about the
    # app replace the transport itself — see `_github_answering`.
    os.environ[github_app.API_ENV] = "http://127.0.0.1:9"
    # And what the machine itself says about GitHub and about who answers its
    # sessions, dropped: a laptop where `gh` is set up, or a cloud session,
    # exports a token and a `GIT_CONFIG_COUNT` that `git.run` and
    # `github_app._config` would build on, and a provider key would take a
    # session's road away from the CLI. A case that wants one poses it.
    for name in list(os.environ):
        if name in MACHINE or name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            del os.environ[name]


# -- the doubles more than one file uses -------------------------------------


def _config(
    body: str = "",
    *,
    web: dict[str, Any] | None = None,
    openrouter: dict[str, Any] | None = None,
    speech: dict[str, Any] | None = None,
    notify: dict[str, Any] | None = None,
    **runner: Any,
) -> C.Config:
    """A configuration read from `body`; the rest sets the constants the file cannot.

    `runner` for the runner's, and a dict for each other table: `web={"poll_seconds": 5}`.
    """
    config = _file_config(body)
    if runner:
        config = replace(config, runner=replace(config.runner, **runner))
    if web:
        config = replace(config, web=replace(config.web, **web))
    if openrouter:
        config = replace(config, openrouter=replace(config.openrouter, **openrouter))
    if speech:
        config = replace(config, speech=replace(config.speech, **speech))
    if notify:
        config = replace(config, notify=replace(config.notify, **notify))
    return config


def _file_config(body: str) -> C.Config:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(body)
    # Written the way a file used to be, and read the way a launch leaves it:
    # its secrets moved into the vault.
    _launched(path)
    return C.load(path)


def _settings(**overrides: Any) -> C.BoardNames:
    return C.BoardNames(**overrides)


class _CommentClient:
    def __init__(self, texts: list[str], error: str = "") -> None:
        self._texts, self._error = texts, error

    def comments(self, page_id: str) -> list[store.Comment]:
        if self._error:
            raise store.StoreError(self._error)
        return [store.Comment(text) for text in self._texts]


def _bare_runner(client: Any) -> Runner:
    """A Runner with its board replaced, and nothing else touched."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = client
    runner.config = _config("")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner._comments = {}
    runner._usage_warned = False
    runner._spellings = conversation.names()
    runner._me = ""  # the board never said; the signature is all there is
    runner._identity_error = ""
    return runner


def _runner_reading(texts: list[str], error: str = "") -> tuple[Runner, list[str]]:
    runner = _bare_runner(_CommentClient(texts, error))
    ticket = type("T", (), {"page": store.Page(id="p-ticket", url="", title="t")})()
    return runner, runner.discussion(ticket)


ME = "bot-user-id"


def _said(text: str, *, by: str = "human", thread: str = "d1", ident: str = "") -> store.Comment:
    return store.Comment(
        text,
        id=ident or f"c-{abs(hash((text, thread))) % 10**6}",
        discussion_id=thread,
        created_by=by,
    )


class _Unblocking(Runner):
    """A runner that only has what `_examine` asks of it, and says what it did."""

    moved: list[dict[str, object]]
    comments_written: list[str]

    def _project_of(self, ticket: ticket_module.Ticket) -> projects.Project:
        return projects.Project(name="", path=None)

    def _body(self, ticket: ticket_module.Ticket, *, done: bool = False) -> str:
        return "Dépend du ticket B."

    def discussion(self, ticket: ticket_module.Ticket) -> list[str]:
        return []

    def _set(self, ticket: ticket_module.Ticket, **values: object) -> None:
        self.moved.append(values)

    def _comment(self, ticket: ticket_module.Ticket, text: str, discussion: str = "") -> None:
        self.comments_written.append(text)

    def comments(self, page_id: str) -> list[store.Comment]:
        return [store.Comment(text) for text in self.comments_written[-1:]]

    def _hold_credits(self, outcome: session.Outcome) -> None:
        pass

    @property
    def workspace(self) -> workspace.Workspace:
        return workspace.Workspace(tickets="db", projects="projects", agents="agents")


@contextmanager
def _no_session(
    answer: str = "Parce que la branche d'hier était déjà en revue.",
    ok: bool | list[bool] | tuple[bool, ...] = True,
    writes: dict[str, str] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Claude, replaced by its answer. Records how it was asked.

    `ok` may be a list, read one entry per call: that is how a session that
    cannot be resumed is told from one that has nothing to say. `writes` is
    `{name: text}` left in the working directory — which is how a document
    ticket answers, the session writing ANSWER.md rather than saying anything.
    """
    calls: list[dict[str, Any]] = []
    verdicts = list(ok) if isinstance(ok, (list, tuple)) else None
    always = ok if isinstance(ok, bool) else True

    def fake_run(prompt_text: str, **kwargs: Any) -> session.Outcome:
        calls.append({"prompt": prompt_text, **kwargs})
        good = verdicts.pop(0) if verdicts else always
        for name, text in (writes or {}).items():
            (Path(kwargs["cwd"]) / name).write_text(text, encoding="utf-8")
        return session.Outcome(
            ok=good,
            blocked=False,
            session_id=kwargs.get("session_id", "s-1"),
            summary="",
            log=Path("/tmp/none.jsonl"),
            answer=answer if good else "",
            error="" if good else "claude exited with code 1",
            seconds=12.0,
            cost_usd=0.01,
        )

    original = session.run
    session.run = fake_run  # type: ignore[assignment]  # a double: it reads the keywords it is given
    try:
        yield calls
    finally:
        session.run = original


def _schedule_page(page_id: str, **values: Any) -> store.Page:
    """One row of the Schedules collection, as the board hands it over."""
    last_ticket = values.get("last_ticket", "")
    return store.Page(
        id=page_id,
        url=f"https://board.invalid/{page_id}",
        title=values.get("name", "Revue des dépendances"),
        properties={
            "Cadence": {"type": "select", "select": {"name": values.get("cadence", "Daily")}},
            "At": {"type": "rich_text", "rich_text": [{"plain_text": values.get("at", "09:00")}]},
            "Day": {"type": "rich_text", "rich_text": [{"plain_text": values.get("day", "")}]},
            "Active": {"type": "checkbox", "checkbox": values.get("active", True)},
            "Next": {
                "type": "date",
                "date": {"start": values["next"]} if values.get("next") else None,
            },
            "Last": {"type": "date", "date": None},
            "Last ticket": {
                "type": "relation",
                "relation": [{"id": last_ticket}] if last_ticket else [],
            },
            "Project": {"type": "relation", "relation": [{"id": "p-northwind"}]},
            "Priorité": {"type": "number", "number": 40},
            **(
                {"Type": {"type": "select", "select": {"name": values["type"]}}}
                if values.get("type")
                else {}
            ),
            **(
                {"Sous-type": {"type": "select", "select": {"name": values["subtype"]}}}
                if values.get("subtype")
                else {}
            ),
            **(
                {"Model": {"type": "select", "select": {"name": values["model"]}}}
                if values.get("model")
                else {}
            ),
        },
    )


class _ScheduleClient:
    """A schedules database, a tickets database, and nothing that reaches out."""

    def __init__(
        self,
        pages: list[store.Page],
        tickets: dict[str, store.Page] | None = None,
        refuses: str = "",
        marks: str = "",
        columns: dict[str, str] | None = None,
    ) -> None:
        self._pages = pages
        self._tickets = tickets or {}
        self._refuses = refuses
        # What a write on a schedule row is answered with, and what the
        # schedules database says its columns are.
        self._marks = marks
        self._columns = columns or {}
        self.written: list[tuple[str, dict[str, Any]]] = []
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.appended: list[tuple[str, str]] = []
        self.trashed: list[str] = []

    def schema(self, database_id: str) -> dict[str, str]:
        if database_id == "db-schedules":
            return dict(self._columns)
        return {"statut": "status"}

    def trash(self, page_id: str) -> str:
        self.trashed.append(page_id)
        self._pages = [page for page in self._pages if page.id != page_id]
        return f"https://board.invalid/{page_id}"

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[store.Page]:
        return list(self._pages)

    def page(self, page_id: str) -> store.Page:
        if page_id in self._tickets:
            return self._tickets[page_id]
        raise store.StoreError(f"{page_id}: object not found")

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if self._marks and database_id == "db-schedules":
            raise store.StoreError(self._marks)
        self.written.append((page_id, dict(values)))

    def create_row(self, database_id: str, title: str, values: dict[str, Any] | None = None) -> str:
        if self._refuses:
            raise store.StoreError(self._refuses)
        self.created.append((title, dict(values or {})))
        return f"t-{len(self.created)}"

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return "Lister les dépendances en retard, et dire lesquelles comptent."

    def append_markdown(self, page_id: str, markdown: str) -> int:
        self.appended.append((page_id, markdown))
        return 1


def _recurring(
    pages: list[store.Page],
    *,
    tickets: dict[str, store.Page] | None = None,
    refuses: str = "",
    marks: str = "",
    columns: dict[str, str] | None = None,
    schedule: bool = True,
    dry_run: bool = False,
) -> Runner:
    """A Runner with nothing underneath it but a schedules database."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = _ScheduleClient(pages, tickets, refuses, marks, columns)  # type: ignore[assignment]  # a fake: only the schedules
    runner.config = C.Config(
        runner=C.Runner(schedule=schedule, max_load_per_core=0),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db-tickets", schedules="db-schedules")
    runner.resolver = projects.Resolver(Path("/nowhere"), {})
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner.dry_run = dry_run
    return runner


@contextmanager
def _state_home() -> Iterator[Path]:
    """A throwaway XDG_STATE_HOME, for what the runner keeps between two runs."""
    previous = os.environ.get("XDG_STATE_HOME")
    cache = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    # Its cache too: the tidy sweeps the `tmp*` folders of `~/.cache`, and a
    # test must never be the one to sweep the developer's.
    os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp()
    try:
        yield Path(os.environ["XDG_STATE_HOME"]) / "ponos"
    finally:
        if cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = cache
        # Its database too: a connection left open per test is three file
        # descriptors, and the suite has hundreds of these. And the journal a
        # command opened there: the next test's directory is another one.
        db.close()
        log.close()
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous


@contextlib.contextmanager
def _installable() -> Iterator[tuple[Callable[..., str], Path, str]]:
    """An installation of this very runner, cloned from a remote of its own.

    Yields `(commit, app, first)`: `commit(message, change)` lands a commit on
    the remote after `change(work)` has edited its files. The launcher is
    written to a home of the test's own, and systemd is out of the PATH — an
    install that rewrote this machine's units would be a test gone too far.
    """
    quiet: dict[str, Any] = {"capture_output": True, "check": True}
    who = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    kept = {name: os.environ.get(name) for name in ("HOME", "PATH", "XDG_CONFIG_HOME")}
    with tempfile.TemporaryDirectory() as directory, _state_home():
        remote, work, app = (Path(directory) / name for name in ("remote.git", "work", "app"))
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)], **quiet)
        subprocess.run(["git", "clone", "--quiet", str(remote), str(work)], **quiet)
        ignore = shutil.ignore_patterns("__pycache__")
        for part in ("src", "bin", "systemd"):
            shutil.copytree(ROOT / part, work / part, ignore=ignore)

        def commit(message: str, change: Callable[[Path], object] = lambda work: None) -> str:
            change(work)
            subprocess.run(["git", "-C", str(work), "add", "-A"], **quiet)
            subprocess.run(
                ["git", *who, "-C", str(work), "commit", "--quiet", "--allow-empty", "-m", message],
                **quiet,
            )
            subprocess.run(
                ["git", "-C", str(work), "push", "--quiet", "origin", "HEAD:main"], **quiet
            )
            return subprocess.run(
                ["git", "-C", str(work), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        first = commit("one")
        subprocess.run(["git", "clone", "--quiet", str(remote), str(app)], **quiet)
        # git and nothing else on the PATH: no systemctl to reload this machine's units with.
        tools = Path(directory) / "bin"
        tools.mkdir()
        (tools / "git").symlink_to(shutil.which("git") or "/usr/bin/git")
        os.environ["HOME"], os.environ["PATH"] = directory, str(tools)
        # And the units under that home: a machine — a GitHub runner among
        # them — that exports `XDG_CONFIG_HOME` would have them written into
        # its own configuration (`update.units_dir`).
        os.environ.pop("XDG_CONFIG_HOME", None)
        # What a version's environment would download — FastAPI, for the
        # console its start is checked by (`update.verify`) — borrowed from this
        # process instead: the test stays offline, and as fast as it was.
        made = environment.create

        def create(app: Path, base: str | None = None) -> str:
            problem = made(app, base)
            borrowed = [path for path in sys.path if path.endswith("-packages")]
            for site in (app / environment.VENV / "lib").glob("python*/site-packages"):
                (site / "borrowed.pth").write_text("\n".join(borrowed), encoding="utf-8")
            return problem

        environment.create = create
        try:
            yield commit, app, first
        finally:
            environment.create = made
            for name, value in kept.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _head(app: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(app), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


class _BoardClient:
    """A tickets database that answers queries and remembers what was written."""

    def __init__(
        self, pages: list[store.Page], options: list[str] | None = None, waiting: bool = False
    ):
        self._pages = pages
        self._options = options if options is not None else ["review", "validated", "done"]
        # A board that predates the attribute simply has no such property, and
        # the runner then waits for the credit with nothing to show for it.
        self.waiting = waiting
        self.written: list[tuple[str, dict[str, Any]]] = []
        self.comments_written: list[str] = []
        self.queried: list[object] = []
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.bodies: list[str] = []
        self.sections: list[tuple[str, str]] = []
        # Columns a test adds to the board: the Runner one, to begin with.
        self.columns: dict[str, str] = {}

    def schema(self, database_id: str) -> dict[str, str]:
        schema = {"statut": "status", "Pull Request": "url", **self.columns}
        if self.waiting:
            schema["Waiting for credit"] = "checkbox"
        return schema

    def options(self, database_id: str, name: str) -> list[str]:
        return list(self._options)

    def me(self) -> str:
        return "u-runner"

    def comments(self, page_id: str) -> list[store.Comment]:
        return []

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return "Le post d'annonce, écrit la semaine dernière et relu depuis."

    def query(self, database_id: str, filter_: dict[str, Any] | None = None) -> list[store.Page]:
        self.queried.append(filter_)
        wanted = (filter_ or {}).get("status", {}).get("equals")
        return [page for page in self._pages if store.read(page, "statut") == wanted]

    def page(self, page_id: str) -> store.Page:
        # The very page the pass read: what a run holds is what the board says,
        # unless a test moves it underneath.
        for page in self._pages:
            if page.id.replace("-", "") == page_id.replace("-", ""):
                return page
        raise store.StoreError(f"GET /pages/{page_id}: 404 not found")

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        self.written.append((page_id, values))

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.comments_written.append(text)

    def create_row(self, database_id: str, title: str, values: dict[str, Any] | None = None) -> str:
        page_id = f"created{len(self.created)}"
        self.created.append((title, values or {}))
        status = (values or {}).get("statut", "")
        self._pages.append(
            store.Page(
                id=page_id,
                url="",
                title=title,
                properties={"statut": {"type": "status", "status": {"name": status}}},
            )
        )
        return page_id

    def append_markdown(self, page_id: str, text: str) -> None:
        self.bodies.append(text)

    def replace_section(self, page_id: str, titles: Sequence[str], markdown: str) -> int:
        # The part « What was done », as each run left it: the last one wins.
        self.sections.append((page_id, markdown))
        return 1


def _reviewed(page_id: str, status: str, pull_request: str | None) -> store.Page:
    properties: dict[str, Any] = {"statut": {"type": "status", "status": {"name": status}}}
    if pull_request is not None:
        properties["Pull Request"] = {"type": "url", "url": pull_request}
    return store.Page(id=page_id, url="", title=page_id, properties=properties)


def _board_runner(
    pages: list[store.Page],
    status: dict[str, str],
    options: list[str] | None = None,
    waiting: bool = False,
) -> Runner:
    """A Runner with nothing underneath it but a fake board."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = _BoardClient(pages, options, waiting)  # type: ignore[assignment]  # a fake: only the board
    runner.config = C.Config(
        # No update looked for mid-pass: that is a `git fetch` of this checkout.
        # Nor the load of whatever else this machine runs: a test case asks for it.
        runner=C.Runner(auto_update=False, max_load_per_core=0),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner.dry_run = False
    runner._claimed = set()
    runner._red = set()
    runner._holding, runner._explained = {}, None
    runner._following = set()
    runner._comments = {}
    runner._usage_warned = False
    runner._spellings = conversation.names()
    runner._me = ""
    runner._identity_error = ""
    runner._landed, runner._replayed_after = {}, {}
    runner._landed_lock = threading.Lock()
    runner._queues = {}
    runner.threads = conversation.Threads(database=Path(tempfile.mkdtemp()) / "ponos.db")
    return runner


@contextmanager
def _github(
    states: dict[str, str],
    merge: Callable[..., str] | None = None,
    blockers: dict[str, str] | None = None,
    unstarted: Callable[..., str] | None = None,
) -> Iterator[None]:
    """`gh`, replaced by what it would have said.

    `blockers` is what GitHub says stands in a pull request's way before a merge
    is asked — see `git.merge_blocker`. Nothing, unless a test says otherwise.
    `unstarted` reads why the red jobs of a refused merge never started — see
    `github_checks.unstarted_checks`: they all ran, unless a test says otherwise.
    """

    asked, original = git_module.pull_request_state, github_checks.merge_pull_request
    blocker = git_module.merge_blocker
    git_module.pull_request_state = lambda url, accounts=None: states.get(url, "")
    git_module.merge_blocker = lambda url, accounts=None: (blockers or {}).get(url, "")
    # Nothing is asked of GitHub about the checks of the pull requests still open.
    head = git_module.pull_request_head
    git_module.pull_request_head = lambda url, accounts=None: ""
    started = github_checks.unstarted_checks
    github_checks.unstarted_checks = unstarted or (lambda url, accounts=None: "")
    if merge is not None:
        github_checks.merge_pull_request = merge
    try:
        yield
    finally:
        git_module.pull_request_state = asked
        github_checks.merge_pull_request = original
        git_module.merge_blocker = blocker
        git_module.pull_request_head = head
        github_checks.unstarted_checks = started


def _closing(
    pages: list[store.Page], states: dict[str, str], status: dict[str, str]
) -> tuple[Any, int]:
    """Run `close_merged` against a fake board and a fake GitHub."""
    runner = _board_runner(pages, status)
    with _github(states):
        return runner.client, runner.close_merged()


def _in_progress(page_id: str, runner_label: str | None) -> store.Page:
    """A ticket left in progress long ago, signed by `runner_label` if given."""
    properties: dict[str, Any] = {"statut": {"type": "status", "status": {"name": "progress"}}}
    if runner_label is not None:
        properties["Agent"] = {"type": "rich_text", "rich_text": [{"plain_text": runner_label}]}
    return store.Page(
        id=page_id,
        url="",
        title=page_id,
        properties=properties,
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )


def _ready(page_id: str) -> store.Page:
    return store.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"statut": {"type": "status", "status": {"name": "ready"}}},
    )


class _NamelessClient:
    """One ticket, its content, and everything written back onto it."""

    def __init__(self, body: str, refuse: bool = False):
        self._body = body
        self._refuse = refuse
        self.written: list[dict[str, Any]] = []

    def schema(self, database_id: str) -> dict[str, str]:
        # Not "Name": the title column is called whatever the board says.
        return {"Titre": "title", "statut": "status"}

    def title_property(self, database_id: str) -> str:
        schema = self.schema(database_id)
        return next((name for name, kind in schema.items() if kind == "title"), "Name")

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._body

    def comments(self, page_id: str) -> list[store.Comment]:
        return []

    def page(self, page_id: str) -> store.Page:
        # The ticket is held by the test, not here: a page this cannot read is
        # a status written as it always was — see `Reports._still`.
        raise store.StoreError(f"GET /pages/{page_id}: 404 not held by this fake")

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        if self._refuse and "Titre" in values:
            raise store.StoreError("PATCH /pages/x: 403 insufficient permissions")
        self.written.append(values)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        pass


class _OneRepository:
    """A resolver for a board whose single project is a repository."""

    def resolve(self, client: Any, page_id: str, *, clone: bool = False) -> projects.Project:
        return projects.Project(name="ponos", path=Path("/repo"))


def _nameless(title: str, body: str, refuse: bool = False) -> tuple[Runner, ticket_module.Ticket]:
    """A Runner about to prepare one ticket, with its board replaced."""
    page = store.Page(
        id="3ce451680af481bc9b66f4d875f74ff5",
        url="https://board.invalid/t",
        title=title,
        properties={
            "Titre": {"type": "title", "title": [{"plain_text": title}]},
            "Project": {"type": "relation", "relation": [{"id": "p-runner"}]},
        },
    )
    runner = _board_runner([page], {})
    runner.client = _NamelessClient(body, refuse)  # type: ignore[assignment]  # a fake: one ticket
    runner.config.runner.base_branch = "main"  # so git is never asked anything
    runner.resolver = _OneRepository()  # type: ignore[assignment]  # a fake: one project
    return runner, ticket_module.Ticket(page)


@contextmanager
def _naming_session(answer: str, missing: bool = False, cost: float = 0.0) -> Iterator[list[str]]:
    """The one-line session that names a ticket, replaced by what it said — and,
    when `cost` says so, by what it was paid."""
    asked: list[str] = []

    def fake_run(prompt_text: str, **kwargs: Any) -> session.Outcome:
        asked.append(prompt_text)
        if missing:
            raise FileNotFoundError("claude not found in PATH")
        return session.Outcome(
            ok=True,
            blocked=False,
            session_id="s-name",
            summary="",
            log=Path("/tmp/none.jsonl"),
            answer=answer,
            cost_usd=cost,
        )

    original = session.run
    session.run = fake_run  # type: ignore[assignment]  # a double: it reads the keywords it is given
    try:
        yield asked
    finally:
        session.run = original


class _TypedClient(_NamelessClient):
    """The same ticket, on a board that has a Type column — in French."""

    def __init__(self, body: str):
        super().__init__(body)
        self.said: list[str] = []

    def schema(self, database_id: str) -> dict[str, str]:
        return {**super().schema(database_id), "Type": "select"}

    def options(self, database_id: str, name: str) -> list[str]:
        return ["Code", "Rédaction", "Action externe", "Publication"] if name == "Type" else []

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.said.append(text)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Fresh:
    """An `Api`, reduced to the three things a first connection asks of it.

    The real one rereads the file whenever its mtime moves, which is what makes
    a run of `apply` see the token it wrote two lines above; this does the same
    by hand, and nothing else.
    """

    def __init__(self, path: Path) -> None:
        self.config = C.load(path)
        self.context = ""

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        saved = web_settings.save(self.config, payload)
        self.config = C.load(self.config.path)
        return saved

    def save_context(self, text: str) -> dict[str, Any]:
        self.context = text.strip()
        return {"ok": True, "text": self.context}

    def forget(self) -> None:
        pass


def _time_passes(console: web_app.Console, seconds: float) -> None:
    """The console's count of attempts, `seconds` later — without waiting them out."""
    clock = console.attempts.clock
    console.attempts.clock = lambda: clock() + seconds


@contextmanager
def _environment(**values: str | None) -> Iterator[None]:
    """Some variables set — or taken away, for None — for the length of a block."""
    previous = {name: os.environ.get(name) for name in values}
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def _http_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Iterator[list[float]]:
    """Every client of `ponos.http` sent to `handler` (an `httpx.MockTransport`).

    Yields the pauses the retry policy takes between attempts — none of which
    are slept for real.
    """
    pauses: list[float] = []
    http_module.transport = httpx.MockTransport(handler)
    http_module.forget()
    http_module.sleep = pauses.append  # type: ignore[assignment]  # the retry policy pauses for floats only
    try:
        yield pauses
    finally:
        http_module.transport = None
        http_module.forget()
        http_module.sleep = time.sleep


class _TalkClient:
    """A page with a discussion on it, and whatever gets written back."""

    def __init__(self, comments: list[store.Comment]) -> None:
        self._comments = comments
        self.written: list[tuple[str, str, str]] = []

    def comments(self, page_id: str) -> list[store.Comment]:
        return list(self._comments)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.written.append((page_id, text, discussion_id))


def _bare_api(client: Any, me: str = "runner-id") -> web_api.Api:
    """An Api with its board replaced, and nothing else built."""
    api = web_api.Api.__new__(web_api.Api)
    api._runner = _bare_runner(client)
    api._runner._me = me
    api.hub = web_live.Hub()
    api._config = C.Config(
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(),
    )
    api._stamp = (0.0, 0.0)
    api._projects = {}
    api._projects_at = 0.0
    # The pictures kept in a directory of the test's own: the real one is under
    # the state directory of whoever runs the suite.
    pictures = Path(tempfile.mkdtemp())
    api._images = images.Cache(pictures, database=pictures / "ponos.db")
    return api


class _ColumnsClient(_TalkClient):
    """A tickets database: three rows, one of them under no known heading."""

    def __init__(self, statuses: list[str]) -> None:
        super().__init__([])
        self._statuses = statuses

    def forget_database(self, database: str) -> None:
        pass

    def query(self, database: str, *args: Any, **kwargs: Any) -> list[store.Page]:
        return [
            store.Page(
                id=f"{index:08d}-0000-0000-0000-000000000000",
                url="",
                title=f"ticket {index}",
                properties={
                    "statut": {"type": "status", "status": {"name": status} if status else None}
                },
                raw={"created_time": "2026-09-01T09:00:00.000Z"},
            )
            for index, status in enumerate(self._statuses)
        ]

    def schema(self, database: str) -> dict[str, str]:
        return {"Name": "title", "statut": "status"}

    def options(self, database: str, prop: str) -> list[str]:
        return ["ready", "progress", "review", "blocked", "done"]


def _saved(body: str = "") -> tuple[Path, C.Config]:
    """A configuration file on disk, and the runner's reading of it."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("# a file somebody wrote by hand\n" + body, encoding="utf-8")
    _launched(path)
    return path, C.load(path)


def _no_secrets() -> None:
    """None of Ponos's own secrets in the vault: what a fresh `secrets.env` used to be."""
    from ponos import vault_store

    vault_store.keep_own({name: None for name in vault_store.own_names()})


def _launched(path: Path) -> None:
    """A file as a launch leaves it: its secrets, and those alone, in the vault.

    Each file of a case used to come with its own `secrets.env`; the vault is
    the case's whole state's, so what an earlier file of the same case moved
    there is taken out first.
    """
    _no_secrets()
    C.move_secrets(path)


@contextmanager
def _state() -> Iterator[Path]:
    """A state directory of its own, so a test never reads yesterday's cursor."""
    previous = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_STATE_HOME"] = directory
        try:
            yield Path(directory)
        finally:
            if previous is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = previous


TICKET = "3ca451680af480ae9443de0b65d9abf8"


class _AnsweringClient:
    """A board that only has to remember what was written on which page."""

    def __init__(self, error: str = "", asked: list[str] | None = None):
        self.written: list[tuple[str, str]] = []
        self._error = error
        self._asked = asked or []

    def comments(self, page_id: str) -> list[store.Comment]:
        return [store.Comment(text, "") for text in self._asked]

    def comment(self, page_id: str, text: str) -> None:
        if self._error:
            raise store.StoreError(self._error)
        self.written.append((page_id, text))


class _StubChannel(channels.Channel):
    name = "telegram"

    def __init__(self, replies: list[channels.Reply]):
        self._replies = replies
        self.said: list[str] = []

    def collect(self) -> list[channels.Reply]:
        return list(self._replies)

    def acknowledge(self, reply: channels.Reply, text: str) -> bool:
        self.said.append(text)
        return True


@contextmanager
def _channel(stub: _StubChannel) -> Iterator[_StubChannel]:
    original = channels.open
    channels.open = lambda settings: [stub]
    try:
        yield stub
    finally:
        channels.open = original


def _answering(
    replies: list[channels.Reply], error: str = "", asked: list[str] | None = None
) -> tuple[Runner, _StubChannel]:
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.config = _config('[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n')
    runner.client = _AnsweringClient(error, asked)  # type: ignore[assignment]  # a fake: comments only
    runner._comments = {}
    runner.dry_run = False
    runner.quiet = True
    stub = _StubChannel(replies)
    with _channel(stub):
        runner.answers()
    return runner, stub


@contextmanager
def _git_answering(**answers: Callable[..., Any]) -> Iterator[None]:
    """git and gh, replaced by what they would have said.

    Each name is replaced in the module that has it: git.py, or github_checks.py
    for what GitHub says of a pull request's checks.
    """

    owners = {name: git_module if hasattr(git_module, name) else github_checks for name in answers}
    original = {name: getattr(owners[name], name) for name in answers}
    for name, replacement in answers.items():
        setattr(owners[name], name, replacement)
    try:
        yield
    finally:
        for name, replacement in original.items():
            setattr(owners[name], name, replacement)


def _plain(text: str) -> str:
    """The same output a pipe would get: colour is not part of what is asserted."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


ROOT = Path(__file__).resolve().parents[1]


FRONTEND = ROOT / "frontend"


@contextmanager
def _board(language: str = "", **settings_overrides: Any) -> Iterator[ledger.Ledger]:
    """A board in the `ponos.db` of the case, emptied: the tickets, and the pages beside them.

    The rest of the state — ideas, history, journal — is the case's own, so
    that two boards of one case still share it.
    """
    with db.transaction() as connection:
        for table in ("tickets", "ticket_comments", "ticket_after"):
            connection.execute(f"DELETE FROM {table}")
        for table in ("board_pages", "board_comments"):
            connection.execute(f"DELETE FROM {table}")
    settings = _settings(**settings_overrides)
    board = ledger.Ledger(pages.Pages(settings), settings, language)
    board.workspace(settings)
    yield board


def _stamp() -> str:
    """The doubles' clock: the real one, to the microsecond.

    To the microsecond because two writes in the same second would otherwise be
    one write as far as a reader could tell, and a conflict test would pass by
    accident.
    """
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _local_api(board: ledger.Ledger) -> web_api.Api:
    """An Api reading a board in `ponos.db`, and nothing else built.

    The same shape `_bare_api` builds, with the store swapped for the real one.
    """
    api = _bare_api(board, me=board.me())
    api._config = C.Config(
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(),
    )
    runner = api._runner
    assert runner is not None  # `_bare_api` built it
    runner.config = api._config
    runner._workspace = board.workspace(api._config.board)
    # Where a project's clone is looked for, for the page that says it.
    runner.resolver = projects.Resolver(api._config.runner.workspace_root, {})
    # What `state()` folds in and nothing here exercises: the chat and the
    # command line are the console's own, and have no board behind them.
    api.chat = type("Chat", (), {"defaults": lambda self: {}})()
    api.commands = type("Commands", (), {"allowed": (), "busy": False})()
    return api


def _ideas_api(board: ledger.Ledger) -> web_api.Api:
    """A console on a board in `ponos.db`, ready to find and keep ideas."""
    api = _local_api(board)
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    api._outbox = web_board.Outbox(journal=lambda report: None)
    api.watch = _Nudged()  # type: ignore[assignment]  # a fake: only counts its nudges
    api._ideas_lock = threading.Lock()
    api._ideas_busy = set()
    api._ideas_person = None
    # Never a session of the real `claude` behind a test's back: a test that
    # wants an idea scored runs what was put aside itself.
    api.ideas_later = lambda work: None  # type: ignore[method-assign]  # see the line above
    return api


class _Nudged:
    def __init__(self) -> None:
        self.count = 0

    def nudge(self) -> None:
        self.count += 1


# A key drawn for these tests and for nothing else: 1024 bits, which GitHub would
# refuse and which signs the same way.
_TEST_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQDmIZaPsUal+WQoQUf6DdKVtrm4AzWXLgBsvcg81ivbuXW+m1m5
IJuOYi2udIK4e3bNdBXeehdLImlnauQEuZfu3pEyxcnWBiZU0bpPDO+JT5pKHMvN
8WFsqDItcnkqkh3ohbAghYqIAq9KiwzFe6YQ45WwtiDlVwBFjFM62Jm6QwIDAQAB
AoGAVljX80Zi6beveuMzrIEvOHl9KawamYTrJ+H1lc4OWr01jrUfbzTq6PuxhDm3
Kp04sFIUOou43bolrmYO9C7m8EVxG63oQEHD1UJF2VIVZ8F9YsWIR0dqUJ7eUbfr
95wqwlKJPDGFcyeQIVrRec0sGcrQ1upFdL37UgR1+Wwkl2ECQQDzeCB3MkxWJQAN
lss4H7yFs93E3LURrrUGf3wnGKtmECQm1OzvDyEhb3qyow1wPVd5G6ohzDTsZXQL
CWMRoTvJAkEA8fm5OOA5UQRG8IoV9QPVoOQGqaW2vtNCyj+bLfWgAZL6TjQkq/k4
EArlHXLFEnKgERAMFeYjK16KTEGZSm/zqwJBAJaJ7jkFRqH1GsVMObcoGF7rSfJR
LTwTtCaiaNebr07aKCBCg4WE601LKqiNnN+LbiyZ6GYhZ4/LYyb31OOvt9ECQQDb
JnudSl4+xOvm0HkgZe+l/r8WCJKg8z8LY14M2uemZVIzX8BSzKz8wpFNAXQAyDW2
Hl2Du+HgVohUlhjaNNhvAkAti2ev+Qs22EGfcCv4CiYwXpx/DC5lmkslVaHAiajP
XTFlXZshGFaUf2SnR17A2A8xR8x7/3K3FOTVofsXTQx6
-----END RSA PRIVATE KEY-----"""


@contextmanager
def _github_answering(
    answer: Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]],
) -> Iterator[list[tuple[str, str, dict[str, str]]]]:
    """GitHub replaced by `answer(method, path, headers, body) -> (status, dict)`.

    Yields the calls made, as (method, path, headers); the configuration, the
    caches and the states are this test's own, and left as they were found —
    the vault each case's own already (`fresh_vault`).
    """
    calls: list[tuple[str, str, dict[str, str]]] = []

    def send(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        path = url[len(github_app.api()) :]
        calls.append((method, path, headers))
        status, payload = answer(method, path, headers, body)
        return status, json.dumps(payload).encode()

    folder = Path(tempfile.mkdtemp())
    original = github_app._send
    config_before = os.environ.get("PONOS_CONFIG")
    github_app._send = send
    _no_secrets()
    # The machine's own configuration says nothing here: `github_token` reads it.
    os.environ["PONOS_CONFIG"] = str(folder / "config.toml")
    github_token._kept = None
    github_app._installations.clear()
    github_app._tokens.clear()
    try:
        yield calls
    finally:
        github_app._send = original
        github_token._kept = None
        if config_before is None:
            os.environ.pop("PONOS_CONFIG", None)
        else:
            os.environ["PONOS_CONFIG"] = config_before
        github_app._installations.clear()
        github_app._tokens.clear()
        shutil.rmtree(folder, ignore_errors=True)


def _test_app(**changes: Any) -> github_app.App:
    held: dict[str, Any] = dict(
        id=42,
        slug="ponos-laptop",
        name="Ponos — laptop",
        owner="hermez",
        pem=_TEST_PEM,
        client_id="Iv1.abc",
        html_url="https://github.com/apps/ponos-laptop",
    )
    held.update(changes)
    return github_app.App(**held)


@contextmanager
def _tools(scripts: dict[str, str]) -> Iterator[Path]:
    """Fake `pass`, `secret-tool` or `bw` at the head of the PATH, as Python scripts."""
    home = Path(tempfile.mkdtemp())
    for name, body in scripts.items():
        (home / name).write_text("#!" + sys.executable + "\nimport sys, os\n" + body)
        (home / name).chmod(0o755)
    previous = os.environ["PATH"]
    os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
    try:
        yield home
    finally:
        os.environ["PATH"] = previous
