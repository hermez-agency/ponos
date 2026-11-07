"""`session.py`: what comes back from a session, and how it is started."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from support import _bare_runner, case

from ponos import config, session, vault

# -- session outcome ---------------------------------------------------------


@case
def a_verdict_is_read_from_the_last_result_line() -> None:
    assert session._verdict("blah\nRESULT: ok — removed the header") == "ok"
    assert session._verdict("**RESULT: blocked — which page?**") == "blocked"
    assert session._verdict("nothing of the sort") == ""
    # The last one wins: an agent may quote the format before using it.
    assert session._verdict("RESULT: blocked — x\nRESULT: ok — y") == "ok"


@case
def a_summary_drops_the_verdict_it_repeats() -> None:
    assert session._summary("x\nRESULT: ok — removed the header") == "removed the header"
    assert session._summary("**RESULT: blocked — which page?**") == "which page?"
    assert session._summary("no verdict here") == "no verdict here"


@case
def project_keys_match_what_claude_code_writes_on_disk() -> None:
    """Observed against real ~/.claude/projects folders."""
    assert session.project_key(Path("/home/salva/workspace/labo/trader-ia")) == (
        "-home-salva-workspace-labo-trader-ia"
    )
    assert (
        session.project_key(Path("/home/salva/.local/state/ponos/worktrees/trader-ia-3ca45168"))
        == "-home-salva--local-state-ponos-worktrees-trader-ia-3ca45168"
    )


@case
def a_remote_link_carries_its_host() -> None:
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
def a_deep_link_survives_a_round_trip() -> None:
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("0486a9fd-44f6-4fff-9dee-9e58bc4062ba", "/home/me/my work")
    parsed = urlparse(link)
    assert parsed.scheme == session.SCHEME
    assert parsed.netloc == "session"
    assert parsed.path.strip("/") == "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"
    assert parse_qs(parsed.query)["cwd"][0] == "/home/me/my work"
    assert session.deep_link("abc") == "ponos://session/abc"


@case
def a_prompt_never_reaches_the_command_line() -> None:
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
def a_session_is_not_given_the_runners_own_secrets() -> None:
    """A container holds every secret as a variable: none of them is the session's.

    An `env` run by the session printed them all into its transcript, the steps
    written into the ticket and the pull request. What the caller hands over —
    the vault's keys, the provider's — still arrives, and what the runner has
    read is masked in what the session prints.
    """
    own = {
        "PONOS_WEB_PASSWORD": "password-of-the-console",
        "PONOS_WEB_TOKEN": "token-of-the-console",
        "PONOS_GITHUB_TOKEN": "github_pat_token-of-github",
        "PONOS_TELEGRAM_TOKEN": "token-of-telegram",
        "PONOS_SLACK_TOKEN": "xoxb-token-of-slack",
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
            f"said = {own['PONOS_SLACK_TOKEN']!r} + ' ' + {own['PONOS_GITHUB_TOKEN']!r}\n"
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
            config.secret(
                {"PONOS_GITHUB_TOKEN": own["PONOS_GITHUB_TOKEN"]}, "github_access", "token"
            )
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
            assert own["PONOS_GITHUB_TOKEN"] not in transcript, transcript
            assert vault.MASK in transcript
        finally:
            vault.forget()
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@case
def a_session_of_a_run_is_given_its_share_of_the_cores_for_its_tests(state_home: Path) -> None:
    """Every runner its tests call reads its number of workers from the environment.

    On 23 October seven sessions took the load to 74 on twenty cores: Vitest
    took a worker per core, Playwright nine browsers, each believing the machine
    was its own. With `max_concurrent = 7` on twenty cores a session gets two —
    and what the project's vault grants under one of these names still wins.
    """
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        seen = home / "seen.json"
        (home / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "sys.stdin.read()\n"
            f"open({str(seen)!r}, 'w').write(json.dumps(dict(os.environ)))\n"
            "print(json.dumps({'type': 'result', 'result': 'RESULT: ok', 'session_id': 's'}))\n"
        )
        (home / "claude").chmod(0o755)
        previous, affinity = os.environ["PATH"], os.sched_getaffinity
        os.environ["PATH"] = f"{home}{os.pathsep}{previous}"
        os.sched_getaffinity = lambda pid: set(range(20))
        runner = _bare_runner(None)
        runner.config.runner.max_concurrent = 7

        def environment(**given: str) -> dict[str, str]:
            outcome = runner._paid(
                "1" * 32,
                "go",
                cwd=home,
                log=home / "session.jsonl",
                timeout_minutes=1,
                environment=given,
            )
            assert outcome.ok, outcome.error
            given_to_it: dict[str, str] = json.loads(seen.read_text())
            return given_to_it

        try:
            got = environment(GOMAXPROCS="8")
            assert {name: got[name] for name in session.WORKERS} == {
                **dict.fromkeys(session.WORKERS, "2"),
                "GOMAXPROCS": "8",
            }, got
            runner.config.runner.max_concurrent = 40
            assert environment()["VITEST_MAX_WORKERS"] == "1", "one at the least"
            runner.config.runner.session_workers = 5
            got = environment()
            assert all(got[name] == "5" for name in session.WORKERS), got
        finally:
            os.environ["PATH"], os.sched_getaffinity = previous, affinity


@case
def a_link_cannot_slip_an_option_into_ssh_or_claude() -> None:
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
    shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}"  # type: ignore[assignment]  # a double: every program is installed
    try:
        cwd, command = session.resume_command(
            session.deep_link(identifier, "/srv/work/app", "salva@vps.example.org")
        )
        _, bracketed = session.resume_command(f"ponos://session/{identifier}?host=me%40%5B::1%5D")
    finally:
        shutil.which = original
    assert command[:4] == ["ssh", "-t", "--", "salva@vps.example.org"], command
    assert command[4].endswith(f"claude --resume {identifier}"), command
    assert bracketed[3] == "me@[::1]", bracketed


@case
def a_session_cut_short_keeps_what_its_last_event_said_it_cost() -> None:
    """The watchdog's kill and the console's Stop do not make a session free."""

    def ended(final: dict[str, Any], **flags: bool) -> session.Outcome:
        return session._outcome(
            final,
            ["half of it"],
            session_id="s",
            log=Path("x"),
            stderr_path=Path("/nowhere/stderr"),
            seconds=1800.0,
            code=-9,
            interrupted=flags.get("interrupted", False),
            timed_out=flags.get("timed_out", False),
            timeout_minutes=30,
        )

    final = {"type": "result", "total_cost_usd": 4.2, "num_turns": 37}
    timed_out = ended(final, timed_out=True)
    assert timed_out.timed_out and timed_out.resulted
    assert timed_out.cost_usd == 4.2 and timed_out.turns == 37, timed_out
    assert ended({}, timed_out=True).cost_usd == 0.0, "no last event, no price to keep"
    stopped = ended({}, interrupted=True)
    assert stopped.stopped and stopped.cost_usd == 0.0


# -- resuming a session ------------------------------------------------------

IDENTIFIER = "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"


@contextmanager
def _installed(*names: str) -> Iterator[list[list[str]]]:
    """Only `names` on the PATH, and every Popen recorded rather than started."""
    started: list[list[str]] = []

    class Popen:
        def __init__(self, command: list[str], **kept: object) -> None:
            assert kept == {"start_new_session": True}, kept
            started.append(command)

    which, popen = shutil.which, subprocess.Popen
    shutil.which = lambda name, *rest, **kept: f"/usr/bin/{name}" if name in names else None  # type: ignore[assignment]  # a double: only these are installed
    subprocess.Popen = Popen  # type: ignore[assignment,misc]  # a double: no terminal opens
    try:
        yield started
    finally:
        shutil.which, subprocess.Popen = which, popen  # type: ignore[misc]


@contextmanager
def _projects() -> Iterator[Path]:
    """A throwaway ~/.claude/projects, where Claude Code files its transcripts."""
    original = session.PROJECTS
    with tempfile.TemporaryDirectory() as tmp:
        session.PROJECTS = Path(tmp)
        try:
            yield session.PROJECTS
        finally:
            session.PROJECTS = original


@case
def a_transcript_is_moved_under_the_repository_it_belongs_to() -> None:
    """The worktree goes, the session follows the repository's picker."""
    repository = Path("/home/me/work/app")
    with _projects() as projects:
        assert session.relocate(IDENTIFIER, repository) is None, "nothing filed, nothing moved"

        worktree = projects / session.project_key(Path("/state/worktrees/app-1"))
        worktree.mkdir()
        (worktree / f"{IDENTIFIER}.jsonl").write_text("{}\n")
        moved = session.relocate(IDENTIFIER, repository)
        target = projects / session.project_key(repository) / f"{IDENTIFIER}.jsonl"
        assert moved == target and target.read_text() == "{}\n", moved
        assert not worktree.exists(), "the worktree's folder, left empty, goes with it"

        assert session.relocate(IDENTIFIER, repository) == target, "already in place: left there"
        assert target.exists()


