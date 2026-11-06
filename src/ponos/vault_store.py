"""Ponos's own vault: the keys typed into Context → Vault, kept encrypted.

`[vault]` reads keys where they already live — the keyring, `pass`, Bitwarden
— and on most machines none of them is installed: every key ended up in the
environment or in `secrets.env`, in clear. This is the place that needs
nothing installed, and keeps nothing in clear: `vault.db`, in the state
directory, `0600`, where each entry is sealed on its own with AES-256-GCM.

What is sealed with what:

- **A nonce of 96 random bits per write**, drawn by `secrets.token_bytes`, as
  GCM requires: a nonce used twice under one key gives both plaintexts away.
- **The entry's identity as associated data** — its id, name, kind, the
  projects it is granted to and its address. A sealed value copied onto
  another row, a project added to a row by hand, or an address changed there,
  no longer opens: GCM refuses the tag, and nobody with write access to the
  file alone can hand a key to a project, nor send a login to another site.
- **A master key of 32 bytes from `secrets.token_bytes`**, never derived from
  a passphrase, and never stored beside the data. It lives, in this order of
  preference, in the system keyring (`secret-tool`), in `PONOS_VAULT_KEY` (a
  unit file, Dokploy), or in `vault.key` under the configuration directory —
  apart from `vault.db`, which `ponos doctor` still warns about: a backup that
  takes both takes everything.

Nothing here is cryptography of its own: `AESGCM` from `cryptography`, which
the console's push already brought in, imported when a value is sealed or
opened — a pass that never touches this vault never imports it.

What this protects: a copy of `vault.db` alone (a backup, a volume moved), and
every place the runner writes — what is read goes through `vault.remember`,
so its value is masked. What it does not: somebody with the Unix account that
runs Ponos, who can read the key wherever it is kept and ask the runner itself.

The journal (`journal` table) says who did what to an entry — created,
replaced, its projects or its address changed, revoked — and every time a session was given
it, with the ticket and the project; never a value. Ponos's browser writes
there too, each time it signs in with a login (`signed_in`): the entry, the
ticket, the project and how it ended.

Any entry may carry an address (`url`): where a login signs in, where a token
is managed or renewed. It is no secret — kept in clear, beside the name — but
it is sealed with the value all the same: for a login it is what Ponos's
browser signs in on, and the only site it ever types that login into (see
browser.py). A session given the entry is given it too, as `<NAME>_URL`
(`addresses`), unmasked: a site's address in a transcript gives nothing away.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from . import config as config_module
from . import vault

# The variable a container or a unit file gives the key in.
VAULT_KEY_ENV = config_module.VAULT_KEY_ENV

# The bytes of a key, and of a nonce: AES-256, and GCM's own 96 bits.
KEY_BYTES = 32
NONCE_BYTES = 12

# What an entry holds, and the variables it becomes in a session.
TOKEN, LOGIN, NOTE = "token", "login", "note"
KINDS = (TOKEN, LOGIN, NOTE)
LOGIN_FIELDS = (("user", "_USER"), ("password", "_PASSWORD"))
# The variable an entry's address is given in, beside its own.
ADDRESS = "_URL"

# A value shorter than this has no fingerprint at all: four characters of an
# eight-character password are half of it.
PRINTED_FROM = 12
PRINTED = 4

# How close an expiry is before `ponos doctor` says so.
EXPIRING_DAYS = 14

# The keyring item the master key is kept under, and the one a rotation writes
# first, so that a rotation cut short leaves a key that opens the vault.
_KEYRING = ("service", "ponos-vault", "key")
_MASTER, _PENDING = "master", "pending"

# What the vault's own check is sealed under: a value nobody reads, that tells
# a wrong key from a right one before any entry is opened. Its associated data
# says how the entries are sealed: `check:2` since an entry's address is part of
# what it is sealed with, `check` before — see `_bind_addresses`.
_CHECK = b"ponos-vault-check"
_CHECKED, _CHECKED_BEFORE = b"check:2", b"check"

_lock = threading.RLock()


class VaultStoreError(vault.VaultError):
    """The vault cannot be opened: no key, a wrong one, or a file refused."""


class Refused(ValueError):
    """A write the vault will not make, said under the field it is about."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def path() -> Path:
    return config_module.state_dir() / "vault.db"


