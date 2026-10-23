"""What every test file of the core shares, and what makes them run without pytest.

The suite is cut into one file per module — `test_update.py` for `update.py`,
`test_web_server.py` for `web/server.py` — so that two tickets touching two
modules touch two files. What more than one of those files needs lives here:
the doubles of Notion, of a session, of a board, and the fixtures.

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
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ponos import (
    channels,
    conversation,
    db,
    environment,
    files,
    github_app,
    github_token,
    images,
    log,
    notion,
    progress,
    projects,
    session,
    store,
    sync,
    voice,
    workspace,
)
from ponos import config as C
from ponos import git as git_module
from ponos import http as http_module
from ponos import ticket as ticket_module
from ponos.runner import Runner
from ponos.web import api as web_api
from ponos.web import board as web_board
from ponos.web import ideas as web_ideas
from ponos.web import live as web_live
from ponos.web import settings as web_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


CASES = []
FIXTURES = {}


def case(function):
    CASES.append(function)
    return function


def fixture(function):
    """A fixture both runners know, by its name: `function(case)` yields its value."""
    FIXTURES[function.__name__] = function
    return function


def call(function) -> None:
    """Run one case the way pytest would, its fixtures opened and closed around it."""
    with contextlib.ExitStack() as stack:
        values = {
            name: stack.enter_context(contextmanager(FIXTURES[name])(function))
            for name in inspect.signature(function).parameters
        }
        function(**values)


def _outcome(index: int) -> tuple[str, str]:
    """One case, in a worker: its name, and its traceback when it failed."""
    function = CASES[index]
    try:
        call(function)
    except Exception:  # noqa: BLE001 — a test runner reports, it does not raise
        return function.__name__, traceback.format_exc()
    return function.__name__, ""


def run(argv: list[str]) -> int:
    """What `python3 tests/run.py` and `python3 tests/functional.py` do with `CASES`.

    The cases are shared among one process per core, as `pytest -n auto` shares
    them: forked once every file is imported, each worker `isolate`s itself
    and is handed the cases one by one, so that none can lean on another having
    run before it. `-j 1` runs them in this process, in order.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    jobs = parser.parse_args(argv).jobs
    started = time.monotonic()
    failures = 0
    if jobs > 1 and "fork" in multiprocessing.get_all_start_methods():
        pool = multiprocessing.get_context("fork").Pool(jobs, initializer=isolate)
    else:
        isolate()
        pool = None
    with pool or contextlib.nullcontext():
        outcomes = (pool.imap if pool else map)(_outcome, range(len(CASES)))
        for name, failure in outcomes:
            if failure:
                failures += 1
                print(f"  ✗ {name}")
                print("".join("      " + line for line in failure.splitlines(True)))
            else:
                print(f"  ✓ {name}")
    total = len(CASES)
    print(f"\n{total - failures}/{total} passed in {time.monotonic() - started:.1f}s")
    return 1 if failures else 0


@fixture
def state_home(case):
    """A throwaway XDG_STATE_HOME: what the runner keeps between two runs, the case's alone."""
    with _state_home() as path:
        yield path


@fixture
def installation(case):
    """An installation of this very runner: `(commit, app, first)`, see `_installable`."""
    with _installable() as installed:
        yield installed


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
    # GitHub, for a machine that has connected an app: an address nothing
    # listens on, so a test that reaches `git.token_for` falls back on `gh` at
    # once rather than asking the real GitHub for a token. The tests about the
    # app replace the transport itself — see `_github_answering`.
    os.environ[github_app.API_ENV] = "http://127.0.0.1:9"


# -- the doubles more than one file uses -------------------------------------


def _config(body: str) -> C.Config:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n' + body)
    # Written the way a file used to be, and read the way a launch leaves it:
    # its secrets moved into secrets.env.
    C.move_secrets(path)
    return C.load(path)


class _FakeClient:
    """Just enough Notion to resolve a workspace, and nothing that reaches out."""

    def __init__(self, rows: dict[str, str], text: str = "", broken: set[str] = frozenset()):
        self._rows = rows
        self._text = text
        self._broken = broken

    def resolve_database(self, identifier: str) -> str:
        if identifier in self._broken:
            raise notion.NotionError(f"{identifier}: object not found")
        return f"db-of-{identifier}"

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        return [notion.Page(id=page, url="", title=title) for title, page in self._rows.items()]

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        if page_id in self._broken:
            raise notion.NotionError(f"{page_id}: object not found")
        return self._text


