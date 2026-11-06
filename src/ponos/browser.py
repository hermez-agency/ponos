"""Ponos's own browser: what the runner and the console know of it, without Playwright.

External tickets used to act in Claude in Chrome, the user's own Chrome: it had
to be open, with its extension connected and the right account active, two
sessions in it stepped on each other, and a session that met a sign-in form
stopped to ask somebody to type the password. So Ponos has a browser of its
own — Chromium driven by Playwright, on this machine, headless unless
`[browser] headless` says otherwise — reached by the sessions as an MCP server,
`ponos-browser` (browser_server.py). This module is the half that stays in the
standard library: the runner and the console import it on every pass, and a
machine without the `browser` extra must still read every line of it.

**One profile per project, one context per session.** A Chromium profile
directory cannot be opened by two processes at once, and two tickets of one
project may run side by side. So what is kept per project is Playwright's
*storage state* — cookies and local storage, one JSON file under
`state/browser/profiles/`, `0600` in a `0700` folder like the vault — and every
session starts its own browser and its own context from it. What a session
leaves is merged back into the file under a lock, cookie by cookie, the newer
one winning: a sign-in done by one session is there for the next, and two
sessions ending together lose nothing of each other's.

**A login only where it belongs.** `same_site` is the guard against phishing:
the browser types a login of the vault only on the host of the entry's `url`,
or on one of its subdomains — never on a page that merely looks like it, nor on
the identity provider somebody redirected it to.

**Which browser.** `chosen`: a line `Browser: chrome` (or `Navigateur :
Ponos`) in the ticket's body, else the project's own word (its settings), else
`[browser] default`. Only external tickets are concerned: a publication still
posts from the user's own accounts, in their Chrome.

**Seeing it live.** A browser that runs writes what it shows into
`state/browser/live/<id>.png` (password fields masked) beside `<id>.json`, and
reads what the console sends it from `<id>.in`, one JSON line per action — a
click, some text, a key. That is the whole of the live view, and how a person
finishes a sign-in a second factor stopped: the console starts a browser of its
own on the project's profile (`open_for_person`), the person types the code,
and the session it opens stays in the profile for the ticket that resumes.
"""

from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import config as config_module
from . import disk

PONOS, CHROME = config_module.BROWSERS
# The name of the MCP server the sessions are given, and so the prefix of its tools.
SERVER = "ponos-browser"

# What the console shows of a live browser stays fresh this long; a browser that
# has not written its screen since is gone, or stuck.
LIVE_FRESH = 120
# How long a browser opened for a person waits for them before it closes itself.
PERSON_IDLE = 15 * 60

# A line of a ticket that names its browser: `Browser: chrome`, `Navigateur : Ponos`.
_NAMED = re.compile(
    r"^[\s>*_-]*(?:browser|navigateur)\s*:\s*\**\s*(ponos|chrome|claude in chrome)\b",
    re.IGNORECASE | re.MULTILINE,
)


# -- installed or not ----------------------------------------------------------


def available() -> bool:
    """Playwright is importable by this Python — the `browser` extra."""
    return importlib.util.find_spec("playwright") is not None


def _browsers_path() -> Path:
    given = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if given and given != "0":
        return Path(given)
    return Path.home() / ".cache" / "ms-playwright"


def chromium() -> str:
    """Where Playwright's Chromium is, or "" when it was never downloaded."""
    root = _browsers_path()
    try:
        found = sorted(
            (child for child in root.iterdir() if child.name.startswith("chromium")),
            key=lambda child: child.name,
        )
    except OSError:
        return ""
    return str(found[-1]) if found else ""


def install_commands() -> list[str]:
    """What installs the browser into the Python that runs Ponos."""
    python = sys.executable or "python3"
    return [
        f"{python} -m pip install 'playwright>=1.64.1'",
        f"{python} -m playwright install chromium",
    ]


def missing() -> str:
    """Why Ponos's browser cannot start here, or "" when it can."""
    if not available():
        return "Playwright is not installed (the `browser` extra)"
    if not chromium():
        return "Playwright's Chromium is not downloaded"
    return ""


# -- which browser -------------------------------------------------------------


def named(body: str) -> str:
    """The browser a ticket names in its body, or ""."""
    found = _NAMED.search(body or "")
    if not found:
        return ""
    return PONOS if found.group(1).lower() == PONOS else CHROME


