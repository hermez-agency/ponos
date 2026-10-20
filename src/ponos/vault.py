"""The keys a ticket's session works with, and the one rule that goes with them.

A ticket that publishes a package or redeploys a service needs a token, and the
only place it could be given used to be the ticket itself — which is a Notion
page, a prompt, a transcript and a pull request description, all at once. So a
secret is never written anywhere Ponos reads from. It stays where it already
lives — the GNOME keyring, `pass`, Bitwarden, the environment — and `[vault]`
says, project by project, which of them a session may have: a Leadz ticket is
given Leadz's keys and nobody else's. They reach the session as environment
variables, by name, and the prompt tells it the names and never the values.

Every adapter is a command the machine already has (`secret-tool`, `pass`,
`bw`) rather than a library: the runner imports nothing it did not ship with,
and a fifth provider — 1Password's `op read`, say — is one class and one line
in `PROVIDERS`.

The other half is that a value read is a value **masked**. A session handed a
token may still print it — an `npm whoami --verbose`, an `env` to debug a
failing deploy — and what it prints travels into its transcript, the steps
written live into the ticket, the comment that closes it, the console and the
phone. Each of those has one door everything goes through (`session.run`,
`notion.Client._request`, the Markdown board's writer, a channel's request, the
console's JSON), and `mask` stands in it: every value this process has read is
replaced by `***` before it goes out. Masked by value rather than by name,
because what leaks is never `$NPM_TOKEN`, it is what it expands to.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# What a value is replaced with, wherever it would have been written.
MASK = "***"

# Below this, a value is not masked: replacing every "1234" in a transcript
# would mask the code rather than the key. A secret that short is no token
# either, so it is not handed to a session at all — see `Grant.read`.
SHORTEST = 6

# How long a provider is given to answer. A keyring that pops an unlock dialog
# nobody is in front of, or a `pass` whose pinentry waits for a passphrase,
# would otherwise hold a ticket for ever.
TIMEOUT = 20

# An environment variable a shell accepts.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class VaultError(Exception):
    """A provider that cannot be asked: missing, locked, or refusing."""


class SecretProvider(Protocol):
    """Where secrets are read from — one item by its name, nothing else.

    `read` hands back the value, or "" when the provider has no such item, and
    raises VaultError when it cannot be asked at all: the two are told apart in
    what the runner says, because "no such key" is fixed in the vault and "the
    vault is locked" is fixed on the machine.
    """

    name: str

    def read(self, item: str) -> str: ...

    def available(self) -> str:
        """Why this provider cannot be used here, or "" when it can."""
        ...


def _command(arguments: list[str], environment: dict[str, str] | None = None) -> str:
    """What a provider's command printed, or "" when it says it has no such item."""
    try:
        done = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **(environment or {})},
        )
    except FileNotFoundError as error:
        raise VaultError(f"{arguments[0]} is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise VaultError(f"{arguments[0]} did not answer in {TIMEOUT}s — locked?") from error
    if done.returncode != 0:
        # The command's own words, which never hold the value — it was not found.
        raise VaultError(f"{arguments[0]}: {done.stderr.strip()[:200] or done.returncode}")
    return done.stdout


@dataclass
class Environment:
    """The environment the runner was started with, then `secrets.env`.

    The provider that needs nothing installed: a container is given its keys
    by its compose file, and a machine by the same file the runner's own
    secrets are kept in.
    """

    stored: dict[str, str]
    name: str = "env"

    def read(self, item: str) -> str:
        return os.environ.get(item) or self.stored.get(item, "")

    def available(self) -> str:
        return ""


@dataclass
class Keyring:
    """The GNOME keyring — any Secret Service — through `secret-tool`.

    An item is found by its attributes. A bare name is `service ponos username
    <name>`, which is what Python's `keyring` writes too; `attribute=value`
    pairs, separated by spaces, look up anything else already in the keyring.
    """

    name: str = "keyring"

    def read(self, item: str) -> str:
        if "=" in item:
            pairs = [part.split("=", 1) for part in item.split()]
            attributes = [word for pair in pairs for word in pair]
        else:
            attributes = ["service", "ponos", "username", item]
        try:
            return _command(["secret-tool", "lookup", *attributes]).rstrip("\n")
        except VaultError as error:
            # `secret-tool lookup` says nothing and exits 1 for an item it lacks.
            if str(error) == "secret-tool: 1":
                return ""
            raise

    def available(self) -> str:
        return (
            "" if shutil.which("secret-tool") else "secret-tool is not installed (libsecret-tools)"
        )


@dataclass
class Pass:
    """`pass`, the standard Unix password manager: the first line of an entry."""

    name: str = "pass"

    def read(self, item: str) -> str:
        try:
            shown = _command(["pass", "show", item])
        except VaultError as error:
            if "is not in the password store" in str(error):
                return ""
            raise
        return shown.split("\n", 1)[0]

    def available(self) -> str:
        return "" if shutil.which("pass") else "pass is not installed"


@dataclass
class Bitwarden:
    """The Bitwarden CLI: an item's password, by its name or its id.

    `bw` answers only once unlocked, with `BW_SESSION` set — in the runner's
    environment or in `secrets.env`, where `bw unlock --raw` puts it.
    """

    stored: dict[str, str]
    name: str = "bitwarden"

    def read(self, item: str) -> str:
        session = os.environ.get("BW_SESSION") or self.stored.get("BW_SESSION", "")
        if not session:
            raise VaultError("bw is locked: no BW_SESSION (bw unlock --raw)")
        try:
            return _command(
                ["bw", "get", "password", item, "--nointeraction"], {"BW_SESSION": session}
            ).strip()
        except VaultError as error:
            if "Not found" in str(error):
                return ""
            raise

    def available(self) -> str:
        return "" if shutil.which("bw") else "bw is not installed (Bitwarden CLI)"


# Every provider `[vault]` may name. Adding one is a class above and a line here.
PROVIDERS: dict[str, Any] = {
    "env": Environment,
    "keyring": Keyring,
    "pass": Pass,
    "bitwarden": Bitwarden,
}


def provider(name: str, stored: dict[str, str] | None = None) -> SecretProvider:
    """The provider of that name, ready to be asked. Raises VaultError for none."""
    kind = PROVIDERS.get(name)
    if kind is None:
        raise VaultError(f"no secret provider called {name!r} ({', '.join(PROVIDERS)})")
    if kind in (Environment, Bitwarden):
        return kind(stored or {})
    return kind()


def where(item: str, default: str) -> tuple[str, str]:
    """The provider and the item an entry names: `pass:hermez/npm`, or just `hermez/npm`.

    A prefix is read as a provider only when it is one — a keyring attribute or
    a Bitwarden item may well hold a colon of its own.
    """
    prefix, colon, rest = item.partition(":")
    if colon and prefix in PROVIDERS and rest:
        return prefix, rest
    return default, item


def problems(variable: str, item: str, reserved: set[str]) -> str:
    """Why `[vault]` cannot hand that variable over, or "" when it can."""
    if not _NAME.match(variable):
        return f"{variable!r} is not an environment variable name"
    if variable in reserved or variable.startswith("PONOS_"):
        return f"{variable} is the runner's own, and is not handed to a project"
    if not item.strip():
        return f"{variable} names no item to read"
    return ""


@dataclass
class Read:
    """What a project's session is given, and what could not be read."""

    values: dict[str, str]
    missing: list[str]


def read(granted: dict[str, str], default: str, stored: dict[str, str] | None = None) -> Read:
    """Every secret a project is granted, read — and remembered, to be masked.

    A secret that cannot be read is left out and said, never a reason to stop
    the ticket: the session is told only the names it has, and a ticket that
    needed the missing one says so in its own words.
    """
    values: dict[str, str] = {}
    missing: list[str] = []
    for variable, entry in granted.items():
        which, item = where(entry, default)
        try:
            value = provider(which, stored).read(item)
        except VaultError as error:
            missing.append(f"{variable} ({which}: {error})")
            continue
        if len(value) < SHORTEST:
            missing.append(
                f"{variable} ({which}: "
                + ("no such item" if not value else "too short to be masked")
                + ")"
            )
            continue
        remember(value)
        values[variable] = value
    return Read(values, missing)


# -- masking -----------------------------------------------------------------

_known: set[str] = set()
_lock = threading.Lock()
# The forms each value is looked for under, longest first — so that a secret
# that contains another is masked whole.
_forms: tuple[str, ...] = ()


def remember(value: str) -> None:
    """Mask this value from now on, wherever this process writes."""
    global _forms
    if len(value) < SHORTEST:
        return
    with _lock:
        if value in _known:
            return
        _known.add(value)
        # As it is, and as JSON writes it: a transcript is JSON lines, and a
        # value with a quote or a backslash in it is not spelled the same there.
        forms = set(_known) | {json.dumps(known)[1:-1] for known in _known}
        _forms = tuple(sorted(forms, key=len, reverse=True))


def forget() -> None:
    """Mask nothing any more — for the tests, which read values of their own."""
    global _forms
    with _lock:
        _known.clear()
        _forms = ()


def mask(text: str) -> str:
    """`text` with every value this process has read replaced by `***`."""
    for form in _forms:
        if form in text:
            text = text.replace(form, MASK)
    return text


def masked(value: Any) -> Any:
    """The same, through a JSON-shaped value: dicts, lists and the strings in them."""
    if not _forms:
        return value
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {key: masked(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [masked(item) for item in value]
    return value


def scrub(path: Path) -> None:
    """Mask a file another process wrote — a session's stderr — in place."""
    if not _forms:
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    cleaned = mask(text)
    if cleaned != text:
        try:
            path.write_text(cleaned, encoding="utf-8")
        except OSError:
            pass
