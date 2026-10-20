"""The first connection: the console asking once for everything it needs.

Until now the only way into a fresh installation was a secret found on disk —
`serve --print-token`, or the line the installer printed and you scrolled past.
That is the wrong order. A token protects an installation that is already set
up; a fresh one has nothing to protect yet, and what it actually needs is for
somebody to say who opens it from now on.

So a console **nobody can sign into and whose token nobody chose** is
*unclaimed*, and what it serves is this form rather than a demand for a secret.
Filling it in is the whole installation, in the order somebody would say it: the
email and password that open the console from here on — which is also what
closes this door behind them — then the Notion integration and the page to build
the board under, the rules every ticket is written against, and the Telegram bot
that reaches your phone. Nothing here is new configuration: every value written
is a key of `config.toml` you could have typed yourself — or, for a secret, a
line of `secrets.env` — saved through the same `config.edit` the Settings tab
saves through.

It is drawn by the console itself, in steps (`frontend/src/components/console/
setup.tsx`), and it is one write per step: who opens the console, which account
answers the sessions, the board, GitHub, the channels — and then what all of it
amounts to, which the Settings page shows again afterwards (`summary`).

Two things are worth saying out loud.

- **Nobody from outside claims the console without its installation code.** On
  a laptop the console listens on loopback, and the first browser to arrive is
  somebody sitting at this machine. In a container it listens to a network, and
  behind a domain to everybody: there, `serve` draws a code once per start and
  prints it — in the container's logs, which Dokploy shows — and the first
  connection asks for it before anything else (see `server.Handler._claim`). A
  request that is not this machine's own, or that came through a proxy, is
  outside. `PONOS_WEB_EMAIL` and `PONOS_WEB_PASSWORD` in the environment claim
  the console before anybody arrives, and the steps start after the account.
- **It is not one transaction, and it does not pretend to be.** The credentials
  are written in a single edit: all of them or none. What comes after them
  creates pages in somebody's Notion, and no undo of that is possible or wanted
  — so a step that fails is said in the report and leaves everything before it
  standing. That is the rule `ponos init` already follows, where running
  it again is how you finish the job; the Settings tab is the other way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import (
    __version__,
    channels,
    github_app,
    github_token,
    notion,
    prerequisites,
    projects,
    provider,
    provision,
    store,
    voice,
)
from .. import config as config_module
from .. import git as git_module
from ..channels import telegram as telegram_channel
from .api import Api

# Behind this port sits a runner that starts Claude Code sessions with
# `bypassPermissions`, and a password is guessable in a way a 32-character token
# is not. Eight characters and a second per wrong attempt (see `_sign_in`) is
# the floor; the field says so before it refuses, rather than after.
SHORTEST_PASSWORD = 8


def _text(payload: dict, key: str) -> str:
    return str(payload.get(key, "") or "").strip()


def apply(api: Api, payload: dict) -> dict:
    """Do the first connection, and say what it did, step by step.

    Returns the report the page draws — `steps` in the order they happened, and
    `problem` for the one that did not. Raises only for what can be refused
    *before* anything is written: everything past the credentials is reported.
    """
    email = _text(payload, "email")
    password = str(payload.get("password", ""))
    confirm = str(payload.get("confirm", password))
    if "@" not in email:
        raise ValueError("an email address is what the console will ask you for")
    if len(password) < SHORTEST_PASSWORD:
        raise ValueError(
            f"a password of {SHORTEST_PASSWORD} characters at the least — behind this "
            "port sits a runner that runs code on this machine"
        )
    if password != confirm:
        raise ValueError("the two passwords are not the same")

    page = _text(payload, "notion_page")
    page_id = config_module.identifier(page)
    if page and not config_module.is_identifier(page_id):
        raise ValueError(f"“{page}” does not contain a Notion page ID")

    bot = _text(payload, "telegram_token")
    chat = _text(payload, "telegram_chat")

    report = provision.Report()
    values: dict[str, object] = {"web.email": email, "web.password": password}
    # Chosen on the step before this one, while nobody could write yet.
    language = _text(payload, "language")
    if language in voice.LANGUAGES:
        values["runner.language"] = values["runner.app_language"] = language
    for name, value in (
        ("notion.token", _text(payload, "notion_token")),
        ("notify.telegram.token", bot),
        ("notify.telegram.chat", chat),
    ):
        if value:
            values[name] = value
    api.save_settings({"settings": values})
    report.note("created", f"this console opens as {email} from now on")

    # The rules are written *into* the context page, so they wait on the board
    # having been built. The chat id does not wait on anything: it is read back
    # from the bot, and a Notion that refused is no reason to leave it unpaired.
    problem = _notion(api, report, page_id) if page_id else ""
    if not problem:
        problem = _rules(api, report, str(payload.get("rules", "")))
    paired = _telegram(api, report, bot) if bot and not chat else ""
    return {
        "steps": [list(step) for step in report.steps],
        "problem": problem or paired,
        "email": email,
    }


def _notion(api: Api, report: provision.Report, page_id: str) -> str:
    """Build the board under the page that was shared, and point the file at it.

    `provision` is the same code `ponos init` runs, which is the point:
    a board built from a browser and a board built from a terminal are the same
    five databases, with the same columns spelled the same way.
    """
    token = api.config.notion.token
    if not token or token == config_module.PLACEHOLDER:
        return "a page without a token: nothing was built under it"
    try:
        built = provision.provision(notion.Client(token), api.config.notion, page_id)
    except store.StoreError as error:
        return f"Notion: {str(error).splitlines()[0]}"
    report.steps.extend(built.steps)
    api.save_settings({"settings": {"notion.workspace": built.workspace}})
    report.note("created", f"the board is {built.workspace} — written to the configuration")
    return ""


def _rules(api: Api, report: provision.Report, rules: str) -> str:
    """The standing context, which is the one text worth typing here.

    Not a nicety: it reaches every prompt before the project's brief and before
    the ticket, and it is what makes an answer sound like you rather than like
    nobody. Written as *the* context rather than appended to the seed `init`
    leaves — a first connection is the moment that page has nothing to keep.
    """
    if not rules.strip():
        return ""
    try:
        # The context page is a page of the board, so there has to be a board.
        # Said here rather than discovered as a 401 from Notion, which is what
        # asking a placeholder token to write somewhere would produce.
        api.config.require_usable()
    except config_module.ConfigError:
        return "nowhere to write the rules yet: fill Notion in, then the Context pane"
    try:
        api.save_context(rules)
    except (ValueError, store.StoreError) as error:
        return f"the rules: {str(error).splitlines()[0]}"
    report.note("created", "the rules — read into every ticket, before the ticket")
    return ""


def _telegram(api: Api, report: provision.Report, token: str) -> str:
    """The chat id, found by reading who has written to the bot.

    The one value of this configuration nobody can look up, and the usual advice
    is to paste your token into somebody else's bot — which is handing them the
    channel. `notify --pair` reads it back from your own bot instead, and this
    is that gesture, taken while the token is still in front of you.
    """
    try:
        found = telegram_channel.chats(token)
    except channels.ChannelError as error:
        return f"Telegram refused: {error}"
    if not found:
        return "nobody has written to that bot yet: say anything to it, then fill in the chat id"
    if len(found) > 1:
        return "several chats have written to that bot — pick one in the settings"
    identifier, name = found[0]
    api.save_settings({"settings": {"notify.telegram.chat": identifier}})
    report.note("created", f"Telegram is paired with “{name}” ({identifier})")
    return ""


# -- the steps after the account ----------------------------------------------


def save_provider(api: Api, payload: dict) -> dict:
    """The provider step: checked first, written only once it answers.

    The CLI is the exception, because what it needs is not typed here: it is
    written at once, and the page asks again — `claude_login` — once somebody
    has run the command in a terminal. A key that is refused is not written: a
    key that does not work, saved, is a ticket that fails on it in the night.
    """
    which = _text(payload, "provider")
    if which not in config_module.PROVIDERS:
        raise ValueError(f"a provider is one of {', '.join(config_module.PROVIDERS)}")
    key = _text(payload, "key")
    values: dict[str, object] = {"claude.provider": which}
    if which == "cli":
        api.save_settings({"settings": values})
        check = provider.cli_login()
        return {"ok": check.ok, "said": check.said, "command": provider.LOGIN}
    if which == "api_key":
        check = provider.api_key(key or api.config.claude.api_key)
        if key:
            values["claude.api_key"] = key
    else:
        settings = api.config.openrouter
        check = provider.openrouter_key(key or settings.key, settings.base_url)
        if key:
            values["openrouter.key"] = key
        values["openrouter.route_sessions"] = bool(payload.get("route_sessions", True))
    if check.ok:
        api.save_settings({"settings": values})
    return {"ok": check.ok, "said": check.said}


def claude_login() -> dict:
    """Has somebody run `claude auth login` yet? Asked again on every click."""
    check = provider.cli_login()
    return {"ok": check.ok, "said": check.said, "command": provider.LOGIN}


def save_notion(api: Api, payload: dict) -> dict:
    """The board step: the token, then the page `ponos init` builds under.

    Nothing to type when the board is already there — the step says what it
    found and leaves it alone. A page given here is the same provisioning
    `ponos init` runs, through the same `_notion` the old first connection used.
    """
    token = _text(payload, "token")
    page = _text(payload, "page")
    page_id = config_module.identifier(page)
    if page and not config_module.is_identifier(page_id):
        raise ValueError(f"“{page}” does not contain a Notion page ID")
    report = provision.Report()
    if token:
        api.save_settings({"settings": {"notion.token": token}})
        report.note("created", "the integration token is written to the configuration")
    # A board found already built, among what was shared: pointed at, not rebuilt.
    workspace = config_module.identifier(_text(payload, "workspace"))
    if workspace and not page_id:
        if not config_module.is_identifier(workspace):
            raise ValueError("that board has no Notion ID")
        api.save_settings({"settings": {"notion.workspace": workspace}})
        report.note("kept", f"the board {workspace} — written to the configuration")
    problem = _notion(api, report, page_id) if page_id else ""
    return {
        "steps": [list(step) for step in report.steps],
        "problem": problem,
        "board": _board(api),
    }


def notion_shared(api: Api, payload: dict) -> dict:
    """Is this token Notion's, and what has been shared with it so far?

    Asked once when the token is pasted and then every few seconds by the page,
    while somebody is in Notion adding the integration to a page: the moment
    the share is done, the page appears here, and nobody has to copy its link.
    A token Notion refuses is not written — the field keeps it, and says why.
    """
    token = _text(payload, "token")
    stored = api.config.notion.token
    if not token and (not stored or stored == config_module.PLACEHOLDER):
        return {"ok": False, "said": "no token yet", "name": "", "pages": [], "boards": []}
    client = notion.Client(token or stored, timeout=provider.CHECK_TIMEOUT)
    try:
        name = client.my_name()
        pages, boards = client.shared(provision.DIRECTORY)
    except store.StoreError as error:
        said = str(error).splitlines()[0]
        # The one refusal a newcomer meets, said by the page in its own words.
        refused = any(word in said.lower() for word in ("401", "unauthorized", "invalid"))
        if refused:
            said = (
                "Notion refused this token — copy the “Internal Integration Secret” "
                "again from notion.so/my-integrations"
            )
        return {"ok": False, "said": said, "refused": refused, "name": "", "pages": [], "boards": []}
    if token and token != stored:
        api.save_settings({"settings": {"notion.token": token}})
    return {"ok": True, "said": "", "name": name, "pages": pages, "boards": boards}


def project_choices(api: Api) -> dict:
    """The repositories this machine already has, to make a first project of one.

    Looked for under `runner.workspace_root`, the folder every ticket's
    repository is found or cloned in — and created here when it does not exist
    yet, since a fresh machine has none and a missing folder is the one thing
    `doctor` would otherwise hold against it.
    """
    root = api.config.runner.workspace_root
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return {"root": str(root), "said": str(error), "repositories": [], "projects": []}
    found = sorted(projects._walk(root, max_depth=2), key=lambda path: path.name.lower())
    try:
        known = [
            {"id": row["id"], "name": row["name"]}
            for row in api.all_projects()["projects"] if row.get("id")
        ]
    except store.StoreError:
        known = []
    return {
        "root": str(root),
        "said": "",
        "repositories": [
            {"name": path.name, "path": str(path), "remote": git_module.remote_url(path)}
            for path in found
        ],
        "projects": known,
    }


# The demonstration ticket: something every installation can do — no repository,
# no pull request, no account but the board's and Claude's — and short enough to
# come back within the minute. Its answer lands on the ticket, which is the point.
DEMO = {
    "en": (
        "Say hello — Ponos demonstration ticket",
        "This ticket was created by the console's first connection, to check that "
        "everything answers.\n\nIn a few lines, introduce yourself: what you can do "
        "for me from this board, and the three things I should write in a ticket for "
        "it to go well.",
    ),
    "fr": (
        "Dire bonjour — ticket de démonstration de Ponos",
        "Ce ticket a été créé par la première connexion de la console, pour vérifier "
        "que tout répond.\n\nEn quelques lignes, présente-toi : ce que tu peux faire "
        "pour moi depuis ce tableau, et les trois choses à écrire dans un ticket pour "
        "qu'il se passe bien.",
    ),
}

# The runs started from here, by ticket: whether one has ended, and how.
_PLAYED: dict[str, subprocess.Popen] = {}


def demo(api: Api, payload: dict) -> dict:
    """Write the demonstration ticket, and play it now rather than at the next pass.

    The timer would pick it up — in half an hour, or never on a machine with no
    systemd. What starts it here is `ponos run --ticket`, the command a pass
    runs, in a process of its own that outlives the request: it takes the same
    lock as the timer, so the two never run the ticket twice.
    """
    language = _text(payload, "language")
    title, body = DEMO.get(language) or DEMO["en"]
    made = api.create_ticket(title, body, _text(payload, "project"), True, "", "writing")
    ticket = made["id"].replace("-", "")
    play(ticket)
    return {"id": ticket, "title": title}


def play(ticket: str) -> None:
    log = config_module.state_dir() / "web" / f"demo-{ticket}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    source = str(Path(__file__).resolve().parents[2])
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([source, os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        "NO_COLOR": "1",
    }
    with log.open("w") as written:
        _PLAYED[ticket] = subprocess.Popen(
            [sys.executable, "-m", "ponos", "run", "--ticket", ticket],
            cwd=str(Path.home()), stdout=written, stderr=subprocess.STDOUT,
            env=environment, start_new_session=True,
        )


def demo_state(api: Api, ticket: str) -> dict:
    """Where the demonstration ticket stands, and — once its run ended badly — why."""
    ticket = ticket.replace("-", "")
    found = next((row for row in api.board().get("tickets", []) if row["id"] == ticket), None)
    if found is None:
        raise LookupError("no such ticket on the board")
    process = _PLAYED.get(ticket)
    code = process.poll() if process else None
    said = ""
    if code:
        log = config_module.state_dir() / "web" / f"demo-{ticket}.log"
        lines = [line for line in log.read_text(errors="replace").splitlines() if line.strip()]
        said = "\n".join(lines[-12:])
    return {
        "id": ticket,
        "title": found["title"],
        "url": found["url"],
        "column": found["column"],
        "status": found["status"],
        "progress": found["progress"],
        "running": process is not None and code is None,
        "code": code,
        "said": said,
    }


def doctor() -> dict:
    """`ponos doctor`, as the terminal prints it — to read, or to copy for support."""
    environment = {**os.environ, "NO_COLOR": "1",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    try:
        answered = subprocess.run(
            [sys.executable, "-m", "ponos", "doctor"],
            capture_output=True, text=True, timeout=180, env=environment, cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        return {"code": -1, "text": "ponos doctor did not answer within three minutes"}
    return {"code": answered.returncode, "text": answered.stdout + answered.stderr}


def _github_token(held: str) -> dict:
    """The token's owner, asked of GitHub — or why it does not answer."""
    try:
        return {"state": "ok", "account": github_token.check(held)["login"], "via": "token",
                "said": "", "command": ""}
    except github_token.GithubTokenError as error:
        return {"state": "error", "account": "", "via": "token", "said": str(error), "command": ""}


