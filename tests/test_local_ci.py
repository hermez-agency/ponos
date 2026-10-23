"""`local_ci.py`: the project's CI on this machine, and what the settings say of it."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

from support import _config, _saved, case

from ponos import health, local_ci, project_settings
from ponos.web import settings as web_settings


def _docker_is(found: local_ci.Docker) -> None:
    local_ci._docker = (time.monotonic(), found)


def _tools(**scripts: str) -> Path:
    """A folder of executables, by name, to put at the head of `PATH`."""
    folder = Path(tempfile.mkdtemp())
    for name, body in scripts.items():
        (folder / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (folder / name).chmod(0o755)
    return folder


@case
def a_declared_command_comes_first_then_act_on_the_workflows_then_nothing():
    workdir = Path(tempfile.mkdtemp())
    previous = os.environ["PATH"]
    os.environ["PATH"] = str(_tools(act="exit 0"))
    try:
        chosen = local_ci.plan("  make ci ", workdir, "1234abcd" * 4)
        assert chosen.argv == ["sh", "-c", "make ci"] and chosen.source == "project", chosen
        assert not local_ci.plan("", workdir, "x"), "act with no workflow to read runs nothing"
        (workdir / ".github" / "workflows").mkdir(parents=True)
        (workdir / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
        chosen = local_ci.plan("", workdir, "1234abcd" * 4)
        assert chosen.source == "act" and "--rm" in chosen.argv, chosen
        assert f"--label {local_ci.LABEL}={local_ci.name('1234abcd' * 4)}" in chosen.argv
        os.environ["PATH"] = str(_tools())
        assert not local_ci.plan("", workdir, "x"), "no act installed: nothing to run"
    finally:
        os.environ["PATH"] = previous


@case
def a_run_is_named_after_its_ticket_and_keeps_the_end_of_what_it_said():
    workdir = Path(tempfile.mkdtemp())
    log = workdir / "ci.log"
    chosen = local_ci.plan(
        'seq 1 500; echo "$COMPOSE_PROJECT_NAME $PONOS_CI_NAME $CI"; exit 4', workdir, "t"
    )
    ran = local_ci.run(chosen, workdir, "ponos-ci-abc", log, timeout_minutes=1)
    assert not ran.ok and ran.code == 4, ran
    assert ran.tail.endswith("ponos-ci-abc ponos-ci-abc true"), ran.tail[-80:]
    assert "\n1\n" not in ran.tail and len(ran.tail.splitlines()) == local_ci.TAIL_LINES
    assert "\n1\n" in "\n" + log.read_text(), "the whole output is kept in the log"
    green = local_ci.run(local_ci.plan("true", workdir, "t"), workdir, "n", log, timeout_minutes=1)
    assert green.ok and green.code == 0, green


@case
def a_local_ci_waits_for_a_place_when_the_machine_has_none_left(state_home):
    order: list[str] = []
    waited = threading.Event()
    local_ci.WAIT_SECONDS, previous = 0.05, local_ci.WAIT_SECONDS
    try:
        with local_ci.place(1):

            def second() -> None:
                with local_ci.place(1, waited.set):
                    order.append("second")

            thread = threading.Thread(target=second)
            thread.start()
            assert waited.wait(5), "the second run did not wait"
            order.append("first")
        thread.join(5)
        assert order == ["first", "second"], order
        with local_ci.place(2), local_ci.place(2) as index:
            assert index == 1, "two places, two runs at once"
    finally:
        local_ci.WAIT_SECONDS = previous


@case
def a_project_says_its_own_word_on_its_local_ci_or_leaves_it_to_the_file(state_home):
    assert project_settings.local_ci("abc") == {"enabled": None, "command": ""}
    project_settings.set_local_ci("abc", "Site", True, " make ci ")
    assert project_settings.local_ci("a-b-c") == {"enabled": True, "command": "make ci"}
    project_settings.set_local_ci("abc", "Site", None, "make ci")
    assert project_settings.local_ci("abc") == {"enabled": None, "command": "make ci"}
    project_settings.set_local_ci("abc", "Site", None, "")
    assert project_settings.local_ci("abc") == {"enabled": None, "command": ""}


@case
def without_docker_the_switch_is_greyed_with_its_reason_and_cannot_be_saved_on():
    path, config = _saved()
    try:
        _docker_is(local_ci.Docker(False, False))
        described = web_settings.describe(config)
        assert described["docker"] == {"available": False, "installed": False}
        fields = {
            field["name"]: field for section in described["sections"] for field in section["fields"]
        }
        assert "not installed" in fields["runner.local_ci"]["unavailable"]
        assert fields["runner.local_ci_attempts"]["unavailable"] == ""
        assert fields["runner.local_ci_attempts"]["fallback"] == 3
        try:
            web_settings.save(config, {"settings": {"runner.local_ci": True}})
        except ValueError as error:
            assert "runner.local_ci" in str(error)
        else:
            raise AssertionError("turned on without Docker")
        # Turning it off is always possible, Docker or not.
        web_settings.save(config, {"settings": {"runner.local_ci": False}})

        _docker_is(local_ci.Docker(True, True, version="29.0.0"))
        described = web_settings.describe(config)
        assert described["docker"]["available"]
        web_settings.save(config, {"settings": {"runner.local_ci": True}})
        assert "local_ci = true" in path.read_text()
    finally:
        local_ci._docker = None


@case
def the_health_of_docker_warns_only_when_the_local_ci_wants_it():
    previous = local_ci._probe
    try:
        local_ci._probe = lambda: local_ci.Docker(True, False, error="permission denied")
        found = health._docker(_config(""))
        assert [check.state for check in found] == [health.INFO], found
        found = health._docker(_config("[runner]\nlocal_ci = true\n"))
        assert found[0].state == health.WARN and found[0].evidence == "permission denied"
        local_ci._probe = lambda: local_ci.Docker(True, True, version="29.0.0")
        found = health._docker(_config("[runner]\nlocal_ci = true\n"))
        assert found[0].state == health.OK and found[0].params == {"version": "29.0.0"}
    finally:
        local_ci._probe = previous
        local_ci._docker = None
