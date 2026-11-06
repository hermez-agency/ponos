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

A fourth state sits beside the three verdicts: `info`, a setting said rather
than judged — the interval of a run, who may answer on a channel. `doctor`
prints it in grey, as it always has, and the dashboard's band, which lists
what is to be fixed, leaves it out.

Checks that wait on a network (a remote, `gh`, Notion) run side by side in
threads: ten projects asked one after the other is half a minute of a page
that looks hung. The one network question only `doctor` asks is the newest
version (`remote=True`): the dashboard reads what the last check found, as the
console's header does, rather than fetching on every page that opens.

The checks are a package, one module per group of the dashboard — Notion
(`notion`, and `columns` for what its databases hold), Claude Code, GitHub,
the projects, the machine (`machine`, and `installation` for Ponos's own
upkeep), the settings — beside `check`, the shape they share, and `fixing`.
Every name stays reachable here, as when they were one file — the modules
the checks ask included (`health.shutil`): `health.X` is what `__main__`,
the console and the tests ask for, and what a double replaces. `run` reads
its checks from this namespace, so a test that swaps one here is heard.
"""

from __future__ import annotations

import logging
import os as os
import shutil as shutil
import subprocess as subprocess
import sys as sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from .. import channels as channels
from .. import config as config_module
from .. import environment as environment
from .. import git as git
from .. import github_app as github_app
from .. import github_token as github_token
from .. import leftovers as leftovers
from .. import log, store
from .. import provider as provider
from .. import resources as resources
from .. import session as session
from .. import systemd as systemd
from .. import update as update_module  # noqa: F401 — `health.update_module`, as before
from .. import workspace as workspace_module
from .check import ERROR as ERROR
from .check import INFO as INFO
from .check import INSTALL_STEP as INSTALL_STEP
from .check import OK as OK
from .check import PROBE_TIMEOUT as PROBE_TIMEOUT
from .check import WARN as WARN
from .check import Check as Check
from .check import _check as _check
from .check import _first_line as _first_line
from .check import _fix as _fix
from .check import _installing as _installing
from .claude import CLAUDE_INSTALL as CLAUDE_INSTALL
from .claude import CLAUDE_MODELS as CLAUDE_MODELS
from .claude import MINIMUM_CLAUDE as MINIMUM_CLAUDE
from .claude import _claude as _claude
from .claude import _claude_version as _claude_version
from .claude import _models as _models
from .claude import _provider as _provider
from .columns import RUNNER_STATUSES as RUNNER_STATUSES
from .columns import SCHEDULE_COLUMNS as SCHEDULE_COLUMNS
from .columns import _on_option as _on_option
from .columns import _other_statuses as _other_statuses
from .columns import _schedules as _schedules
from .columns import _schema as _schema
from .columns import _stray_subtypes as _stray_subtypes
from .columns import _subtypes as _subtypes
from .columns import _types as _types
from .fixing import _Shaped as _Shaped
from .fixing import _shaped as _shaped
from .fixing import fix as fix
from .github import _WRITING as _WRITING
from .github import _gh as _gh
from .github import _github_access as _github_access
from .github import _github_billing as _github_billing
from .github import _github_rights as _github_rights
from .github import _github_token as _github_token
from .github import _repository as _repository
from .installation import NOTIFY_SAID as NOTIFY_SAID
from .installation import STRAY_SHOWN as STRAY_SHOWN
from .installation import _answerers as _answerers
from .installation import _database as _database
from .installation import _environment as _environment
from .installation import _notifications as _notifications
from .installation import _restore as _restore
from .installation import _spared as _spared
from .installation import _stray as _stray
from .installation import _version as _version
from .machine import CHECKOUTS as CHECKOUTS
from .machine import DOCKER_INSTALL as DOCKER_INSTALL
from .machine import IO_CLASSES as IO_CLASSES
from .machine import _disk as _disk
from .machine import _docker as _docker
from .machine import _has_display as _has_display
from .machine import _load as _load
from .machine import _machine as _machine
from .machine import _memory as _memory
from .machine import _priority as _priority
from .machine import _private_state as _private_state
from .machine import _runner as _runner
from .machine import _service as _service
from .machine import _tools as _tools
from .machine import _video_sent as _video_sent
from .machine import _workers as _workers
from .notion import NOTION_INTEGRATIONS as NOTION_INTEGRATIONS
from .notion import _board as _board
from .notion import _comments as _comments
from .notion import _notion_token as _notion_token
from .notion import _project_rows as _project_rows
from .notion import _projects_database as _projects_database
from .notion import _workspace as _workspace
from .projects import _ci_at_push as _ci_at_push
from .projects import _local_repository as _local_repository
from .projects import _project as _project
from .projects import _workspace_root as _workspace_root
from .projects import base_without_ci as base_without_ci
from .settings import _console as _console
from .settings import _ideas as _ideas
from .settings import _keys as _keys
from .settings import _languages as _languages
from .settings import _secrets as _secrets
from .settings import _settings as _settings
from .settings import _validation as _validation
from .settings import _vault as _vault

logger = logging.getLogger(__name__)


GROUPS = ("notion", "github", "claude", "projects", "machine", "settings")


def run(
    config: config_module.Config, client: store.Store | None = None, *, remote: bool = False
) -> list[Check]:
    """Every check, in the order the dashboard lists them (`GROUPS`).

    `remote`: ask the remote for the newest version, as `doctor` does, rather
    than read what the last check found.
    """
    client = client or store.open(config, notion_only=True)
    jobs: list[tuple[str, Callable[[], list[Check]]]] = [
        ("claude", lambda: _claude(config)),
        ("claude", lambda: _models(config)),
        ("github", _github_token),
        ("github", _github_billing),
        ("projects", lambda: _workspace_root(config)),
        ("machine", lambda: _machine(config)),
        ("machine", lambda: _notifications(config)),
        ("machine", lambda: _version(config, remote)),
        ("machine", _environment),
        ("machine", _database),
        ("machine", _stray),
        ("settings", lambda: _settings(config)),
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_guarded(group, job)) for group, job in jobs]
        notion_found, space = _guard_notion(config, client)
        rows = _project_rows(client, space)
        # Only now: whether GitHub missing is a problem depends on the projects.
        access = pool.submit(_guarded("github", partial(_github_access, config, code=bool(rows))))
        per_project = [
            pool.submit(_guarded("projects", partial(_project, config, row))) for row in rows
        ]
        found = [
            *access.result(),
            *(check for future in futures for check in future.result()),
        ]
        project_found = [check for future in per_project for check in future.result()]
    # A repository the board's projects already answered for is said once, there.
    covered = {
        check.params.get("repository")
        for check in project_found
        if check.code == "github.repository"
    }
    found = [
        check
        for check in found
        if not (check.code == "github.reach" and check.params.get("repository") in covered)
    ]
    every = [*notion_found, *project_found, *found]
    # Sorted by group alone: within one, each check keeps its place.
    return [check for group in GROUPS for check in every if check.group == group]


def _guard_notion(
    config: config_module.Config, client: store.Store
) -> tuple[list[Check], workspace_module.Workspace | None]:
    try:
        return _board(config, client)
    except Exception as error:  # a check that cannot be made is a line, not a crash
        logger.exception("health: the Notion checks could not be made", extra=log.FILE_ONLY)
        return [_unknown("notion", error)], None


def _guarded(group: str, job: Callable[[], list[Check]]) -> Callable[[], list[Check]]:
    def guarded() -> list[Check]:
        try:
            return job()
        except Exception as error:
            logger.exception("health: the %s checks could not be made", group, extra=log.FILE_ONLY)
            return [_unknown(group, error)]

    return guarded


def _unknown(group: str, error: object) -> Check:
    return Check(
        f"{group}.unknown",
        group,
        WARN,
        "Check",
        "This check could not be made.",
        evidence=_first_line(error),
    )


def problems(checks: list[Check]) -> int:
    return sum(check.state == ERROR for check in checks)