def _settings(**overrides) -> C.Notion:
    values = {"token": "ntn_real", "workspace": "space", "pages": {}}
    values.update(overrides)
    return C.Notion(**values)


class _Board:
    """A Notion that remembers what was created, without a network in sight."""

    def __init__(self, databases=None, rows=None, schemas=None, text=""):
        self._databases = databases or {}  # page id -> {title: db id}
        self._rows = rows or {}  # db id -> {title: page id}
        self._schemas = schemas or {}  # db id -> {name: {shape}}
        self._text = text
        self.created = []
        self.patched = []
        self.appended = []

    # reading
    def child_databases(self, page_id):
        return dict(self._databases.get(page_id, {}))

    def schema(self, database_id):
        return {
            name: next(iter(shape)) for name, shape in self._schemas.get(database_id, {}).items()
        }

    def database(self, database_id):
        return {
            "properties": {
                name: {"type": next(iter(shape)), **shape}
                for name, shape in self._schemas.get(database_id, {}).items()
            }
        }

    def query(self, database_id, filter_=None):
        return [
            notion.Page(id=page, url="", title=title)
            for title, page in self._rows.get(database_id, {}).items()
        ]

    def blocks_text(self, page_id, depth=0, *, live=True):
        return self._text

    # writing
    def create_database(self, parent_page_id, title, properties, *, inline=True):
        identifier = f"db-{title.lower().replace(' ', '-')}"
        self._databases.setdefault(parent_page_id, {})[title] = identifier
        self._schemas[identifier] = dict(properties)
        self._rows.setdefault(identifier, {})
        self.created.append(identifier)
        return identifier

    def add_properties(self, database_id, properties):
        self._schemas.setdefault(database_id, {}).update(properties)
        self.patched.append((database_id, sorted(properties)))

    def create_row(self, database_id, title, values=None):
        page = f"page-{title.lower().replace(' ', '-')}"
        self._rows.setdefault(database_id, {})[title] = page
        self.created.append(page)
        return page

    def append_markdown(self, page_id, markdown):
        # A page that has just been written to is no longer empty — which is
        # what stops the second `init` from seeding the context page again.
        self.appended.append(page_id)
        self._text = markdown
        return 1


class _CommentClient:
    def __init__(self, texts: list[str], error: str = ""):
        self._texts, self._error = texts, error

    def comments(self, page_id: str) -> list[notion.Comment]:
        if self._error:
            raise notion.NotionError(self._error)
        return [notion.Comment(text) for text in self._texts]