@case
def a_transcript_moved_leaves_what_else_its_folder_held() -> None:
    other = "11111111-2222-3333-4444-555555555555"
    with _projects() as projects:
        worktree = projects / "-state-worktrees-app-1"
        worktree.mkdir()
        (worktree / f"{IDENTIFIER}.jsonl").write_text("{}\n")
        (worktree / f"{other}.jsonl").write_text("{}\n")
        moved = session.relocate(IDENTIFIER, Path("/home/me/work/app"))
        assert moved is not None and moved.exists(), moved
        assert (worktree / f"{other}.jsonl").exists() and not (worktree / moved.name).exists()


@case
def a_transcript_that_cannot_move_stays_resumable_where_it_is() -> None:
    with _projects() as projects:
        worktree = projects / "-state-worktrees-app-1"
        worktree.mkdir()
        (worktree / f"{IDENTIFIER}.jsonl").write_text("{}\n")
        # Where the repository's folder should be, a file: mkdir fails.
        (projects / session.project_key(Path("/home/me/work/app"))).write_text("")
        assert session.relocate(IDENTIFIER, Path("/home/me/work/app")) is None
        assert (worktree / f"{IDENTIFIER}.jsonl").exists()


@case
def a_link_that_is_not_a_session_link_is_refused() -> None:
    for uri in (
        f"https://session/{IDENTIFIER}",
        f"ponos://open/{IDENTIFIER}",
        "ponos://session/",
    ):
        try:
            session.resume_command(uri)
        except ValueError as error:
            assert str(error), uri
        else:
            raise AssertionError(f"accepted: {uri}")


