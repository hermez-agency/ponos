"""`session.py`: what comes back from a session, and how it is started."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from support import case

from ponos import config, session, vault

# -- session outcome ---------------------------------------------------------


@case
def a_verdict_is_read_from_the_last_result_line():
    assert session._verdict("blah\nRESULT: ok — removed the header") == "ok"
    assert session._verdict("**RESULT: blocked — which page?**") == "blocked"
    assert session._verdict("nothing of the sort") == ""
    # The last one wins: an agent may quote the format before using it.
    assert session._verdict("RESULT: blocked — x\nRESULT: ok — y") == "ok"


@case
def a_summary_drops_the_verdict_it_repeats():
    assert session._summary("x\nRESULT: ok — removed the header") == "removed the header"
    assert session._summary("**RESULT: blocked — which page?**") == "which page?"
    assert session._summary("no verdict here") == "no verdict here"


@case
def project_keys_match_what_claude_code_writes_on_disk():
    """Observed against real ~/.claude/projects folders."""
    assert session.project_key(Path("/home/salva/workspace/labo/trader-ia")) == (
        "-home-salva-workspace-labo-trader-ia"
    )
    assert (
        session.project_key(Path("/home/salva/.local/state/ponos/worktrees/trader-ia-3ca45168"))
        == "-home-salva--local-state-ponos-worktrees-trader-ia-3ca45168"
    )


@case
def a_remote_link_carries_its_host():
    """Once the runner is on a server, the session is there too.

    A link with a host resolves to an ssh command instead of a local claude,
    which is what keeps the Session column clickable from a laptop.
    """
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("abc-123", "/srv/work/app", "salva@vps")
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    assert query["host"] == ["salva@vps"]
    assert query["cwd"] == ["/srv/work/app"]
    # Without a host the link stays purely local.
    assert "host=" not in session.deep_link("abc-123", "/srv/work/app")


@case
def a_deep_link_survives_a_round_trip():
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("0486a9fd-44f6-4fff-9dee-9e58bc4062ba", "/home/me/my work")
    parsed = urlparse(link)
    assert parsed.scheme == session.SCHEME
    assert parsed.netloc == "session"
    assert parsed.path.strip("/") == "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"
    assert parse_qs(parsed.query)["cwd"][0] == "/home/me/my work"
    assert session.deep_link("abc") == "ponos://session/abc"


@case
def a_prompt_never_reaches_the_command_line():
    """The prompt goes on stdin, whatever its size, and argv keeps only options.

    Too long, an argument is refused by Linux before the session exists (E2BIG
    past 128 KiB). Short, it is worse: `ps` shows it to every user, and
    `pkill -f` matches it — a ticket quoting the last run's `vite --port 5199`
    had its session kill itself with `pkill -f "vite --port 5199"`. The marker
    here is drawn fresh, so this test cannot kill anything but its own fake.
    """
    marker = f"vite --port {uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        seen = home / "seen.json"
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, shutil, subprocess, sys\n"
            "prompt = sys.stdin.read()\n"
            # What the session that died did: kill a server by its command line.
            f"if shutil.which('pkill'): subprocess.run(['pkill', '-f', {marker!r}])\n"
            f"open({str(seen)!r}, 'w').write(json.dumps({{'args': sys.argv[1:], 'prompt': prompt}}))\n"
            "print(json.dumps({'type': 'result', 'result': 'RESULT: ok', 'session_id': 's'}))\n"
        )
        (home / "claude").chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        prompts = {
            "short": f"Restart the server: {marker}.",
            "long": f"{marker} " + "x" * 300_000,  # past the 128 KiB Linux takes
        }
        try:
            for name, text in prompts.items():
                for resume in (False, True):
                    outcome = session.run(
                        text,
                        cwd=home,
                        log=home / f"{name}.jsonl",
                        timeout_minutes=1,
                        session_id="0486a9fd-44f6-4fff-9dee-9e58bc4062ba",
                        resume=resume,
                    )
                    assert outcome.ok, (name, resume, outcome.error)
                    got = json.loads(seen.read_text())
                    assert got["prompt"] == text, (name, resume)
                    assert not any(marker in word for word in got["args"]), got["args"]
                    assert all(len(word) < 100 for word in got["args"]), got["args"]
        finally:
            os.environ["PATH"] = previous


@case
def a_session_is_not_given_the_runners_own_secrets():
    """A container holds every secret as a variable: none of them is the session's.

    An `env` run by the session printed them all into its transcript, the steps
    written into the ticket and the pull request. What the caller hands over —
    the vault's keys, the provider's — still arrives, and what the runner has
    read is masked in what the session prints.
    """
    own = {
        "PONOS_WEB_PASSWORD": "password-of-the-console",
        "PONOS_WEB_TOKEN": "token-of-the-console",
        "PONOS_NOTION_TOKEN": "ntn_token-of-notion",
        "PONOS_TELEGRAM_TOKEN": "token-of-telegram",
        "PONOS_SLACK_TOKEN": "xoxb-token-of-slack",
        "TICKET_RUNNER_NOTION_TOKEN": "ntn_token-of-old-notion",
    }
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        seen = home / "seen.json"
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "sys.stdin.read()\n"
            f"open({str(seen)!r}, 'w').write(json.dumps(dict(os.environ)))\n"
            # What `env` would have printed, had the variable been there.
            f"said = {own['PONOS_SLACK_TOKEN']!r} + ' ' + {own['PONOS_NOTION_TOKEN']!r}\n"
            "print(json.dumps({'type': 'assistant', 'message': {'content': "
            "[{'type': 'text', 'text': said}]}}))\n"
            "print(json.dumps({'type': 'result', 'result': 'RESULT: ok', 'session_id': 's'}))\n"
        )
        (home / "claude").chmod(0o755)
        previous = {name: os.environ.get(name) for name in [*own, "PATH", "UNRELATED"]}
        os.environ.update(own, UNRELATED="kept")
        os.environ["PATH"] = f"{home}{os.pathsep}{previous['PATH']}"
        try:
            # Read as `config.load` reads them: from now on, masked.
            config.secret({}, "notify.slack", "token")
            config.secret({"PONOS_NOTION_TOKEN": own["PONOS_NOTION_TOKEN"]}, "notion", "token")
            outcome = session.run(
                "env",
                cwd=home,
                log=home / "session.jsonl",
                timeout_minutes=1,
                environment={"NPM_TOKEN": "granted-by-the-vault"},
            )
            assert outcome.ok, outcome.error
            got = json.loads(seen.read_text())
            for name in own:
                assert name not in got, name
            assert got["UNRELATED"] == "kept"
            assert got["NPM_TOKEN"] == "granted-by-the-vault"
            transcript = (home / "session.jsonl").read_text()
            assert own["PONOS_SLACK_TOKEN"] not in transcript, transcript
            assert own["PONOS_NOTION_TOKEN"] not in transcript, transcript
            assert vault.MASK in transcript
        finally:
            vault.forget()
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@case
def a_link_cannot_slip_an_option_into_ssh_or_claude():
    """A link is something anybody can paste into a cell, and a click runs it.

    `host=-oProxyCommand=…` is not a machine, it is an ssh option that runs a
    command before any connection is tried — and an identifier starting with a
    dash would be an option to `claude` just the same. Both are refused before
    anything is looked up, and the destination ssh is given comes after `--`.
    """
    identifier = "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"
    for uri in (
        f"ponos://session/{identifier}?host=-oProxyCommand=touch%20/tmp/owned",
        f"ponos://session/{identifier}?host=me%40box%20-oProxyCommand=x",
        f"ponos://session/{identifier}?host=me;id",
        "ponos://session/--dangerously-skip-permissions",
        "ponos://session/abc$(id)",
    ):
        try:
            session.resume_command(uri)
        except ValueError as error:
            assert str(error), uri
        else:
            raise AssertionError(f"accepted: {uri}")

    original = shutil.which
    session.shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"
    try:
        cwd, command = session.resume_command(
            session.deep_link(identifier, "/srv/work/app", "salva@vps.example.org")
        )
        _, bracketed = session.resume_command(f"ponos://session/{identifier}?host=me%40%5B::1%5D")
    finally:
        session.shutil.which = original
    assert command[:4] == ["ssh", "-t", "--", "salva@vps.example.org"], command
    assert command[4].endswith(f"claude --resume {identifier}"), command
    assert bracketed[3] == "me@[::1]", bracketed