def key_path() -> Path:
    """`vault.key`: beside the configuration, never in the state directory with `vault.db`."""
    return config_module.config_dir() / "vault.key"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# -- the master key ------------------------------------------------------------


@dataclass
class Key:
    raw: bytes
    # "keyring", "env" or "file" — and where, as a person would look for it.
    source: str
    where: str


def keyring_usable() -> bool:
    """`secret-tool` is installed — whether the keyring answers is asked next."""
    return shutil.which("secret-tool") is not None


def _secret_tool(arguments: list[str], given: str | None = None) -> str | None:
    """What `secret-tool` printed, or None when it could not answer."""
    try:
        done = subprocess.run(
            ["secret-tool", *arguments],
            input=given,
            capture_output=True,
            text=True,
            timeout=vault.TIMEOUT,
            stdin=None if given is not None else subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decoded(text: str) -> bytes:
    """A key as it is written — URL-safe base64, or hexadecimal — or VaultStoreError."""
    text = text.strip()
    try:
        raw = bytes.fromhex(text) if len(text) == 2 * KEY_BYTES else b""
    except ValueError:
        raw = b""
    if not raw:
        try:
            raw = base64.urlsafe_b64decode(
                text.replace("+", "-").replace("/", "_") + "=" * (-len(text) % 4)
            )
        except (ValueError, binascii.Error):
            raw = b""
    if len(raw) != KEY_BYTES:
        raise VaultStoreError(f"a vault key is {KEY_BYTES} bytes, base64 or hex")
    return raw


def _keyring_read(which: str) -> bytes | None:
    if not keyring_usable():
        return None
    shown = _secret_tool(["lookup", *_KEYRING, which])
    if not shown or not shown.strip():
        return None
    try:
        return decoded(shown)
    except VaultStoreError:
        return None


def _keyring_write(which: str, raw: bytes) -> bool:
    label = "Ponos vault key" + ("" if which == _MASTER else f" ({which})")
    return (
        _secret_tool(["store", f"--label={label}", *_KEYRING, which], given=_encoded(raw))
        is not None
    )


def _keyring_clear(which: str) -> None:
    _secret_tool(["clear", *_KEYRING, which])


def _file_read(target: Path) -> bytes | None:
    try:
        return decoded(target.read_text(encoding="utf-8"))
    except OSError:
        return None


def _file_write(target: Path, raw: bytes) -> None:
    from .disk import write_atomic  # 0600 from the first byte

    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, _encoded(raw) + "\n")


def _pending_path() -> Path:
    return key_path().with_name("vault.key.pending")


def _found() -> Key | None:
    """The key that is there, in the order of preference — or None."""
    raw = _keyring_read(_MASTER)
    if raw:
        return Key(raw, "keyring", "the system keyring (secret-tool, service ponos-vault)")
    given = os.environ.get(VAULT_KEY_ENV, "").strip()
    if given:
        return Key(decoded(given), "env", f"the {VAULT_KEY_ENV} environment variable")
    raw = _file_read(key_path())
    if raw:
        return Key(raw, "file", str(key_path()))
    return None


def _pending(source: str) -> bytes | None:
    """A key a rotation wrote before it rewrote the vault, and did not get to promote."""
    if source == "keyring":
        return _keyring_read(_PENDING)
    if source == "file":
        return _file_read(_pending_path())
    return None


def _drawn() -> Key:
    """A key drawn now, for a vault that has none yet: the keyring first, else the file."""
    import secrets

    raw = secrets.token_bytes(KEY_BYTES)
    if keyring_usable() and _keyring_write(_MASTER, raw) and _keyring_read(_MASTER) == raw:
        return Key(raw, "keyring", "the system keyring (secret-tool, service ponos-vault)")
    _file_write(key_path(), raw)
    return Key(raw, "file", str(key_path()))


