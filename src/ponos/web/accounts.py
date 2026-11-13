"""The people a console is shared with, what each may do, and what each did.

One password was one person: at two, everybody was the same somebody, a
validated merge was nobody's, and an intern could force one. So a console now
has accounts, each an email, a name, a scrypt digest — `passwords`, as the
console's own — and one of three roles:

- **reader** sees, and does nothing: no write reaches a route (`web/app.py`
  answers 403), and the page draws no button that would ask for one;
- **member** writes, launches, answers and validates tickets — the work;
- **admin** is a member who also changes how the console runs: the settings,
  the vault, a type's forced validation, the GitHub App, the accounts.

**The console's own sign-in is the first admin, and is not a row.** `[web]
email` and its password stay where they are, read as they always were; the
account they make is drawn here (`owner`) whenever a browser signs in with
them, with id 0. Nothing is migrated, nothing can drift between the file and
the table, and the person who installed the console cannot be demoted or
deleted from it by somebody they invited. The token is the same person again,
by another door: a script or `--print-token` acts as the machine itself.

**An invitation is a link, not an email.** Ponos sends no mail: an admin draws
a link for a role, copies it, and gives it however they like. The link carries
a code drawn once, kept here as its SHA-256 — reading the database opens
nothing — good for a week and for one account: taking it deletes it, in the
same transaction that creates the account, so two browsers racing on one link
make one account.

**The audit is the console's, not the board's.** A comment written from the
console now says who wrote it (`Answered from the console by Léa`), but a move
leaves no comment — one on a blocked ticket would be read as an answer — and
the board's own history names the runner's token for everything. So each thing
somebody does to a ticket from here is a row, with the name as it was then:
nothing here can look a person up later, and a deleted account keeps its past.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db, passwords
from .setup import SHORTEST_PASSWORD

READER = "reader"
MEMBER = "member"
ADMIN = "admin"
# In the order of what they may do: each may do what those before it may.
ROLES = (READER, MEMBER, ADMIN)

# A link given on a Monday is used by the end of the week, or was not meant to be.
INVITATION_DAYS = 7

# What a name may hold: what a comment on a ticket says, and nothing longer.
LONGEST_NAME = 60


@functools.cache
def _nobody() -> str:
    """The digest checked when the email is nobody's, so that a wrong email takes
    as long to refuse as a wrong password — see `server.SignIn.opens`. Drawn the
    first time it is needed: a tenth of a second nobody else should pay."""
    return passwords.digest(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class Account:
    """One person who signs into the console. Id 0 is the console's own sign-in."""

    id: int
    email: str
    name: str
    role: str
    digest: str = ""
    created: str = ""

    @property
    def owner(self) -> bool:
        return self.id == 0

    def may(self, needed: str) -> bool:
        return may(self.role, needed)

    def proof(self, secret: str) -> str:
        """What this account's sessions are signed from — see `sessions.issue`.

        Its id, its email and its digest: a new password signs its browsers out,
        and an account deleted and invited again under the same email is
        another id, whose sessions the old cookies are not.
        """
        said = f"account\n{self.id}\n{self.email.lower()}\n{self.digest}"
        return hmac.new(secret.encode(), said.encode(), hashlib.sha256).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "created": self.created,
            "owner": self.owner,
        }


def may(role: str, needed: str) -> bool:
    """`role` may do what `needed` may: an unknown role may do nothing."""
    if role not in ROLES or needed not in ROLES:
        return False
    return ROLES.index(role) >= ROLES.index(needed)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def name_of(email: str) -> str:
    """The name the console's own sign-in goes by: its email, before the @."""
    return email.split("@", 1)[0].strip() or email.strip()


def owner(email: str) -> Account:
    """The console's own sign-in, as an account: the first admin, always."""
    return Account(id=0, email=email.strip(), name=name_of(email), role=ADMIN)


def _account(row: sqlite3.Row | tuple[Any, ...]) -> Account:
    return Account(
        id=int(row[0]),
        email=str(row[1]),
        name=str(row[2]),
        digest=str(row[3]),
        role=str(row[4]),
        created=str(row[5]),
    )