def _bare_runner(client) -> Runner:
    """A Runner with its Notion replaced, and nothing else touched."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = client
    runner.config = _config("")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner._comments = {}
    runner._usage_warned = False
    runner._spellings = conversation.names()
    runner._me = ""  # Notion never said; the signature is all there is
    runner._identity_error = ""
    return runner


def _runner_reading(texts: list[str], error: str = "") -> tuple[Runner, list[str]]:
    runner = _bare_runner(_CommentClient(texts, error))
    ticket = type("T", (), {"page": notion.Page(id="p-ticket", url="", title="t")})()
    return runner, runner.discussion(ticket)


ME = "bot-user-id"


def _said(text: str, *, by: str = "human", thread: str = "d1", ident: str = "") -> notion.Comment:
    return notion.Comment(
        text,
        id=ident or f"c-{abs(hash((text, thread))) % 10**6}",
        discussion_id=thread,
        created_by=by,
    )


class _Unblocking(Runner):
    """A runner that only has what `_examine` asks of it, and says what it did."""

    moved: list
    comments_written: list

    def _project_of(self, ticket):
        return projects.Project(name="", path=None)

    def _body(self, ticket):
        return "Dépend du ticket B."

    def discussion(self, ticket):
        return []

    def _set(self, ticket, **values):
        self.moved.append(values)

    def _comment(self, ticket, text, discussion=""):
        self.comments_written.append(text)

    def comments(self, page_id):
        return [notion.Comment(text) for text in self.comments_written[-1:]]

    def _hold_credits(self, outcome):
        pass

    @property
    def workspace(self):
        return workspace.Workspace(tickets="db", projects="projects", agents="agents")


@contextmanager
def _no_session(
    answer: str = "Parce que la branche d'hier était déjà en revue.", ok=True, writes=None
):
    """Claude, replaced by its answer. Records how it was asked.

    `ok` may be a list, read one entry per call: that is how a session that
    cannot be resumed is told from one that has nothing to say. `writes` is
    `{name: text}` left in the working directory — which is how a document
    ticket answers, the session writing ANSWER.md rather than saying anything.
    """
    calls: list[dict] = []
    verdicts = list(ok) if isinstance(ok, (list, tuple)) else None

    def fake_run(prompt_text, **kwargs):
        calls.append({"prompt": prompt_text, **kwargs})
        good = verdicts.pop(0) if verdicts else (ok if verdicts is None else True)
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
    session.run = fake_run
    try:
        yield calls
    finally:
        session.run = original


def _schedule_page(page_id: str, **values) -> notion.Page:
    """One row of the Schedules database, as Notion hands it over."""
    last_ticket = values.get("last_ticket", "")
    return notion.Page(
        id=page_id,
        url=f"https://notion.so/{page_id}",
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
            "Priority": {"type": "number", "number": 40},
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

    def __init__(self, pages, tickets=None, refuses=""):
        self._pages = pages
        self._tickets = tickets or {}
        self._refuses = refuses
        self.written: list[tuple[str, dict]] = []
        self.created: list[tuple[str, dict]] = []
        self.appended: list[tuple[str, str]] = []
        self.trashed: list[str] = []

    def schema(self, database_id):
        return {"Status": "status"}

    def trash(self, page_id):
        self.trashed.append(page_id)
        self._pages = [page for page in self._pages if page.id != page_id]
        return f"https://notion.so/{page_id}"

    def query(self, database_id, filter_=None):
        return list(self._pages)

    def page(self, page_id):
        if page_id in self._tickets:
            return self._tickets[page_id]
        raise notion.NotionError(f"{page_id}: object not found")

    def update(self, database_id, page_id, values):
        self.written.append((page_id, dict(values)))

    def create_row(self, database_id, title, values=None):
        if self._refuses:
            raise notion.NotionError(self._refuses)
        self.created.append((title, dict(values or {})))
        return f"t-{len(self.created)}"

    def blocks_text(self, block_id, depth=0, *, live=True):
        return "Lister les dépendances en retard, et dire lesquelles comptent."

    def append_markdown(self, page_id, markdown):
        self.appended.append((page_id, markdown))
        return 1


def _recurring(pages, *, tickets=None, refuses="", schedule=True, dry_run=False) -> Runner:
    """A Runner with nothing underneath it but a schedules database."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = _ScheduleClient(pages, tickets, refuses)
    runner.config = C.Config(
        notion=C.Notion(properties=dict(C._DEFAULT_PROPERTIES), status={}),
        runner=C.Runner(schedule=schedule),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db-tickets", schedules="db-schedules")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner.dry_run = dry_run
    return runner


@contextmanager
def _state_home():
    """A throwaway XDG_STATE_HOME, for what the runner keeps between two runs."""
    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    try:
        yield Path(os.environ["XDG_STATE_HOME"]) / "ponos"
    finally:
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
def _installable():
    """An installation of this very runner, cloned from a remote of its own.

    Yields `(commit, app, first)`: `commit(message, change)` lands a commit on
    the remote after `change(work)` has edited its files. The launcher is
    written to a home of the test's own, and systemd is out of the PATH — an
    install that rewrote this machine's units would be a test gone too far.
    """
    quiet = {"capture_output": True, "check": True}
    who = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    kept = {name: os.environ.get(name) for name in ("HOME", "PATH")}
    with tempfile.TemporaryDirectory() as directory, _state_home():
        remote, work, app = (Path(directory) / name for name in ("remote.git", "work", "app"))
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)], **quiet)
        subprocess.run(["git", "clone", "--quiet", str(remote), str(work)], **quiet)
        ignore = shutil.ignore_patterns("__pycache__")
        for part in ("src", "bin", "systemd"):
            shutil.copytree(ROOT / part, work / part, ignore=ignore)

        def commit(message: str, change=lambda work: None) -> str:
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
        # What a version's environment would download — FastAPI, for the
        # console its start is checked by (`update.verify`) — borrowed from this
        # process instead: the test stays offline, and as fast as it was.
        made = environment.create

        def create(version: Path, base: str | None = None) -> str:
            problem = made(version, base)
            borrowed = [path for path in sys.path if path.endswith("-packages")]
            for site in (version / environment.VENV / "lib").glob("python*/site-packages"):
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
        self, pages: list[notion.Page], options: list[str] | None = None, waiting: bool = False
    ):
        self._pages = pages
        self._options = options if options is not None else ["In review", "Validated", "Done"]
        # A board that predates the attribute simply has no such property, and
        # the runner then waits for the credit with nothing to show for it.
        self.waiting = waiting
        self.written: list[tuple[str, dict]] = []
        self.comments_written: list[str] = []
        self.queried: list[object] = []
        self.created: list[tuple[str, dict]] = []
        self.bodies: list[str] = []
        # Columns a test adds to the board: the Runner one, to begin with.
        self.columns: dict[str, str] = {}

    def schema(self, database_id: str) -> dict[str, str]:
        schema = {"Status": "status", "Pull Request": "url", **self.columns}
        if self.waiting:
            schema["Waiting for credit"] = "checkbox"
        return schema

    def options(self, database_id: str, name: str) -> list[str]:
        return list(self._options)

    def me(self) -> str:
        return "u-runner"

    def comments(self, page_id: str) -> list[notion.Comment]:
        return []

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return "Le post d'annonce, écrit la semaine dernière et relu depuis."

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        self.queried.append(filter_)
        wanted = (filter_ or {}).get("status", {}).get("equals")
        return [page for page in self._pages if notion.read(page, "Status") == wanted]

    def page(self, page_id: str) -> notion.Page:
        # The very page the pass read: what a run holds is what Notion says,
        # unless a test moves it underneath.
        for page in self._pages:
            if page.id.replace("-", "") == page_id.replace("-", ""):
                return page
        raise notion.NotionError(f"GET /pages/{page_id}: 404 not found")

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        self.written.append((page_id, values))

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.comments_written.append(text)

    def create_row(self, database_id: str, title: str, values: dict | None = None) -> str:
        page_id = f"created{len(self.created)}"
        self.created.append((title, values or {}))
        status = (values or {}).get("Status", "")
        self._pages.append(
            notion.Page(
                id=page_id,
                url="",
                title=title,
                properties={"Status": {"type": "status", "status": {"name": status}}},
            )
        )
        return page_id

    def append_markdown(self, page_id: str, text: str) -> None:
        self.bodies.append(text)