def whereabouts() -> dict[str, str]:
    """Where the key is kept, as the page and `doctor` say it — never the key."""
    try:
        found = _found()
    except VaultStoreError as error:
        return {"source": "env", "where": f"{VAULT_KEY_ENV}: {error}"}
    if found is None:
        return {"source": "", "where": ""}
    return {"source": found.source, "where": found.where}


# -- sealing -------------------------------------------------------------------


def _aesgcm(raw: bytes) -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as error:  # an environment made before cryptography came in
        raise VaultStoreError("the cryptography package is not installed") from error
    return AESGCM(raw)


def _associated(identifier: str, name: str, kind: str, projects: list[str], url: str = "") -> bytes:
    """What a sealed value is bound to: the entry it was written for, who may read it, and where."""
    return "\n".join(
        ["ponos-vault:2", identifier, name, kind, ",".join(sorted(projects)), url]
    ).encode()


def _associated_before(identifier: str, name: str, kind: str, projects: list[str]) -> bytes:
    """The same, as a vault sealed it before an entry's address was part of it."""
    return "\n".join(["ponos-vault:1", identifier, name, kind, ",".join(sorted(projects))]).encode()


def _bound(row: sqlite3.Row) -> bytes:
    """The associated data of a row as it is in the file."""
    return _associated(row["id"], row["name"], row["kind"], _projects(row), row["url"])


def _seal(raw: bytes, plain: bytes, associated: bytes) -> tuple[bytes, bytes]:
    import secrets

    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce, _aesgcm(raw).encrypt(nonce, plain, associated)


def _open(raw: bytes, nonce: bytes, sealed: bytes, associated: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag

    try:
        opened: bytes = _aesgcm(raw).decrypt(nonce, sealed, associated)
    except InvalidTag as error:
        raise VaultStoreError("an entry of the vault was changed, or moved: refused") from error
    return opened


# -- the file --------------------------------------------------------------------


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    projects TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    expires TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    print TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    nonce BLOB NOT NULL,
    sealed BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL,
    name TEXT NOT NULL,
    action TEXT NOT NULL,
    by TEXT NOT NULL DEFAULT '',
    ticket TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_entry ON journal (entry, id);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    nonce BLOB NOT NULL,
    sealed BLOB NOT NULL
);
"""


def exists() -> bool:
    return path().is_file()


@contextmanager
def _connected(create: bool = True) -> Iterator[sqlite3.Connection]:
    target = path()
    if not target.exists():
        if not create:
            raise FileNotFoundError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 0600 before SQLite writes a byte into it.
        os.close(os.open(target, os.O_CREAT | os.O_WRONLY, 0o600))
    connection = sqlite3.connect(target, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        # The rollback journal SQLite writes beside it is deleted, never kept,
        # and takes the file's own mode.
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA secure_delete=ON")
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)")}
        if "url" not in columns:
            # A vault written before an entry could say which site it is for.
            connection.execute("ALTER TABLE entries ADD COLUMN url TEXT NOT NULL DEFAULT ''")
        written = {row[1] for row in connection.execute("PRAGMA table_info(journal)")}
        if "detail" not in written:
            # A journal written before it said what an entry's address became.
            connection.execute("ALTER TABLE journal ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
        with connection:
            yield connection
    finally:
        connection.close()


def _key(connection: sqlite3.Connection, create: bool) -> Key:
    """The key that opens this vault — drawn for a vault that never had one."""
    check = connection.execute("SELECT nonce, sealed FROM meta WHERE key = 'check'").fetchone()
    found = _found()
    if check is None:
        if found is None:
            if not create:
                raise VaultStoreError("the vault has no key yet")
            found = _drawn()
        nonce, sealed = _seal(found.raw, _CHECK, _CHECKED)
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, nonce, sealed) VALUES ('check', ?, ?)",
            (nonce, sealed),
        )
        return found
    if found is None:
        raise VaultStoreError(
            "the vault's key is missing: neither the keyring, "
            f"{VAULT_KEY_ENV} nor {key_path()} holds it"
        )
    for raw in (found.raw, _pending(found.source)):
        if raw is None:
            continue
        for checked in (_CHECKED, _CHECKED_BEFORE):
            try:
                _open(raw, check["nonce"], check["sealed"], checked)
            except VaultStoreError:
                continue
            if raw != found.raw:
                # A rotation that rewrote the vault and stopped before it kept its key.
                _keep(found.source, raw)
            if checked == _CHECKED_BEFORE:
                _bind_addresses(connection, raw)
            return Key(raw, found.source, found.where)
    raise VaultStoreError(f"the key in {found.where} does not open this vault")


def _bind_addresses(connection: sqlite3.Connection, raw: bytes) -> None:
    """Every entry sealed again with its address, once, the first time the vault is opened.

    The check is sealed again last, in the same transaction: from then on an
    entry opens under its address only, and a vault cannot be taken back to
    the old way by hand — the check would not open under it without the key.
    An entry that does not open the old way stays as it is, and is refused as
    it was before.
    """
    for row in connection.execute("SELECT * FROM entries").fetchall():
        try:
            plain = _open(
                raw,
                row["nonce"],
                row["sealed"],
                _associated_before(row["id"], row["name"], row["kind"], _projects(row)),
            )
        except VaultStoreError:
            continue
        nonce, sealed = _seal(raw, plain, _bound(row))
        connection.execute(
            "UPDATE entries SET nonce = ?, sealed = ? WHERE id = ?", (nonce, sealed, row["id"])
        )
    nonce, sealed = _seal(raw, _CHECK, _CHECKED)
    connection.execute("UPDATE meta SET nonce = ?, sealed = ? WHERE key = 'check'", (nonce, sealed))


def _keep(source: str, raw: bytes) -> None:
    """`raw` as the master key, where the old one was kept."""
    if source == "keyring":
        if not _keyring_write(_MASTER, raw):
            raise VaultStoreError("the keyring refused the new key")
        _keyring_clear(_PENDING)
    elif source == "file":
        _file_write(key_path(), raw)
        _pending_path().unlink(missing_ok=True)


# -- the entries -----------------------------------------------------------------


def variables(name: str, kind: str) -> list[str]:
    """The variables an entry becomes in a session: its name, or `<NAME>_USER` and `<NAME>_PASSWORD`."""
    if kind == LOGIN:
        return [name + suffix for _, suffix in LOGIN_FIELDS]
    return [name]


def address_variable(name: str) -> str:
    """The variable an entry's address is given in: `<NAME>_URL`, whatever its kind."""
    return name + ADDRESS


