"""Keeping the installation on the latest version, with nobody asking for it.

The runner already wakes up on a timer, so it does not need a second one: a run
looks at the clock before it looks at the tickets, and once an hour it asks the
remote whether the installed code is still the newest. One `git fetch` in the
install directory answers that — which is why `install.sh` *clones* the
repository there rather than unpacking a tarball. "Am I up to date" is a
question git already knows how to answer; a version number in a file would only
be a second, less truthful copy of it.

An update lands **between** two runs, never inside one. The check happens under
the run lock and before a single ticket is claimed, so no session is ever
swapped out from under itself; the code that just landed takes over on the next
pass, which is at most one interval away.

The console is the exception, and `restart_console` is why: it is one process
that answers for weeks, so nothing about it takes over on its own.

What "the newest" means is `runner.update_channel`, and the default is the
careful one: **the newest release**, a `vX.Y.Z` tag. Following `main` meant
that every commit pushed there — a runner opens its own pull requests, and
merges the ones you validate — was running on every installation within the
hour, before anybody had called it a version. A tag is somebody saying "this
one"; `main` stays available for whoever wants every commit as it lands. No tag
at all is not a reason to fall back on `main`: nothing is updated, and the run
says why.

A release is only ever a step *forward*. An installation already ahead of the
newest tag — a clone of `main` that has just been switched to the release
channel — is left where it is rather than taken back to the tag.

An installation made from a local copy (`TR_SRC=.`) has no remote to compare
itself against. That is not an error and never fails a run — it is said once,
and the runner carries on.

**Each version has a directory of its own, and `app` is a link to one of them.**
On 30 September 2026 a pass started while an update was rewriting `app` in
place: it imported a `files.py` already new and a `store.py` still old, and died
on `ImportError: cannot import name 'SLOTS'`. The run lock could not have
prevented it — a process imports its modules before it ever asks for the lock.
So nothing in use is written to any more: the new version is copied beside the
old one as `app-<commit>`, checked, and `app` is moved onto it by one rename.
The launcher resolves the link once, when it starts, so a process imports every
module from the one version it found, however long it runs. The version it
replaced stays on disk — for what is still running on it, and for going back.

**In a container, none of this.** There is no link to move, no unit to restart,
and the code is the image's: a version written into it would be gone at the
next `docker compose up`. A new version is a new image, pulled by whoever runs
it — so every road here stops at `CONTAINER`, said once rather than tried.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import disk, environment, git
from .config import Runner, in_container, state_dir

# What a container says instead of updating itself, and what to type instead.
PULL = "docker compose pull && docker compose up -d"
CONTAINER = f"this is a container: a new version is a new image — {PULL}"


def app_dir() -> Path:
    """Where the sources live: the link `install.sh` made, when there is one.

    This file resolves to the version it belongs to (`app-<commit>`); what an
    update moves is the link beside it, named like it without the commit — and
    that link may already name a newer version than the one asking. A checkout,
    a copy, or an installation from before the link answer with themselves.
    """
    here = Path(__file__).resolve().parents[2]
    link = here.with_name(here.name.rpartition("-")[0] or here.name)
    return link if link.is_symlink() else here


# A release, as `scripts/release.py` tags one: `v` and three numbers. A
# pre-release (`v1.0.0-rc1`) is not one, and neither is anything else starting
# with a `v`.
RELEASE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


@dataclass
class Status:
    current: str = ""
    latest: str = ""
    reason: str = ""
    # The release `latest` is, on the release channel — what a person reads.
    tag: str = ""
    # How many commits `latest` has that `current` has not, and their subjects,
    # newest first — what the header lists under the button.
    behind: int = 0
    commits: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        """True only when both sides are known and they differ.

        A check that could not reach the remote is not an update: the runner
        must never reinstall itself on the strength of a missing answer.
        """
        return bool(self.current and self.latest and self.current != self.latest)


def installed_version() -> Path | None:
    """The version directory `install.sh` or an update made, None for a checkout.

    By its name rather than by the link: a copy installed with `TR_SRC` is
    `app-copy-<time>`, which no link beside it is named after.
    """
    version = app_dir().resolve()
    return version if version.name.startswith("app-") else None


def _stamp() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "update.json"


def remember(status: Status, *, clock: bool = True) -> None:
    """Record that a check happened, and what it found.

    The timestamp is what rate-limits the whole thing: it is written whether the
    check succeeded or not, so an unreachable remote is asked once an hour like
    everything else, not once per run.

    `clock=False` is the console's own look (`web.upgrade.Upgrade.look`): what
    it found is kept, but not the time — every quarter of an hour, it would
    otherwise keep a run from ever finding its own check due, and from ever
    installing anything.
    """
    payload = {
        "checked_at": time.time() if clock else last_check(),
        "current": status.current,
        "latest": status.latest,
        "reason": status.reason,
        "tag": status.tag,
        "behind": status.behind,
        "commits": status.commits,
    }
    try:
        disk.write_atomic(_stamp(), json.dumps(payload))
    except OSError:
        pass


def remembered() -> Status:
    """What the last check found, without asking the remote again.

    The console draws its header on every reconnection, and a `git fetch`
    behind that would be one per laptop lid. The stamp a run already writes
    answers the same question for free — and answers "nothing known yet" as an
    empty Status, which reads as "up to date" rather than as a warning.
    """
    try:
        payload = json.loads(_stamp().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Status()
    return Status(
        current=str(payload.get("current") or ""),
        latest=str(payload.get("latest") or ""),
        reason=str(payload.get("reason") or ""),
        tag=str(payload.get("tag") or ""),
        behind=int(payload.get("behind") or 0),
        commits=[str(line) for line in payload.get("commits") or []],
    )


def last_check() -> float:
    try:
        return float(json.loads(_stamp().read_text(encoding="utf-8"))["checked_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def due(interval_seconds: int) -> bool:
    """Has the interval elapsed? An installation never checked is due at once."""
    return time.time() - last_check() >= interval_seconds


def _look(app: Path, channel: str = "release") -> Status:
    if not (app / ".git").exists():
        return Status(
            reason=f"{app} is a copy, not a clone — run install.sh again to follow the repository"
        )
    ref = git.git(["rev-parse", "--abbrev-ref", "HEAD"], app).out
    if not ref or ref == "HEAD":
        # Installed on a tag (TR_REF=v1.2): a fixed revision is a choice, and
        # following anything else instead would quietly undo it.
        return Status(reason=f"{app} is pinned to a fixed revision — nothing to follow")
    if channel == "main":
        fetched = git.git(["fetch", "--quiet", "origin", ref], app, timeout=120)
        if not fetched.ok:
            return Status(reason=f"git fetch: {fetched.err or fetched.out}")
        current = git.git(["rev-parse", "HEAD"], app).out
        latest = git.git(["rev-parse", "FETCH_HEAD"], app).out
        if not current or not latest:
            return Status(reason=f"nothing to compare in {app}")
        return _between(app, Status(current=current, latest=latest))
    return _release(app)


def _release(app: Path) -> Status:
    """The newest release tag, against what is installed — never a step back."""
    fetched = git.git(["fetch", "--quiet", "--tags", "origin"], app, timeout=120)
    if not fetched.ok:
        return Status(reason=f"git fetch: {fetched.err or fetched.out}")
    tag = newest_release(git.git(["tag", "--list", "v*"], app).out.splitlines())
    if not tag:
        return Status(
            reason="no release tagged yet (vX.Y.Z) — nothing to update to; "
            'runner.update_channel = "main" follows every commit instead'
        )
    current = git.git(["rev-parse", "HEAD"], app).out
    latest = git.git(["rev-parse", f"refs/tags/{tag}^{{commit}}"], app).out
    if not current or not latest:
        return Status(reason=f"nothing to compare in {app}")
    if latest != current and git.git(["merge-base", "--is-ancestor", latest, current], app).ok:
        # Already past it: a clone of `main` newer than the last release. Going
        # back to the tag would be a downgrade nobody asked for.
        return Status(current=current, latest=current, tag=tag)
    return _between(app, Status(current=current, latest=latest, tag=tag))


# The subjects kept for the header: enough to read what is coming, not a log.
LISTED = 30


def _between(app: Path, status: Status) -> Status:
    """`status`, with the commits its update would bring — read once, at the check.

    Both commits are in the clone once it has fetched, so this is two local
    commands; a count that cannot be read leaves the update offered without one.
    """
    if not status.stale:
        return status
    span = f"{status.current}..{status.latest}"
    counted = git.git(["rev-list", "--count", span], app).out
    status.behind = int(counted) if counted.isdigit() else 0
    status.commits = git.git(
        ["log", f"--max-count={LISTED}", "--format=%s", span], app
    ).out.splitlines()
    return status


def newest_release(tags: list[str]) -> str:
    """The highest `vX.Y.Z` of those, compared as numbers — or "" for none."""
    releases = [
        (tuple(int(part) for part in match.groups()), tag.strip())
        for tag in tags
        if (match := RELEASE.match(tag.strip()))
    ]
    return max(releases)[1] if releases else ""


def check(app: Path | None = None, channel: str = "release", *, clock: bool = True) -> Status:
    """What is installed, against what the remote has on that channel.

    Never raises: a remote that hangs until the timeout, or a directory that has
    become unreadable, are answers like any other. Checking a version is not
    worth failing a run over. `clock`: see `remember`.
    """
    if in_container():
        return Status(reason=CONTAINER)
    try:
        status = _look(app or app_dir(), channel)
    except (OSError, subprocess.SubprocessError) as error:
        status = Status(reason=f"version not checked: {error}")
    remember(status, clock=clock)
    return status


def running() -> dict:
    """The version this code is, as the header prints it: the number and the commit.

    The number in `__init__` only moves at a release, and between two releases
    every commit ran under it — so it is followed by the commit, `0.1.0+1a2b3c4`,
    read from git rather than written anywhere: nothing to bump, and nothing
    that can disagree with the code. Asked of the directory this file is in,
    not of `app_dir()`, whose link may already name a newer version than the
    one running. A directory that is not a repository — a copy, an image — says
    the number alone.
    """
    from . import __version__

    here = Path(__file__).resolve().parents[2]
    said = ""
    if (here / ".git").exists():
        try:
            said = git.git(["log", "-1", "--format=%h%x1f%H%x1f%cI%x1f%s"], here, timeout=10).out
        except (OSError, subprocess.SubprocessError):
            said = ""
    parts = said.split("\x1f")
    if len(parts) != 4 or not parts[0]:
        return {"version": __version__, "commit": "", "date": "", "subject": ""}
    short, commit, date, subject = parts
    return {"version": f"{__version__}+{short}", "commit": commit, "date": date, "subject": subject}


def between_runs(
    settings: Runner,
    *,
    say: Callable[[str], None],
    notify: Callable[[str, str], None],
) -> None:
    """Once an interval, make sure the installed code is still the newest.

    Called at the top of a pass rather than by a timer of its own: a run already
    wakes up on a schedule, and doing it there — under the run lock, before a
    single ticket is claimed — is what makes an update land between two
    sessions instead of underneath one. The new code takes over on the next
    pass.

    Nothing here can fail a run: an unreachable remote, an installation made
    from a copy, no release to follow, a refused write are all one line and
    then the tickets.
    """
    if in_container():
        return
    healed = heal_environment()
    if healed:
        say(f"  ! {healed}")
    if not settings.auto_update or not due(settings.update_interval_seconds):
        return
    status = check(channel=settings.update_channel)
    if status.reason:
        say(f"  ! version not checked: {status.reason}")
        return
    if not status.stale:
        return
    short = describe(status)
    say(f"  ↑ a newer version is out ({short}) — updating")
    error = apply(status, settings.interval_seconds)
    if error:
        say(f"  ! update failed: {error}")
        return
    say("    updated — the next run uses it")
    notify("Ponos updated", short)


def heal_environment() -> str:
    """The environment of the version in use, made if an update left it without one.

    Only for an installation `install.sh` made — `app` a link — never for a
    checkout someone runs the suite in.
    """
    app = app_dir()
    if not app.is_symlink():
        return ""
    problem = environment.ensure(app.resolve())
    return f"no environment for this version yet: {problem}" if problem else ""


def describe(status: Status) -> str:
    """“1a2b3c4d → v0.4.0 (5e6f7a8b)”, or the two commits when there is no tag."""
    target = f"{status.tag} ({status.latest[:8]})" if status.tag else status.latest[:8]
    return f"{status.current[:8]} → {target}"


# -- what install.sh generates outside the app directory ----------------------


def _binary() -> Path:
    return Path(shutil.which("ponos") or Path.home() / ".local/bin/ponos")


def write_launcher(app: Path | None = None) -> Path:
    """Rewrite ~/.local/bin/ponos from the template in the app directory.

    Safe to do from the runner itself: the launcher `exec`s Python, so by the
    time this runs the shell that read it is long gone.
    """
    app = app or app_dir()
    binary = _binary()
    text = (app / "bin" / "ponos.in").read_text()
    # The machine's Python, not this process's: from inside an environment that
    # would be a link into a version directory an update later prunes.
    text = text.replace("@APP_DIR@", str(app)).replace("@PYTHON@", environment.base_python())
    binary.parent.mkdir(parents=True, exist_ok=True)
    # Renamed over the old one: the timer may start it at any moment, and a
    # launcher read half-written is a pass that does not start.
    disk.write_atomic(binary, text, mode=0o755)
    return binary


def write_units(interval_seconds: int, app: Path | None = None) -> Path:
    """Regenerate the systemd units from the templates shipped with the app.

    The interval lives in the configuration, not in the unit: changing a number
    and running `ponos enable` is a better story than reinstalling.
    """
    app = app or app_dir()
    units = Path.home() / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)

    service = (app / "systemd" / "ponos.service.in").read_text()
    service = service.replace("@BIN@", str(_binary())).replace("@PATH@", os.environ.get("PATH", ""))
    (units / "ponos.service").write_text(service)

    timer = (app / "systemd" / "ponos.timer.in").read_text()
    timer = timer.replace("@INTERVAL@", str(interval_seconds))
    timer = timer.replace("@ACCURACY@", "1s" if interval_seconds < 60 else "30s")
    (units / "ponos.timer").write_text(timer)

    # The console's unit is written whether or not it is enabled: writing it
    # costs nothing, and an update that refreshed the timer but left the console
    # on last month's ExecStart would be the kind of half-update this module
    # exists to prevent. Starting it is `install.sh` and `ponos enable`;
    # an update never turns on what somebody turned off.
    console = app / "systemd" / "ponos-web.service.in"
    if console.exists():
        text = console.read_text()
        text = text.replace("@BIN@", str(_binary())).replace("@PATH@", os.environ.get("PATH", ""))
        (units / "ponos-web.service").write_text(text)
    # Same reasoning: written, never enabled — `ponos tailscale enable` is the
    # decision to publish the MCP endpoint, and an update does not take it.
    tailnet = app / "systemd" / "ponos-tailscale.service.in"
    if tailnet.exists():
        text = tailnet.read_text()
        text = text.replace("@BIN@", str(_binary())).replace("@PATH@", os.environ.get("PATH", ""))
        (units / "ponos-tailscale.service").write_text(text)
    return units


def restart_console() -> None:
    """Put the console on the code that just landed, if it is running.

    A run is a process that ends, so the next pass is already the new version.
    The console is not: it is started once and answers for weeks, with the
    Python it was given at boot — while serving `web/static/` from the disk,
    which an update has just replaced. The two then disagree, and the browser is
    where it shows: on 18 September 2026 the project list drew and opening a
    project answered `no such route: /api/projects/<id>`, because the page was
    this morning's and the server it asked was the day before's.

    `try-restart` rather than `restart`, for the reason the unit is written with:
    an update never turns on what somebody turned off. And nothing here is worth
    failing an update over — a console left on the old code is a console to
    restart by hand, not a version to roll back.

    Typed *in* the console (`update` is a verb it offers), this cuts the very
    command that asked for it: the page loses its stream and reconnects onto the
    new version, which is what was asked for. The unit says the same about a
    chat turn — a restart costs the connection and nothing else.
    """
    git.run(["systemctl", "--user", "try-restart", "ponos-web.service"], timeout=30)


def apply(status: Status, interval_seconds: int, app: Path | None = None) -> str:
    """Move the installation to `status.latest`. Returns "" or what went wrong.

    What `install.sh` writes outside the app directory is written again from the
    sources that just landed — otherwise a version changing the launcher or the
    systemd units would be installed everywhere except where it counts. And the
    console is restarted onto it, because it is the one part of the installation
    that would otherwise keep running the old code.
    """
    if in_container():
        return CONTAINER
    error = install(status, interval_seconds, app)
    if error:
        return error
    if shutil.which("systemctl"):
        restart_console()
    return ""


def install(status: Status, interval_seconds: int, app: Path | None = None) -> str:
    """Put `status.latest` in use, or leave `status.current` there. "" or why.

    Everything but the restart, so that the console — which is the process an
    update restarts — can say "installed" before it goes. And never half of it:
    the new version is a directory of its own, copied from the one in use and
    moved to the new commit there, and `app` only points at it once it imports.
    A version that does not start is never pointed at; one whose launcher and
    units cannot be written is pointed away from again, launcher and units
    included. A runner on last week's code runs tickets; a runner on a commit
    that fails at `import` runs nothing, and nobody is there to notice.
    """
    app = app or app_dir()
    try:
        previous = _versioned(app)
    except (OSError, subprocess.SubprocessError) as error:
        return f"the installation could not be given a version directory: {error}"
    version = app.with_name(f"{app.name}-{status.latest[:12]}")
    if version == previous:
        # Moved by hand inside its directory: the name is taken by what is in use.
        version = version.with_name(f"{version.name}-{int(time.time())}")
    problem = _prepare(previous, version, status.latest)
    if problem:
        _remove(version)
        return f"{problem} — still on {status.current[:8] or previous.name}"
    try:
        _switch(app, version)
        _regenerate(interval_seconds, app)
    except (OSError, subprocess.SubprocessError) as error:
        problem = f"the installed files could not be regenerated: {error}"
    if not problem:
        remember(Status(current=status.latest, latest=status.latest, tag=status.tag))
        _prune(app, keep={version, previous})
        return ""
    try:
        _switch(app, previous)
        _regenerate(interval_seconds, app)
    except (OSError, subprocess.SubprocessError) as error:
        return f"{problem} — and going back to {status.current[:8]} failed: {error}"
    _remove(version)
    return f"{problem} — back on {status.current[:8] or previous.name}"


def _versioned(app: Path) -> Path:
    """The directory of the version in use — made one, the first time.

    An installation from before the link has `app` as a plain directory. It is
    renamed after the commit it holds, and `app` becomes the link to it: the
    one moment, once, when `app` is missing — a pass started then does not
    start at all, which is a failure the next tick forgets, not a mixture.
    """
    if app.is_symlink():
        return app.resolve()
    head = git.git(["rev-parse", "HEAD"], app).out
    named = app.with_name(f"{app.name}-{head[:12] or int(time.time())}")
    _remove(named)
    app.rename(named)
    _switch(app, named)
    return named


def _prepare(previous: Path, version: Path, commit: str) -> str:
    """Copy the version in use to `version`, move it to `commit`, and start it.

    Its environment is made afresh rather than copied: what it requires is the
    new commit's `requirements.txt`, and an environment moved from one
    directory to another is not one any more.
    """
    staging = version.with_name(f"{version.name}.partial")
    _remove(version)
    _remove(staging)
    try:
        shutil.copytree(
            previous,
            staging,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", environment.VENV, f"{environment.VENV}.*"),
        )
        reset = git.git(["reset", "--hard", "--quiet", commit], staging)
        if not reset.ok:
            _remove(staging)
            return f"git reset: {reset.err or reset.out}"
        staging.rename(version)
    except (OSError, shutil.Error, subprocess.SubprocessError) as error:
        _remove(staging)
        return f"the new version could not be copied: {error}"
    problem = environment.create(version)
    if problem:
        return problem
    return verify(version)


def _switch(app: Path, version: Path) -> None:
    """Point `app` at `version` in one rename: a launcher reads one or the other."""
    scratch = app.with_name(f".{app.name}.{os.getpid()}.link")
    scratch.unlink(missing_ok=True)
    # Relative, so that the whole directory can move without breaking it.
    scratch.symlink_to(version.name)
    os.replace(scratch, app)


def _prune(app: Path, keep: set[Path]) -> None:
    """Drop the versions older than the previous one, and what a crash left."""
    kept = {path.resolve() for path in keep}
    for path in app.parent.glob(f"{app.name}-*"):
        if path.resolve() not in kept:
            _remove(path)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)


def _regenerate(interval_seconds: int, app: Path) -> None:
    write_launcher(app)
    if shutil.which("systemctl"):
        write_units(interval_seconds, app)
        git.run(["systemctl", "--user", "daemon-reload"])


def verify(app: Path) -> str:
    """Does the code on disk start? "" when it does, what it said otherwise.

    Imported by a Python of its own, from the directory itself — the one its
    launcher will run, its environment's when it has one: the process asking is
    still running the old modules, and would answer for those. The console's
    application is imported with the rest, FastAPI with it: an environment
    missing a package is a console that does not start after the move. Its
    page is checked too — it is committed, and a version without it is a
    console that answers every address with a 404.
    """
    probe = "import ponos.__main__, ponos.web.server, ponos.web.app"
    variables = {**os.environ, "PYTHONPATH": str(app / "src")}
    try:
        done = subprocess.run(
            [environment.interpreter(app), "-c", probe],
            cwd=app,
            env=variables,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return f"the new version could not be started: {error}"
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        return f"the new version does not start: {said[-1] if said else done.returncode}"
    if not (app / "src" / "ponos" / "web" / "static" / "index.html").is_file():
        return "the new version has no console page (web/static/index.html)"
    return ""


def waiting(app: Path | None = None) -> Status:
    """What the last check found — if it still describes what is installed.

    The stamp is written before an update is applied and read for hours after,
    so it can describe a commit that is no longer on disk: the installation it
    compared was moved since, by a run, by hand, or by `git pull` in the app
    directory. Asked of the directory itself, that is one `rev-parse`; an update
    offered for a version that is already installed was the one lie the header
    could tell.
    """
    status = remembered()
    if not status.stale:
        return status
    try:
        head = git.git(["rev-parse", "HEAD"], app or app_dir()).out
    except (OSError, subprocess.SubprocessError):
        return status
    if head and head != status.current:
        return Status(current=head, latest=head, tag=status.tag if head == status.latest else "")
    return status


def repository_page(app: Path | None = None) -> str:
    """The installation's remote, as a GitHub page — or "" when it is not one."""
    try:
        url = git.git(["config", "--get", "remote.origin.url"], app or app_dir()).out.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.match(
        r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"([\w.-]+/[\w.-]+?)(?:\.git)?/?$",
        url,
    )
    return f"https://github.com/{match.group(1)}" if match else ""


def notes(status: Status, page: str) -> str:
    """Where what changed is written: the release, or the commits in between."""
    if not page or not status.stale:
        return ""
    if status.tag:
        return f"{page}/releases/tag/{status.tag}"
    return f"{page}/compare/{status.current[:12]}...{status.latest[:12]}"
