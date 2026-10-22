"""Who answers a session: the CLI signed in as you, an Anthropic key, or OpenRouter.

On a laptop the question never came up. Claude Code was signed in once with
`claude login`, and every session the runner started was that subscription.
A server is where it does come up: nobody sits at its browser to sign in, a key
is what a server is usually given, and the three ways are not the same thing.

- **`cli`** — the subscription, signed in with `claude login` (in a container,
  from the terminal Dokploy gives you) or handed over as a token drawn by
  `claude setup-token`, in `CLAUDE_CODE_OAUTH_TOKEN`. The only one that keeps
  Claude in Chrome, which loads on an OAuth session and nothing else, and the
  only one whose credits come in windows worth waiting for (credits.py).
- **`api_key`** — an Anthropic key, billed by the token. No browser, nothing to
  wait for.
- **`openrouter`** — the key of `[openrouter]`; with `route_sessions` the
  sessions run there, and a model is an OpenRouter slug. openrouter.py says what
  goes with that.

The choice is `claude.provider`. A file that has none reads the way it always
did — see `chosen` — so an installation nobody touches is not moved anywhere.

The checks below say whether a choice *works*, not merely whether it is filled
in, because a key with a typo in it is found out on the first ticket otherwise —
on a server, hours later, by nobody.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from . import http, openrouter, session
from .config import OPENROUTER_URL, Config

ANTHROPIC_MODELS = "https://api.anthropic.com/v1/models"

# What each provider is called where a person reads it.
NAMES = {
    "cli": "Claude Code CLI (subscription)",
    "api_key": "Anthropic API key",
    "openrouter": "OpenRouter",
}

# What somebody types to sign the CLI in, and where. In a container that is the
# terminal Dokploy opens on the service — or `docker compose exec`.
LOGIN = "claude auth login"

# The other way to hand a server the subscription: a long-lived token drawn with
# `claude setup-token` on a machine that has a browser, which Claude Code reads
# from the environment. Nothing to type in a terminal on the server.
OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"

CHECK_TIMEOUT = 15


@dataclass(frozen=True)
class Check:
    """One answer: does it work, and in a sentence, who or why."""

    ok: bool
    said: str


def chosen(config: Config) -> str:
    """The provider in use: the one the file names, else the one it behaved as."""
    if config.claude.provider:
        return config.claude.provider
    if config.openrouter.key and config.openrouter.route_sessions:
        return "openrouter"
    return "cli"


def on_openrouter(model: str) -> bool:
    """Is this model an OpenRouter slug — `vendor/model` — and not a Claude name?"""
    return "/" in model.strip()


def environment(config: Config, model: str = "") -> dict[str, str]:
    """What a session is started with, on top of the environment it inherits.

    The OpenRouter key is handed over whatever the provider — a ticket may want a
    GPT whoever answers it. An Anthropic key only when it is the provider: given
    to a CLI session, it would quietly take the place of the subscription.

    A session asked to run on an OpenRouter slug is the exception to the rule
    below: it talks to OpenRouter whatever the provider, because that is the
    only place the slug means anything — the console's chat can change model, and
    so gateway, from one message to the next.
    """
    variables = openrouter.environment(config.openrouter)
    which = chosen(config)
    if which == "api_key" and config.claude.api_key:
        variables["ANTHROPIC_API_KEY"] = config.claude.api_key
    if which != "openrouter":
        # A key that is only *available* must not carry the sessions off.
        variables.pop("ANTHROPIC_BASE_URL", None)
        variables.pop("ANTHROPIC_AUTH_TOKEN", None)
    if model and on_openrouter(model) and config.openrouter.key:
        variables["ANTHROPIC_BASE_URL"] = openrouter.anthropic_url(config.openrouter)
        variables["ANTHROPIC_AUTH_TOKEN"] = config.openrouter.key
    return variables


def masked(secret: str) -> str:
    """Enough of a key to recognise it by: its start and its last four."""
    secret = secret.strip()
    if len(secret) <= 12:
        return "set" if secret else ""
    return f"{secret[:6]}…{secret[-4:]}"


def cli_login() -> Check:
    """Is Claude Code signed in with an account — not with a key?

    Asked of `claude auth status`, with every key taken out of its environment:
    a key in the container's environment would answer "logged in" for an
    account nobody signed into.
    """
    binary = session.available()
    if not binary:
        return Check(False, "claude is not installed")
    quiet = {
        name: value
        for name, value in os.environ.items()
        if name not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
    }
    try:
        answered = subprocess.run(
            [binary, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT,
            env=quiet,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Check(False, f"claude auth status: {error}")
    try:
        status = json.loads(answered.stdout or "{}")
    except ValueError:
        status = {}
    if not isinstance(status, dict) or not status.get("loggedIn"):
        return Check(False, f"not signed in — {LOGIN}")
    if status.get("authMethod") == "oauth_token":
        # `claude setup-token`, given as CLAUDE_CODE_OAUTH_TOKEN: the
        # subscription, with no account to name — and no sign-in to keep.
        return Check(True, f"subscription token ({OAUTH_TOKEN_ENV})")
    who = str(status.get("email") or status.get("orgName") or "an account")
    plan = str(status.get("subscriptionType") or "")
    return Check(True, f"{who} ({plan})" if plan else who)


def _get(service: str, url: str, headers: dict[str, str]) -> tuple[int, dict]:
    answer = http.send(service, "GET", url, headers=headers, timeout=CHECK_TIMEOUT)
    if answer.status >= 400:
        return answer.status, {}
    return answer.status, json.loads(answer.body.decode("utf-8") or "{}")


def api_key(key: str) -> Check:
    """An Anthropic key, asked to list the models it can use."""
    if not key:
        return Check(False, "no key")
    try:
        code, _ = _get(
            "anthropic", ANTHROPIC_MODELS, {"x-api-key": key, "anthropic-version": "2023-06-01"}
        )
    except (http.Unanswered, ValueError) as error:
        return Check(False, f"Anthropic could not be reached: {error}")
    if code == 200:
        return Check(True, f"accepted by Anthropic — {masked(key)}")
    if code in (401, 403):
        return Check(False, "Anthropic refused this key")
    return Check(False, f"Anthropic answered {code}")


def openrouter_key(key: str, base_url: str = OPENROUTER_URL) -> Check:
    """An OpenRouter key, asked what it is."""
    if not key:
        return Check(False, "no key")
    base = (base_url or OPENROUTER_URL).rstrip("/")
    try:
        code, said = _get("openrouter", f"{base}/key", {"Authorization": f"Bearer {key}"})
    except (http.Unanswered, ValueError) as error:
        return Check(False, f"OpenRouter could not be reached: {error}")
    if code == 200:
        data = said.get("data") if isinstance(said.get("data"), dict) else {}
        label = str(data.get("label") or "") if data else ""
        return Check(True, f"accepted by OpenRouter — {label or masked(key)}")
    if code in (401, 403):
        return Check(False, "OpenRouter refused this key")
    return Check(False, f"OpenRouter answered {code}")


def describe(config: Config) -> tuple[str, str]:
    """The provider and what it runs on, in a few words — no network, no secret."""
    which = chosen(config)
    if which == "api_key":
        return NAMES[which], masked(config.claude.api_key) or "no key"
    if which == "openrouter":
        key = masked(config.openrouter.key) or "no key"
        where = (
            "sessions on OpenRouter"
            if config.openrouter.route_sessions
            else "sessions still on the CLI's sign-in"
        )
        return NAMES[which], f"{key}, {where}"
    return NAMES[which], "claude login"


def problem(config: Config) -> str:
    """What makes the chosen provider unusable from the file alone, or ""."""
    which = chosen(config)
    if which == "api_key" and not config.claude.api_key:
        return 'claude.provider = "api_key" with no key: claude.api_key, or ANTHROPIC_API_KEY'
    if which == "openrouter" and not config.openrouter.key:
        return 'claude.provider = "openrouter" with no key: openrouter.key, or OPENROUTER_API_KEY'
    return ""