def _names(name: str, kind: str) -> set[str]:
    """Every variable an entry may give, its address's included — what no other entry may take."""
    return {*variables(name, kind), address_variable(name)}


def fingerprint(value: str) -> str:
    """The end of a value, to tell two apart — nothing for a short one."""
    value = value.strip()
    if len(value) < PRINTED_FROM:
        return ""
    return "…" + value[-PRINTED:]


def reserved() -> set[str]:
    """The variables that are the runner's own, and never an entry's name."""
    return config_module.reserved_variables()


def _projects(row: sqlite3.Row) -> list[str]:
    listed: list[str] = json.loads(row["projects"])
    return listed


def _shown(row: sqlite3.Row, last: dict[str, dict[str, str]]) -> dict[str, Any]:
    """An entry as the page and the CLI list it: everything but its value."""
    used = last.get(row["id"], {})
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "variables": variables(row["name"], row["kind"]),
        "projects": _projects(row),
        "description": row["description"],
        "expires": row["expires"],
        "created": row["created"],
        "updated": row["updated"],
        "print": row["print"],
        "url": row["url"],
        "url_variable": address_variable(row["name"]) if row["url"] else "",
        "last_used": used.get("at", ""),
        "last_ticket": used.get("ticket", ""),
        "last_project": used.get("project", ""),
    }


def _last_reads(connection: sqlite3.Connection) -> dict[str, dict[str, str]]:
    rows = connection.execute(
        "SELECT entry, at, ticket, project FROM journal WHERE id IN "
        "(SELECT MAX(id) FROM journal WHERE action = 'read' GROUP BY entry)"
    ).fetchall()
    return {row["entry"]: dict(row) for row in rows}


