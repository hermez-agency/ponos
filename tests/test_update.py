"""`update.py`: staying up to date, and taking back a version that does not start."""

from __future__ import annotations

import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from support import ROOT, _bare_api, _config, _head, _TalkClient, case

from ponos import config as C
from ponos import state, update

# -- staying up to date ------------------------------------------------------


@case
def an_update_needs_both_sides_to_be_known():
    """A check that could not reach the remote must not look like a new version.

    Everything else here fails quietly, so `stale` is the one place where a
    missing answer would otherwise turn into a reinstall.
    """
    assert update.Status(current="a" * 40, latest="b" * 40).stale
    assert not update.Status(current="a" * 40, latest="a" * 40).stale
    assert not update.Status(current="a" * 40).stale
    assert not update.Status(reason="git fetch: could not resolve host").stale
    assert not update.Status().stale


@case
def the_check_is_hourly_rather_than_once_per_run(state_home):
    """At a ten-second cadence the difference is 360 git fetches an hour."""
    assert update.due(3600), "an installation never checked is due at once"
    update.remember(update.Status(current="a" * 40, latest="a" * 40))
    assert not update.due(3600), "and not again before the interval is out"
    assert update.due(0)
    assert update.last_check() > 0


@case
def a_stamp_that_cannot_be_read_makes_the_check_due(state_home):
    state_home.mkdir(parents=True)
    (state_home / "update.json").write_text("half a line of jso")
    assert update.last_check() == 0.0
    assert update.due(3600)