def _reviewed(page_id: str, status: str, pull_request: str | None) -> notion.Page:
    properties = {"Status": {"type": "status", "status": {"name": status}}}
    if pull_request is not None:
        properties["Pull Request"] = {"type": "url", "url": pull_request}
    return notion.Page(id=page_id, url="", title=page_id, properties=properties)


def _board_runner(
    pages: list[notion.Page], status: dict[str, str], options=None, waiting: bool = False
) -> Runner:
    """A Runner with nothing underneath it but a fake board."""
    runner = Runner.__new__(Runner)
    runner._journals = {}
    runner.client = _BoardClient(pages, options, waiting)
    runner.config = C.Config(
        notion=C.Notion(properties=dict(C._DEFAULT_PROPERTIES), status=status),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db", projects="projects", agents="agents")
    runner.agent_label = "ponos@laptop"
    runner.quiet = True
    runner.dry_run = False
    runner._claimed = set()
    runner._holding, runner._explained = {}, None
    runner._comments = {}
    runner._usage_warned = False
    runner._spellings = conversation.names()
    runner._me = ""
    runner._identity_error = ""
    runner._ledger_lock = threading.Lock()
    runner._landed, runner._replayed_after = {}, {}
    runner._landed_lock = threading.Lock()
    runner._queues = {}
    runner._ledger = conversation.Ledger(database=Path(tempfile.mkdtemp()) / "ponos.db")
    return runner


@contextmanager
def _github(states: dict[str, str], merge=None, blockers: dict[str, str] | None = None):
    """`gh`, replaced by what it would have said.

    `blockers` is what GitHub says stands in a pull request's way before a merge
    is asked — see `git.merge_blocker`. Nothing, unless a test says otherwise.
    """

    asked, original = git_module.pull_request_state, git_module.merge_pull_request
    blocker = git_module.merge_blocker
    git_module.pull_request_state = lambda url, accounts=None: states.get(url, "")
    git_module.merge_blocker = lambda url, accounts=None: (blockers or {}).get(url, "")
    # Nothing is asked of GitHub about the checks of the pull requests still open.
    head = git_module.pull_request_head
    git_module.pull_request_head = lambda url, accounts=None: ""
    if merge is not None:
        git_module.merge_pull_request = merge
    try:
        yield
    finally:
        git_module.pull_request_state = asked
        git_module.merge_pull_request = original
        git_module.merge_blocker = blocker
        git_module.pull_request_head = head


def _closing(pages: list[notion.Page], states: dict[str, str], status: dict[str, str]):
    """Run `close_merged` against a fake board and a fake GitHub."""
    runner = _board_runner(pages, status)
    with _github(states):
        return runner.client, runner.close_merged()


def _in_progress(page_id: str, runner_label: str | None) -> notion.Page:
    """A ticket left in progress long ago, signed by `runner_label` if given."""
    properties: dict = {"Status": {"type": "status", "status": {"name": "In progress"}}}
    if runner_label is not None:
        properties["Runner"] = {"type": "rich_text", "rich_text": [{"plain_text": runner_label}]}
    return notion.Page(
        id=page_id,
        url="",
        title=page_id,
        properties=properties,
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )


def _ready(page_id: str) -> notion.Page:
    return notion.Page(
        id=page_id,
        url="",
        title=page_id,
        properties={"Status": {"type": "status", "status": {"name": "Ready"}}},
    )


class _NamelessClient:
    """One ticket, its content, and everything written back onto it."""

    def __init__(self, body: str, refuse: bool = False):
        self._body = body
        self._refuse = refuse
        self.written: list[dict] = []

    def schema(self, database_id: str) -> dict[str, str]:
        # Not "Name": the title column is called whatever Notion was told.
        return {"Titre": "title", "Status": "status"}

    def title_property(self, database_id: str) -> str:
        return notion.Client.title_property(self, database_id)  # the real lookup

    def blocks_text(self, block_id: str, depth: int = 0, *, live: bool = True) -> str:
        return self._body

    def comments(self, page_id: str) -> list[notion.Comment]:
        return []

    def page(self, page_id: str) -> notion.Page:
        # The ticket is held by the test, not here: a page this cannot read is
        # a status written as it always was — see `Reports._still`.
        raise notion.NotionError(f"GET /pages/{page_id}: 404 not held by this fake")

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        if self._refuse and "Titre" in values:
            raise notion.NotionError("PATCH /pages/x: 403 insufficient permissions")
        self.written.append(values)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        pass


class _OneRepository:
    """A resolver for a board whose single project is a repository."""

    def resolve(self, client, page_id: str, *, clone: bool = False) -> projects.Project:
        return projects.Project(name="ponos", path=Path("/repo"))


def _nameless(title: str, body: str, refuse: bool = False):
    """A Runner about to prepare one ticket, with Notion replaced."""
    page = notion.Page(
        id="3ce451680af481bc9b66f4d875f74ff5",
        url="https://notion.so/t",
        title=title,
        properties={
            "Titre": {"type": "title", "title": [{"plain_text": title}]},
            "Project": {"type": "relation", "relation": [{"id": "p-runner"}]},
        },
    )
    runner = _board_runner([page], {})
    runner.client = _NamelessClient(body, refuse)
    runner.config.runner.base_branch = "main"  # so git is never asked anything
    runner.resolver = _OneRepository()
    return runner, ticket_module.Ticket(page)


@contextmanager
def _naming_session(answer: str, missing: bool = False):
    """The one-line session that names a ticket, replaced by what it said."""
    asked: list[str] = []

    def fake_run(prompt_text, **kwargs):
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
        )

    original = session.run
    session.run = fake_run
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
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _run_on(page, words: str, said: str, *, ok: bool = True, page_id: str = "page") -> None:
    """One session's live report, as `execution` would leave it on the page."""
    clock = _Clock()
    live = progress.Live(page, page_id, words=voice.Voice(words), clock=clock)
    live.add(progress.Step(said, said=True))
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 90
    live.close("stopped" if not ok else "", ok=ok)