def chosen(config: config_module.Config, project: str, body: str = "") -> str:
    """The browser an external ticket of `project` acts in: the ticket's, the project's, the file's."""
    from . import project_settings

    return named(body) or project_settings.browser(project) or config.browser.default


# -- the guard -------------------------------------------------------------------


def host(url: str) -> str:
    """The host of `url`, lower case — "" when it has none."""
    if "://" not in url:
        url = "https://" + url
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def same_site(url: str, entry_url: str) -> bool:
    """May a login made for `entry_url` be typed on `url`? Its host, or one of its subdomains.

    Not the other way round: a login for `app.example.com` is not typed on
    `example.com`, nor on `evil-example.com`. An entry without an address is
    typed nowhere.
    """
    page, entry = host(url), host(entry_url)
    if not page or not entry:
        return False
    return page == entry or page.endswith("." + entry)


# -- the profiles ----------------------------------------------------------------


def root() -> Path:
    return config_module.state_dir() / "browser"


def slug(project: str) -> str:
    """A project's name as a file name: what its profile is kept under."""
    made = re.sub(r"[^a-z0-9]+", "-", project.strip().casefold()).strip("-")
    return made[:80] or "no-project"


def profiles_dir() -> Path:
    return root() / "profiles"


def profile_path(project: str) -> Path:
    return profiles_dir() / f"{slug(project)}.json"


@contextlib.contextmanager
def _locked(project: str) -> Iterator[None]:
    folder = disk.private_dir(profiles_dir())
    with open(folder / f".{slug(project)}.lock", "a", opener=disk.opener()) as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load(project: str) -> dict[str, Any] | None:
    """The project's storage state, as Playwright takes it — None for a profile never used."""
    try:
        state = json.loads(profile_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    return {"cookies": state.get("cookies") or [], "origins": state.get("origins") or []}


def _cookie_key(cookie: dict[str, Any]) -> tuple[str, str, str]:
    return (str(cookie.get("name")), str(cookie.get("domain")), str(cookie.get("path")))


def merge(kept: dict[str, Any] | None, fresh: dict[str, Any], dropped: set[str]) -> dict[str, Any]:
    """`fresh` over `kept`: its cookies and origins win, the rest of `kept` stays.

    `dropped` names the cookies (by `name|domain|path`) the session saw and
    no longer has — signed out — which are taken out of `kept` too.
    """
    kept = kept or {"cookies": [], "origins": []}
    cookies = {
        _cookie_key(cookie): cookie
        for cookie in kept.get("cookies", [])
        if "|".join(_cookie_key(cookie)) not in dropped
    }
    for cookie in fresh.get("cookies", []):
        cookies[_cookie_key(cookie)] = cookie
    origins = {origin.get("origin"): origin for origin in kept.get("origins", [])}
    for origin in fresh.get("origins", []):
        origins[origin.get("origin")] = origin
    return {"cookies": list(cookies.values()), "origins": list(origins.values())}


def save(project: str, fresh: dict[str, Any], dropped: set[str] | None = None) -> None:
    """Merge what a browser holds now into the project's profile, under its lock."""
    with _locked(project):
        merged = merge(load(project), fresh, dropped or set())
        disk.write_atomic(profile_path(project), json.dumps(merged))


def sites(state: dict[str, Any] | None) -> list[str]:
    """The domains a profile holds cookies for, without their leading dot."""
    if not state:
        return []
    now = time.time()
    found = {
        str(cookie.get("domain", "")).lstrip(".")
        for cookie in state.get("cookies", [])
        if cookie.get("domain")
        and (cookie.get("expires", -1) in (-1, None) or cookie["expires"] > now)
    }
    return sorted(found)


def profiles() -> list[dict[str, Any]]:
    """Every profile kept: the project it belongs to (as a file name), its sites, when it changed."""
    try:
        files = sorted(profiles_dir().glob("*.json"))
    except OSError:
        return []
    listed: list[dict[str, Any]] = []
    for target in files:
        try:
            state = json.loads(target.read_text(encoding="utf-8"))
            changed = target.stat().st_mtime
        except (OSError, ValueError):
            continue
        listed.append(
            {
                "slug": target.stem,
                "sites": sites(state if isinstance(state, dict) else None),
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(changed)),
            }
        )
    return listed


def reset(project: str) -> bool:
    """Forget everything a project's browser kept — every site signed out. True if there was one."""
    with _locked(project):
        try:
            profile_path(project).unlink()
        except FileNotFoundError:
            return False
    return True