@contextmanager
def _installation():
    """A remote and an installation cloned from it, as `install.sh` leaves one.

    Yields `commit(message, tag="")`, which lands a commit on the remote's
    `main` — tagged when asked — and the installation's directory.
    """
    quiet = {"capture_output": True, "check": True}
    who = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    with tempfile.TemporaryDirectory() as directory:
        remote, work, app = (Path(directory) / name for name in ("remote.git", "work", "app"))
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)], **quiet)
        subprocess.run(["git", "clone", "--quiet", str(remote), str(work)], **quiet)

        def commit(message: str, tag: str = "") -> str:
            subprocess.run(
                ["git", *who, "-C", str(work), "commit", "--quiet", "--allow-empty", "-m", message],
                **quiet,
            )
            if tag:
                subprocess.run(["git", *who, "-C", str(work), "tag", "-a", tag, "-m", tag], **quiet)
            subprocess.run(
                ["git", "-C", str(work), "push", "--quiet", "--follow-tags", "origin", "HEAD:main"],
                **quiet,
            )
            return subprocess.run(
                ["git", "-C", str(work), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        first = commit("one")
        subprocess.run(["git", "clone", "--quiet", str(remote), str(app)], **quiet)
        yield commit, app, first


@case
def an_installation_follows_releases_and_not_every_commit_of_main(state_home):
    """Every commit pushed to `main` used to run on every installation within
    the hour. The default now follows the newest `vX.Y.Z` tag — and with none,
    updates nothing and says why rather than falling back on `main`."""
    with _installation() as (commit, app, first):
        commit("two, merged but not released")
        status = update.check(app, "release")
        assert not status.stale, "no release, no update"
        assert "no release" in status.reason, status.reason

        released = commit("three", tag="v0.2.0")
        commit("four, not released yet")
        commit("a pre-release", tag="v0.3.0-rc1")
        status = update.check(app, "release")
        assert status.stale and status.latest == released and status.tag == "v0.2.0", status
        assert status.current == first

        followed = update.check(app, "main")
        assert followed.stale and followed.latest not in (released, first), "main is every commit"
        assert not followed.tag

        # Already past the release — a clone of main switched to the release
        # channel — is not taken back to it.
        subprocess.run(
            ["git", "-C", str(app), "reset", "--quiet", "--hard", followed.latest],
            capture_output=True,
            check=True,
        )
        ahead = update.check(app, "release")
        assert not ahead.stale and not ahead.reason, ahead

    assert update.newest_release(["v0.9.0", "v0.10.0", "v0.10.0-rc2", "vnext", "v1"]) == "v0.10.0"
    assert update.newest_release([]) == ""


@case
def the_update_channel_is_release_unless_the_file_says_main():
    assert C.Runner().update_channel == "release"
    assert _config("[runner]\n").runner.update_channel == "release"
    assert _config('[runner]\nupdate_channel = "main"\n').runner.update_channel == "main"
    assert _config('[runner]\nupdate_channel = "Main"\n').runner.update_channel == "main"
    assert _config('[runner]\nupdate_channel = "nightly"\n').runner.update_channel == "release", (
        "a typo must not put an installation on every commit"
    )
    example = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    assert 'update_channel = "release"' in example


@case
def a_copy_is_told_apart_from_a_clone_before_anything_is_fetched():
    """An install made with TR_SRC has no remote: a reason, not a failure."""
    status = update._look(Path(tempfile.mkdtemp()))
    assert not status.stale and "copy" in status.reason


@case
def an_update_puts_the_console_on_the_code_it_just_installed(installation):
    """A run ends and the next one is the new code; the console never ends.

    On 18 September 2026 the console had been up since the evening before,
    serving `web/static/` off the disk — five commits newer than the Python
    answering it. The project list drew, because that route was in both; opening
    a project answered `no such route: /api/projects/<id>`, and the page said
    only that the project could not be read.

    `try-restart`, so that an update never starts a console somebody stopped.
    """
    commit, app, first = installation
    # A `systemctl` that only writes down what it was asked, on a PATH of the
    # installation's own: a test that reloads this machine's units is a test
    # gone somewhere it was never asked to go.
    asked = app.parent / "systemctl.log"
    (app.parent / "bin" / "systemctl").write_text(f'#!/bin/sh\necho "$@" >> {asked}\n')
    (app.parent / "bin" / "systemctl").chmod(0o755)
    (app.parent / "bin" / "sh").symlink_to(shutil.which("sh") or "/bin/sh")
    commit("two")
    error = update.apply(update.check(app, "main"), 600, app)
    ran = asked.read_text().splitlines()

    assert error == "", error
    restarts = [line for line in ran if "ponos-web.service" in line]
    assert restarts, "the console is left running the code the update replaced"
    assert restarts[0] == "--user try-restart ponos-web.service", (
        "a plain restart would start a console somebody stopped on purpose"
    )
    assert ran.index(restarts[0]) > ran.index("--user daemon-reload"), (
        "the console is restarted before its unit is reloaded"
    )


@case
def a_version_that_does_not_start_is_taken_back_and_one_that_does_is_kept(installation):
    """An update is all of it or none of it.

    `git reset` was the whole update: a commit that failed at `import` would
    have been installed, and every run after it would have died before
    claiming a ticket — with nobody there, since the runner runs alone. The new
    code is started by a Python of its own first, and the installation goes
    back to the commit it replaced when it does not.
    """
    commit, app, first = installation
    broken = commit(
        "broken",
        lambda work: (work / "src/ponos/__main__.py").write_text("this is not python\n"),
    )
    status = update.check(app, "main")
    assert status.stale and status.latest == broken
    error = update.install(status, 600, app)
    assert error and "does not start" in error and f"still on {first[:8]}" in error, error
    assert _head(app) == first, "a version that does not start was left installed"
    assert update.waiting(app).stale, "the update is still to be made"
    assert app.is_symlink() and app.resolve().name == f"app-{first[:12]}", (
        "the installation was not given a directory per version"
    )
    assert not app.with_name(f"app-{broken[:12]}").exists(), "the broken version was kept"

    fixed = commit(
        "fixed",
        lambda work: shutil.copy(ROOT / "src/ponos/__main__.py", work / "src/ponos/__main__.py"),
    )
    status = update.check(app, "main")
    assert update.install(status, 600, app) == ""
    assert _head(app) == fixed
    assert app.resolve().name == f"app-{fixed[:12]}"
    # The version replaced is still whole on disk: what was started on it
    # keeps importing from it, and it is the one to go back to.
    previous = app.with_name(f"app-{first[:12]}")
    assert _head(previous) == first, "the previous version was written over"
    third = commit("three")
    assert update.install(update.check(app, "main"), 600, app) == ""
    assert _head(app) == third
    assert not previous.exists(), "every version ever installed is kept"
    assert _head(app.with_name(f"app-{fixed[:12]}")) == fixed, "the previous one is gone"
    launcher = Path(os.environ["HOME"]) / ".local/bin/ponos"
    assert str(app) in launcher.read_text(), "the launcher still points at the old sources"
    assert not update.waiting(app).stale, (
        "the header still offered the update it had just installed"
    )


@case
def each_version_runs_in_an_environment_of_its_own_made_before_it_is_pointed_at(installation):
    """A version gets its `.venv` before `app` names it, and keeps it.

    The day the runner requires a package, it is installed in the version's own
    environment — never in one something is running on, never in the machine's
    Python. The version replaced keeps the environment it ran in, which is what
    going back to it needs.
    """
    from ponos import environment

    commit, app, first = installation
    second = commit("two")
    assert update.install(update.check(app, "main"), 600, app) == ""
    assert _head(app) == second
    made = environment.python(app.resolve())
    assert made.exists(), "the new version was pointed at without its environment"
    assert environment.interpreter(app.resolve()) == str(made)
    launcher = (Path(os.environ["HOME"]) / ".local/bin/ponos").read_text()
    assert ".venv/bin/python" in launcher, "the launcher does not run the environment"
    assert f'PYTHON="{environment.base_python()}"' in launcher, (
        "the launcher falls back on a Python inside a version directory"
    )

    # A version whose packages cannot be installed is never pointed at.
    third = commit(
        "asks for a package",
        lambda work: (work / "requirements.txt").write_text("a-package-nobody-published\n"),
    )
    error = update.install(update.check(app, "main"), 600, app)
    assert error and "could not be" in error, error  # made, or installed into
    assert _head(app) == second and made.exists(), "the version in use lost its environment"
    assert not app.with_name(f"app-{third[:12]}").exists()


@case
def an_installation_updated_by_a_version_without_environments_gets_one_on_its_next_pass(
    installation,
):
    """The first update onto this code is made by the code before it.

    That code copies the version, moves it, points `app` at it — and makes no
    environment, since it knows of none. The launcher runs the machine's Python
    meanwhile, and the next pass makes the environment, once.
    """
    from ponos import environment

    commit, app, first = installation
    update.install(update.check(app, "main"), 600, app)  # gives `app` its link
    version = app.resolve()
    shutil.rmtree(version / environment.VENV, ignore_errors=True)
    assert environment.interpreter(version, "/usr/bin/python3") == "/usr/bin/python3"
    said: list[str] = []
    original = update.app_dir
    update.app_dir = lambda: app
    try:
        update.between_runs(C.Runner(auto_update=False), say=said.append, notify=lambda *_: None)
    finally:
        update.app_dir = original
    assert environment.python(version).exists(), said
    assert said == [], said
    assert environment.ensure(version) == "", "a second pass made it again"


@case
def only_the_consoles_application_imports_a_package_from_outside():
    """The runner, and `web/server.py`, stay the standard library's alone.

    The runner because a pass must not depend on an environment it may have
    to make (`environment.ensure`) — httpx and pydantic are the exceptions:
    only `http.py` imports the first, when the first request is sent, and only
    `schema.py` the second, when the file is read. And `server.py`
    because an installation still on v0.1.0 checks that a new version starts
    by importing it with the machine's Python — had it imported FastAPI, the
    update that brings FastAPI would have been refused on every such machine,
    for good.
    """
    outside = {"app.py", "routes.py"}
    for path in sorted((ROOT / "src" / "ponos").rglob("*.py")):
        if path.parent.name == "web" and path.name in outside:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if (path.name, top) in (
                    ("http.py", "httpx"),
                    ("schema.py", "pydantic"),
                    ("schema.py", "pydantic_core"),
                ):
                    continue
                assert top in sys.stdlib_module_names or top == "ponos", (path.name, name)
    probe = (
        "import sys\n"
        "for name in ('fastapi', 'uvicorn', 'starlette', 'pydantic', 'anyio', 'httpx'):\n"
        "    sys.modules[name] = None\n"
        "import ponos.__main__, ponos.web.server, ponos.runner\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


@case
def the_launcher_runs_the_environment_and_the_machines_python_without_one():
    from ponos import environment

    with tempfile.TemporaryDirectory() as directory:
        version = Path(directory) / "app-1"
        (version / "src" / "ponos").mkdir(parents=True)
        (version / "src" / "ponos" / "__init__.py").write_text("", encoding="utf-8")
        (version / "src" / "ponos" / "__main__.py").write_text(
            "import sys\nprint(sys.prefix)\n", encoding="utf-8"
        )
        app = Path(directory) / "app"
        app.symlink_to(version.name)
        launcher = Path(directory) / "ponos"
        launcher.write_text(
            (ROOT / "bin" / "ponos.in")
            .read_text(encoding="utf-8")
            .replace("@APP_DIR@", str(app))
            .replace("@PYTHON@", environment.base_python()),
            encoding="utf-8",
        )
        launcher.chmod(0o755)

        def prefix() -> str:
            return subprocess.run(
                [str(launcher)], capture_output=True, text=True, check=True
            ).stdout.strip()

        assert Path(prefix()).resolve() == Path(sys.base_prefix).resolve(), (
            "without an environment, the machine's Python"
        )
        assert environment.create(version) == ""
        assert Path(prefix()) == version / environment.VENV, "the environment was not used"


@contextmanager
def _bare_machine():
    """A home of its own and a PATH with no uv on it — what a fresh Debian has.

    Yields the directory the uv archive is "published" in: `file://` URLs are
    what `fetch_uv` downloads from here, so no test of it touches the network.
    """
    from ponos import environment

    kept = {name: os.environ.get(name) for name in ("HOME", "PATH")}
    pinned = (environment.UV_RELEASES, dict(environment.UV_SHA256))
    with tempfile.TemporaryDirectory() as directory:
        home, published, tools = (Path(directory) / name for name in ("home", "releases", "bin"))
        for made in (home, published, tools):
            made.mkdir()
        os.environ["HOME"], os.environ["PATH"] = str(home), str(tools)
        environment.UV_RELEASES = published.as_uri()
        try:
            yield published
        finally:
            environment.UV_RELEASES, sums = pinned
            environment.UV_SHA256.clear()
            environment.UV_SHA256.update(sums)
            for name, value in kept.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _publish_uv(published: Path, script: str) -> str:
    """A uv release for this machine, whose `uv` is `script`. Its SHA-256."""
    import hashlib
    import tarfile

    from ponos import environment

    target = environment._platform()
    folder = published / environment.UV_VERSION
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"uv-{target}.tar.gz"
    payload = script.encode()
    with tarfile.open(archive, "w:gz") as packed:
        member = tarfile.TarInfo(f"uv-{target}/uv")
        member.size, member.mode = len(payload), 0o755
        packed.addfile(member, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    environment.UV_SHA256[target] = digest
    return digest


@case
def a_machine_without_pip_fetches_uv_and_installs_with_it():
    """Debian without `python3-venv`: no ensurepip, no uv, and a package to install.

    The update used to be refused at every pass until somebody typed `sudo apt`.
    The pinned uv is fetched, its sum checked, and the packages go through it;
    a sum that does not match is never unpacked, and without the network the
    version is simply not made — the one in use carries on.
    """
    from ponos import environment

    with _bare_machine() as published, tempfile.TemporaryDirectory() as directory:
        version = Path(directory) / "app-1"
        version.mkdir()
        (version / "requirements.txt").write_text(
            'httpx==0.28.1 ; python_version >= "3.11" \\\n    --hash=sha256:00\n', encoding="utf-8"
        )
        assert environment._name(environment.required(version)[0]) == "httpx"
        seen = Path(directory) / "uv-was-asked"
        original = environment._has_ensurepip
        environment._has_ensurepip = lambda base: False
        try:
            # Offline: nothing to fetch, nothing made.
            problem = environment.create(version)
            assert "uv could not be fetched" in problem, problem
            assert not environment.python(version).exists()

            # A release whose sum is not the pinned one is refused, and left packed.
            _publish_uv(published, "#!/bin/sh\nexit 0\n")
            environment.UV_SHA256[environment._platform()] = "0" * 64
            assert "SHA-256" in environment.create(version)
            assert environment.uv() == "", "an archive that failed its sum was unpacked"

            _publish_uv(published, f'#!/bin/sh\necho "$@" > "{seen}"\n')
            assert environment.create(version) == ""
        finally:
            environment._has_ensurepip = original
        fetched = Path(os.environ["HOME"]) / ".local/share/ponos/uv/uv"
        assert environment.uv() == str(fetched)
        asked = seen.read_text()
        assert "pip install" in asked and "--require-hashes" in asked, asked
        assert ".venv.partial/bin/python" in asked, "installed into an environment in use"
        assert environment.python(version).exists()
        state, said = environment.diagnose(version)
        assert state == "error" and "httpx" in said, (state, said)


@case
def an_environment_whose_python_the_distribution_replaced_is_made_again():
    """A distribution upgrade takes away the Python `.venv` was made from.

    Either its link leads nowhere, or it leads to a newer `python3` the
    packages were not built for, and only `pyvenv.cfg` still names the one that
    is gone. The next pass makes the environment again.
    """
    from ponos import environment

    with tempfile.TemporaryDirectory() as directory:
        version = Path(directory) / "app-1"
        version.mkdir()
        assert environment.stale(version) == "there is no environment"
        assert environment.create(version) == ""
        if not environment.python(version).exists():
            return  # this python3 makes no environment at all: nothing to go stale
        assert environment.stale(version) == ""
        assert environment.diagnose(version)[0] == "ok"

        settings = version / environment.VENV / "pyvenv.cfg"
        settings.write_text(
            "home = /nowhere/bin\nversion = 3.9.2\nexecutable = /nowhere/bin/python3.9\n",
            encoding="utf-8",
        )
        assert "/nowhere/bin/python3.9" in environment.stale(version)
        assert environment.ensure(version) == ""
        assert environment.stale(version) == "", "the environment was not made again"

        link = environment.python(version)
        link.unlink()
        link.symlink_to("/nowhere/bin/python3.9")
        assert "leads nowhere" in environment.stale(version)
        assert environment.diagnose(version)[0] == "warn", "nothing to install: no fault"
        assert environment.ensure(version) == ""
        assert environment.stale(version) == ""


@case
def the_header_does_not_offer_a_version_already_installed(installation):
    """On 30 September 2026 the header said ↑ on an installation already on the
    newest commit: the stamp was written before the update it announced, and
    read for the hour after. What is on disk has the last word."""
    commit, app, first = installation
    second = commit("two")
    update.remember(update.Status(current=first, latest=second))
    assert update.waiting(app).stale, "installed is what the stamp compared: an update"
    subprocess.run(
        ["git", "-C", str(app), "pull", "--quiet", "origin", "main"],
        capture_output=True,
        check=True,
    )
    assert not update.waiting(app).stale, "moved by hand since the check: nothing to offer"
    page = "https://github.com/owner/repo"
    tagged = update.Status(current="a" * 40, latest="b" * 40, tag="v0.2.0")
    assert update.notes(tagged, page) == f"{page}/releases/tag/v0.2.0"
    assert update.notes(update.Status(current="a" * 40, latest="b" * 40), page) == (
        f"{page}/compare/{'a' * 12}...{'b' * 12}"
    )
    assert update.notes(update.Status(current="a" * 40, latest="a" * 40), page) == ""


@case
def a_waiting_update_says_how_many_commits_it_brings_and_which(installation):
    """The button carries a number and its tooltip the subjects: read at the
    check, from the clone that has just fetched, and kept in the stamp."""
    commit, app, first = installation
    commit("two")
    commit("three")
    status = update.check(app, "main")
    assert status.behind == 2 and status.commits == ["three", "two"], status
    assert update.waiting(app).behind == 2, "the count is not in the stamp"
    assert update.waiting(app).commits == ["three", "two"]


@case
def the_console_looks_for_an_update_without_moving_the_run_s_clock(installation):
    """A run checks once its interval has passed since the last check. The
    console looking every quarter of an hour must not count as one — or a run
    would never find its own due again, and never install anything."""
    from ponos.web import upgrade as web_upgrade

    commit, app, first = installation
    update.remember(update.Status(current=first, latest=first))
    checked = update.last_check()
    second = commit("two")
    said: list[dict] = []
    upgrade = web_upgrade.Upgrade(
        lambda kind, **payload: said.append(payload),
        lambda: C.Runner(update_channel="main"),
        app=app,
    )
    upgrade.look()
    assert update.last_check() == checked, "the console's look moved the run's clock"
    assert said and said[-1]["available"] and said[-1]["latest"] == second[:8]
    assert said[-1]["behind"] == 1 and said[-1]["commits"] == ["two"]
    upgrade.look()
    assert len(said) == 1, "nothing changed, and the pages were told again"

    commit("three")
    off = web_upgrade.Upgrade(
        lambda kind, **payload: said.append(payload),
        lambda: C.Runner(auto_update=False, update_channel="main"),
        app=app,
    )
    off.look()
    assert len(said) == 1 and update.waiting(app).behind == 1, (
        "runner.auto_update = false, and the console fetched anyway"
    )


class _FakeUpdate:
    """`update`, as `web.upgrade` uses it: what is waiting, and what installing did."""

    def __init__(self, error: str = "") -> None:
        self.error = error
        self.installed: list[str] = []
        self.status = update.Status(current="a" * 40, latest="b" * 40)

    def __enter__(self):
        from ponos.web import upgrade as web_upgrade

        self.module = web_upgrade.update_module
        self.kept = {name: getattr(self.module, name) for name in ("waiting", "check", "install")}
        self.module.waiting = lambda app=None: self.status
        self.module.check = lambda app=None, channel="release": self.status
        self.module.install = lambda status, interval, app=None: (
            self.installed.append(status.latest) or self.error
        )
        return self

    def __exit__(self, *_):
        for name, value in self.kept.items():
            setattr(self.module, name, value)


def _until(condition, seconds: float = 5.0) -> None:
    deadline = time.time() + seconds
    while not condition():
        if time.time() > deadline:
            raise AssertionError("waited in vain")
        time.sleep(0.02)


@case
def an_update_from_the_console_waits_for_the_ticket_in_flight(state_home):
    """A click while a ticket runs is queued behind the run lock, never under it.

    Every session a ticket starts runs inside a pass that holds the lock; the
    update takes the same lock, so nothing is swapped while one runs, and the
    timer's next pass finds it busy and claims nothing. Called off while it
    waits, nothing is installed; a chat turn is waited for as well.
    """
    from ponos.web import upgrade as web_upgrade

    with _FakeUpdate() as fake:
        said: list[dict] = []
        restarted: list[int] = []
        talking = {"now": "a conversation turn is being answered"}
        upgrade = web_upgrade.Upgrade(
            lambda kind, **payload: said.append(payload),
            C.Runner,
            lambda: talking["now"],
            app=Path(tempfile.mkdtemp()),
            reboot=lambda: restarted.append(1),
            poll=0.02,
        )
        with state.lock():
            upgrade.start()
            _until(lambda: upgrade.detail == "a conversation turn is being answered")
            talking["now"] = ""
            _until(lambda: upgrade.detail == "a ticket is running")
            assert upgrade.phase == "waiting" and not fake.installed, "installed under a run"
            try:
                upgrade.start()
            except RuntimeError:
                pass
            else:
                raise AssertionError("two updates at once")
        _until(lambda: restarted)
        assert fake.installed == ["b" * 40]
        assert upgrade.phase == "restarting"
        phases = [payload["phase"] for payload in said]
        assert phases.index("installing") > phases.index("waiting")
        assert phases[-1] == "restarting"
        # The process that comes back knows what it came back from.
        again = web_upgrade.Upgrade(lambda kind, **payload: None, C.Runner, app=upgrade.app)
        assert again.phase == "done" and again.target == "b" * 8

        # Called off while it waits: nothing installed, nothing restarted. (The
        # restart above was a function: a real one would have ended this process.)
        upgrade.phase = "idle"
        fake.installed.clear()
        restarted.clear()
        with state.lock():
            upgrade.start()
            _until(lambda: upgrade.detail == "a ticket is running")
            upgrade.cancel()
            _until(lambda: upgrade.phase == "idle")
        time.sleep(0.1)
        assert not fake.installed and not restarted


@case
def a_failed_update_from_the_console_says_why_and_restarts_nothing(state_home):
    from ponos.web import upgrade as web_upgrade

    with _FakeUpdate("the new version does not start: boom — back on aaaaaaaa"):
        restarted: list[int] = []
        upgrade = web_upgrade.Upgrade(
            lambda kind, **payload: None,
            C.Runner,
            app=Path(tempfile.mkdtemp()),
            reboot=lambda: restarted.append(1),
            poll=0.02,
        )
        upgrade.start()
        _until(lambda: upgrade.phase == "failed")
        assert "back on aaaaaaaa" in upgrade.error
        assert any("failed:" in line for line in upgrade.progress()["log"])
        assert "failed:" in web_upgrade.log_path().read_text(encoding="utf-8"), "no log to read"
        assert not restarted, "the console was restarted onto a version that was taken back"
        offer = upgrade.offer(local=False)
        assert offer["available"] and not offer["automatic"] and offer["command"] == "ponos update"


@case
def the_update_endpoint_answers_only_this_machine_and_the_console_page():
    """The one write that replaces the code answering it: loopback, the guard
    header, and an `Origin` that is the console's own — and a body that
    chooses nothing."""
    import urllib.error
    import urllib.request

    from ponos.web import app as web_app

    started: list[int] = []

    class Upgrade:
        def start(self):
            started.append(1)
            return {"phase": "waiting"}

        def cancel(self):
            raise RuntimeError("the update is no longer waiting")

    api = _bare_api(_TalkClient([]))
    api._upgrade = Upgrade()
    console = web_app.Console(("127.0.0.1", 0), api, "tok")
    threading.Thread(target=console.serve_forever, daemon=True).start()
    port = console.server_address[1]

    def post(path: str, **headers: str):
        sent = {"Authorization": "Bearer tok", "Content-Type": "application/json", **headers}
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=b'{"command": "rm -rf ~"}',
            headers=sent,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    guard = {"X-Ponos": "1"}
    try:
        assert post("/api/update") == 403, "a form posted from another page"
        assert post("/api/update", Origin="http://evil.example", **guard) == 403
        assert not started
        assert post("/api/update", Origin=f"http://127.0.0.1:{port}", **guard) == 200
        assert post("/api/update", **guard) == 200, "a script with the token sends no Origin"
        assert post("/api/update/cancel", **guard) == 409
    finally:
        console.shutdown()
        console.server_close()
    assert len(started) == 2

    for address, local in (
        ("127.0.0.1", True),
        ("::1", True),
        ("192.168.1.20", False),
        ("100.64.0.3", False),
    ):
        assert web_app.is_local(address) is local, address