class _Fresh:
    """An `Api`, reduced to the three things a first connection asks of it.

    The real one rereads the file whenever its mtime moves, which is what makes
    a run of `apply` see the token it wrote two lines above; this does the same
    by hand, and nothing else.
    """

    def __init__(self, path: Path) -> None:
        self.config = C.load(path)
        self.context = ""

    def save_settings(self, payload: dict) -> dict:
        saved = web_settings.save(self.config, payload)
        self.config = C.load(self.config.path)
        return saved

    def save_context(self, text: str) -> dict:
        self.context = text.strip()
        return {"ok": True, "text": self.context}

    def forget(self) -> None:
        pass


def _time_passes(console, seconds: float) -> None:
    """The console's count of attempts, `seconds` later — without waiting them out."""
    clock = console.attempts.clock
    console.attempts.clock = lambda: clock() + seconds


@contextmanager
def _environment(**values: str | None):
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
def _http_answering(handler):
    """Every client of `ponos.http` sent to `handler` (an `httpx.MockTransport`).

    Yields the pauses the retry policy takes between attempts — none of which
    are slept for real.
    """
    pauses: list[float] = []
    http_module.transport = httpx.MockTransport(handler)
    http_module.forget()
    http_module.sleep = pauses.append
    try:
        yield pauses
    finally:
        http_module.transport = None
        http_module.forget()
        http_module.sleep = time.sleep