@case
def a_remote_session_is_resumed_over_ssh_with_its_words_quoted() -> None:
    """The remote command is one string a shell reads: the directory is quoted."""
    cwd = "/srv/my work/it's here"
    with _installed("ssh"):
        home, command = session.resume_command(session.deep_link(IDENTIFIER, cwd, "me@vps"))
    assert home == str(Path.home()), "the local side has no directory to be in"
    assert command[:4] == ["ssh", "-t", "--", "me@vps"], command
    assert command[4] == (
        f"cd {shlex.quote(cwd)} 2>/dev/null; claude --resume {shlex.quote(IDENTIFIER)}"
    ), command
    assert "'/srv/my work/it'\"'\"'s here'" in command[4], command

    with _installed("claude"):
        try:
            session.resume_command(session.deep_link(IDENTIFIER, cwd, "me@vps"))
        except FileNotFoundError as error:
            assert "ssh" in str(error) and "me@vps" in str(error), error
        else:
            raise AssertionError("resumed over an ssh that is not there")


@case
def a_local_session_is_resumed_in_its_directory_or_at_home() -> None:
    with tempfile.TemporaryDirectory() as tmp, _installed("claude"):
        assert session.resume_command(session.deep_link(IDENTIFIER, tmp)) == (
            tmp,
            ["/usr/bin/claude", "--resume", IDENTIFIER],
        )
        gone = session.deep_link(IDENTIFIER, f"{tmp}/deleted-worktree")
        assert session.resume_command(gone)[0] == str(Path.home()), "a vanished worktree: home"
        assert session.resume_command(f"ponos://session/{IDENTIFIER}")[0] == str(Path.home())
        # A link written before the rename is no longer one.
        try:
            session.resume_command(f"ticket-runner://session/{IDENTIFIER}?cwd={tmp}")
        except ValueError:
            pass
        else:
            raise AssertionError("an old ticket-runner:// link was opened")

    with tempfile.TemporaryDirectory() as tmp, _installed("ssh"):
        try:
            session.resume_command(session.deep_link(IDENTIFIER, tmp))
        except FileNotFoundError as error:
            assert "claude" in str(error), error
        else:
            raise AssertionError("resumed with no claude installed")