def listing() -> list[dict[str, Any]]:
    """Every entry, by name, without its value — nothing is created for a vault never used."""
    if not exists():
        return []
    with _lock, _connected() as connection:
        last = _last_reads(connection)
        rows = connection.execute("SELECT * FROM entries ORDER BY name").fetchall()
        return [_shown(row, last) for row in rows]


def history(identifier: str) -> list[dict[str, Any]]:
    """What happened to one entry, newest first."""
    if not exists():
        raise LookupError("no such entry in the vault")
    with _lock, _connected() as connection:
        if not connection.execute("SELECT 1 FROM entries WHERE id = ?", (identifier,)).fetchone():
            raise LookupError("no such entry in the vault")
        rows = connection.execute(
            "SELECT action, by, ticket, project, detail, at FROM journal WHERE entry = ? "
            "ORDER BY id DESC LIMIT 200",
            (identifier,),
        ).fetchall()
        return [dict(row) for row in rows]


def _write_down(
    connection: sqlite3.Connection,
    row: dict[str, Any] | sqlite3.Row,
    action: str,
    by: str = "",
    ticket: str = "",
    project: str = "",
    detail: str = "",
) -> None:
    connection.execute(
        "INSERT INTO journal (entry, name, action, by, ticket, project, detail, at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["name"], action, by, ticket, project, detail, _now()),
    )


def _checked_name(name: str, kind: str, connection: sqlite3.Connection, but: str = "") -> str:
    name = name.strip()
    if not vault._NAME.match(name):
        raise Refused("name", f"{name!r} is not an environment variable name")
    taken = reserved()
    mine = _names(name, kind)
    for variable in sorted(mine):
        if variable in taken or variable.startswith("PONOS_"):
            raise Refused("name", f"{variable} is the runner's own, and is not handed to a project")
    for other in connection.execute("SELECT id, name, kind FROM entries").fetchall():
        if other["id"] != but and mine & _names(other["name"], other["kind"]):
            raise Refused("name", f"the vault already gives {other['name']} under that name")
    return name


def _checked_values(kind: str, values: dict[str, str]) -> dict[str, str]:
    """The fields an entry of `kind` is written with, each long enough to be masked."""
    fields = [field for field, _ in LOGIN_FIELDS] if kind == LOGIN else ["value"]
    kept: dict[str, str] = {}
    for field in fields:
        value = values.get(field, "")
        # A key pasted with its newline: kept without, as every provider reads it.
        value = value.strip("\n") if kind == NOTE else value.strip()
        if len(value) < vault.SHORTEST:
            raise Refused(
                field,
                f"at least {vault.SHORTEST} characters: shorter, it could not be masked "
                "where a session writes it",
            )
        kept[field] = value
    return kept


def _checked_expiry(expires: str) -> str:
    expires = expires.strip()
    if not expires:
        return ""
    try:
        return date.fromisoformat(expires[:10]).isoformat()
    except ValueError:
        raise Refused("expires", f"{expires!r} is not a date (YYYY-MM-DD)") from None


# The longest address an entry keeps.
URL_LENGTH = 500
# A scheme written before the address — `https:`, `javascript:` — and not a host's port.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)")


def _checked_url(url: str) -> str:
    """The address of the site an entry is for: http(s) and a host, or nothing.

    A bare host is read as `https://` it, as a browser's address bar reads it;
    any other scheme — `javascript:`, `file:`, `ftp:` — is refused, since the
    console makes the address a link.
    """
    from urllib.parse import urlsplit

    url = url.strip()
    if not url:
        return ""
    if not _SCHEME.match(url):
        url = "https://" + url
    refused = Refused("url", f"{url!r} is not the address of a site (https://…)")
    if len(url) > URL_LENGTH or any(character.isspace() for character in url):
        raise refused
    try:
        parts = urlsplit(url)
        hostname, _ = parts.hostname, parts.port
    except ValueError:
        raise refused from None
    if parts.scheme.lower() not in ("http", "https") or not hostname:
        raise refused
    return url