class _TalkClient:
    """A page with a discussion on it, and whatever gets written back."""

    def __init__(self, comments: list[notion.Comment]) -> None:
        self._comments = comments
        self.written: list[tuple[str, str, str]] = []

    def comments(self, page_id: str) -> list[notion.Comment]:
        return list(self._comments)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.written.append((page_id, text, discussion_id))


def _bare_api(client, me: str = "runner-id") -> web_api.Api:
    """An Api with its Notion replaced, and nothing else built."""
    api = web_api.Api.__new__(web_api.Api)
    api._runner = _bare_runner(client)
    api._runner._me = me
    api.hub = web_live.Hub()
    api._config = C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(),
    )
    api._stamp = (0.0, 0.0)
    api._projects = {}
    api._projects_at = 0.0
    api._briefs = {}
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

    def query(self, database: str, *args, **kwargs) -> list[notion.Page]:
        return [
            notion.Page(
                id=f"{index:08d}-0000-0000-0000-000000000000",
                url="",
                title=f"ticket {index}",
                properties={
                    "Status": {"type": "status", "status": {"name": status} if status else None}
                },
                raw={"created_time": "2026-09-01T09:00:00.000Z"},
            )
            for index, status in enumerate(self._statuses)
        ]

    def schema(self, database: str) -> dict[str, str]:
        return {"Name": "title", "Status": "status"}

    def options(self, database: str, prop: str) -> list[str]:
        return ["Ready", "In progress", "In review", "Blocked", "Failed", "Done"]


