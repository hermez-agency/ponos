"""Whether the installation can run a ticket — and what to do when it cannot.

A badly configured Ponos fails without a word: the ticket does not start, or
starts and dies on a repository nobody can push to, and the only trace is a
line in a log. This module is the one place that asks, and it is asked by two
readers — `ponos doctor`, on a terminal, and the dashboard of the console — so
that the two cannot disagree about what "in place" means.

Three decisions shape it.

- **A check is data, and its sentences are templates.** Each one carries a
  `code`, a `state`, and sentences with `{{name}}` holes and the `params` that
  fill them. The terminal fills them in (`Check.text`); the console hands the
  template itself to its dictionary, as it does for every other sentence, so
  the French is a translation of the English and not a second implementation.
  What a tool printed — git's error, Notion's — travels in `evidence`, quoted
  as it came.
- **A fix is offered only when Ponos can make it, and never made unasked.**
  `Check.fix` names an action from `FIXES`; the console confirms it with a
  dialog and `fix()` refuses to run without `confirmed=True`, so the second
  guard holds even for a script that skipped the first. Everything else —
  sharing a page with the integration, installing the GitHub App — happens in
  somebody else's interface, and there the check says the exact steps and the
  link instead.
- **Nothing here fails the caller.** A check that cannot be made says so
  as a check (`unknown`), it does not raise: a health page that crashes on
  the first unreachable service is worse than none.

Checks that wait on a network (a remote, `gh`, Notion) run side by side in
threads: ten projects asked one after the other is half a minute of a page
that looks hung.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable

from . import channels, git, github_app, projects, provider, provision, resources, session, store, systemd
from . import config as config_module
from . import workspace as workspace_module

OK, WARN, ERROR = "ok", "warn", "error"

GROUPS = ("notion", "github", "claude", "projects", "machine")

# A floor, not a measurement: Claude Code older than this is reported as too
# old before a ticket finds out. Raise it the day a flag the runner passes
# needs a newer one.
MINIMUM_CLAUDE = (2, 0, 0)

# One probe never holds a page for longer than this — `provider.CHECK_TIMEOUT`
# is for a single call, and a remote that does not answer is the case at hand.
PROBE_TIMEOUT = 15

NOTION_INTEGRATIONS = "https://www.notion.so/profile/integrations"
CLAUDE_INSTALL = "https://docs.claude.com/en/docs/claude-code/setup"


@dataclass
class Check:
    code: str
    group: str
    state: str
    title: str
    said: str
    params: dict[str, str] = field(default_factory=dict)
    # Why it is likely so, and what to do by hand: sentences like `said`.
    cause: str = ""
    steps: list[str] = field(default_factory=list)
    url: str = ""
    # What a tool printed, quoted — never translated.
    evidence: str = ""
    # {"action", "label", "confirm", "target"} when Ponos can make the fix.
    fix: dict[str, str] | None = None

    def text(self, template: str) -> str:
        """A sentence of this check with its holes filled, for the terminal."""
        return re.sub(r"\{\{(\w+)\}\}", lambda hole: str(self.params.get(hole[1], hole[0])), template)

    def asdict(self) -> dict:
        return asdict(self)


def _check(code: str, state: str, title: str, said: str, **rest) -> Check:
    return Check(code, code.split(".", 1)[0], state, title, said, **rest)


def _first_line(error: object) -> str:
    return (str(error).strip().splitlines() or [""])[0]


# -- Notion --------------------------------------------------------------------


def _notion(config: config_module.Config, client: store.Store) -> tuple[list[Check], workspace_module.Workspace | None]:
    found: list[Check] = []
    if not config.storage.notion:
        return found, None
    try:
        config.require_usable()
    except config_module.ConfigError as error:
        found.append(
            _check(
                "notion.token", ERROR, "Notion token", "No Notion token or tickets database is set.",
                cause="The integration was never created, or its token never reached the settings.",
                steps=[
                    "Create an integration on Notion and copy its secret.",
                    "Paste it in Settings › Notion (notion.token).",
                ],
                url=NOTION_INTEGRATIONS, evidence=_first_line(error),
            )
        )
        return found, None
    try:
        name = client.my_name() or "integration"
    except store.StoreError as error:
        found.append(
            _check(
                "notion.token", ERROR, "Notion token", "Notion refused the token.",
                cause="The token was revoked, mistyped, or belongs to another workspace.",
                steps=[
                    "Open the integration on Notion and copy its secret again.",
                    "Paste it in Settings › Notion (notion.token).",
                ],
                url=NOTION_INTEGRATIONS, evidence=_first_line(error),
            )
        )
        return found, None
    found.append(_check("notion.token", OK, "Notion token", "Connected as “{{name}}”.", params={"name": name}))

    try:
        space = workspace_module.resolve(client, config.notion)
        client.schema(space.tickets)
    except store.StoreError as error:
        found.append(
            _check(
                "notion.tickets", ERROR, "Tickets database", "The tickets database cannot be read.",
                cause="The database is not shared with the integration, or it was deleted or renamed.",
                steps=[
                    "Add the Ponos integration to your Notion page: ··· menu › Connections.",
                    "Check that the page or database named in the settings still exists.",
                ],
                url=NOTION_INTEGRATIONS, evidence=_first_line(error),
            )
        )
        return found, None
    found.append(_check("notion.tickets", OK, "Tickets database", "Tickets database found and shared."))

    if space.projects:
        try:
            client.schema(space.projects)
            found.append(_check("notion.projects", OK, "Projects database", "Projects database found and shared."))
        except store.StoreError as error:
            found.append(
                _check(
                    "notion.projects", ERROR, "Projects database", "The projects database cannot be read.",
                    cause="The database is not shared with the integration.",
                    steps=["Add the Ponos integration to the Projects page: ··· menu › Connections."],
                    url=NOTION_INTEGRATIONS, evidence=_first_line(error),
                )
            )
    else:
        found.append(
            _check(
                "notion.projects", WARN, "Projects database", "No projects database was found.",
                cause="Without it no ticket is tied to a repository, so none can produce a pull request.",
                steps=["Create the Projects database under your Ponos page, or run `ponos init`."],
            )
        )
    found.extend(_schema(config, client, space))
    return found, space


def _schema(config: config_module.Config, client: store.Store, space: workspace_module.Workspace) -> list[Check]:
    """The tickets board against what the runner works with: columns, then statuses."""
    settings = config.notion
    # Asked again, not remembered: the console outlives the column somebody just added.
    client.forget_database(space.tickets)
    schema = client.schema(space.tickets)
    missing: list[str] = []
    wrong: list[str] = []
    costs: list[str] = []
    for key, (accepted, cost) in store.COLUMNS.items():
        name = settings.prop(key)
        kind = schema.get(name)
        if kind is None:
            missing.append(name)
            costs.append(f"“{name}”: {cost}")
        elif kind not in accepted:
            wrong.append(f"“{name}” is a {kind}, not {' or '.join(accepted)}")
    wanted_columns = provision.tickets_schema(settings, space.projects, space.agents)
    addable = sorted(provision.missing_properties(schema, wanted_columns))
    found: list[Check] = []
    if not missing and not wrong:
        found.append(_check("notion.columns", OK, "Tickets properties", "Every property the runner uses is there."))
    else:
        said = "Properties missing on the tickets database: {{missing}}." if missing else (
            "Properties of the wrong type on the tickets database: {{wrong}}."
        )
        found.append(
            _check(
                "notion.columns", ERROR, "Tickets properties", said,
                params={"missing": ", ".join(f"“{name}”" for name in missing), "wrong": "; ".join(wrong)},
                cause="The board predates a version of Ponos, or a property was renamed or retyped.",
                steps=(
                    ["Rename the property in Notion, or its name under [notion.properties]."] if wrong else []
                ),
                evidence="\n".join(costs),
                # What `init` would add: a relation to a database that does not exist is not on the list.
                fix=_fix(
                    "notion_columns",
                    "Configure",
                    "Add {{missing}} to the tickets database? Existing properties are left as they are.",
                    addable,
                ) if addable else None,
            )
        )

    options = client.options(space.tickets, settings.prop("status"))
    wanted = {key: settings.state(key) for key in ("ready", "running", "review", "validated", "done", "failed", "blocked")}
    absent = [name for name in wanted.values() if name not in options]
    if not options or not absent:
        found.append(_check("notion.statuses", OK, "Tickets statuses", "Every status the runner moves tickets through is offered."))
        return found
    board = client.database(space.tickets)
    is_select = ((board.get("properties") or {}).get(settings.prop("status")) or {}).get("type") == "select"
    found.append(
        _check(
            "notion.statuses", ERROR, "Tickets statuses", "Statuses missing: {{missing}}.",
            params={"missing": ", ".join(f"“{name}”" for name in absent)},
            cause="The board was built by hand, or by an older Ponos.",
            steps=[] if is_select else [
                "Notion cannot add a status option from outside: add {{missing}} in the Status property, by hand.",
            ],
            fix=_fix(
                "notion_statuses", "Configure",
                "Add the statuses {{missing}} to the Status property? The existing ones are kept.", absent,
            ) if is_select else None,
        )
    )
    return found


def _fix(action: str, label: str, confirm: str, names: list[str], target: str = "") -> dict[str, str]:
    return {
        "action": action, "label": label, "confirm": confirm,
        "missing": ", ".join(f"“{name}”" for name in names), "target": target,
    }


def _project_rows(client: store.Store, space: workspace_module.Workspace | None) -> list[dict[str, str]]:
    """The projects that have a repository or a path, as the board declares them."""
    if space is None or not space.projects:
        return []
    rows = []
    try:
        for page in client.query(space.projects):
            repository = str(projects._property(page, "Repository", "repository", "github", "repo") or "")
            path = str(projects._property(page, "Path", "path") or "")
            if repository or path:
                rows.append({"id": page.id.replace("-", ""), "name": page.title or "(untitled project)",
                             "repository": repository, "path": path})
    except store.StoreError:
        pass
    return rows


# -- Claude Code ---------------------------------------------------------------


def _claude(config: config_module.Config) -> list[Check]:
    binary = session.available()
    if not binary:
        return [
            _check(
                "claude.installed", ERROR, "Claude Code", "Claude Code is not installed on this machine.",
                cause="`claude` is not on the PATH of the runner.",
                steps=["Install Claude Code, then check that `claude --version` answers."],
                url=CLAUDE_INSTALL,
            )
        ]
    found: list[Check] = []
    try:
        printed = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=PROBE_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        printed = ""
    version = re.search(r"\d+(?:\.\d+){1,2}", printed)
    if not version:
        found.append(
            _check("claude.version", WARN, "Claude Code version", "The version of Claude Code could not be read.",
                   evidence=printed.strip())
        )
    else:
        numbers = tuple(int(part) for part in version.group(0).split("."))
        numbers += (0,) * (3 - len(numbers))
        needed = ".".join(str(part) for part in MINIMUM_CLAUDE)
        if numbers < MINIMUM_CLAUDE:
            found.append(
                _check(
                    "claude.version", ERROR, "Claude Code version",
                    "Claude Code {{version}} is older than {{needed}}.",
                    params={"version": version.group(0), "needed": needed},
                    cause="The runner passes flags that older versions do not know.",
                    steps=["Update Claude Code: run `claude update`."], url=CLAUDE_INSTALL,
                )
            )
        else:
            found.append(
                _check("claude.version", OK, "Claude Code version", "Claude Code {{version}} is installed.",
                       params={"version": version.group(0)})
            )
    if reason := provider.problem(config):
        found.append(
            _check(
                "claude.login", ERROR, "Claude connection", "Sessions have no way to answer: {{reason}}.",
                params={"reason": reason},
                cause="The provider the settings name is missing its key.",
                steps=["Choose a provider and give its key in Settings › Claude."],
            )
        )
    elif provider.chosen(config) == "cli":
        login = provider.cli_login()
        if login.ok:
            found.append(_check("claude.login", OK, "Claude connection", "Signed in: {{who}}.", params={"who": login.said}))
        else:
            found.append(
                _check(
                    "claude.login", ERROR, "Claude connection", "Claude Code is not signed in.",
                    cause="No account was connected to the CLI on this machine.",
                    steps=["In a terminal on this machine, run `claude auth login` and follow the link."],
                    evidence=login.said,
                )
            )
    else:
        found.append(
            _check("claude.login", OK, "Claude connection", "Sessions are answered by {{name}}.",
                   params={"name": provider.NAMES[provider.chosen(config)]})
        )
    return found


# -- GitHub --------------------------------------------------------------------

_WRITING = {"WRITE", "MAINTAIN", "ADMIN"}


def _github_access() -> list[Check]:
    for app in github_app.describe(with_repositories=False):
        if app["error"]:
            return [
                _check(
                    "github.access", ERROR, "GitHub access", "The GitHub App {{slug}} gets no answer from GitHub.",
                    params={"slug": app["slug"]}, evidence=app["error"],
                    cause="The App was deleted on GitHub, or its key no longer matches.",
                    steps=["Connect the App again from Settings › GitHub."],
                )
            ]
        if app["installations"]:
            accounts = ", ".join(one["account"] for one in app["installations"])
            return [_check("github.access", OK, "GitHub access", "GitHub App {{slug}} installed on {{accounts}}.",
                           params={"slug": app["slug"], "accounts": accounts})]
        return [
            _check(
                "github.access", ERROR, "GitHub access", "The GitHub App {{slug}} is installed nowhere.",
                params={"slug": app["slug"]},
                cause="The App exists, but no account or organisation gave it a repository.",
                steps=["Install the GitHub App on your account, and choose the repositories."],
                url=app["install_url"],
            )
        ]
    if not shutil.which("gh"):
        return [
            _check(
                "github.access", ERROR, "GitHub access", "No GitHub App is connected and `gh` is not installed.",
                cause="Pull requests are opened with a GitHub App or with the `gh` command.",
                steps=["Connect a GitHub App from Settings › GitHub, or install `gh` and run `gh auth login`."],
                url="https://cli.github.com",
            )
        ]
    answered = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    if answered.returncode == 0:
        return [_check("github.access", OK, "GitHub access", "`gh` is signed in.")]
    return [
        _check(
            "github.access", ERROR, "GitHub access", "`gh` is not signed in.",
            cause="Without a token Ponos can neither push nor open a pull request.",
            steps=["In a terminal on this machine, run `gh auth login`."],
            evidence=_first_line(answered.stderr or answered.stdout),
        )
    ]


def _repository(remote: str) -> tuple[str, str]:
    """(owner/name, owner) of a remote, or empty when it is not a GitHub one."""
    parts = git.reference_parts(remote)
    if len(parts) < 3 or "github.com" not in remote:
        return "", ""
    return "/".join(parts[1:3]), git.owner(remote)


def _github_rights(config: config_module.Config, name: str, owner: str) -> Check:
    """May the runner read, push and open a pull request on that repository?"""
    title = "GitHub rights on {{repository}}"
    params = {"repository": name}
    if github_app.apps():
        reached = github_app.covers(name, owner)
        if reached is False:
            app = github_app.apps()[0]
            return _check(
                "github.repository", ERROR, title, "The GitHub App does not reach {{repository}}.", params=params,
                cause="The App is installed without this repository, or on another account.",
                steps=["Install the GitHub App on this repository: choose it in the installation's list."],
                url=app.install_url,
            )
        if reached:
            granted = (github_app.installation_for(owner) or (None, {}))[1].get("permissions") or {}
            weak = [name for name in ("contents", "pull_requests") if granted and granted.get(name) != "write"]
            if weak:
                return _check(
                    "github.repository", ERROR, title, "The GitHub App cannot write {{rights}} on {{repository}}.",
                    params={**params, "rights": " or ".join(weak)},
                    cause="The App was created with read-only permissions, or the installation was not accepted again.",
                    steps=["Open the App's installation on GitHub and accept its new permissions."],
                    url=github_app.apps()[0].install_url,
                )
            return _check("github.repository", OK, title, "The GitHub App reaches {{repository}}.", params=params)
    token = git.token_for(name, config.github)
    answered = git.run(["gh", "repo", "view", "--json", "viewerPermission", "--jq", ".viewerPermission", "--", name],
                       timeout=PROBE_TIMEOUT, token=token) if shutil.which("gh") else None
    if answered is None:
        return _check("github.repository", WARN, title, "{{repository}} cannot be checked without `gh`.", params=params)
    if not answered.ok:
        return _check(
            "github.repository", ERROR, title, "{{repository}} cannot be reached with this GitHub account.",
            params=params, evidence=_first_line(answered.err or answered.out),
            cause="The repository does not exist, or the account has no access to it.",
            steps=["Check the Repository property of the project, and that the account can open it on GitHub."],
        )
    permission = answered.out.strip()
    if permission in _WRITING:
        return _check("github.repository", OK, title, "Push and pull requests allowed on {{repository}}.", params=params)
    return _check(
        "github.repository", ERROR, title, "The account can only {{permission}} {{repository}}.",
        params={**params, "permission": "read" if permission == "READ" else permission.lower()},
        cause="Pushing a branch and opening a pull request need write access.",
        steps=["Ask for write access on this repository, or connect an account that has it."],
        url=f"https://github.com/{name}",
    )


# -- Projects ------------------------------------------------------------------


def _project(config: config_module.Config, row: dict[str, str]) -> list[Check]:
    name = row["name"]
    params = {"project": name}
    resolver = projects.Resolver(config.runner.workspace_root, config.projects, config.github)
    path = resolver.locate(name, row["path"], row["repository"])
    found: list[Check] = []
    if path is None:
        if row["repository"]:
            found.append(
                _check(
                    "projects.path", WARN, "Local copy of {{project}}",
                    "No local copy of {{project}} yet: it is cloned when its first ticket starts.", params=params,
                )
            )
            return found
        found.append(
            _check(
                "projects.path", ERROR, "Local copy of {{project}}",
                "The path of {{project}} is not a git repository: {{path}}.", params={**params, "path": row["path"]},
                cause="The folder was moved or deleted, or the Path property is mistyped.",
                steps=["Correct the Path property of the project, or give its Repository so it can be cloned."],
            )
        )
        return found
    found.append(_check("projects.path", OK, "Local copy of {{project}}", "{{project}} is in {{path}}.",
                        params={**params, "path": str(path)}))

    remote = git.remote_url(path)
    if not remote:
        found.append(
            _check(
                "projects.remote", ERROR, "Remote of {{project}}", "{{project}} has no origin remote.", params=params,
                cause="Without it nothing can be pushed and no pull request opened.",
                steps=["In the repository, run `git remote add origin <url>`."],
            )
        )
        return found
    probe = git.run(["git", "ls-remote", "--exit-code", "origin", "HEAD"], path, timeout=PROBE_TIMEOUT)
    if probe.ok:
        found.append(_check("projects.remote", OK, "Remote of {{project}}", "The remote of {{project}} answers.", params=params))
    else:
        found.append(
            _check(
                "projects.remote", ERROR, "Remote of {{project}}", "The remote of {{project}} cannot be reached.",
                params=params, evidence=_first_line(probe.err or probe.out),
                cause="No network, a repository that moved, or credentials git does not have.",
                steps=["In the repository, run `git ls-remote origin` and fix what it prints."],
            )
        )
    if git.git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], path).ok:
        found.append(_check("projects.branch", OK, "Default branch of {{project}}", "{{project}} starts from {{branch}}.",
                            params={**params, "branch": git.default_branch(path)}))
    else:
        found.append(
            _check(
                "projects.branch", WARN, "Default branch of {{project}}",
                "The default branch of {{project}} is not known: {{branch}} is assumed.",
                params={**params, "branch": git.default_branch(path)},
                cause="The clone never recorded which branch the origin treats as its default.",
                steps=["In the repository, run `git remote set-head origin --auto`."],
                fix=_fix(
                    "project_branch", "Configure",
                    "Ask the origin of {{project}} for its default branch (git remote set-head origin --auto)?",
                    [name], target=row["id"],
                ) if probe.ok else None,
            )
        )
    owner_repo, owner = _repository(remote)
    if owner_repo and probe.ok:
        found.append(_github_rights(config, owner_repo, owner))
    return found


# -- Machine -------------------------------------------------------------------


def _machine(config: config_module.Config) -> list[Check]:
    found: list[Check] = []
    room = resources.disk_mb(config_module.state_dir())
    minimum = config.runner.min_free_disk_mb
    if room is None:
        found.append(_check("machine.disk", WARN, "Disk space", "The free disk space cannot be read here."))
    elif 0 < minimum and room[0] < minimum:
        found.append(
            _check(
                "machine.disk", ERROR, "Disk space", "{{free}} MB free, under the {{minimum}} MB a ticket needs to start.",
                params={"free": str(room[0]), "minimum": str(minimum)},
                cause="Worktrees and logs of past tickets fill the disk; no ticket is started until it has room.",
                steps=["Free some room: Settings › Disk tidies the logs and the finished worktrees."],
            )
        )
    else:
        found.append(_check("machine.disk", OK, "Disk space", "{{free}} MB free.", params={"free": str(room[0])}))

    if config_module.in_container():
        found.append(_check("machine.runner", OK, "Runner", "The runner starts with the container."))
    elif not shutil.which("systemctl"):
        # Not a fault: a machine without systemd runs the runner some other way, and nothing here can see it.
        found.append(_check("machine.runner", OK, "Runner", "No systemd here: the runner is started with `ponos run --every`."))
    else:
        timer = systemd.read()
        if timer.enabled != "enabled":
            found.append(
                _check(
                    "machine.runner", ERROR, "Runner", "The runner's timer is {{state}}: no ticket is picked up.",
                    params={"state": timer.enabled},
                    cause="`ponos enable` was never run, or the timer was disabled.",
                    steps=["In a terminal on this machine, run `ponos enable`."],
                )
            )
        elif timer.stalled:
            found.append(
                _check(
                    "machine.runner", ERROR, "Runner", "The runner's timer is enabled but will never fire.",
                    cause="systemd holds no next run for it.",
                    steps=["In a terminal on this machine, run `ponos enable` to arm it again."],
                )
            )
        else:
            found.append(_check("machine.runner", OK, "Runner", "The runner's timer is active."))

    for channel in channels.open(config.notify):
        try:
            found.append(_check("machine.notify", OK, "{{channel}} notifications", "{{channel}}: {{said}}.",
                                params={"channel": channel.name, "said": channel.check()}))
        except channels.ChannelError as error:
            found.append(
                _check(
                    "machine.notify", ERROR, "{{channel}} notifications", "{{channel}} does not answer.",
                    params={"channel": channel.name}, evidence=_first_line(error),
                    cause="The token was revoked, or the chat or channel is wrong.",
                    steps=["Check the {{channel}} token and chat in Settings › Notifications."],
                )
            )
    return found


# -- running them --------------------------------------------------------------


def run(config: config_module.Config, client: store.Store | None = None) -> list[Check]:
    """Every check, in the order the dashboard lists them (`GROUPS`)."""
    client = client or store.open(config)
    jobs: dict[str, Callable[[], list[Check]]] = {
        "claude": lambda: _claude(config),
        "github": _github_access,
        "machine": lambda: _machine(config),
    }
    space: workspace_module.Workspace | None = None
    notion_found: list[Check] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {group: pool.submit(_guarded(group, job)) for group, job in jobs.items()}
        notion_found, space = _guard_notion(config, client)
        rows = _project_rows(client, space)
        per_project = [pool.submit(_guarded("projects", lambda row=row: _project(config, row))) for row in rows]
        done = {group: future.result() for group, future in futures.items()}
        project_found = [check for future in per_project for check in future.result()]
    done["notion"] = notion_found
    done["projects"] = project_found
    # The repository checks are GitHub's, and said there.
    for check in [c for c in project_found if c.code == "github.repository"]:
        project_found.remove(check)
        done["github"].append(check)
    return [check for group in GROUPS for check in done.get(group, [])]


def _guard_notion(config, client):
    try:
        return _notion(config, client)
    except Exception as error:  # noqa: BLE001 — a check that cannot be made is a line, not a crash
        return [_unknown("notion", error)], None


def _guarded(group: str, job: Callable[[], list[Check]]) -> Callable[[], list[Check]]:
    def guarded() -> list[Check]:
        try:
            return job()
        except Exception as error:  # noqa: BLE001
            return [_unknown(group, error)]

    return guarded


def _unknown(group: str, error: object) -> Check:
    return Check(f"{group}.unknown", group, WARN, "Check", "This check could not be made.", evidence=_first_line(error))


def problems(checks: list[Check]) -> int:
    return sum(check.state == ERROR for check in checks)


# -- fixing --------------------------------------------------------------------


def fix(config: config_module.Config, client: store.Store, action: str, target: str = "", *, confirmed: bool = False) -> str:
    """Make one of the fixes a check offered, and say what was done.

    Refuses without `confirmed`: a fix changes somebody's Notion or somebody's
    clone, and the console asks first, but this does not rely on it.
    """
    if not confirmed:
        raise PermissionError("a fix is made only once it is confirmed")
    if action in ("notion_columns", "notion_statuses"):
        space = workspace_module.resolve(client, config.notion)
        settings = config.notion
        if action == "notion_columns":
            wanted = provision.tickets_schema(settings, space.projects, space.agents)
            absent = provision.missing_properties(client.schema(space.tickets), wanted)
            client.add_properties(space.tickets, absent)
            return "added " + ", ".join(sorted(absent)) if absent else "nothing to add"
        widened = provision.missing_options(
            client.database(space.tickets), settings.prop("status"), provision.status_options(settings)
        )
        client.add_properties(space.tickets, widened)
        return "statuses added" if widened else "nothing to add"
    if action == "project_branch":
        space = workspace_module.resolve(client, config.notion)
        row = next((row for row in _project_rows(client, space) if row["id"] == target), None)
        if row is None:
            raise LookupError("that project is not on the board")
        resolver = projects.Resolver(config.runner.workspace_root, config.projects, config.github)
        path = resolver.locate(row["name"], row["path"], row["repository"])
        if path is None:
            raise LookupError("that project has no local copy")
        result = git.git(["remote", "set-head", "origin", "--auto"], path, timeout=PROBE_TIMEOUT)
        if not result.ok:
            raise RuntimeError(_first_line(result.err or result.out) or "git remote set-head failed")
        return git.default_branch(path)
    raise ValueError(f"unknown fix: {action}")
