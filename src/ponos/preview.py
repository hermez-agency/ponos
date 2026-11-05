"""Before/after captures of a ticket for a user interface, taken from the running project.

Judging an interface ticket means starting the project and looking at it,
which a phone cannot do: the runner does it once, after the commits, and
reports pictures only.

**The installed Chrome, without Playwright.** `chrome --headless --screenshot`
is enough for one page at a time and needs no dependency: no Python package
(the core takes none in passing), no Node for a project that has none. Without
Chrome nothing is taken and the ticket goes to review as before.

**Nothing runs unless `preview` is set, and nothing is left after the pass.**
The server is started in its own process group and the whole group is killed,
whether the captures worked or not: `npm run dev` leaves grandchildren that
`terminate()` would not see.

**A port that already answers is never photographed.** If something replies on
the address before the launch (the user's own dev server, another pass), the
page captured would not be the branch's: the pass is dropped, and says why.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import disk, state

CHROMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")

# How long the server has to answer, and a page to draw itself.
READY_SECONDS = 90
PAGE_SECONDS = 45
MAX_PAGES = 6
WINDOW = "1280,800"
SIDES = ("before", "after")
KINDS = {".png": "image/png"}


@dataclass(frozen=True)
class Setting:
    """A project's `preview = { command, url, pages }`."""

    command: str = ""
    url: str = ""
    pages: tuple[str, ...] = ("/",)

    def __bool__(self) -> bool:
        return bool(self.command and self.url)

    def as_dict(self) -> dict[str, Any]:
        return {"command": self.command, "url": self.url, "pages": list(self.pages)}


def parse(raw: object) -> Setting:
    """The setting as kept; whatever does not read is « no preview »."""
    if not isinstance(raw, dict):
        return Setting()
    command = raw.get("command")
    url = raw.get("url")
    pages = raw.get("pages")
    if not isinstance(command, str) or not isinstance(url, str):
        return Setting()
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return Setting()
    listed = (
        tuple(p.strip() for p in pages if isinstance(p, str) and p.strip())[:MAX_PAGES]
        if isinstance(pages, list)
        else ()
    )
    return Setting(command.strip(), url.strip().rstrip("/"), listed or ("/",))


@dataclass
class Taken:
    """What a pass brought back: the files by side, and why it stopped."""

    files: dict[str, list[Path]] = field(default_factory=lambda: {side: [] for side in SIDES})
    skipped: str = ""

    @property
    def pairs(self) -> int:
        return min(len(self.files["before"]), len(self.files["after"]))


def chrome() -> str:
    """The installed Chrome, or nothing."""
    return next((found for name in CHROMES if (found := shutil.which(name))), "")


def folder(ticket_id: str) -> Path:
    """Where a ticket's captures are kept, under the state directory."""
    path = state.logs_dir().parent / "previews" / ticket_id.replace("-", "")[:32]
    return path


def listing(ticket_id: str) -> list[dict[str, str]]:
    """The captures kept for a ticket: `side`, `page` and `file`, in page order."""
    root = folder(ticket_id)
    if not root.is_dir():
        return []
    shots = []
    for side in SIDES:
        for path in sorted(root.glob(f"{side}-*.png")):
            number = path.stem.split("-", 1)[1]
            shots.append({"side": side, "page": _page_of(root, number), "file": path.name})
    return shots


def _page_of(root: Path, number: str) -> str:
    try:
        pages = (root / "pages.txt").read_text(encoding="utf-8").splitlines()
        return pages[int(number)]
    except (OSError, ValueError, IndexError):
        return ""


def read(ticket_id: str, name: str) -> bytes | None:
    """A capture by its name — never a path."""
    if name != Path(name).name or Path(name).suffix not in KINDS:
        return None
    try:
        return (folder(ticket_id) / name).read_bytes()
    except OSError:
        return None


def _answers(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _stop(process: subprocess.Popen[bytes]) -> None:
    """The whole group, politely then by force: nothing of the server may survive.

    The group, not its leader: the shell can be gone while the server it
    started ignores SIGTERM and keeps the port — only an empty group is done.
    """
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except OSError:
            break
        deadline = time.monotonic() + 5
        while _group_alive(process) and time.monotonic() < deadline:
            time.sleep(0.1)
        if not _group_alive(process):
            break
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _group_alive(process: subprocess.Popen[bytes]) -> bool:
    """Is anything of that group still running? Its leader is reaped on the way."""
    process.poll()
    try:
        os.killpg(process.pid, 0)
    except OSError:
        return False
    return True


def shoot(
    setting: Setting,
    workdir: Path,
    destination: Path,
    side: str,
    *,
    log: Path,
    env: dict[str, str] | None = None,
) -> tuple[list[Path], str]:
    """Start the project in `workdir`, photograph each page, kill everything.

    The files taken (`<side>-<n>.png`, in page order) and what kept it from
    going to the end, empty when all went well.
    """
    browser = chrome()
    if not browser:
        return [], "no Chrome found"
    if _answers(setting.url):
        return [], f"{setting.url} already answers before the project is started"
    destination.mkdir(parents=True, exist_ok=True)
    taken: list[Path] = []
    with disk.open_private(log) as output:
        output.write(f"$ {setting.command}\n")
        output.flush()
        try:
            process = subprocess.Popen(
                ["sh", "-c", setting.command],
                cwd=str(workdir),
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env={**os.environ, **(env or {}), "CI": "true", "BROWSER": "none"},
                start_new_session=True,
            )
        except OSError as error:
            return [], str(error)
        try:
            deadline = time.monotonic() + READY_SECONDS
            while not _answers(setting.url):
                if process.poll() is not None:
                    return [], f"`{setting.command}` stopped with exit {process.returncode}"
                if time.monotonic() > deadline:
                    return [], f"{setting.url} did not answer within {READY_SECONDS}s"
                time.sleep(0.5)
            for number, page in enumerate(setting.pages):
                target = destination / f"{side}-{number}.png"
                if _screenshot(browser, setting.url + "/" + page.lstrip("/"), target):
                    taken.append(target)
            return taken, "" if taken else "Chrome took no capture"
        finally:
            _stop(process)


def _screenshot(browser: str, url: str, target: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="ponos-chrome-") as profile:
        try:
            subprocess.run(
                [
                    browser,
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--no-first-run",
                    f"--user-data-dir={profile}",
                    f"--window-size={WINDOW}",
                    "--virtual-time-budget=8000",
                    f"--screenshot={target}",
                    url,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PAGE_SECONDS,
                start_new_session=True,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    return target.is_file() and target.stat().st_size > 0


def write_pages(destination: Path, setting: Setting) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "pages.txt").write_text("\n".join(setting.pages), encoding="utf-8")


def clear(destination: Path) -> None:
    """The captures of an earlier pass: one pass replaces another."""
    shutil.rmtree(destination, ignore_errors=True)