def _saved(body: str = "") -> tuple[Path, C.Config]:
    """A configuration file on disk, and the runner's reading of it."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        "# a file somebody wrote by hand\n"
        '[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n' + body,
        encoding="utf-8",
    )
    C.move_secrets(path)  # as a launch leaves it, see `_config`
    return path, C.load(path)


@contextmanager
def _state():
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
    """A Notion that only has to remember what was written on which page."""

    def __init__(self, error: str = "", asked: list[str] | None = None):
        self.written: list[tuple[str, str]] = []
        self._error = error
        self._asked = asked or []

    def comments(self, page_id: str) -> list[notion.Comment]:
        return [notion.Comment(text, "") for text in self._asked]

    def comment(self, page_id: str, text: str) -> None:
        if self._error:
            raise notion.NotionError(self._error)
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
def _channel(stub):
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
    runner.client = _AnsweringClient(error, asked)
    runner._comments = {}
    runner.dry_run = False
    runner.quiet = True
    stub = _StubChannel(replies)
    with _channel(stub):
        runner.answers()
    return runner, stub


@contextmanager
def _git_answering(**answers):
    """git and gh, replaced by what they would have said."""

    original = {name: getattr(git_module, name) for name in answers}
    for name, replacement in answers.items():
        setattr(git_module, name, replacement)
    try:
        yield
    finally:
        for name, replacement in original.items():
            setattr(git_module, name, replacement)


def _plain(text: str) -> str:
    """The same output a pipe would get: colour is not part of what is asserted."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


ROOT = Path(__file__).resolve().parents[1]


FRONTEND = ROOT / "frontend"


@contextmanager
def _board(**settings_overrides):
    """A throwaway Markdown board, and the naming settings it is read under."""
    directory = tempfile.mkdtemp()
    try:
        yield files.Board(Path(directory) / "board", _settings(**settings_overrides))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _NotionBoard:
    """Notion reduced to a dictionary, with the surface the mirror uses.

    Not a mock: it keeps pages, bodies and `last_edited_time`, because the whole
    of the reconciliation is about which side moved and when. What it does not
    have is a network, which is the point.
    """

    def __init__(self, context: str = "") -> None:
        self.pages: dict[str, store.Page] = {}
        self.bodies: dict[str, str] = {}
        self.where: dict[str, str] = {}  # page id -> database
        self.context = context
        self.said: list[tuple[str, str]] = []
        self._counter = 0

    # -- the shape -----------------------------------------------------------

    def resolve_database(self, identifier):
        return identifier

    def forget_database(self, database_id):
        pass

    def schema(self, database_id):
        return files.schemas(_settings())[database_id]

    def options(self, database_id, name):
        return []

    def title_property(self, database_id):
        return "Name"

    def workspace(self, settings):
        space = workspace.Workspace(
            tickets="tickets",
            projects="projects",
            agents="agents",
            schedules="schedules",
            rows={"Context": "ctx"},
            context_page="ctx",
        )
        space.context = self.context
        return space

    # -- reading -------------------------------------------------------------

    def query(self, database_id, filter_=None):
        return [page for page_id, page in self.pages.items() if self.where[page_id] == database_id]

    def page(self, page_id):
        if page_id not in self.pages:
            raise store.StoreError(f"no such page: {page_id}")
        return self.pages[page_id]

    def blocks_text(self, block_id, depth=0, *, live=True):
        if block_id == "ctx":
            return self.context
        return self.bodies.get(block_id, "")

    def comments(self, page_id):
        return []

    def me(self):
        return "notion-user"

    def my_name(self):
        return "Ponos"

    # -- writing -------------------------------------------------------------

    def _touch(self, page_id, at=""):
        page = self.pages[page_id]
        page.raw["last_edited_time"] = at or _stamp()

    def create_row(self, database_id, title, values=None, at=""):
        self._counter += 1
        page_id = f"{self._counter:032x}"
        self.pages[page_id] = store.Page(
            id=page_id,
            url=f"https://notion.so/{page_id}",
            title=title,
            properties={"Name": store.written("title", title)},
            raw={"created_time": at or _stamp(), "last_edited_time": at or _stamp()},
        )
        self.where[page_id] = database_id
        self.update(database_id, page_id, values or {}, at=at)
        return page_id

    def update(self, database_id, page_id, values, at=""):
        page = self.pages[page_id]
        schema = self.schema(database_id)
        for name, value in values.items():
            if name == "Name":
                page.title = str(value)
            shape = store.written(schema.get(name, "rich_text"), value)
            if shape is not None:
                page.properties[name] = shape
        self._touch(page_id, at)

    def append_markdown(self, page_id, markdown, at=""):
        if page_id == "ctx":
            self.context = f"{self.context}\n\n{markdown}".strip()
            return 1
        self.bodies[page_id] = f"{self.bodies.get(page_id, '')}\n\n{markdown}".strip()
        self._touch(page_id, at)
        return 1

    def replace_markdown(self, page_id, markdown, at=""):
        if page_id == "ctx":
            self.context = markdown.strip()
            return 1
        self.bodies[page_id] = markdown.strip()
        self._touch(page_id, at)
        return 1

    def comment(self, page_id, text, discussion_id=""):
        self.said.append((page_id, text))

    def append_blocks(self, block_id, blocks):
        return []

    def update_block(self, block_id, payload):
        pass