def _checked_projects(projects: list[str]) -> list[str]:
    return sorted({project.strip() for project in projects if project.strip()}, key=str.casefold)


def _plain(name: str, kind: str, values: dict[str, str]) -> bytes:
    if kind == LOGIN:
        held = {name + suffix: values[field] for field, suffix in LOGIN_FIELDS}
    else:
        held = {name: values["value"]}
    return json.dumps(held, ensure_ascii=False).encode()


def _print_of(kind: str, values: dict[str, str]) -> str:
    if kind == NOTE:
        return ""
    return fingerprint(values["password"] if kind == LOGIN else values["value"])


def create(
    name: str,
    kind: str,
    values: dict[str, str],
    projects: list[str],
    description: str = "",
    expires: str = "",
    by: str = "",
    url: str = "",
) -> dict[str, Any]:
    """A new entry, sealed — and said without its value."""
    if kind not in KINDS:
        raise Refused("kind", f"an entry is one of {', '.join(KINDS)}")
    with _lock, _connected() as connection:
        name = _checked_name(name, kind, connection)
        kept = _checked_values(kind, values)
        row: dict[str, Any] = {
            "id": uuid.uuid4().hex[:16],
            "name": name,
            "kind": kind,
            "projects": _checked_projects(projects),
            "description": description.strip()[:500],
            "expires": _checked_expiry(expires),
            "url": _checked_url(url),
            "created": _now(),
        }
        key = _key(connection, create=True)
        nonce, sealed = _seal(
            key.raw,
            _plain(name, kind, kept),
            _associated(row["id"], name, kind, row["projects"], row["url"]),
        )
        connection.execute(
            "INSERT INTO entries (id, name, kind, projects, description, expires, created, "
            "updated, print, url, nonce, sealed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                name,
                kind,
                json.dumps(row["projects"]),
                row["description"],
                row["expires"],
                row["created"],
                row["created"],
                _print_of(kind, kept),
                row["url"],
                nonce,
                sealed,
            ),
        )
        _write_down(connection, row, "created", by)
        written = connection.execute("SELECT * FROM entries WHERE id = ?", (row["id"],)).fetchone()
        return _shown(written, {})


def _row(connection: sqlite3.Connection, identifier: str) -> sqlite3.Row:
    found = connection.execute(
        "SELECT * FROM entries WHERE id = ? OR name = ?", (identifier, identifier)
    ).fetchone()
    if found is None:
        raise LookupError("no such entry in the vault")
    row: sqlite3.Row = found
    return row


def change(
    identifier: str,
    values: dict[str, str] | None = None,
    projects: list[str] | None = None,
    description: str | None = None,
    expires: str | None = None,
    by: str = "",
    url: str | None = None,
) -> dict[str, Any]:
    """An entry's value replaced, its projects changed, or what it says of itself.

    A change of projects seals the value again: who may read it is part of
    what it is sealed with.
    """
    if not exists():
        raise LookupError("no such entry in the vault")
    with _lock, _connected() as connection:
        row = _row(connection, identifier)
        kind, name = row["kind"], row["name"]
        was = _projects(row)
        now = was if projects is None else _checked_projects(projects)
        address = row["url"] if url is None else _checked_url(url)
        said = row["description"] if description is None else description.strip()[:500]
        ends = row["expires"] if expires is None else _checked_expiry(expires)
        key = _key(connection, create=False)
        # Read again after `_key`, which may have sealed every entry anew.
        row = _row(connection, row["id"])
        if values:
            kept = _checked_values(kind, values)
            plain = _plain(name, kind, kept)
            printed = _print_of(kind, kept)
        else:
            plain = _open(key.raw, row["nonce"], row["sealed"], _bound(row))
            printed = row["print"]
        nonce, sealed = _seal(key.raw, plain, _associated(row["id"], name, kind, now, address))
        connection.execute(
            "UPDATE entries SET projects = ?, description = ?, expires = ?, updated = ?, "
            "print = ?, url = ?, nonce = ?, sealed = ? WHERE id = ?",
            (json.dumps(now), said, ends, _now(), printed, address, nonce, sealed, row["id"]),
        )
        if values:
            _write_down(connection, row, "replaced", by)
        if now != was:
            _write_down(connection, row, "projects", by, project=", ".join(now))
        if address != row["url"]:
            _write_down(connection, row, "url", by, detail=address)
        described = (said, ends) != (row["description"], row["expires"])
        if described or not (values or now != was or address != row["url"]):
            _write_down(connection, row, "described", by)
        written = connection.execute("SELECT * FROM entries WHERE id = ?", (row["id"],)).fetchone()
        return _shown(written, _last_reads(connection))


