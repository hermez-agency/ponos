"""The bell, rung on a phone: Web Push from the console installed as an app.

The bell (notifications.py) keeps what waits for you, but only for whoever
opens the console; Telegram and Slack reach a phone, through a third party and
a bot somebody has to set up. Web Push is the browser's own: the phone's
browser hands the console an address at its push service (Google's, Apple's,
Mozilla's) and two keys, and a message posted there wakes the console's
service worker, which shows it — the console closed, the phone asleep.

**Nothing to set up but a switch.** The console signs what it posts with a key
of its own (VAPID, RFC 8292), drawn the first time a browser asks for it and
kept beside the console's token — no account anywhere, no key to paste. And the
message is encrypted for the browser that subscribed (RFC 8291): the push
service carries it without being able to read it. That is what `cryptography`
is here for, and the only place it is imported — when a push is sent, not
before, like httpx in `http.py`: a pass on the machine's Python, before its
`.venv` exists, still imports this file, and rings nothing.

**The same moments as the bell, once.** A push is sent when the bell rings
anew for a ticket — not when it rings again for what is already unread — and
each carries the ticket as its `Topic` and its `tag`: a ticket that asks
twice while the phone was off is one notification on it, the latest. Quiet
hours are the phone's: its Do Not Disturb already knows them.

**Touching it opens the decision**: the address it carries is the ticket's page,
on the tab where it is answered — the discussion of a blocked ticket, Decide
for one in review.

Sent by the runner, kept by the console: a subscription the push service says
is gone (404, 410) is deleted, and anything else that fails is logged and
forgotten — a phone that could not be told is never a reason for a ticket to
fail.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from . import db, http
from .config import state_dir

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey

logger = logging.getLogger(__name__)

# How long a push service keeps a message for a phone that is off: a day, past
# which a question is better read on the bell than as a late buzz.
TTL = 24 * 60 * 60

# What a push may say: the record a push service carries is 4 kB, and a lock
# screen shows three lines of it anyway.
LONGEST_BODY = 600

# Who the console is, to a push service that has to reach somebody about it:
# the address of the console's account when it has one.
SUBJECT = "https://the-ponos.app"

# The bell's kinds whose ticket waits in review rather than blocked: its
# notification opens on Decide, every other on the discussion.
DECIDED = ("review",)


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def key_path() -> Path:
    return state_dir() / "web" / "vapid.pem"


def _load() -> EllipticCurvePrivateKey | None:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    try:
        loaded = load_pem_private_key(key_path().read_bytes(), password=None)
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, ec.EllipticCurvePrivateKey) else None


def _key() -> EllipticCurvePrivateKey:
    """The console's signing key: drawn once, kept, and the same for every process.

    Linked into place rather than written there: two consoles drawing one at
    the same moment keep the first, and neither hands a browser a key the
    other then replaces — a subscription made with it would be refused for good.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from .disk import write_private

    found = _load()
    if found is not None:
        return found
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    drawn = ec.generate_private_key(ec.SECP256R1())
    pem = drawn.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    scratch = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write_private(scratch, pem)
    try:
        os.link(scratch, path)
    except FileExistsError:
        pass
    finally:
        scratch.unlink(missing_ok=True)
    kept = _load()
    if kept is None:
        raise OSError(f"{path} could not be read back")
    return kept


def _point(key: EllipticCurvePrivateKey) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def public_key() -> str:
    """What a browser subscribes with (`applicationServerKey`), drawing the key if need be."""
    return _b64(_point(_key()))


def available() -> bool:
    """Whether this Python can sign and encrypt a push at all."""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def subscribe(endpoint: str, p256dh: str, auth: str, label: str = "", who: str = "") -> bool:
    """Keep a browser's subscription — False for one that is not one."""
    try:
        if urlsplit(endpoint).scheme != "https" or len(_unb64(p256dh)) != 65:
            return False
        if len(_unb64(auth)) != 16:
            return False
    except ValueError:
        return False
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, label, who, created) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (endpoint) DO UPDATE SET "
            "p256dh = excluded.p256dh, auth = excluded.auth, label = excluded.label, "
            "who = excluded.who",
            (endpoint, p256dh, auth, label[:120], who, _now()),
        )
    return True


