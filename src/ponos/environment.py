"""The virtual environment each installed version runs in.

Until October 2026 the runner imported the standard library and nothing else,
and the launcher ran it with whatever `python3` the machine had. Then libraries
came in — httpx for the runner (see http.py), FastAPI and uvicorn for the
console (see web/app.py) — and they have to be installed somewhere that is the
installation's own: a system Python shared with everything else on the machine
is not that.

So every version directory gets its own `.venv`, made from the machine's Python
when the version is installed, *before* `app` points at it: `install.sh` makes
it in the directory it has just cloned, and `update.install` in the copy it has
just moved to the new commit. A version whose environment cannot be made is a
version that is never pointed at — the one in use stays, with its own
environment untouched, which is what going back means here. Nothing is ever
installed into an environment something is running on.

Two cases are not failures, because an installation that used to work must
keep working:

- **No package to install.** A Python without `ensurepip` (Debian's, without
  `python3-venv`) still makes an environment with `--without-pip`; and if even
  that fails, the launcher runs the machine's Python as it always has — there is
  nothing the environment would have added.
- **An installation from before the environment.** The first update onto this
  code is applied by the previous version, which knows nothing of `.venv`:
  `ensure` makes it on the next pass, under the run lock, and the launcher runs
  the machine's Python until then — the runner's passes as before, and a
  console that says what it is missing and starts again, on the environment,
  once the pass has made it (`server.serve`).

Packages to install on that same Python is where pip is missing, and asking for
`sudo apt install python3-venv` in the middle of an automatic update is asking
nobody: the update would be refused at every pass, forever. So when there is
neither `uv` nor `ensurepip`, the runner fetches uv itself — the official
binary, at the version pinned here, its SHA-256 checked before it is unpacked —
into `~/.local/share/ponos/uv`, beside the versions and outside any of them, and
installs with it. Offline, that fails like any other install: the version is
not pointed at, and the one in use carries on.

An environment is also lost under its feet when the distribution moves to
another Python: `.venv` names an interpreter (`executable` in `pyvenv.cfg`) that
the upgrade removed. `ensure` sees it with a `stat`, and makes it again.

Optional extras (`voice`, `browser`) are *declared*, never guessed: `[install]
extras` in `config.toml`. A new environment is built from scratch, so Piper
installed by hand in the one before it was lost at every update, and the console
said it was not installed. Each version ships `requirements-<extra>.txt` beside
`requirements.txt` (the same export, with the extra, hashes included) and
`create` installs the declared ones after the base — *before* the version is
pointed at. An extra that cannot be installed does not stop the update: the
version is the better one, only without that feature, and `.venv/ponos-extras.json`
says which one is missing and why, for `ponos doctor`, the console and the
notification. The first pass on this code, when `[install]` is still absent,
reads the extras already installed — in the environment in use and in the version
kept for going back — and declares them: an installation that had Piper keeps it.

In a container none of this: the image installs `requirements.txt` into its own
Python when it is built.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path

from . import config as config_module
from .config import in_container

# Inside the version directory, so that one rename moves code and environment
# together, and the version kept for going back keeps the environment it ran in.
VENV = ".venv"
# What the code imports beyond the standard library, exported from `uv.lock`
# (`uv export --no-dev --no-emit-project`), with hashes.
REQUIREMENTS = "requirements.txt"

# Inside the environment, so that it goes with it: which declared extras could not
# be installed (`{extra: why}`), and the declaration a version was last checked against.
EXTRA_FAILURES = "ponos-extras.json"
EXTRA_CHECKED = "ponos-extras.checked"

# The uv fetched when the machine has no way to install a package. Pinned, with
# the sums of its release page: a new one is a commit that changes both.
UV_VERSION = "0.12.5"
UV_RELEASES = "https://github.com/astral-sh/uv/releases/download"
UV_SHA256 = {
    "x86_64-unknown-linux-gnu": "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2",
    "aarch64-unknown-linux-gnu": "9bf43b4d1a07665bf64d4c4e710930b382321a785e0eb10aac07f46471f86a31",
    "x86_64-apple-darwin": "b3b2137477cf96c9686ebfb71524614cec780c673fd73e59bce099aef02e70e8",
    "aarch64-apple-darwin": "5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62",
}

# What `ponos doctor` tells to type when the environment is not what it should be.
REPAIR = "ponos update --environment"


def base_python() -> str:
    """The machine's Python, even when asked from inside an environment.

    An environment's `python` is a link into the version directory it belongs
    to, and that directory is pruned two updates later: neither a launcher nor
    the next environment may be built on it. From an environment whose Python
    the distribution replaced, the one it was made from is gone too: then the
    interpreter actually running, wherever its links lead.
    """
    base = getattr(sys, "_base_executable", "")
    if base and Path(base).is_file():
        return base
    return str(Path(sys.executable).resolve())


def python(app: Path) -> Path:
    return app / VENV / "bin" / "python"


def interpreter(app: Path, fallback: str | None = None) -> str:
    """The Python to run `app` with: its environment's, or the machine's until it has one."""
    candidate = python(app)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return fallback or base_python()


def _settings(app: Path) -> dict[str, str]:
    """`pyvenv.cfg`, as the `key = value` lines venv and uv both write."""
    try:
        text = (app / VENV / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return {}
    pairs = (line.partition("=") for line in text.splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, _, value in pairs}


def stale(app: Path) -> str:
    """Why `app` has no usable environment, "" when it has one. Only `stat`s.

    A link that leads nowhere, or an interpreter `pyvenv.cfg` names and the
    machine no longer has: the distribution moved to another Python, and the
    environment's packages were built for the one it removed.
    """
    candidate = python(app)
    if not candidate.exists():
        if candidate.is_symlink():
            return f"{candidate} leads nowhere: the machine's Python changed"
        return "there is no environment"
    if not os.access(candidate, os.X_OK):
        return f"{candidate} is not executable"
    settings = _settings(app)
    made_from = settings.get("executable", "")
    if not made_from and settings.get("home"):
        version = settings.get("version") or settings.get("version_info", "")
        made_from = str(Path(settings["home"]) / f"python{'.'.join(version.split('.')[:2])}")
    if made_from and not Path(made_from).exists():
        return f"{made_from}, which it was made from, is gone: the machine's Python changed"
    return ""


def required(app: Path) -> list[str]:
    """The packages `app` asks for — "" lines, comments and hashes left out."""
    try:
        text = (app / REQUIREMENTS).read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("#", "--hash"))
    ]


def _run(command: list[str], app: Path, timeout: int) -> str:
    """ "" when the command succeeded, its last line of output otherwise."""
    try:
        done = subprocess.run(command, cwd=app, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    if done.returncode == 0:
        return ""
    said = (done.stderr or done.stdout).strip().splitlines()
    return said[-1] if said else f"exit {done.returncode}"


def create(app: Path, base: str | None = None, source: Path | None = None) -> str:
    """Make `app/.venv` and install what `app` requires. "" or what went wrong.

    The extras `[install]` declares are installed too (`source`, the version in
    use, is where an installation that has not declared any yet is read from —
    see `declare`). One that cannot be installed is recorded, not returned: it
    does not make the version one that is never pointed at.

    Built beside, as `.venv.partial`, and renamed into place once complete: an
    environment is either all there or not there. An environment already in
    place is made again — `create` is for a version nothing runs on yet.
    """
    base = base or base_python()
    packages = required(app)
    target = app / VENV
    staging = app / f"{VENV}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    installer = uv() if packages else ""
    if packages and not installer and not _has_ensurepip(base):
        installer, problem = fetch_uv()
        if problem:
            return f"the packages could not be installed: uv could not be fetched: {problem}"
    # Without pip when there is nothing to install, or uv to install it: it is
    # faster, and it works on a Python that has no `ensurepip`.
    command = [base, "-m", "venv"]
    if not packages or installer:
        command.append("--without-pip")
    problem = _run([*command, str(staging)], app, timeout=300)
    if problem:
        shutil.rmtree(staging, ignore_errors=True)
        if packages:
            # Debian and Ubuntu ship `venv` without `ensurepip`: pip comes with
            # `python3-venv`, and uv needs neither.
            return (
                f"the environment could not be made: {problem} "
                "(install uv, or python3-venv, and the next update will try again)"
            )
        # Nothing to install, so nothing lost: the launcher runs the machine's
        # Python, exactly as before environments existed.
        return ""
    if packages:
        problem = _install(app, staging, installer)
        if problem:
            shutil.rmtree(staging, ignore_errors=True)
            return f"the packages could not be installed: {problem}"
        failures = _extras(app, staging, installer, declare(app, [source] if source else []))
        _record(staging, failures)
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return ""


def _extras(app: Path, environment: Path, installer: str, extras: list[str]) -> dict[str, str]:
    """Install each extra into `environment`: the ones that could not be, with why."""
    failures: dict[str, str] = {}
    for extra in extras:
        problem = _install_extra(app, environment, installer, extra)
        if problem:
            failures[extra] = problem
    return failures


def _install_extra(app: Path, environment: Path, installer: str, extra: str) -> str:
    if extra not in available(app):
        return f"this version has no `{extra}` extra"
    if not (app / f"{REQUIREMENTS[:-4]}-{extra}.txt").is_file():
        return f"this version ships no {REQUIREMENTS[:-4]}-{extra}.txt"
    return _install(app, environment, installer, extra)


def _install(app: Path, environment: Path, installer: str, extra: str = "") -> str:
    """Install `requirements.txt` — or the extra's — into `environment`, hashes checked.

    With uv when there is one. An extra's file is the base plus the extra, so it
    installs onto an environment that already has the base as well as onto none.
    """
    requirements = str(app / (f"{REQUIREMENTS[:-4]}-{extra}.txt" if extra else REQUIREMENTS))
    target = str(environment / "bin" / "python")
    if installer:
        return _run(
            [
                installer,
                "pip",
                "install",
                "--quiet",
                "--python",
                target,
                "--require-hashes",
                "-r",
                requirements,
            ],
            app,
            timeout=900,
        )
    return _run(
        [
            target,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            "--require-hashes",
            "-r",
            requirements,
        ],
        app,
        timeout=900,
    )


def ensure(app: Path) -> str:
    """Give the version in use the environment it lacks. "" or why not.

    For the installation updated onto this code by a version that made none,
    and for the one whose Python the distribution replaced: called at the top
    of a pass, under the run lock. Cheap when there is one — a few `stat`s —
    and never fatal: the launcher keeps running the machine's Python.
    """
    if in_container() or not stale(app):
        return ""
    return create(app)


# -- the extras: declared, installed with every version ------------------------


def available(app: Path) -> dict[str, list[str]]:
    """The extras `app`'s `pyproject.toml` offers, each with the packages that are its own."""
    try:
        with (app / "pyproject.toml").open("rb") as handle:
            table = tomllib.load(handle).get("project", {}).get("optional-dependencies", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {
        str(extra): [_name(line) for line in lines if isinstance(line, str)]
        for extra, lines in table.items()
        if isinstance(lines, list)
    }


def declared() -> list[str] | None:
    """`[install] extras` of `config.toml`; None when the file does not say (yet)."""
    table = config_module.read_raw(config_module.config_path()).get("install")
    if not isinstance(table, dict) or not isinstance(table.get("extras"), list):
        return None
    return list(dict.fromkeys(str(name).strip().lower() for name in table["extras"] if name))


def _write(extras: list[str]) -> str:
    """Write `[install] extras`. "" or why not."""
    path = config_module.config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        config_module.edit(path, [("install", "extras", extras)])
    except (config_module.ConfigError, config_module.RealStateRefused, OSError) as error:
        return str(error)
    return ""


def _installed(interpreter_path: Path, names: list[str]) -> set[str]:
    """Which of `names` the environment of that Python has installed (distribution metadata)."""
    probe = (
        "import importlib.metadata as m, json, sys\n"
        "found = []\n"
        "for name in json.loads(sys.argv[1]):\n"
        "    try:\n"
        "        m.distribution(name)\n"
        "        found.append(name)\n"
        "    except Exception:\n"
        "        pass\n"
        "print(json.dumps(found))\n"
    )
    if not names or not interpreter_path.is_file():
        return set()
    try:
        done = subprocess.run(
            [str(interpreter_path), "-I", "-c", probe, json.dumps(names)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return set(json.loads(done.stdout)) if done.returncode == 0 else set()
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()


def present(app: Path, sources: list[Path]) -> list[str]:
    """The extras of `app` whose packages one of the environments of `sources` holds."""
    offered = available(app)
    found: list[str] = []
    for extra, names in offered.items():
        if names and any(_installed(python(source), names) == set(names) for source in sources):
            found.append(extra)
    return found


def declare(app: Path, sources: list[Path]) -> list[str]:
    """The extras to install: the declaration, or — the first time — what is already there.

    An installation from before the declaration has `piper-tts` in the
    environment in use, put there by hand, and no line that says so: the extras
    found in `sources` are written to `[install]` so that this update, and the
    next ones, keep them. Once the table is there it is the user's word, and
    an extra removed from it is not found again.
    """
    wanted = declared()
    if wanted is not None:
        return wanted
    found = present(app, sources)
    if found:
        _write(found)
    return found


def failures(app: Path) -> dict[str, str]:
    """The declared extras the environment of `app` could not be given, with why."""
    try:
        said = json.loads((app / VENV / EXTRA_FAILURES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in said.items()} if isinstance(said, dict) else {}


def describe_failures(lost: dict[str, str]) -> str:
    """“the `voice` extra is not installed: …” — for the log, the notification and doctor."""
    return "; ".join(f"the `{extra}` extra is not installed: {why}" for extra, why in lost.items())


def _record(environment: Path, lost: dict[str, str]) -> None:
    path = environment / EXTRA_FAILURES
    if not lost:
        path.unlink(missing_ok=True)
        return
    try:
        path.write_text(json.dumps(lost), encoding="utf-8")
    except OSError:
        pass


def _versions(app: Path) -> list[Path]:
    """The version directories beside `app`, itself included: where an extra may still be read."""
    return [app, *sorted(path for path in app.parent.glob("app-*") if path != app)]


def _tool(app: Path) -> tuple[str, str]:
    """(uv, "") to install into the environment in use, ("", "") for its own pip, or ("", why)."""
    installer = uv()
    if installer:
        return installer, ""
    if not _run([str(python(app)), "-m", "pip", "--version"], app, timeout=60):
        return "", ""
    return fetch_uv()


def add(app: Path, extra: str) -> str:
    """Install `extra` into the environment of `app` and declare it. "" or what went wrong."""
    if in_container():
        return "in a container the image holds its extras: rebuild it"
    if stale(app):
        return "there is no usable environment: `ponos update --environment` makes it"
    offered = available(app)
    if extra not in offered:
        return f"no `{extra}` extra here (it has: {', '.join(offered) or 'none'})"
    installer, problem = _tool(app)
    if problem:
        return f"uv could not be fetched: {problem}"
    problem = _install_extra(app, app / VENV, installer, extra)
    if problem:
        return f"the `{extra}` extra could not be installed: {problem}"
    lost = failures(app)
    if lost.pop(extra, None) is not None:
        _record(app / VENV, lost)
    wanted = declared() or []
    return "" if extra in wanted else _write([*wanted, extra])


def remove(app: Path, extra: str) -> str:
    """Stop declaring `extra` and uninstall its own packages from the environment of `app`."""
    wanted = [name for name in (declared() or []) if name != extra]
    problem = _write(wanted)
    if problem:
        return problem
    names = available(app).get(extra, [])
    if names and not in_container() and not stale(app):
        installer, _ = _tool(app)
        command = (
            [installer, "pip", "uninstall", "--python", str(python(app)), *names]
            if installer
            else [str(python(app)), "-m", "pip", "uninstall", "--yes", *names]
        )
        _run(command, app, timeout=300)
    lost = failures(app)
    if lost.pop(extra, None) is not None:
        _record(app / VENV, lost)
    return ""


def sync(app: Path) -> tuple[dict[str, str], bool]:
    """Bring the environment in use to the declaration: the extras still missing, with why, and whether this was news.

    Called at the top of a pass, under the run lock. Cheap when there is nothing
    to do: the declaration it last checked is stamped inside the environment.
    This is how an installation updated onto this code by a version that knew of
    no extras gets its Piper back — read from the version kept for going back.
    """
    if in_container() or stale(app):
        return {}, False
    wanted = declare(app, _versions(app))
    stamp = app / VENV / EXTRA_CHECKED
    try:
        if stamp.read_text(encoding="utf-8") == ",".join(wanted):
            return failures(app), False
    except OSError:
        pass
    lost: dict[str, str] = {}
    there = set(present(app, [app]))
    todo = [extra for extra in wanted if extra not in there]
    if todo:
        installer, problem = _tool(app)
        for extra in todo:
            if problem:
                lost[extra] = f"uv could not be fetched: {problem}"
                continue
            said = _install_extra(app, app / VENV, installer, extra)
            if said:
                lost[extra] = said
    _record(app / VENV, lost)
    try:
        stamp.write_text(",".join(wanted), encoding="utf-8")
    except OSError:
        pass
    return lost, True


# -- uv, when the machine has nothing else to install with ---------------------


def uv_home() -> Path:
    return Path.home() / ".local" / "share" / "ponos" / "uv"


def uv() -> str:
    """The uv to install with: the machine's, or the one fetched earlier. "" when neither."""
    found = shutil.which("uv")
    if found:
        return found
    fetched = uv_home() / "uv"
    return str(fetched) if fetched.is_file() and os.access(fetched, os.X_OK) else ""


def _has_ensurepip(base: str) -> bool:
    """Whether `base -m venv` can give an environment pip — not on a Debian without `python3-venv`."""
    return not _run([base, "-I", "-c", "import ensurepip"], Path.home(), timeout=60)


def _platform() -> str:
    """The name uv's releases give this machine, "" for one they do not cover."""
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    system = {"linux": "unknown-linux-gnu", "darwin": "apple-darwin"}.get(platform.system().lower())
    return f"{machine}-{system}" if system else ""


def fetch_uv() -> tuple[str, str]:
    """Download the pinned uv into `uv_home()`: (its path, "") or ("", what went wrong).

    The archive is read whole and its sum checked before a byte of it is
    unpacked; the binary is renamed into place once written, so a fetch cut
    short leaves nothing that `uv()` would pick up.
    """
    target = _platform()
    expected = UV_SHA256.get(target)
    if not expected:
        return "", f"no uv {UV_VERSION} for {platform.system()} {platform.machine()}"
    url = f"{UV_RELEASES}/{UV_VERSION}/uv-{target}.tar.gz"
    home = uv_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            archive = response.read()
    except (OSError, ValueError) as error:
        return "", f"{url}: {error}"
    if hashlib.sha256(archive).hexdigest() != expected:
        return "", f"{url}: the SHA-256 is not uv {UV_VERSION}'s"
    staging = home / "uv.partial"
    try:
        with tempfile.TemporaryFile(dir=home) as copy:
            copy.write(archive)
            copy.seek(0)
            with tarfile.open(fileobj=copy, mode="r:gz") as unpacked:
                member = next(
                    (
                        one
                        for one in unpacked.getmembers()
                        if one.isfile() and one.name.endswith("/uv")
                    ),
                    None,
                )
                source = unpacked.extractfile(member) if member else None
                if source is None:
                    return "", f"{url}: no uv in the archive"
                staging.write_bytes(source.read())
        staging.chmod(0o755)
        staging.rename(home / "uv")
    except (OSError, tarfile.TarError) as error:
        staging.unlink(missing_ok=True)
        return "", f"uv could not be unpacked: {error}"
    return str(home / "uv"), ""


# -- what `ponos doctor` says of it --------------------------------------------


def missing(app: Path) -> list[str]:
    """The packages of `requirements.txt` the environment of `app` cannot import.

    Asked of the environment's own Python: the process asking may run another
    one. A package counts as there when its distribution is installed and each
    module it provides imports.
    """
    wanted = [_name(line) for line in required(app)]
    if not wanted:
        return []
    probe = (
        "import importlib, importlib.metadata as m, json, re, sys\n"
        "canon = lambda name: re.sub(r'[-_.]+', '-', name).lower()\n"
        "modules = {}\n"
        "for module, owners in m.packages_distributions().items():\n"
        "    for owner in owners:\n"
        "        modules.setdefault(canon(owner), []).append(module)\n"
        "lost = []\n"
        "for name in json.loads(sys.argv[1]):\n"
        "    try:\n"
        "        m.distribution(name)\n"
        "        for module in modules.get(canon(name), []):\n"
        "            importlib.import_module(module)\n"
        "    except Exception:\n"
        "        lost.append(name)\n"
        "print(json.dumps(lost))\n"
    )
    try:
        done = subprocess.run(
            [str(python(app)), "-I", "-c", probe, json.dumps(wanted)],
            cwd=app,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return list(json.loads(done.stdout)) if done.returncode == 0 else wanted
    except (OSError, subprocess.SubprocessError, ValueError):
        return wanted


def _name(requirement: str) -> str:
    """`httpx==0.28.1 ; python_version >= "3.11" \\` → `httpx`."""
    name = requirement.split(";", 1)[0].strip()
    for mark in ("[", "=", "<", ">", "!", "~", " ", "\\"):
        name = name.split(mark, 1)[0]
    return name.strip()


def diagnose(app: Path) -> tuple[str, str]:
    """("ok" | "warn" | "error", one sentence) — the environment of the version `app`."""
    packages = required(app)
    why = stale(app)
    if why and not packages:
        # The machine's Python runs Ponos, as before environments: nothing lost.
        return (
            "warn",
            f"no environment ({why}) — nothing to install, the machine's Python runs ponos",
        )
    if why:
        return "error", f"{why} — {len(packages)} package(s) to install"
    lost = missing(app)
    if lost:
        return "error", f"{python(app)} cannot import {', '.join(lost)}"
    held = f"{len(packages)} package(s)" if packages else "no package to install"
    return "ok", f"{app / VENV} — {held}"