def github() -> dict:
    """What the GitHub step shows: who answers (`_github`), and where a token is made."""
    return {**_github(), "create_url": github_token.CREATE_URL}


def _github() -> dict:
    """Which GitHub account a pull request would be opened as — or why none.

    `GH_TOKEN` in the environment is how a container is usually given one, and
    `gh` reads it without being logged in: asking `gh` who it is covers both.
    A GitHub App connected from the console comes first, as it does for the
    tickets — see github_app.py. A personal access token is the other choice
    (github_token.py): it comes first when `[github_access] mode` says so, and
    otherwise after the App.
    """
    if github_token.access().mode == "token" and (held := github_token.token()):
        return _github_token(held)
    for app in github_app.describe(with_repositories=False):
        if accounts := [one["account"] for one in app["installations"]]:
            return {"state": "ok", "account": f"{app['slug']}[bot] ({', '.join(accounts)})",
                    "via": "app", "said": "", "command": ""}
    if held := github_token.token():
        return _github_token(held)
    via = "GH_TOKEN" if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") else "gh"
    if not shutil.which("gh"):
        return {"state": "missing", "account": "", "via": via, "said": "gh is not installed",
                "command": "gh auth login"}
    try:
        answered = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=provider.CHECK_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"state": "error", "account": "", "via": via, "said": str(error),
                "command": "gh auth login"}
    account = answered.stdout.strip()
    if answered.returncode == 0 and account:
        return {"state": "ok", "account": account, "via": via, "said": "", "command": ""}
    said = (answered.stderr.strip().splitlines() or ["not signed in"])[0]
    return {"state": "missing", "account": "", "via": via, "said": said,
            "command": "gh auth login"}


