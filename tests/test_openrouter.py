"""`openrouter.py`: a session routed elsewhere, told where to go and with what."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
from pathlib import Path

from support import _config, case

from ponos import config as C
from ponos import openrouter, session

# -- every other model --------------------------------------------------------


@case
def no_openrouter_key_starts_a_session_exactly_as_before():
    """The one thing an unconfigured key must cost: nothing at all."""
    config = _config("")
    assert config.openrouter.key == ""
    assert config.openrouter.route_sessions is False
    assert openrouter.environment(config.openrouter) == {}
    # And a key can be there without anything about the runner changing.
    keyed = _config('[openrouter]\nkey = "sk-or-v1-secret"\n')
    assert openrouter.environment(keyed.openrouter) == {
        "OPENROUTER_API_KEY": "sk-or-v1-secret",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }


@case
def a_routed_session_is_told_where_to_go_and_with_what():
    """`ANTHROPIC_AUTH_TOKEN`, not `ANTHROPIC_API_KEY`: a gateway wants a bearer."""
    config = _config('[openrouter]\nkey = "sk-or-v1-secret"\nroute_sessions = true\n')
    variables = openrouter.environment(config.openrouter)
    assert variables["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert variables["ANTHROPIC_AUTH_TOKEN"] == "sk-or-v1-secret"
    assert "ANTHROPIC_API_KEY" not in variables
    # A gateway of your own, and the trailing slash that would double up.
    own = _config(
        '[openrouter]\nkey = "k"\nroute_sessions = true\nbase_url = "https://gw.example/v1/"\n'
    )
    assert openrouter.environment(own.openrouter)["ANTHROPIC_BASE_URL"] == "https://gw.example/v1"
    blank = _config('[openrouter]\nkey = "k"\nbase_url = ""\n')
    assert blank.openrouter.base_url == C.OPENROUTER_URL, "emptied, the default answers"


@case
def what_the_runner_adds_wins_over_the_shell_it_was_started_from():
    """A key configured for the runner beats one that happens to be exported."""
    seen: dict[str, str] = {}

    class _Process:
        stdin = io.StringIO()
        stdout: list[str] = []
        returncode = 0

        def wait(self) -> None:
            pass

    def _popen(command, **arguments):
        seen.update(arguments["env"])
        return _Process()

    directory = Path(tempfile.mkdtemp())
    original = (session.available, subprocess.Popen)
    session.available = lambda: "/usr/bin/claude"
    subprocess.Popen = _popen
    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-shell"
    try:
        session.run(
            "hello",
            cwd=directory,
            log=directory / "run.jsonl",
            environment={"OPENROUTER_API_KEY": "sk-or-v1-configured"},
        )
    finally:
        session.available, subprocess.Popen = original
        os.environ.pop("OPENROUTER_API_KEY", None)
    assert seen["OPENROUTER_API_KEY"] == "sk-or-v1-configured"
    assert seen["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