# -- what a session is given ---------------------------------------------------


def server_environment(
    *,
    project: str,
    ticket: str,
    session: str,
    headless: bool,
    logins: dict[str, str],
    downloads: Path,
) -> dict[str, str]:
    """What `browser_server` is told by its environment — never a value of the vault."""
    source = str(Path(__file__).resolve().parent.parent)
    return {
        "PYTHONPATH": source,
        "PONOS_BROWSER_PROJECT": project,
        "PONOS_BROWSER_TICKET": ticket,
        "PONOS_BROWSER_SESSION": session,
        "PONOS_BROWSER_HEADLESS": "1" if headless else "0",
        "PONOS_BROWSER_LOGINS": json.dumps(logins),
        "PONOS_BROWSER_DOWNLOADS": str(downloads),
        "XDG_STATE_HOME": str(config_module.state_dir().parent),
    }


def mcp_config(target: Path, environment: dict[str, str]) -> Path:
    """Write the `--mcp-config` file that gives a session `ponos-browser`; return its path."""
    server = {
        SERVER: {
            "type": "stdio",
            "command": sys.executable or "python3",
            "args": ["-m", "ponos.browser_server"],
            "env": environment,
        }
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    disk.write_atomic(target, json.dumps({"mcpServers": server}, indent=2))
    return target


# -- live --------------------------------------------------------------------------


def live_dir() -> Path:
    return root() / "live"


def live_id(text: str) -> str:
    """An identifier that is a file name, and nothing else."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text)[:120].strip(".-") or "browser"


def person_id(project: str) -> str:
    return f"person-{slug(project)}"


def live() -> list[dict[str, Any]]:
    """The browsers running now, freshest first, as each one describes itself."""
    try:
        files = list(live_dir().glob("*.json"))
    except OSError:
        return []
    now = time.time()
    found: list[dict[str, Any]] = []
    for target in files:
        try:
            said = json.loads(target.read_text(encoding="utf-8"))
            fresh = target.stat().st_mtime
        except (OSError, ValueError):
            continue
        if not isinstance(said, dict) or now - fresh > LIVE_FRESH or said.get("closed"):
            continue
        if not _alive(int(said.get("pid") or 0)):
            continue
        found.append({**said, "id": target.stem})
    return sorted(found, key=lambda item: str(item.get("at", "")), reverse=True)


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def screen(identifier: str) -> Path | None:
    """The last screen a live browser wrote, after saying somebody is looking at it."""
    identifier = live_id(identifier)
    target = live_dir() / f"{identifier}.png"
    if not target.is_file():
        return None
    watched = live_dir() / f"{identifier}.watch"
    with contextlib.suppress(OSError):
        watched.touch()
    return target


ACTIONS = ("click", "type", "press", "goto", "scroll", "close")


def send(identifier: str, action: dict[str, Any]) -> None:
    """Hand a live browser one action of the console: it plays it at its next breath."""
    if action.get("action") not in ACTIONS:
        raise ValueError(f"an action is one of {', '.join(ACTIONS)}")
    identifier = live_id(identifier)
    if not (live_dir() / f"{identifier}.json").is_file():
        raise LookupError("no such browser")
    folder = disk.private_dir(live_dir())
    with disk.open_private(folder / f"{identifier}.in", "a") as handle:
        handle.write(json.dumps(action) + "\n")


def open_for_person(config: config_module.Config, project: str, url: str) -> str:
    """Start a browser on `project`'s profile for a person to drive from the console; its id.

    What it signs in to stays in the profile: the way a second factor or a
    CAPTCHA the browser never answers itself is finished by somebody.
    """
    if why := missing():
        raise RuntimeError(why)
    if not host(url):
        raise ValueError("say which address to open")
    identifier = person_id(project)
    if any(item["id"] == identifier for item in live()):
        send(identifier, {"action": "goto", "url": url})
        return identifier
    folder = disk.private_dir(live_dir())
    environment = {
        **os.environ,
        **server_environment(
            project=project,
            ticket="",
            session=identifier,
            headless=config.browser.headless,
            logins={},
            downloads=folder,
        ),
    }
    with open(folder / f"{identifier}.log", "a", opener=disk.opener()) as errors:
        subprocess.Popen(
            [sys.executable or "python3", "-m", "ponos.browser_server", "--person", url],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            start_new_session=True,
        )
    return identifier
