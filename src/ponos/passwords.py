"""The console's password, kept as a scrypt digest rather than as itself.

`secrets.env` is `0600`, and that was the whole of the protection: a backup, a
volume copied to another host, a `cat` pasted into a ticket, and the password —
the one that opens a runner in `bypassPermissions` — went with it, readable.
What is kept now is what a password *proves* rather than what it *is*.

scrypt because `hashlib` has it, so the core still needs nothing but Python; and
its parameters are written with the digest, `scrypt:n:r:p:salt:hash`, so that
raising them one day leaves every password written before readable. The
separators and the alphabet are the ones `secrets.env` writes bare — no `$`,
which a compose `env_file` would try to expand.

A value without that prefix is a password still in clear: one written before
this module, or one a unit file or a compose file passes in the environment.
`matches` takes both, so neither stops working; `config.hash_password` turns the
first kind into a digest on the next launch, and the second is the
environment's to keep.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PREFIX = "scrypt"

# 2¹⁵ × 8: 32 MiB and a tenth of a second per check on a laptop — nothing for
# somebody signing in, and a lot for somebody guessing, who is also slowed by
# the console's own counter (`web/attempts.py`) before ever reaching this.
COST = 2**15
BLOCK = 8
PARALLEL = 1
LENGTH = 32


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decoded(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=length,
        # The default ceiling is 32 MiB, which is exactly what these parameters
        # need — and a little more than that is what the computation takes.
        maxmem=2 * 128 * r * n + 1024 * 1024,
    )


def digest(password: str) -> str:
    """`password`, as the line `secrets.env` keeps for it."""
    salt = secrets.token_bytes(16)
    derived = _scrypt(password, salt, COST, BLOCK, PARALLEL, LENGTH)
    return f"{PREFIX}:{COST}:{BLOCK}:{PARALLEL}:{_encoded(salt)}:{_encoded(derived)}"


def is_digest(value: str) -> bool:
    """`value` is a digest this module wrote, and not a password in clear."""
    parts = value.strip().split(":")
    return len(parts) == 6 and parts[0] == PREFIX and all(part.isdigit() for part in parts[1:4])


def matches(password: str, stored: str) -> bool:
    """`password` is the one `stored` keeps — a digest, or a password in clear.

    A digest whose parameters cannot be read is no way in: refused, never
    compared as if it were the password itself.
    """
    stored = stored.strip()
    if not stored:
        return False
    if not is_digest(stored):
        # Compared as bytes: `compare_digest` refuses two strings when either
        # holds a character outside ASCII, and a password may have an accent.
        return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))
    _, n, r, p, salt, expected = stored.split(":")
    try:
        wanted = _decoded(expected)
        derived = _scrypt(password, _decoded(salt), int(n), int(r), int(p), len(wanted))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derived, wanted)