def revoke(identifier: str, by: str = "") -> dict[str, Any]:
    """An entry gone for good: its sealed value overwritten, its journal kept."""
    if not exists():
        raise LookupError("no such entry in the vault")
    with _lock, _connected() as connection:
        row = _row(connection, identifier)
        shown = _shown(row, _last_reads(connection))
        connection.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
        # `secure_delete` zeroes the pages it was on: the sealed bytes do not
        # wait in the free list for a backup to take them.
        _write_down(connection, row, "revoked", by)
    return shown


def problem() -> str:
    """Why the vault cannot be opened now, or "" when it can — or holds nothing yet."""
    if not exists():
        return ""
    try:
        with _lock, _connected() as connection:
            if connection.execute("SELECT 1 FROM meta WHERE key = 'check'").fetchone():
                _key(connection, create=False)
    except (vault.VaultError, sqlite3.Error, OSError) as error:
        return str(error)
    return ""


def granted(project: str) -> dict[str, str]:
    """The variables `project`'s sessions are given from this vault, as `[vault]` names them."""
    if not exists():
        return {}
    wanted = project.strip().casefold()
    with _lock, _connected() as connection:
        rows = connection.execute("SELECT name, kind, projects FROM entries").fetchall()
    given: dict[str, str] = {}
    for row in rows:
        if wanted in {name.casefold() for name in _projects(row)}:
            for variable in variables(row["name"], row["kind"]):
                given[variable] = f"ponos:{variable}"
    return given


def read(variable: str) -> str:
    """The value of one variable an entry gives — "" when no entry gives it."""
    if not exists():
        return ""
    with _lock, _connected() as connection:
        for row in connection.execute("SELECT * FROM entries").fetchall():
            if variable in variables(row["name"], row["kind"]) or variable == row["name"]:
                key = _key(connection, create=False)
                # Read again after `_key`, which may have sealed every entry anew.
                row = _row(connection, row["id"])
                held: dict[str, str] = json.loads(
                    _open(key.raw, row["nonce"], row["sealed"], _bound(row))
                )
                if variable in held:
                    return held[variable]
                # A login named by its entry rather than one of its two variables.
                return held.get(variable + "_PASSWORD", "")
    return ""


def addresses(project: str) -> dict[str, str]:
    """The addresses of the entries granted to `project`, as `<NAME>_URL` — none for an entry without.

    Given to a session beside the values, and not masked: an address is no
    secret. Only those of the entries that open — an address changed in the
    file by hand is not handed over, any more than the value it is sealed with.
    """
    if not exists():
        return {}
    wanted = project.strip().casefold()
    given: dict[str, str] = {}
    with _lock, _connected() as connection:
        rows = connection.execute("SELECT * FROM entries WHERE url != ''").fetchall()
        mine = [row for row in rows if wanted in {name.casefold() for name in _projects(row)}]
        if not mine:
            return {}
        key = _key(connection, create=False)
        for row in mine:
            row = _row(connection, row["id"])
            try:
                _open(key.raw, row["nonce"], row["sealed"], _bound(row))
            except VaultStoreError:
                continue
            given[address_variable(row["name"])] = row["url"]
    return given


def used(variables_given: list[str], ticket: str, project: str) -> None:
    """Write down that a session was given these variables — once per entry."""
    if not variables_given or not exists():
        return
    with _lock, _connected() as connection:
        for row in connection.execute("SELECT id, name, kind FROM entries").fetchall():
            if set(variables(row["name"], row["kind"])) & set(variables_given):
                _write_down(connection, row, "read", ticket=ticket, project=project)