def save_channels(api: Api, payload: dict) -> dict:
    """The channels step: what was typed, the Telegram chat found, each one asked."""
    bot = _text(payload, "telegram_token")
    chat = _text(payload, "telegram_chat")
    values = {
        name: value
        for name, value in (
            ("notify.telegram.token", bot),
            ("notify.telegram.chat", chat),
            ("notify.slack.token", _text(payload, "slack_token")),
            ("notify.slack.channel", _text(payload, "slack_channel")),
        )
        if value
    }
    report = provision.Report()
    if values:
        api.save_settings({"settings": values})
    problem = _telegram(api, report, bot) if bot and not chat else ""
    return {
        "steps": [list(step) for step in report.steps],
        "problem": problem,
        "channels": _channels(api),
    }


def _channels(api: Api) -> list[dict]:
    answered = []
    for channel in channels.open(api.config.notify):
        try:
            answered.append({"name": channel.name, "ok": True, "said": channel.check()})
        except channels.ChannelError as error:
            answered.append({"name": channel.name, "ok": False, "said": str(error)})
    return answered


# -- what it all amounts to ---------------------------------------------------


def _board(api: Api) -> dict:
    """The board this console reads, and how many tickets are on it."""
    configuration = api.config
    drawn = {
        "state": "ok",
        "storage": configuration.storage.mode,
        "workspace": configuration.notion.workspace or configuration.notion.tickets_database,
        "path": str(configuration.storage.path) if configuration.storage.markdown else "",
        "tickets": None,
        "said": "",
    }
    try:
        configuration.require_usable()
    except config_module.ConfigError as error:
        return {**drawn, "state": "missing", "said": str(error).splitlines()[0]}
    try:
        drawn["tickets"] = len(api.board().get("tickets", []))
    except Exception as error:  # noqa: BLE001 — the summary says it, it does not fail on it
        return {**drawn, "state": "error", "said": str(error).splitlines()[0]}
    return drawn