def unsubscribe(endpoint: str) -> None:
    with db.transaction() as connection:
        connection.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def subscriptions() -> list[Subscription]:
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions ORDER BY created"
            ).fetchall()
    except db.ERRORS:
        return []
    return [Subscription(*row) for row in rows]


def devices() -> list[dict[str, str]]:
    """The subscriptions as the console lists them: never their keys."""
    try:
        with db.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT endpoint, label, who, created FROM push_subscriptions ORDER BY created"
            ).fetchall()
    except db.ERRORS:
        return []
    return [
        {"endpoint": endpoint, "label": label, "who": who, "created": created}
        for endpoint, label, who, created in rows
    ]


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None) -> bytes:
    """`payload` as one aes128gcm record for that browser (RFC 8291, RFC 8188)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    theirs = _unb64(p256dh)
    secret = _unb64(auth)
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    ours = _point(ephemeral)
    shared = ephemeral.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), theirs)
    )
    ikm = HKDF(hashes.SHA256(), 32, salt=secret, info=b"WebPush: info\x00" + theirs + ours).derive(
        shared
    )
    salt = salt or os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    # One record, the last: the delimiter is 0x02, and no padding after it.
    sealed = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(ours)) + ours + sealed


def authorization(endpoint: str, subject: str = SUBJECT) -> str:
    """The VAPID header for a push service: a JWT for its origin, and the key that signed it."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    key = _key()
    parts = urlsplit(endpoint)
    head = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(time.time()) + 12 * 60 * 60,
        "sub": subject,
    }
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signed = f"{head}.{body}".encode("ascii")
    r, s = decode_dss_signature(key.sign(signed, ec.ECDSA(hashes.SHA256())))
    signature = _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{body}.{signature}, k={_b64(_point(key))}"


def address(ticket: str, kind: str) -> str:
    """The console's page of the ticket, on the tab its decision is taken in."""
    tab = "decide" if kind in DECIDED else "discussion"
    return f"/?view=console/tickets/read/{ticket}&tab={tab}"


def topic(ticket: str) -> str:
    """What a push service replaces a waiting message by: one per ticket.

    At most 32 characters of the URL-safe alphabet, which a ticket's
    identifier is not always — a file board's is a file's name.
    """
    return hashlib.sha256(ticket.encode()).hexdigest()[:32]


def send(
    subscription: Subscription,
    message: dict[str, str],
    *,
    urgent: bool = False,
    subject: str = SUBJECT,
) -> int:
    """Post one message to one browser: the push service's status, or 0 without an answer."""
    payload = json.dumps(message, ensure_ascii=False).encode()
    headers = {
        "Authorization": authorization(subscription.endpoint, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL),
        "Urgency": "high" if urgent else "normal",
    }
    if message.get("tag"):
        headers["Topic"] = topic(message["tag"])
    try:
        answer = http.send(
            "push",
            "POST",
            subscription.endpoint,
            headers=headers,
            content=encrypt(payload, subscription.p256dh, subscription.auth),
            timeout=15,
            attempts=2,
        )
    except http.Unanswered as error:
        logger.warning("push to %s: %s", urlsplit(subscription.endpoint).netloc, error)
        return 0
    if answer.status in (404, 410):
        # The browser unsubscribed, or the phone was reset: the address is dead for good.
        unsubscribe(subscription.endpoint)
    elif answer.status >= 400:
        logger.warning(
            "push to %s refused: %s %s",
            urlsplit(subscription.endpoint).netloc,
            answer.status,
            answer.body[:200].decode("utf-8", "replace"),
        )
    return answer.status


def ring(kind: str, ticket: str, title: str, body: str, *, contact: str = "") -> int:
    """Tell every subscribed browser what the bell just rang for. How many took it."""
    found = subscriptions()
    if not found or not available() or _load() is None:
        return 0
    message = {
        "title": title,
        "body": body[:LONGEST_BODY],
        "tag": ticket,
        "kind": kind,
        "url": address(ticket, kind),
    }
    subject = f"mailto:{contact}" if contact else SUBJECT
    taken = 0
    for subscription in found:
        try:
            status = send(subscription, message, urgent=kind == "question", subject=subject)
        except Exception:  # a phone that could not be told never fails a ticket
            logger.exception("push to %s", urlsplit(subscription.endpoint).netloc)
            continue
        taken += 200 <= status < 300
    return taken