def logins(project: str) -> dict[str, str]:
    """The logins granted to `project`, by name, with the address of their site ("" for none).

    Read without the key: who may use an entry and where it signs in are not
    sealed, only its value is.
    """
    if not exists():
        return {}
    wanted = project.strip().casefold()
    with _lock, _connected() as connection:
        rows = connection.execute(
            "SELECT name, projects, url FROM entries WHERE kind = ?", (LOGIN,)
        ).fetchall()
    return {
        row["name"]: row["url"]
        for row in rows
        if wanted and wanted in {name.casefold() for name in _projects(row)}
    }


# How a sign-in by the browser ended, as the journal writes it: one action each.
SIGNED_IN, SIGN_IN_FAILED, SECOND_FACTOR, SIGN_IN_REFUSED = (
    "login",
    "login-failed",
    "login-second-factor",
    "login-refused",
)
SIGN_INS = (SIGNED_IN, SIGN_IN_FAILED, SECOND_FACTOR, SIGN_IN_REFUSED)


def signed_in(name: str, ticket: str, project: str, result: str) -> None:
    """Write down that Ponos's browser signed in with `name`, and how it ended (`SIGN_INS`)."""
    if result not in SIGN_INS:
        raise ValueError(f"a sign-in ends in one of {', '.join(SIGN_INS)}")
    if not exists():
        return
    with _lock, _connected() as connection:
        row = connection.execute("SELECT id, name FROM entries WHERE name = ?", (name,)).fetchone()
        if row is not None:
            _write_down(connection, row, result, ticket=ticket, project=project)


def rotate() -> tuple[int, Key]:
    """Every entry sealed again under a new key; the old one opens nothing any more.

    The new key is kept aside first, the vault rewritten in one transaction,
    and only then the new key put in the old one's place — a rotation cut short
    anywhere leaves a key that opens the vault (see `_key`). A key given by
    `PONOS_VAULT_KEY` cannot be replaced from here: the new one is handed back,
    for whoever set the variable to set again.
    """
    import secrets

    with _lock, _connected() as connection:
        old = _key(connection, create=True)
        fresh = secrets.token_bytes(KEY_BYTES)
        if old.source == "keyring" and not _keyring_write(_PENDING, fresh):
            raise VaultStoreError("the keyring refused the new key")
        if old.source == "file":
            _file_write(_pending_path(), fresh)
        rows = connection.execute("SELECT * FROM entries").fetchall()
        for row in rows:
            associated = _bound(row)
            plain = _open(old.raw, row["nonce"], row["sealed"], associated)
            nonce, sealed = _seal(fresh, plain, associated)
            connection.execute(
                "UPDATE entries SET nonce = ?, sealed = ? WHERE id = ?", (nonce, sealed, row["id"])
            )
            _write_down(connection, row, "rotated")
        nonce, sealed = _seal(fresh, _CHECK, _CHECKED)
        connection.execute(
            "UPDATE meta SET nonce = ?, sealed = ? WHERE key = 'check'", (nonce, sealed)
        )
    _keep(old.source, fresh)
    return len(rows), Key(fresh, old.source, old.where)


def encoded(key: Key) -> str:
    """A key as `PONOS_VAULT_KEY` is given it."""
    return _encoded(key.raw)


# -- what `ponos doctor` reads ---------------------------------------------------


def mode_of(target: Path) -> int | None:
    try:
        return target.stat().st_mode & 0o777
    except OSError:
        return None


def expiring(today: date | None = None) -> tuple[list[str], list[str]]:
    """The entries past their date, and those within `EXPIRING_DAYS` of it."""
    today = today or date.today()
    past: list[str] = []
    soon: list[str] = []
    for entry in listing():
        if not entry["expires"]:
            continue
        left = (date.fromisoformat(entry["expires"]) - today).days
        if left < 0:
            past.append(entry["name"])
        elif left < EXPIRING_DAYS:
            soon.append(entry["name"])
    return past, soon