@case
def a_link_opens_the_first_terminal_installed() -> None:
    link = session.deep_link(IDENTIFIER, "/nowhere")
    previous = os.environ.pop("PONOS_TERMINAL", None)
    try:
        with _installed("claude", "kitty", "foot") as started:
            assert session.open_link(link) == 0
        assert started == [
            ["kitty", "--directory", str(Path.home()), "/usr/bin/claude", "--resume", IDENTIFIER]
        ], started

        os.environ["PONOS_TERMINAL"] = "wezterm"
        with _installed("claude", "kitty", "wezterm") as started:
            assert session.open_link(link) == 0
        assert started == [["wezterm", "-e", "/usr/bin/claude", "--resume", IDENTIFIER]], started

        # The one asked for is not installed: the list is tried as before.
        with _installed("claude", "gnome-terminal") as started:
            session.open_link(link)
        assert started[0][:2] == ["gnome-terminal", f"--working-directory={Path.home()}"], started
    finally:
        os.environ.pop("PONOS_TERMINAL", None)
        if previous is not None:
            os.environ["PONOS_TERMINAL"] = previous


@case
def a_link_with_no_terminal_to_open_it_starts_nothing() -> None:
    previous = os.environ.pop("PONOS_TERMINAL", None)
    try:
        with _installed("claude") as started:
            try:
                session.open_link(session.deep_link(IDENTIFIER))
            except FileNotFoundError as error:
                assert "PONOS_TERMINAL" in str(error), error
            else:
                raise AssertionError("opened a terminal that is not there")
        assert started == [], started
    finally:
        if previous is not None:
            os.environ["PONOS_TERMINAL"] = previous


class _Process:
    """What `halt` and `reap` read of a session's process: its pid, and its wait."""

    pid = 4242

    def __init__(self, lingers: bool = False) -> None:
        self.lingers = lingers
        self.waited: list[float] = []

    def wait(self, timeout: float) -> int:
        self.waited.append(timeout)
        if self.lingers:
            raise subprocess.TimeoutExpired("claude", timeout)
        return 0


@contextmanager
def _group(*answers: type[OSError] | None) -> Iterator[list[int]]:
    """`os.killpg` doubled: each call gets the next answer (None: delivered)."""
    sent: list[int] = []
    left = list(answers)

    def killpg(pid: int, number: int) -> None:
        assert pid == _Process.pid, pid
        sent.append(number)
        answer = left.pop(0) if left else None
        if answer is not None:
            raise answer()

    original = os.killpg
    os.killpg = killpg
    try:
        yield sent
    finally:
        os.killpg = original


@case
def halting_a_group_already_gone_sends_nothing_more() -> None:
    for gone in (ProcessLookupError, PermissionError):
        process = _Process()
        with _group(gone) as sent:
            session.halt(cast(subprocess.Popen[str], process))
        assert sent == [signal.SIGTERM] and process.waited == [], (sent, process.waited)


@case
def halting_a_session_that_will_not_end_kills_its_group() -> None:
    process = _Process(lingers=True)
    # Asked, waited for in vain, killed — and gone by then, which is no error.
    with _group(None, ProcessLookupError) as sent:
        session.halt(cast(subprocess.Popen[str], process))
    assert sent == [signal.SIGTERM, signal.SIGKILL], sent
    assert process.waited == [session.GRACE_SECONDS], process.waited


@case
def reaping_an_empty_group_waits_for_nothing() -> None:
    with _group(ProcessLookupError) as sent:
        session.reap(cast(subprocess.Popen[str], _Process()))
    assert sent == [signal.SIGTERM], sent
    # Asked, then found gone at the first look.
    with _group(None, ProcessLookupError) as sent:
        session.reap(cast(subprocess.Popen[str], _Process()))
    assert sent == [signal.SIGTERM, 0], sent


@case
def reaping_a_group_that_outlives_its_grace_kills_it() -> None:
    grace = session.GRACE_SECONDS
    session.GRACE_SECONDS = 0  # the deadline is already past: no look, straight to the kill
    try:
        for kill in (None, ProcessLookupError):
            with _group(None, kill) as sent:
                session.reap(cast(subprocess.Popen[str], _Process()))
            assert sent == [signal.SIGTERM, signal.SIGKILL], sent
    finally:
        session.GRACE_SECONDS = grace
