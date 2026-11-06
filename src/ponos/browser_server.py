"""`ponos-browser`: the MCP server a session drives Ponos's browser with.

Started by Claude Code itself, one per session (`--mcp-config`, see
browser.py), and spoken to over its standard input and output, one JSON-RPC
message per line — the whole of the protocol a stdio server needs is here, so
that nothing but Playwright comes in. Playwright is imported when the first
tool is called, through `importlib`: the module reads on a machine without the
`browser` extra, and a session that never browses never starts Chromium.

**The model never holds a value of the vault.** `browser_login` takes the name
of a login entry, and the server does the rest: it opens the entry's address,
finds the user and password fields, fills them, submits, and answers with one
of three words — connected, failed (and why), second factor requested. The
values themselves are read here, from the session's environment when the
runner gave them, from the vault otherwise; they are kept in this process only
long enough to be typed, and every word this server sends back — a page's
text, its accessibility tree, an error — goes through `vault.mask` first.
Screenshots are taken with the password fields, the fields it filled and any
element showing a value masked. `browser_type` refuses to type a value of the
vault the model would have read or guessed: a login goes through `browser_login`
or not at all.

**Only where it belongs.** An entry is used only if the runner granted it to
the session's project (`PONOS_BROWSER_LOGINS`), and only on its own site:
`browser.same_site`, checked on the address asked for and again on the page the
browser landed on — a redirection to somebody else's form is refused.

**Never past a second factor.** A CAPTCHA or a one-time code is reported as it
is, with a screenshot, and the session is told to stop: a person finishes the
sign-in from the console, on the same profile (`--person`).

Every sign-in is written in the vault's journal (`vault_store.signed_in`).
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import json
import logging
import os
import re
import select
import sys
import time
from pathlib import Path
from typing import Any

from . import browser, disk, vault, vault_store

logger = logging.getLogger(__name__)

PROTOCOL = "2025-06-18"
# What a page's text or tree is cut to: a session pays for every character it reads.
LONGEST = 30_000
# How long a page is given to load, and a click to settle, in milliseconds.
LOADING = 30_000
SETTLING = 3_000
# How often a browser nobody watches still writes its screen, in seconds.
QUIET_SCREEN = 10

_SECOND_FACTOR = re.compile(
    r"two[- ]factor|2fa|two[- ]step|verification code|security code|authenticator|"
    r"one[- ]time (?:code|password)|enter the code|code de v[ée]rification|"
    r"double authentification|authentification [àa] deux|code de s[ée]curit[ée]|"
    r"saisissez le code|entrez le code",
    re.IGNORECASE,
)
_CAPTCHA = re.compile(r"captcha|are you a robot|not a robot|je ne suis pas un robot", re.I)

# What the page is asked about its sign-in form: marks the two fields it finds.
_PROBE = """() => {
  const visible = (e) => {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
      && !e.disabled && !e.readOnly;
  };
  document.querySelectorAll('[data-ponos-login]').forEach((e) => e.removeAttribute('data-ponos-login'));
  const inputs = [...document.querySelectorAll('input')].filter(visible);
  const pass = inputs.find((e) => e.type === 'password');
  const texty = (e) => ['text', 'email', 'tel', ''].includes((e.getAttribute('type') || '').toLowerCase());
  let candidates = inputs.filter((e) => texty(e) && (!pass || !pass.form || e.form === pass.form));
  if (pass) candidates = candidates.filter((e) => e.compareDocumentPosition(pass) & Node.DOCUMENT_POSITION_FOLLOWING);
  const words = (e) => [e.autocomplete, e.name, e.id, e.type, e.placeholder, e.getAttribute('aria-label')].join(' ').toLowerCase();
  const otp = (e) => e.autocomplete === 'one-time-code' || /otp|totp|2fa|mfa|one.?time|verif|passcode/.test(words(e));
  const score = (e) => (/user|mail|login|identifiant|account|compte/.test(words(e)) ? 2 : 0);
  candidates = candidates.filter((e) => !otp(e));
  const user = candidates.map((e, i) => [score(e), i, e]).sort((a, b) => b[0] - a[0] || b[1] - a[1]).map((x) => x[2])[0];
  if (pass) pass.setAttribute('data-ponos-login', 'password');
  if (user) user.setAttribute('data-ponos-login', 'user');
  const captcha = !!document.querySelector(
    'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[src*="captcha"], '
    + '.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]');
  const errors = [...document.querySelectorAll('[role=alert], .error, .alert, .flash, [aria-live=assertive]')]
    .filter(visible).map((e) => e.innerText.trim()).filter(Boolean).join(' ').slice(0, 300);
  return {password: !!pass, user: !!user, otp: inputs.some(otp), captcha, errors};
}"""

# The values of the password fields on the page, to be masked in what is read of it.
_PASSWORDS = """() => [...document.querySelectorAll('input[type=password]')]
  .map((e) => e.value).filter((v) => v && v.length >= 4)"""


class Refused(Exception):
    """A tool the server will not run, said to the model as it is."""


def _target_schema(
    extra: dict[str, Any] | None = None, required: list[str] | None = None
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "role": {"type": "string", "description": "ARIA role, e.g. button, link, textbox"},
        "name": {"type": "string", "description": "accessible name, with role"},
        "label": {"type": "string", "description": "the label of a form field"},
        "text": {"type": "string", "description": "visible text of the element"},
        "selector": {"type": "string", "description": "a CSS selector, when nothing else names it"},
        **(extra or {}),
    }
    return {"type": "object", "properties": properties, "required": required or []}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "browser_navigate",
        "description": "Open an address in Ponos's browser.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "browser_read",
        "description": (
            "Read the page: its accessibility tree (what = tree, the default: roles and names "
            "to target with the other tools) or its visible text (what = text). Password fields "
            "and the vault's values are masked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"what": {"type": "string", "enum": ["tree", "text"]}},
        },
    },
    {
        "name": "browser_click",
        "description": "Click an element, named by role and name, label, text or selector.",
        "inputSchema": _target_schema(),
    },
    {
        "name": "browser_type",
        "description": (
            "Type text into a field (it replaces what the field held), then press Enter if "
            "submit is true. Never a password: sign in with browser_login."
        ),
        "inputSchema": _target_schema(
            {"value": {"type": "string"}, "submit": {"type": "boolean"}}, ["value"]
        ),
    },
    {
        "name": "browser_press",
        "description": "Press a key on the page, e.g. Enter, Escape, Tab, ArrowDown.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "browser_screenshot",
        "description": "A screenshot of the page as it is, password fields masked.",
        "inputSchema": {"type": "object", "properties": {"full_page": {"type": "boolean"}}},
    },
    {
        "name": "browser_download",
        "description": "Click what starts a download, and keep the file in the working directory.",
        "inputSchema": _target_schema(),
    },
    {
        "name": "browser_upload",
        "description": "Give a file of the working directory to a file field.",
        "inputSchema": _target_schema({"path": {"type": "string"}}, ["path"]),
    },
    {
        "name": "browser_login",
        "description": (
            "Sign in with a login entry of the vault, by its name: the browser opens the "
            "entry's site, fills the form and submits it itself — you never see the password. "
            "Answers connected, failed (with why) or second factor requested. `url` opens "
            "another sign-in page of the same site."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"entry": {"type": "string"}, "url": {"type": "string"}},
            "required": ["entry"],
        },
    },
]


class Browser:
    """One browser, one context, one page: a session's, or a person's."""

    def __init__(self, *, person: bool = False) -> None:
        self.project = os.environ.get("PONOS_BROWSER_PROJECT", "")
        self.ticket = os.environ.get("PONOS_BROWSER_TICKET", "")
        self.identifier = browser.live_id(
            os.environ.get("PONOS_BROWSER_SESSION", "") or f"session-{os.getpid()}"
        )
        self.headless = os.environ.get("PONOS_BROWSER_HEADLESS", "1") != "0"
        self.downloads = Path(os.environ.get("PONOS_BROWSER_DOWNLOADS", "") or os.getcwd())
        try:
            granted = json.loads(os.environ.get("PONOS_BROWSER_LOGINS", "") or "{}")
        except ValueError:
            granted = {}
        self.logins: dict[str, str] = granted if isinstance(granted, dict) else {}
        self.person = person
        self.waiting = ""
        self._values: dict[str, str] = {}
        self._known_cookies: set[str] = set()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._screen_at = 0.0
        self._commands_read = 0

    # -- the vault's values -------------------------------------------------

    def _value(self, variable: str) -> str:
        """A value of the vault: the session's environment first, the vault itself next."""
        if variable not in self._values:
            value = os.environ.get(variable, "")
            if not value:
                try:
                    value = vault_store.read(variable)
                except (vault.VaultError, OSError) as error:
                    logger.warning("the vault cannot be read: %s", error)
                    value = ""
            self._values[variable] = value
            vault.remember(value)
        return self._values[variable]

    def _secrets(self) -> list[str]:
        """Every value of the logins this session may use, read once."""
        found = []
        for name in self.logins:
            for _, suffix in vault_store.LOGIN_FIELDS:
                value = self._value(name + suffix)
                if value:
                    found.append(value)
        return found

    # -- the browser --------------------------------------------------------

    @property
    def page(self) -> Any:
        if self._page is None:
            self._start()
        return self._page

    def _start(self) -> None:
        if why := browser.missing():
            raise Refused(f"Ponos's browser is not installed here: {why}")
        sync_api = importlib.import_module("playwright.sync_api")
        self._playwright = sync_api.sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        state = browser.load(self.project) if self.project else None
        self._known_cookies = {
            "|".join(browser._cookie_key(c)) for c in (state or {}).get("cookies", [])
        }
        self._context = self._browser.new_context(
            storage_state=state, accept_downloads=True, viewport={"width": 1280, "height": 800}
        )
        self._context.set_default_timeout(LOADING)
        self._page = self._context.new_page()

    def keep(self) -> None:
        """What the context holds now, merged into the project's profile."""
        if self._context is None or not self.project:
            return
        try:
            state = self._context.storage_state()
        except Exception as error:  # noqa: BLE001 - a browser that went away: nothing to keep
            logger.warning("the browser's state could not be read: %s", error)
            return
        now = {"|".join(browser._cookie_key(cookie)) for cookie in state.get("cookies", [])}
        browser.save(self.project, state, self._known_cookies - now)
        self._known_cookies = now

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.keep()
        for done in (self._browser, self._playwright):
            if done is not None:
                with contextlib.suppress(Exception):
                    done.close() if done is self._browser else done.stop()
        for suffix in (".json", ".png", ".in", ".watch"):
            with contextlib.suppress(OSError):
                (browser.live_dir() / f"{self.identifier}{suffix}").unlink()

    def _settle(self) -> None:
        with contextlib.suppress(Exception):
            self.page.wait_for_load_state("networkidle", timeout=SETTLING)

    # -- what goes back to the model ---------------------------------------

    def masked(self, text: str) -> str:
        """`text` without a value of the vault, nor what a password field on the page holds."""
        for value in self._secrets():
            text = text.replace(value, vault.MASK)
        if self._page is not None:
            with contextlib.suppress(Exception):
                for typed in self._page.evaluate(_PASSWORDS):
                    text = text.replace(str(typed), vault.MASK)
        return vault.mask(text)

    def masked_safely(self, text: str) -> str:
        """`masked`, for an error that may have come from a browser that is gone."""
        for value in self._values.values():
            if value:
                text = text.replace(value, vault.MASK)
        return vault.mask(text)

    def screenshot(self, full_page: bool = False) -> bytes:
        page = self.page
        hidden = [page.locator("input[type=password]"), page.locator("[data-ponos-login]")]
        for value in self._secrets():
            hidden.append(page.get_by_text(value, exact=False))
        shot: bytes = page.screenshot(full_page=full_page, mask=hidden, animations="disabled")
        return shot

    def publish(self, force: bool = False) -> None:
        """Write the screen for the console's live view: when watched, or now and then."""
        if self._page is None:
            return
        folder = browser.live_dir()
        watched = folder / f"{self.identifier}.watch"
        try:
            looked = time.time() - watched.stat().st_mtime < 15
        except OSError:
            looked = False
        if not (force or looked or time.time() - self._screen_at > QUIET_SCREEN):
            return
        self._screen_at = time.time()
        disk.private_dir(folder)
        try:
            shot = self.screenshot()
            title = self.masked(self.page.title())
            url = self.masked(self.page.url)
        except Exception as error:  # noqa: BLE001 - a screen is never worth a tool's answer
            logger.warning("the live screen could not be taken: %s", error)
            return
        scratch = folder / f".{self.identifier}.png.tmp"
        with open(scratch, "wb", opener=disk.opener()) as handle:
            handle.write(shot)
        scratch.replace(folder / f"{self.identifier}.png")
        disk.write_atomic(
            folder / f"{self.identifier}.json",
            json.dumps(
                {
                    "project": self.project,
                    "ticket": self.ticket,
                    "url": url,
                    "title": title,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pid": os.getpid(),
                    "person": self.person,
                    "waiting": self.waiting,
                }
            ),
        )

    def console_actions(self) -> bool:
        """Play what the console sent since the last time; True when it asked to close."""
        source = browser.live_dir() / f"{self.identifier}.in"
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        fresh, self._commands_read = lines[self._commands_read :], len(lines)
        closing = False
        for line in fresh:
            try:
                action = json.loads(line)
            except ValueError:
                continue
            closing = self._play(action) or closing
        if fresh:
            self.publish(force=True)
            self.keep()
        return closing

    def _play(self, action: dict[str, Any]) -> bool:
        page = self.page
        kind = action.get("action")
        try:
            if kind == "click":
                page.mouse.click(float(action.get("x", 0)), float(action.get("y", 0)))
            elif kind == "type":
                page.keyboard.type(str(action.get("text", "")))
            elif kind == "press":
                page.keyboard.press(str(action.get("key", "Enter")))
            elif kind == "scroll":
                page.mouse.wheel(0, float(action.get("y", 400)))
            elif kind == "goto":
                page.goto(str(action.get("url", "")), wait_until="domcontentloaded")
            elif kind == "close":
                return True
        except Exception as error:  # noqa: BLE001 - whatever Playwright raises
            logger.warning("a console action failed: %s", error)
        self._settle()
        return False

    # -- the tools ----------------------------------------------------------

    def _locate(self, arguments: dict[str, Any]) -> Any:
        page = self.page
        if arguments.get("selector"):
            return page.locator(str(arguments["selector"])).first
        if arguments.get("role"):
            name = arguments.get("name")
            return page.get_by_role(str(arguments["role"]), name=name or None).first
        if arguments.get("label"):
            return page.get_by_label(str(arguments["label"])).first
        if arguments.get("text"):
            return page.get_by_text(str(arguments["text"])).first
        raise Refused("say which element: role and name, label, text or selector")

    def _where(self) -> str:
        return self.masked(f"{self.page.title()} — {self.page.url}")

    def call(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        handler = getattr(self, "tool_" + name.removeprefix("browser_"), None)
        if handler is None or not name.startswith("browser_"):
            raise Refused(f"no tool {name}")
        said = handler(arguments)
        self.publish(force=True)
        self.keep()
        if isinstance(said, bytes):
            return [
                {"type": "image", "data": base64.b64encode(said).decode(), "mimeType": "image/png"}
            ]
        return [{"type": "text", "text": self.masked(str(said))}]

    def tool_navigate(self, arguments: dict[str, Any]) -> str:
        url = str(arguments.get("url", "")).strip()
        if not browser.host(url):
            raise Refused("say which address to open")
        if "://" not in url:
            url = "https://" + url
        self.page.goto(url, wait_until="domcontentloaded")
        self._settle()
        return f"Opened: {self._where()}"

    def tool_read(self, arguments: dict[str, Any]) -> str:
        page = self.page
        if arguments.get("what") == "text":
            content = page.locator("body").inner_text()
        else:
            content = page.locator("body").aria_snapshot()
        content = self.masked(content)
        if len(content) > LONGEST:
            content = content[:LONGEST] + f"\n… (cut at {LONGEST} characters)"
        return f"{self._where()}\n\n{content}"

    def tool_click(self, arguments: dict[str, Any]) -> str:
        self._locate(arguments).click()
        self._settle()
        return f"Clicked. Now on: {self._where()}"

    def tool_type(self, arguments: dict[str, Any]) -> str:
        value = str(arguments.get("value", ""))
        bare = value.strip()
        for secret in self._secrets() + list(self._every_value()):
            if secret and (secret in value or (bare and bare == secret.strip())):
                raise Refused(
                    "refused: that is a value of the vault. Sign in with browser_login and the "
                    "entry's name; the browser fills it itself."
                )
        field = self._locate(arguments)
        field.fill(value)
        if arguments.get("submit"):
            field.press("Enter")
            self._settle()
        return f"Typed. Now on: {self._where()}"

    def _every_value(self) -> list[str]:
        """The values of every login the session's environment holds, granted here or not."""
        return [
            value
            for variable, value in os.environ.items()
            if variable.endswith(("_PASSWORD", "_USER")) and len(value) >= vault.SHORTEST
        ]

    def tool_press(self, arguments: dict[str, Any]) -> str:
        self.page.keyboard.press(str(arguments.get("key", "Enter")))
        self._settle()
        return f"Pressed. Now on: {self._where()}"

    def tool_screenshot(self, arguments: dict[str, Any]) -> bytes:
        return self.screenshot(bool(arguments.get("full_page")))

    def tool_download(self, arguments: dict[str, Any]) -> str:
        target = self._locate(arguments)
        with self.page.expect_download() as waited:
            target.click()
        download = waited.value
        self.downloads.mkdir(parents=True, exist_ok=True)
        kept = self.downloads / Path(download.suggested_filename).name
        download.save_as(str(kept))
        return f"Downloaded: {kept}"

    def tool_upload(self, arguments: dict[str, Any]) -> str:
        given = Path(str(arguments.get("path", "")))
        source = given if given.is_absolute() else self.downloads / given
        if not source.is_file():
            raise Refused(f"no such file: {source}")
        self._locate(arguments).set_input_files(str(source))
        self._settle()
        return f"Given {source.name}. Now on: {self._where()}"

    def tool_login(self, arguments: dict[str, Any]) -> str:
        entry = str(arguments.get("entry", "")).strip()
        result, said = self._login(entry, str(arguments.get("url", "") or "").strip())
        try:
            vault_store.signed_in(entry, self.ticket, self.project, result)
        except Exception as error:  # noqa: BLE001 - the journal never undoes a sign-in
            logger.warning("the vault's journal: %s", error)
        return said

    def _login(self, entry: str, url: str) -> tuple[str, str]:
        refused = vault_store.SIGN_IN_REFUSED
        failed = vault_store.SIGN_IN_FAILED
        if entry not in self.logins:
            granted = ", ".join(sorted(self.logins)) or "none"
            return refused, (
                f"refused: {entry!r} is not a login granted to this project (granted: {granted})."
            )
        site = self.logins[entry]
        if not site:
            return failed, (
                f"failed: the entry {entry} has no site address. Somebody has to give it one "
                "in Settings → Vault."
            )
        target = url or site
        if not browser.same_site(target, site):
            return refused, (
                f"refused: {browser.host(target)} is not the site of {entry} "
                f"({browser.host(site)}). A login is only typed on its own site."
            )
        user = self._value(entry + "_USER")
        password = self._value(entry + "_PASSWORD")
        if not user or not password:
            return failed, f"failed: the vault does not give {entry}'s user and password here."
        page = self.page
        page.goto(target if "://" in target else "https://" + target, wait_until="domcontentloaded")
        self._settle()
        if not browser.same_site(page.url, site):
            return refused, (
                f"refused: the sign-in page is on {browser.host(page.url)}, not on "
                f"{browser.host(site)}: nothing was typed."
            )
        found = page.evaluate(_PROBE)
        if found["captcha"]:
            return self._second_factor("a CAPTCHA")
        if not found["password"] and not found["user"]:
            self.keep()
            return vault_store.SIGNED_IN, (
                f"connected: no sign-in form on {self._where()} — already signed in."
            )
        if found["user"]:
            page.locator("[data-ponos-login=user]").fill(user)
            if not found["password"]:
                # A form in two steps: the address first, the password on the next screen.
                page.locator("[data-ponos-login=user]").press("Enter")
                self._settle()
                if not browser.same_site(page.url, site):
                    return refused, (
                        f"refused: the next step is on {browser.host(page.url)}, not on "
                        f"{browser.host(site)}: the password was not typed."
                    )
                found = page.evaluate(_PROBE)
                if found["captcha"]:
                    return self._second_factor("a CAPTCHA")
                if not found["password"]:
                    return failed, f"failed: no password field after the user on {self._where()}."
        page.locator("[data-ponos-login=password]").fill(password)
        page.locator("[data-ponos-login=password]").press("Enter")
        self._settle()
        with contextlib.suppress(Exception):
            page.wait_for_load_state("domcontentloaded")
        after = page.evaluate(_PROBE)
        text = ""
        with contextlib.suppress(Exception):
            text = page.locator("body").inner_text()[:5000]
        if after["captcha"] or (_CAPTCHA.search(text) and after["password"]):
            return self._second_factor("a CAPTCHA")
        if after["otp"] or (not after["password"] and _SECOND_FACTOR.search(text)):
            return self._second_factor("a second factor")
        if after["password"]:
            why = self.masked(after.get("errors") or "") or "the form is still there"
            return failed, f"failed: the site did not let the login in — {why}."
        self.keep()
        return vault_store.SIGNED_IN, f"connected: now on {self._where()}."

    def _second_factor(self, what: str) -> tuple[str, str]:
        self.waiting = what
        shot = ""
        with contextlib.suppress(Exception):
            self.downloads.mkdir(parents=True, exist_ok=True)
            target = self.downloads / "ponos-browser-sign-in.png"
            target.write_bytes(self.screenshot())
            shot = f" A screenshot is at {target}."
        self.keep()
        return vault_store.SECOND_FACTOR, (
            f"second factor requested: the site asks for {what}, which Ponos's browser never "
            f"answers.{shot} Stop here and end blocked (CATEGORY: manual): ask the person to "
            "finish signing in from the console — the project's settings, Browser, Sign in "
            "here — and to answer « done »; the session it opens stays in the project's profile."
        )


# -- the protocol ------------------------------------------------------------------


def _answer(identifier: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def handle(engine: Browser, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message, and what is sent back — None for a notification."""
    method = message.get("method")
    identifier = message.get("id")
    if identifier is None:
        return None
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion") or PROTOCOL
        return _answer(
            identifier,
            {
                "protocolVersion": asked,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": browser.SERVER, "version": "1"},
                "instructions": (
                    "Ponos's browser. Sign in with browser_login and the name of a login "
                    "entry; never type a password yourself."
                ),
            },
        )
    if method == "ping":
        return _answer(identifier, {})
    if method == "tools/list":
        return _answer(identifier, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            content = engine.call(str(params.get("name", "")), params.get("arguments") or {})
            return _answer(identifier, {"content": content, "isError": False})
        except Refused as error:
            said = str(error)
        except Exception as error:  # noqa: BLE001 - said to the model, which carries on
            said = f"{type(error).__name__}: {error}"
        return _answer(
            identifier,
            {"content": [{"type": "text", "text": engine.masked_safely(said)}], "isError": True},
        )
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {"code": -32601, "message": f"no method {method}"},
    }


def serve(engine: Browser) -> None:
    """Answer on stdin and stdout until the session closes it; play the console between."""
    buffered = b""
    stdin = sys.stdin.fileno()
    try:
        while True:
            ready, _, _ = select.select([stdin], [], [], 1.0)
            if not ready:
                if engine._page is not None:
                    engine.console_actions()
                    engine.publish()
                continue
            chunk = os.read(stdin, 1 << 16)
            if not chunk:
                return
            buffered += chunk
            while b"\n" in buffered:
                line, buffered = buffered.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                reply = handle(engine, message)
                if reply is not None:
                    sys.stdout.write(json.dumps(reply) + "\n")
                    sys.stdout.flush()
    finally:
        engine.close()


def assist(engine: Browser, url: str) -> None:
    """A browser for a person, driven from the console until they close it or leave it."""
    try:
        engine.page.goto(url if "://" in url else "https://" + url, wait_until="domcontentloaded")
        engine.publish(force=True)
        last = time.time()
        while time.time() - last < browser.PERSON_IDLE:
            time.sleep(0.5)
            before = engine._commands_read
            if engine.console_actions():
                return
            if engine._commands_read != before:
                last = time.time()
            engine.publish()
    finally:
        engine.close()


def main(arguments: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if arguments[:1] == ["--person"] and len(arguments) == 2:
        assist(Browser(person=True), arguments[1])
        return 0
    serve(Browser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
