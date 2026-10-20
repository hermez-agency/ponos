"""Every request the runner sends, and what it does when one goes unanswered.

Until October 2026 there were nine `urlopen` in seven modules, and only the
Notion client asked again: four attempts, the pause a 429 asks for, and a
write replayed only when it cannot have been carried out. GitHub, OpenRouter,
the channels, the pictures and the MCP probe gave up on the first silence —
and a 429 from Telegram was a notification lost. That policy is this module's
now, word for word, and every service goes through it.

**What may be sent again.** A request refused before anything was done — a
429, a connection that never opened, a body that never left — is always worth
another try. A request that may have been carried out — a 5xx, an answer cut
while it was read — only when doing it twice is doing it once: a read, or a
write that sets a value. What *adds* something is not replayed, because the
second copy is a duplicate somebody has to delete by hand. The method says
which by default; a service whose reads are spelt as POST (Notion's query and
search) says so itself, by `replayable`.

**One `httpx.Client` per service**, made on first use and kept: its
connections are reused from one call to the next, which the console's
polling of Notion notices. Each has its timeout, `ponos` as User-Agent, and
the machine's certificates — those `urllib` trusted, not `certifi`'s, so that
a company's authority installed on the machine still opens the same doors.
Redirects are followed, as `urlopen` did.

**httpx is imported when the first request is sent, not before.** An
installation from before `.venv` (see environment.py) is updated onto this
code by a version that checks it with the machine's Python: the code has to
import there, and give itself an environment on its next pass. And no
request leaves before that pass does.

**What comes back is an `Answer`** — a status, headers and the body, read
whole or up to `limit` — whatever the status: what a 404 means is the
caller's business. No answer at all is `Unanswered`.
"""

from __future__ import annotations

import logging
import ssl
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

USER_AGENT = "ponos"
TIMEOUT = 30
MAX_ATTEMPTS = 4
# Past this, a Retry-After is not a pause, it is the service saying "not
# today": the run moves on and the next one asks again.
LONGEST_WAIT = 60
# What a service is asked again for, when the request may be sent twice.
UNAVAILABLE = (500, 502, 503, 504)

# The door a test puts in front of every client (`httpx.MockTransport`), then
# `forget()` so that the clients already made are made again on it. None
# everywhere else.
transport: httpx.BaseTransport | None = None

# How the policy waits between two attempts: a test counts the pauses instead.
sleep = time.sleep

_clients: dict[str, httpx.Client] = {}
_lock = threading.Lock()


class Unanswered(Exception):
    """No answer to go by: the network failed every attempt, or once where retrying was unsafe.

    `offline` when every attempt died on DNS or on the connection — the service
    was never reached. `cause` is the error at the bottom of it (a
    `socket.gaierror`, an `ssl.SSLError`…), for a caller that tells them apart.
    """

    def __init__(self, message: str, *, offline: bool = False, cause: BaseException | None = None):
        super().__init__(message)
        self.offline = offline
        self.cause = cause


@dataclass(frozen=True)
class Answer:
    status: int
    headers: httpx.Headers
    body: bytes

    @property
    def reason(self) -> str:
        import httpx

        return httpx.codes.get_reason_phrase(self.status)

    @property
    def kind(self) -> str:
        """The content type, without its parameters — `text/plain` when unsaid, as `urllib` read it."""
        declared = self.headers.get("content-type", "") or "text/plain"
        return declared.split(";", 1)[0].strip().lower()


def idempotent(method: str) -> bool:
    """Is doing it twice doing it once — as HTTP defines the method?"""
    return method.upper() in ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")


def retried(status: int, replayable: bool) -> bool:
    """Is this status worth asking again for? A 429 always; a 5xx on what may be replayed."""
    return status == 429 or (status in UNAVAILABLE and replayable)


def retry_after(headers: httpx.Headers) -> float:
    """What a 429 asks us to wait, in seconds — bounded, and 0 when unsaid."""
    try:
        return min(float(headers.get("Retry-After", "") or 0), LONGEST_WAIT)
    except (TypeError, ValueError):
        return 0.0


def client(service: str) -> httpx.Client:
    """The client of that service, made on first use."""
    import httpx

    # The library says every request it sends at INFO, URL included — and a
    # Telegram bot's token is part of its URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with _lock:
        made = _clients.get(service)
        if made is None:
            made = httpx.Client(
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                verify=ssl.create_default_context(),
                transport=transport,
            )
            _clients[service] = made
        return made


def forget() -> None:
    """Drop every client: the next request makes its own, on `transport` as it then is."""
    with _lock:
        for made in _clients.values():
            made.close()
        _clients.clear()


def _cause(error: BaseException) -> BaseException:
    seen = error
    while seen.__cause__ is not None or seen.__context__ is not None:
        seen = seen.__cause__ or seen.__context__  # type: ignore[assignment]
    return seen


def _said(error: BaseException) -> str:
    return str(error) or type(_cause(error)).__name__


def _once(
    service: str,
    method: str,
    url: str,
    headers: dict[str, str] | None,
    content: bytes | None,
    timeout: float | None,
    limit: int | None,
) -> Answer:
    extra: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
    with client(service).stream(method, url, headers=headers, content=content, **extra) as response:
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if limit is not None and len(body) > limit:
                break
        return Answer(response.status_code, response.headers, bytes(body))


def send(
    service: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float | None = None,
    replayable: bool | None = None,
    attempts: int = MAX_ATTEMPTS,
    limit: int | None = None,
) -> Answer:
    """One request, asked again as the policy says. The last answer, or `Unanswered`.

    `limit` stops reading the body one byte past it: the caller sees it is too
    long without having held all of it.
    """
    import httpx

    method = method.upper()
    replayable = idempotent(method) if replayable is None else replayable
    answer: Answer | None = None
    last = ""
    offline = False
    cause: BaseException | None = None
    for attempt in range(attempts):
        wait = 1.5 * (attempt + 1)
        try:
            answer = _once(service, method, url, headers, content, timeout, limit)
        except (httpx.InvalidURL, httpx.UnsupportedProtocol, httpx.LocalProtocolError) as error:
            # A malformed address never becomes valid by retrying — most often
            # a configuration value that is not what it claims to be.
            raise Unanswered(_said(error), cause=_cause(error)) from error
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            # Raised while connecting: the request never reached the service,
            # so even a comment is safe to send again.
            answer, last, cause = None, _said(error), _cause(error)
            offline = not isinstance(error, httpx.PoolTimeout)
        except (httpx.WriteError, httpx.WriteTimeout, httpx.ProxyError) as error:
            # Raised while sending: the service never had the request whole.
            answer, last, cause, offline = None, _said(error), _cause(error), False
        except httpx.TransportError as error:
            # Raised while *reading* the answer — a timeout, a reset, a
            # connection closed halfway. The request may have been carried
            # out, and a second comment is worse than an error.
            answer, cause, offline = None, _cause(error), False
            last = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
            if not replayable:
                raise Unanswered(
                    f"{last} — not retried, it may have been applied", cause=cause
                ) from error
        except ValueError as error:
            # A header that is not ASCII, a body that is not bytes: ours, and
            # no more valid the second time.
            raise Unanswered(str(error), cause=error) from error
        else:
            if not retried(answer.status, replayable):
                return answer
            offline = False
            if answer.status == 429:
                # Refused before anything was done, whatever the method:
                # always worth the wait the service asks for.
                wait = max(wait, retry_after(answer.headers))
        if attempt < attempts - 1:
            sleep(wait)
    if answer is not None:
        return answer
    raise Unanswered(f"{last} (gave up after {attempts} attempts)", offline=offline, cause=cause)
