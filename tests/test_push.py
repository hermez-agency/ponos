"""`push.py`: the bell, encrypted for a phone, signed by the console, and sent once."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from support import _http_answering, case

from ponos import notifications, push

ENDPOINT = "https://push.example.test/send/abc"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class _Browser:
    """What a browser holds of its subscription, and how it opens what it is sent."""

    def __init__(self, endpoint: str = ENDPOINT) -> None:
        self.endpoint = endpoint
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.point = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )

    def subscribe(self, label: str = "Android") -> bool:
        return push.subscribe(self.endpoint, _b64(self.point), _b64(self.auth), label=label)

    def open(self, body: bytes) -> dict[str, str]:
        """RFC 8291, the receiving side."""
        salt, size, length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        assert size == 4096 and length == 65, (size, length)
        theirs = body[21 : 21 + length]
        shared = self.key.exchange(
            ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), theirs)
        )
        ikm = HKDF(
            hashes.SHA256(), 32, salt=self.auth, info=b"WebPush: info\x00" + self.point + theirs
        ).derive(shared)
        cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00")
        nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00")
        plain = AESGCM(cek.derive(ikm)).decrypt(nonce.derive(ikm), body[21 + length :], None)
        assert plain.endswith(b"\x02"), "one record, the last"
        opened: dict[str, str] = json.loads(plain[:-1])
        return opened


def _verified(header: str) -> dict[str, object]:
    """The claims of a VAPID header, once its signature checks against the key it names."""
    assert header.startswith("vapid t="), header
    token, key = header[len("vapid t=") :].split(", k=")
    head, body, signature = token.split(".")
    raw = _unb64(signature)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64(key))
    public.verify(
        encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        f"{head}.{body}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )
    assert json.loads(_unb64(head)) == {"typ": "JWT", "alg": "ES256"}
    assert key == push.public_key(), "signed with the key the browser subscribed with"
    claims: dict[str, object] = json.loads(_unb64(body))
    return claims


@case
def a_bell_reaches_a_subscribed_phone_encrypted_signed_and_opening_the_decision(
    state_home: Path,
) -> None:
    """The ticket's criterion, short of a phone: what the push service is handed.

    The message is readable by the browser that subscribed and nobody else, the
    console signs it with the key that browser was given, the push service is
    told to keep one per ticket, and what the phone opens is the ticket's page
    on the tab its decision is taken in.
    """
    assert push.ring("question", "t1", "blocked", "Le header") == 0, "nobody subscribed"
    key = push.public_key()
    assert len(_unb64(key)) == 65 and push.public_key() == key, "drawn once, then kept"
    assert push.key_path().stat().st_mode & 0o077 == 0, "nobody else reads the key"

    phone = _Browser()
    assert phone.subscribe()
    assert phone.subscribe(), "subscribing again is the same subscription"
    assert [device["label"] for device in push.devices()] == ["Android"]

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(201)

    with _http_answering(handler):
        assert push.ring("question", "t1", "Blocked · Le header", "Which colour?", contact="a@b.c")
        assert push.ring("review", "t2", "To review · Le footer", "PR #3") == 1

    question, review = sent
    assert str(question.url) == ENDPOINT and question.method == "POST"
    assert question.headers["Content-Encoding"] == "aes128gcm"
    assert question.headers["TTL"] == str(push.TTL)
    assert question.headers["Urgency"] == "high" and review.headers["Urgency"] == "normal"
    assert question.headers["Topic"] == push.topic("t1") != push.topic("t2")
    assert len(question.headers["Topic"]) <= 32
    claims = _verified(question.headers["Authorization"])
    assert claims["aud"] == "https://push.example.test" and claims["sub"] == "mailto:a@b.c"

    opened = phone.open(question.content)
    assert opened == {
        "title": "Blocked · Le header",
        "body": "Which colour?",
        "tag": "t1",
        "kind": "question",
        "url": "/?view=console/tickets/read/t1&tab=discussion",
    }, opened
    assert phone.open(review.content)["url"].endswith("&tab=decide")
    try:
        _Browser().open(question.content)
    except InvalidTag:
        pass
    else:
        raise AssertionError("another browser read a message that was not for it")


@case
def a_subscription_the_push_service_forgot_is_dropped_and_a_bad_one_never_kept(
    state_home: Path,
) -> None:
    push.public_key()
    gone, kept = _Browser(ENDPOINT + "/gone"), _Browser(ENDPOINT + "/kept")
    assert gone.subscribe() and kept.subscribe()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410 if str(request.url).endswith("/gone") else 201)

    with _http_answering(handler):
        assert push.ring("blocked", "t1", "blocked", "") == 1
    assert [item.endpoint for item in push.subscriptions()] == [kept.endpoint]

    point, auth = _b64(kept.point), _b64(kept.auth)
    assert not push.subscribe("http://push.example.test/x", point, auth), "HTTPS only"
    assert not push.subscribe(ENDPOINT + "/x", "short", auth)
    assert not push.subscribe(ENDPOINT + "/x", point, _b64(b"0" * 8))
    assert len(push.subscriptions()) == 1

    def silent(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    with _http_answering(silent):
        assert push.ring("blocked", "t1", "blocked", "") == 0, "said quietly, never raised"
    assert len(push.subscriptions()) == 1, "a silence is not a refusal"


@case
def a_ticket_already_waiting_unread_is_not_pushed_twice(state_home: Path) -> None:
    """What `reports._tell` pushes on: the bell rung anew, not rung again."""
    assert notifications.add("question", "t1", "Le header")
    assert not notifications.add("question", "t1", "Le header"), "already waiting"
    assert notifications.add("review", "t1", "Le header"), "another thing to do"
    assert not notifications.add("routine", "t1", "Le header")
    notifications.read()
    assert notifications.add("question", "t1", "Le header"), "read, then asked again"
