"""The virtual environment each installed version runs in.

Until October 2026 the runner imported the standard library and nothing else,
and the launcher ran it with whatever `python3` the machine had. That stays
true of the code today — `requirements.txt` lists no package — but the day a
library comes in, it has to be installed somewhere that is the runner's own,
and a system Python shared with everything else on the machine is not that.

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
  the machine's Python until then.

In a container none of this: the image installs `requirements.txt` into its own
Python when it is built.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import in_container

# Inside the version directory, so that one rename moves code and environment
# together, and the version kept for going back keeps the environment it ran in.
VENV = ".venv"
# What the code imports beyond the standard library, exported from `uv.lock`
# (`uv export --no-dev --no-emit-project`), with hashes.
REQUIREMENTS = "requirements.txt"


def base_python() -> str:
    """The machine's Python, even when asked from inside an environment.

    An environment's `python` is a link into the version directory it belongs
    to, and that directory is pruned two updates later: neither a launcher nor
    the next environment may be built on it.
    """
    return getattr(sys, "_base_executable", "") or sys.executable


def python(app: Path) -> Path:
    return app / VENV / "bin" / "python"


def interpreter(app: Path, fallback: str | None = None) -> str:
    """The Python to run `app` with: its environment's, or the machine's until it has one."""
    candidate = python(app)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return fallback or base_python()


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
    """"" when the command succeeded, its last line of output otherwise."""
    try:
        done = subprocess.run(
            command, cwd=app, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    if done.returncode == 0:
        return ""
    said = (done.stderr or done.stdout).strip().splitlines()
    return said[-1] if said else f"exit {done.returncode}"


def create(app: Path, base: str | None = None) -> str:
    """Make `app/.venv` and install what `app` requires. "" or what went wrong.

    Built beside, as `.venv.partial`, and renamed into place once complete: an
    environment is either all there or not there. An environment already in
    place is made again — `create` is for a version nothing runs on yet.
    """
    base = base or base_python()
    packages = required(app)
    target = app / VENV
    staging = app / f"{VENV}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    # Without pip when there is nothing to install: it is faster, and it works
    # on a Python that has no `ensurepip`.
    command = [base, "-m", "venv"]
    if not packages or shutil.which("uv"):
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
        problem = _install(app, staging)
        if problem:
            shutil.rmtree(staging, ignore_errors=True)
            return f"the packages could not be installed: {problem}"
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return ""


def _install(app: Path, environment: Path) -> str:
    """Install `requirements.txt` into `environment`, hashes checked."""
    requirements = str(app / REQUIREMENTS)
    target = str(environment / "bin" / "python")
    if shutil.which("uv"):
        return _run(
            ["uv", "pip", "install", "--quiet", "--python", target, "--require-hashes",
             "-r", requirements],
            app, timeout=900,
        )
    return _run(
        [target, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "--require-hashes", "-r", requirements],
        app, timeout=900,
    )


def ensure(app: Path) -> str:
    """Give the version in use the environment it was installed without. "" or why not.

    For the installation updated onto this code by a version that made none:
    called at the top of a pass, under the run lock. Cheap when there is one —
    a `stat` — and never fatal: the launcher keeps running the machine's Python.
    """
    if in_container() or python(app).exists():
        return ""
    return create(app)