_COLUMNS = "id, email, name, digest, role, created"


def listed() -> list[Account]:
    """Every account, in the order they were made."""
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(f"SELECT {_COLUMNS} FROM accounts ORDER BY id").fetchall()
    return [_account(row) for row in rows]


def shared() -> bool:
    """Somebody besides the console's own sign-in has an account."""
    try:
        with db.transaction(immediate=False) as connection:
            return connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None
    except db.ERRORS:
        return False


def find(identifier: int) -> Account | None:
    try:
        with db.transaction(immediate=False) as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM accounts WHERE id = ?", (identifier,)
            ).fetchone()
    except db.ERRORS:
        return None
    return _account(row) if row else None


def by_email(email: str) -> Account | None:
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE lower(email) = ?", (email.strip().lower(),)
        ).fetchone()
    return _account(row) if row else None


def signing_in(email: str, password: str) -> Account | None:
    """The account an email and a password open, or None — in the same time either way."""
    found = by_email(email) if email.strip() else None
    right = passwords.matches(password, found.digest if found else _nobody())
    return found if found and right else None


def _role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"“{role}” is not a role — {', '.join(ROLES)}")
    return role


def _checked(email: str, name: str, password: str) -> tuple[str, str]:
    email, name = email.strip(), " ".join(name.split())
    if "@" not in email:
        raise ValueError("an email address is what the console will ask you for")
    if not name:
        raise ValueError("a name is what your comments on tickets will be signed with")
    if len(name) > LONGEST_NAME:
        raise ValueError(f"a name of {LONGEST_NAME} characters at the most")
    if len(password) < SHORTEST_PASSWORD:
        raise ValueError(
            f"a password of {SHORTEST_PASSWORD} characters at the least — behind this "
            "port sits a runner that runs code on this machine"
        )
    return email, name


def _insert(
    connection: sqlite3.Connection, email: str, name: str, password: str, role: str
) -> Account:
    if connection.execute(
        "SELECT 1 FROM accounts WHERE lower(email) = ?", (email.lower(),)
    ).fetchone():
        raise ValueError(f"{email} already has an account")
    created = _now()
    digest = passwords.digest(password)
    cursor = connection.execute(
        "INSERT INTO accounts (email, name, digest, role, created) VALUES (?, ?, ?, ?, ?)",
        (email, name, digest, role, created),
    )
    return Account(int(cursor.lastrowid or 0), email, name, role, digest, created)


def create(email: str, name: str, password: str, role: str, reserved: str = "") -> Account:
    """A new account, without an invitation — what a test or a script makes.

    `reserved` is the console's own email, which no account may take.
    """
    email, name = _checked(email, name, password)
    if reserved and email.lower() == reserved.strip().lower():
        raise ValueError(f"{email} is this console's own sign-in")
    with db.transaction() as connection:
        return _insert(connection, email, name, password, _role(role))


def set_role(identifier: int, role: str) -> Account:
    with db.transaction() as connection:
        changed = connection.execute(
            "UPDATE accounts SET role = ? WHERE id = ?", (_role(role), identifier)
        ).rowcount
    found = find(identifier) if changed else None
    if found is None:
        raise LookupError("no such account")
    return found


def remove(identifier: int) -> Account:
    """Delete an account: its sessions are refused from its next request on.

    Nothing else is needed for that — see `sessions.holder`: a cookie names
    its account, and an account that is not here any more signs nothing.
    """
    found = find(identifier)
    if found is None:
        raise LookupError("no such account")
    with db.transaction() as connection:
        connection.execute("DELETE FROM accounts WHERE id = ?", (identifier,))
    return found


# -- invitations ---------------------------------------------------------------


