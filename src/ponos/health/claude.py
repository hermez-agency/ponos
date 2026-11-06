"""The Claude Code group: the binary, its version, who answers the sessions, the models."""

from __future__ import annotations

import re
import subprocess

from .. import config as config_module
from .. import models, provider, session
from .check import ERROR, INFO, OK, PROBE_TIMEOUT, WARN, Check, _check, _installing

# A floor, not a measurement: Claude Code older than this is reported as too
# old before a ticket finds out. Raise it the day a flag the runner passes
# needs a newer one.
MINIMUM_CLAUDE = (2, 0, 0)


CLAUDE_INSTALL = "https://docs.claude.com/en/docs/claude-code/setup"


CLAUDE_MODELS = {"haiku", "sonnet", "opus", "fable"}


def _claude(config: config_module.Config) -> list[Check]:
    binary = session.available()
    found: list[Check] = []
    if not binary:
        found.append(
            _check(
                "claude.installed",
                ERROR,
                "Claude Code",
                "Claude Code is not installed on this machine.",
                cause="`claude` is not on the PATH of the runner.",
                url=CLAUDE_INSTALL,
                **_installing(
                    "claude", "Install Claude Code, then check that `claude --version` answers."
                ),
            )
        )
    else:
        found.append(_claude_version(binary))
    found.extend(_provider(config, installed=bool(binary)))
    return found


def _claude_version(binary: str) -> Check:
    try:
        printed = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=PROBE_TIMEOUT
        ).stdout
    except (OSError, subprocess.SubprocessError):
        printed = ""
    version = re.search(r"\d+(?:\.\d+){1,2}", printed)
    if not version:
        return _check(
            "claude.version",
            WARN,
            "Claude Code version",
            "The version of Claude Code could not be read.",
            evidence=printed.strip(),
        )
    numbers = tuple(int(part) for part in version.group(0).split("."))
    numbers += (0,) * (3 - len(numbers))
    needed = ".".join(str(part) for part in MINIMUM_CLAUDE)
    if numbers < MINIMUM_CLAUDE:
        return _check(
            "claude.version",
            ERROR,
            "Claude Code version",
            "Claude Code {{version}} is older than {{needed}}.",
            params={"version": version.group(0), "needed": needed},
            cause="The runner passes flags that older versions do not know.",
            steps=["Update Claude Code: run `claude update`."],
            url=CLAUDE_INSTALL,
        )
    return _check(
        "claude.version",
        OK,
        "Claude Code version",
        "Claude Code {{version}} is installed at {{path}}.",
        params={"version": version.group(0), "path": binary},
    )


def _provider(config: config_module.Config, *, installed: bool) -> list[Check]:
    """Which account the sessions run on, and whether it would answer — see provider.py.

    No key leaves this machine here: the CLI's sign-in is asked of the CLI, and
    a key is said to be there or not. Whether Anthropic or OpenRouter accept it
    is the first connection's question, asked while somebody is there to fix it.
    """
    which = provider.chosen(config)
    name, detail = provider.describe(config)
    stated = config.claude.provider
    found = [
        _check(
            "claude.provider",
            OK,
            "Claude provider",
            "{{name}}: {{detail}} ({{origin}}).",
            params={
                "name": name,
                "detail": detail,
                "origin": f'claude.provider = "{stated}"' if stated else "claude.provider not set",
            },
        )
    ]
    if reason := provider.problem(config):
        found.append(
            _check(
                "claude.login",
                ERROR,
                "Claude connection",
                "Sessions have no way to answer: {{reason}}.",
                params={"reason": reason},
                cause="The provider the settings name is missing its key.",
                steps=["Choose a provider and give its key in Settings › Claude."],
            )
        )
    elif which == "cli":
        if not installed:
            return found
        login = provider.cli_login()
        if login.ok:
            found.append(
                _check(
                    "claude.login",
                    OK,
                    "Claude connection",
                    "Signed in: {{who}}.",
                    params={"who": login.said},
                )
            )
        else:
            found.append(
                _check(
                    "claude.login",
                    ERROR,
                    "Claude connection",
                    "Claude Code is not signed in.",
                    cause="No account was connected to the CLI on this machine.",
                    steps=[
                        "In a terminal on this machine, run `claude auth login` and follow the link."
                    ],
                    evidence=login.said,
                )
            )
    else:
        found.append(
            _check(
                "claude.login",
                OK,
                "Claude connection",
                "Sessions are answered by {{name}}: no Claude in Chrome, nothing to wait for, billed as it is used.",
                params={"name": provider.NAMES[which]},
            )
        )
    return found


def _models(config: config_module.Config) -> list[Check]:
    """Which model a ticket runs on when it names none, and who finds the ideas."""
    runner = config.runner
    routed = bool(config.openrouter.key and config.openrouter.route_sessions)
    found: list[Check] = []
    if runner.auto_model:
        grid = runner.model_grid()
        found.append(
            _check(
                "claude.model",
                OK,
                "Models",
                "An empty Model is chosen by the rules: {{levels}}.",
                params={
                    "levels": ", ".join(
                        f"{level} {grid.model(level) or '—'}" for level in models.LEVELS
                    )
                },
            )
        )
        if not runner.auto_model_escalate:
            found.append(
                _check(
                    "claude.model",
                    INFO,
                    "Models",
                    "runner.auto_model_escalate = false: a failed run comes back on the same model.",
                )
            )
        if routed and any(grid.model(level) in CLAUDE_MODELS for level in models.LEVELS):
            found.append(
                _check(
                    "claude.model",
                    WARN,
                    "Models",
                    "Sessions go through OpenRouter: name its slugs in runner.auto_model_*.",
                )
            )
    else:
        found.append(
            _check(
                "claude.model",
                INFO,
                "Models",
                "runner.auto_model = false: an empty Model runs on {{model}}.",
                params={"model": runner.model or "the CLI's default model"},
            )
        )
    found.append(
        _check(
            "claude.ideas",
            OK,
            "Ideas model",
            "Ideas are found by {{model}}, ten at a batch (runner.ideas_model).",
            params={"model": runner.ideas_model or "the CLI's default model"},
        )
    )
    if routed and runner.ideas_model in CLAUDE_MODELS:
        found.append(
            _check(
                "claude.ideas",
                WARN,
                "Ideas model",
                "Sessions go through OpenRouter: name its slug in runner.ideas_model.",
            )
        )
    # Off, Fable never runs, whatever a level or a ticket says.
    if runner.use_fable:
        found.append(
            _check(
                "claude.fable",
                OK,
                "Claude Fable",
                "Claude Fable is allowed (runner.use_fable = true).",
            )
        )
    else:
        found.append(
            _check(
                "claude.fable",
                INFO,
                "Claude Fable",
                "runner.use_fable = false: Claude Fable is not allowed, {{instead}} runs in its place.",
                params={"instead": models.INSTEAD_OF_FABLE},
            )
        )
    return found