def summary(api: Api) -> dict:
    """The installation at a glance: one entry per thing that has to work.

    Each has a `state` — ok, missing, or error — and what the page needs to say
    it in its own words; the sentences are the page's, so they can be
    translated, and what comes from here is data: an account, a masked key, a
    count. Nothing secret leaves: a key goes out as its first and last letters.
    """
    configuration = api.config
    which = provider.chosen(configuration)
    claude: dict = {
        "state": "ok",
        "provider": which,
        "stated": configuration.claude.provider,
        "account": "",
        "key": "",
        "route_sessions": configuration.openrouter.route_sessions,
        "said": provider.problem(configuration),
    }
    if claude["said"]:
        claude["state"] = "missing"
    elif which == "cli":
        login = provider.cli_login()
        claude.update(state="ok" if login.ok else "missing", account=login.said if login.ok else "",
                      said="" if login.ok else login.said.removeprefix("not signed in — "))
    elif which == "api_key":
        claude["key"] = provider.masked(configuration.claude.api_key)
    else:
        claude["key"] = provider.masked(configuration.openrouter.key)

    runner = configuration.runner
    model = {
        "state": "ok",
        "model": runner.model,
        "auto": runner.auto_model,
        "said": "",
    }
    if which == "openrouter" and configuration.openrouter.route_sessions:
        names = {"haiku", "sonnet", "opus", "fable"}
        grid = runner.model_grid()
        if runner.model in names or (
            runner.auto_model and any(grid.model(level) in names for level in grid.models)
        ):
            model.update(state="error", said="the sessions run on OpenRouter: name its slugs")

    root = runner.workspace_root
    found = projects._walk(root, max_depth=2) if root.is_dir() else []
    repositories = {
        "state": "ok" if root.is_dir() else "missing",
        "root": str(root),
        "repositories": len(found),
        "configured": len(configuration.projects),
    }

    active = [channel.name for channel in channels.open(configuration.notify)]
    needs = prerequisites.check(config_module.state_dir(), runner.min_free_disk_mb)
    machine = {
        "state": "error" if any(not need.ok and need.required for need in needs)
        else "missing" if any(not need.ok for need in needs) else "ok",
        "needs": [
            {"name": need.name, "ok": need.ok, "required": need.required,
             "said": need.said, "fix": need.fix}
            for need in needs
        ],
    }
    return {
        "machine": machine,
        "provider": claude,
        "model": model,
        "board": _board(api),
        "github": github(),
        "projects": repositories,
        "channels": {"state": "ok" if active else "missing", "active": active},
        "environment": {
            "state": "ok",
            "container": config_module.in_container(),
            "version": __version__,
        },
    }
