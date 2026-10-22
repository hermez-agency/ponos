"""`provider.py`: who answers the sessions."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess

from support import _environment, _saved, case

from ponos.runner import Runner

# -- what a message to the workspace carries ----------------------------------


@case
def a_subscription_token_in_the_environment_is_a_signed_in_cli():
    """`claude setup-token` handed over as CLAUDE_CODE_OAUTH_TOKEN: the CLI works, and says how."""
    from ponos import provider

    answered = json.dumps({"loggedIn": True, "authMethod": "oauth_token"})
    original = provider.subprocess.run, provider.session.available
    provider.session.available = lambda: "/usr/bin/claude"
    provider.subprocess.run = lambda *_, **__: subprocess.CompletedProcess([], 0, answered, "")
    try:
        check = provider.cli_login()
    finally:
        provider.subprocess.run, provider.session.available = original
    assert check.ok and "CLAUDE_CODE_OAUTH_TOKEN" in check.said, check


@case
def a_file_with_no_provider_runs_its_sessions_where_it_always_did():
    """`claude.provider` is a choice; a file written before it is not moved anywhere."""
    from ponos import provider

    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        _, plain = _saved()
        assert provider.chosen(plain) == "cli" and provider.environment(plain) == {}
        _, routed = _saved('\n[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n')
        assert provider.chosen(routed) == "openrouter"
        assert provider.environment(routed)["ANTHROPIC_AUTH_TOKEN"] == "sk-or-1234567890"

        # Chosen on purpose, the provider wins over a key that is only there.
        _, cli = _saved(
            '\n[claude]\nprovider = "cli"\n[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n'
        )
        given = provider.environment(cli)
        assert "ANTHROPIC_AUTH_TOKEN" not in given and "ANTHROPIC_BASE_URL" not in given
        assert given["OPENROUTER_API_KEY"] == "sk-or-1234567890", "still there for the work"

        _, keyed = _saved('\n[claude]\nprovider = "api_key"\napi_key = "sk-ant-abcdefghijkl"\n')
        assert provider.environment(keyed) == {"ANTHROPIC_API_KEY": "sk-ant-abcdefghijkl"}
        assert provider.describe(keyed) == ("Anthropic API key", "sk-ant…ijkl")
        _, typo = _saved('\n[claude]\nprovider = "anthropic"\n')
        assert typo.claude.provider == "" and provider.chosen(typo) == "cli"

        _, empty = _saved('\n[claude]\nprovider = "api_key"\n')
        assert "ANTHROPIC_API_KEY" in provider.problem(empty)
        # The CLI's session is never handed the key it would sign in with instead.
        _, cli_keyed = _saved('\n[claude]\nprovider = "cli"\napi_key = "sk-ant-abcdefghijkl"\n')
        assert provider.environment(cli_keyed) == {}

    # A container is given its keys in the environment; the file still wins.
    with _environment(
        ANTHROPIC_API_KEY="sk-ant-from-env-0000", OPENROUTER_API_KEY="sk-or-env-0000"
    ):
        _, bare = _saved()
        assert bare.claude.api_key == "sk-ant-from-env-0000"
        assert bare.openrouter.key == "sk-or-env-0000"
        _, written = _saved('\n[claude]\napi_key = "sk-ant-typed"\n')
        assert written.claude.api_key == "sk-ant-typed"
        assert provider.problem(_saved('\n[claude]\nprovider = "api_key"\n')[1]) == ""


@case
def only_the_cli_waits_for_credits():
    """A key is billed as it is used: no window to wait for, no share to reserve."""
    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        assert Runner(_saved()[1], quiet=True)._waits_for_credits
        keyed = _saved('\n[claude]\nprovider = "api_key"\napi_key = "sk-ant-abcdefghijkl"\n')[1]
        assert not Runner(keyed, quiet=True)._waits_for_credits
        routed = _saved('\n[openrouter]\nkey = "sk-or-1234567890"\nroute_sessions = true\n')[1]
        assert not Runner(routed, quiet=True)._waits_for_credits


@case
def doctor_says_which_provider_answers_and_counts_one_that_cannot():
    from ponos.__main__ import _doctor_provider

    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert _doctor_provider(_saved('\n[claude]\nprovider = "api_key"\n')[1]) == 1
        assert "Anthropic API key" in out.getvalue() and "ANTHROPIC_API_KEY" in out.getvalue()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            routed = '\n[claude]\nprovider = "openrouter"\n[openrouter]\nkey = "sk-or-1234567890"\n'
            assert _doctor_provider(_saved(routed)[1]) == 0
        said = out.getvalue()
        assert 'claude.provider = "openrouter"' in said and "sk-or-…7890" in said
        assert "route_sessions = false" in said, "a provider whose sessions are not on it is said"


@case
def a_slug_session_reaches_claude_code_without_the_v1_it_adds_itself():
    """`/api/v1` + Claude Code's `/v1/messages` was a 404, told as « issue with the selected model »."""
    from ponos import provider

    with _environment(ANTHROPIC_API_KEY=None, OPENROUTER_API_KEY=None):
        _, keyed = _saved('\n[openrouter]\nkey = "sk-or-1234567890"\n')
        given = provider.environment(keyed, model="deepseek/deepseek-v3.1-terminus")
        assert given["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
        assert given["OPENROUTER_BASE_URL"] == "https://openrouter.ai/api/v1"
        _, own = _saved(
            '\n[openrouter]\nkey = "sk-or-1234567890"\nbase_url = "https://gw.example/anthropic/"\n'
        )
        given = provider.environment(own, model="deepseek/deepseek-v3.1-terminus")
        assert given["ANTHROPIC_BASE_URL"] == "https://gw.example/anthropic"