def _digest(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8", "replace")).hexdigest()


def invite(role: str, by: str = "", now: datetime | None = None) -> tuple[str, dict[str, Any]]:
    """Draw an invitation for `role`: its code — the only time it is seen — and itself."""
    moment = now or datetime.now(UTC)
    code = secrets.token_urlsafe(24)
    created = moment.isoformat(timespec="seconds")
    expires = (moment + timedelta(days=INVITATION_DAYS)).isoformat(timespec="seconds")
    with db.transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO invitations (digest, role, made_by, created, expires) "
            "VALUES (?, ?, ?, ?, ?)",
            (_digest(code), _role(role), by, created, expires),
        )
    drawn = {"id": int(cursor.lastrowid or 0), "role": role, "by": by}
    return code, {**drawn, "created": created, "expires": expires}


def invitations() -> list[dict[str, Any]]:
    """The invitations nobody has taken yet, and still good — never their code."""
    now = _now()
    with db.transaction() as connection:
        connection.execute("DELETE FROM invitations WHERE expires <= ?", (now,))
        rows = connection.execute(
            "SELECT id, role, made_by, created, expires FROM invitations ORDER BY id"
        ).fetchall()
    return [
        {"id": int(row[0]), "role": row[1], "by": row[2], "created": row[3], "expires": row[4]}
        for row in rows
    ]


def withdraw(identifier: int) -> None:
    with db.transaction() as connection:
        gone = connection.execute("DELETE FROM invitations WHERE id = ?", (identifier,)).rowcount
    if not gone:
        raise LookupError("no such invitation")


def invited(code: str) -> str:
    """The role an invitation's code is for, or "" for one that is not, or not any more."""
    if not code.strip():
        return ""
    with db.transaction(immediate=False) as connection:
        row = connection.execute(
            "SELECT role FROM invitations WHERE digest = ? AND expires > ?",
            (_digest(code), _now()),
        ).fetchone()
    return str(row[0]) if row else ""


def accept(code: str, email: str, name: str, password: str, reserved: str = "") -> Account:
    """Take an invitation: the account it was for, made, and the link spent.

    Raises PermissionError for a code that opens nothing — wrong, taken or
    expired, the three said alike — and ValueError for what the form got wrong,
    the invitation kept for a second try.
    """
    email, name = _checked(email, name, password)
    if reserved and email.lower() == reserved.strip().lower():
        raise ValueError(f"{email} is this console's own sign-in")
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT id, role FROM invitations WHERE digest = ? AND expires > ?",
            (_digest(code), _now()),
        ).fetchone()
        if row is None:
            raise PermissionError("this invitation is not valid any more")
        account = _insert(connection, email, name, password, str(row[1]))
        connection.execute("DELETE FROM invitations WHERE id = ?", (row[0],))
    return account


# -- the audit -------------------------------------------------------------------

# What somebody can do to a ticket from the console, as the audit names it.
ACTIONS = (
    "created",
    "moved",
    "told",
    "decided",
    "priority",
    "on",
    "goal",
    "launched",
    "result",
    "revise",
)

# What a ticket's journal shows, at most: the latest.
AUDIT_SHOWN = 200


def record(ticket: str, who: Account | None, action: str, detail: str = "", by: str = "") -> None:
    """One thing done to a ticket from the console. Never a reason for the write to fail.

    `by` names who did it when no account did: an MCP client, by the name it
    registered under — the assistant launching a ticket is not the token.
    """
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO audit (ticket, at, who, email, action, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticket.replace("-", ""),
                    _now(),
                    who.name if who else by,
                    who.email if who else "",
                    action,
                    detail,
                ),
            )
    except db.ERRORS:
        pass


def journal(ticket: str) -> list[dict[str, Any]]:
    """What was done to one ticket from the console, newest first."""
    with db.transaction(immediate=False) as connection:
        rows = connection.execute(
            "SELECT at, who, email, action, detail FROM audit WHERE ticket = ? "
            "ORDER BY id DESC LIMIT ?",
            (ticket.replace("-", ""), AUDIT_SHOWN),
        ).fetchall()
    return [
        {"at": row[0], "who": row[1], "email": row[2], "action": row[3], "detail": row[4]}
        for row in rows
    ]