def _stamp() -> str:
    """The fake Notion's clock: the real one, to the microsecond.

    To the microsecond because that is the resolution the reconciliation reads
    both sides at — two writes in the same second would otherwise be one write
    as far as it could tell, and a conflict test would pass by accident.
    """
    return datetime.now(UTC).isoformat(timespec="microseconds")


@contextmanager
def _mirror(context: str = ""):
    """Both boards and a fresh set of stamps, with nothing shared between runs."""
    directory = Path(tempfile.mkdtemp())
    try:
        here = _NotionBoard(context)
        there = files.Board(directory / "board", _settings())
        both = sync.Mirror(here, there)
        yield here, there, both, sync.Stamps(directory / "ponos.db")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _markdown_api(board: files.Board) -> web_api.Api:
    """An Api reading a board made of files, and nothing else built.

    The same shape `_bare_api` builds, with the store swapped and a
    `[storage]` that says so: these three panes exist to be usable on an
    installation where there is no integration to ask anything of.
    """
    api = _bare_api(board, me=board.me())
    api._config = C.Config(
        notion=C.Notion(),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(),
        storage=C.Storage(mode="markdown", path=board.root),
    )
    api._runner.config = api._config
    api._runner._workspace = board.workspace(api._config.notion)
    # Where a project's clone is looked for, for the page that says it.
    api._runner.resolver = projects.Resolver(api._config.runner.workspace_root, {})
    # What `state()` folds in and nothing here exercises: the chat and the
    # command line are the console's own, and have no board behind them.
    api.chat = type("Chat", (), {"state": lambda self: {}})()
    api.commands = type("Commands", (), {"allowed": (), "busy": False})()
    return api


def _ideas_api(board: files.Board) -> web_api.Api:
    """A console on a Markdown board, ready to find and keep ideas."""
    api = _markdown_api(board)
    api._schema_at = time.time()
    api._reader = web_board.Reader(journal=lambda report: None)
    api._outbox = web_board.Outbox(journal=lambda report: None)
    api.watch = _Nudged()
    api.ideas = web_ideas.Ideas(api)
    # Never a session of the real `claude` behind a test's back: a test that
    # wants an idea scored runs what was put aside itself.
    api.ideas.later = lambda work: None
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
def _github_answering(answer):
    """GitHub replaced by `answer(method, path, headers, body) -> (status, dict)`.

    Yields the calls made, as (method, path, headers); the secrets file, the
    caches and the states are this test's own, and left as they were found.
    """
    calls: list[tuple[str, str, dict]] = []

    def send(method, url, headers, body):
        path = url[len(github_app.api()) :]
        calls.append((method, path, headers))
        status, payload = answer(method, path, headers, body)
        return status, json.dumps(payload).encode()

    folder = Path(tempfile.mkdtemp())
    original, before = github_app._send, os.environ.get(C.SECRETS_PATH_ENV)
    config_before = os.environ.get("PONOS_CONFIG")
    github_app._send = send
    os.environ[C.SECRETS_PATH_ENV] = str(folder / "secrets.env")
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
        if before is None:
            os.environ.pop(C.SECRETS_PATH_ENV, None)
        else:
            os.environ[C.SECRETS_PATH_ENV] = before
        if config_before is None:
            os.environ.pop("PONOS_CONFIG", None)
        else:
            os.environ["PONOS_CONFIG"] = config_before
        github_app._installations.clear()
        github_app._tokens.clear()
        shutil.rmtree(folder, ignore_errors=True)


def _test_app(**changes) -> github_app.App:
    held = dict(
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
def _tools(scripts: dict[str, str]):
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
