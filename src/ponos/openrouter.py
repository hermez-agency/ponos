"""One key, and every model behind it.

What the runner drives is Claude Code, and Claude Code talks to Anthropic. That
is one family of models on one subscription — so a ticket that wants GPT to
write the copy, a transcription of an audio file, or a video made from a prompt,
has nowhere to go and no way of paying for it.

OpenRouter is one key in front of every provider there is. Configured here, it
reaches a session in two ways, and they are not the same gesture.

**The key, in the session's environment.** `OPENROUTER_API_KEY` is the name
every library and every snippet already looks for, so the work can call whatever
model it needs — a GPT, an image, a video — without anything in the runner
having to know what a video model is. Nothing else changes: the agent doing the
work is the one you have always had, it simply now has an account.

**The sessions themselves, run on it.** Off by default, and it is the switch to
think about: Claude Code then speaks to OpenRouter's Anthropic-compatible
endpoint instead of to Anthropic, and every model named anywhere — a ticket's
Model column, an agent's, `runner.model` — becomes an OpenRouter slug,
`openai/gpt-5` or `anthropic/claude-sonnet-4.5`. Two things travel with that,
and neither is a detail. The CLI is no longer signed in as you but as a bearer
token, so Claude in Chrome does not load (session.py says why). And the bill is
OpenRouter's rather than the subscription's, so there is no window to wait for
and `runner.wait_for_credits` has nothing left to hold (credits.py says why).

An empty key is the whole of the old behaviour: nothing here is added to
anything, and a session starts exactly as it used to.

**And one thing the runner does with it itself: listening.** Claude Code reads
text, images and PDFs, and not a word of audio — so a message dictated in the
console is turned into text here, before it ever reaches a session, and handed
back to the page to be read over. Without a key there is no one to transcribe
it, and `Unavailable` says so in a sentence rather than as a failed request.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from . import http
from .config import OPENROUTER_URL, OpenRouter

# What the browser records in, as the transcription endpoint names it. Chrome
# and Firefox write WebM/Opus, Safari MP4; anything else is sent as it came and
# left to the provider to recognise.
FORMATS = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}

# A dictated sentence is seconds of audio; a minute is already a long one.
TRANSCRIPTION_TIMEOUT = 90


class Unavailable(RuntimeError):
    """Nothing to transcribe with — said as the reason, not as an error code."""


class TranscriptionError(RuntimeError):
    """OpenRouter was asked and did not answer with text."""


def anthropic_url(settings: OpenRouter) -> str:
    """Where Claude Code is pointed: the base URL without its `/v1`.

    Claude Code adds `/v1/messages` to `ANTHROPIC_BASE_URL` itself, so the
    `/api/v1` the rest of OpenRouter's API lives under would be asked for
    `/api/v1/v1/messages` — a 404 it reports as a model that does not exist.
    """
    base = settings.base_url.rstrip("/") or OPENROUTER_URL
    return base.removesuffix("/v1")


def environment(settings: OpenRouter) -> dict[str, str]:
    """What a session is started with, on top of the environment it inherits."""
    if not settings.key:
        return {}
    base = settings.base_url.rstrip("/") or OPENROUTER_URL
    variables = {"OPENROUTER_API_KEY": settings.key, "OPENROUTER_BASE_URL": base}
    if settings.route_sessions:
        # `ANTHROPIC_AUTH_TOKEN` and not `ANTHROPIC_API_KEY`: the first is sent
        # as a bearer token, which is what a gateway in front of the Messages
        # API expects, and it is the one Claude Code documents for exactly this.
        variables["ANTHROPIC_BASE_URL"] = anthropic_url(settings)
        variables["ANTHROPIC_AUTH_TOKEN"] = settings.key
    return variables


def audio_format(content_type: str) -> str:
    """The format a recording is announced as, from the type it was sent with."""
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    return FORMATS.get(kind, kind.rsplit("/", 1)[-1] or "webm")


def transcribe(settings: OpenRouter, audio: bytes, content_type: str, language: str = "") -> str:
    """The words in a recording, as text — or `Unavailable` when there is no key.

    `language` is an ISO-639-1 code, or nothing at all: Whisper guesses well,
    and better than a guess of ours that was wrong.
    """
    if not settings.key:
        raise Unavailable(
            "no OpenRouter key — dictation is transcribed by OpenRouter: "
            "set openrouter.key in the settings"
        )
    if not audio:
        raise ValueError("the recording is empty")
    body: dict[str, Any] = {
        "model": settings.transcription_model,
        "input_audio": {
            "data": base64.b64encode(audio).decode("ascii"),
            "format": audio_format(content_type),
        },
    }
    if language:
        body["language"] = language
    base = settings.base_url.rstrip("/") or OPENROUTER_URL
    try:
        sent = http.send(
            "openrouter",
            "POST",
            f"{base}/audio/transcriptions",
            content=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.key}",
                "Content-Type": "application/json",
                "X-Title": "ponos",
            },
            timeout=TRANSCRIPTION_TIMEOUT,
        )
    except http.Unanswered as error:
        raise TranscriptionError(f"OpenRouter could not be reached: {error}") from error
    if sent.status >= 400:
        raise TranscriptionError(f"OpenRouter refused the recording: {_said(sent)}")
    try:
        answer = json.loads(sent.body.decode("utf-8"))
    except ValueError as error:
        raise TranscriptionError("OpenRouter answered something that is not JSON") from error
    text = answer.get("text") if isinstance(answer, dict) else None
    if not isinstance(text, str):
        raise TranscriptionError("OpenRouter answered without a transcription")
    return text.strip()


def _said(answer: http.Answer) -> str:
    """The sentence an HTTP error came with, rather than only its number."""
    try:
        payload = json.loads(answer.body.decode("utf-8"))
        message = payload.get("error", {}).get("message") if isinstance(payload, dict) else ""
    except (ValueError, AttributeError):
        message = ""
    return f"{answer.status} {message}".strip() if message else f"{answer.status} {answer.reason}"


def _per_million(item: dict[str, Any], which: str) -> float | None:
    """What a model's `which` tokens cost per million, in dollars — None when unsaid.

    OpenRouter prices a token, as a string (`"0.000003"`); a million of them is
    the unit anyone reads a price in. A negative price is its router's own
    ("auto"), not a cost.
    """
    pricing = item.get("pricing")
    try:
        price = float(pricing[which]) if isinstance(pricing, dict) else -1.0
    except (KeyError, TypeError, ValueError):
        return None
    return round(price * 1_000_000, 4) if price >= 0 else None


# The catalogue is a few hundred models and changes a few times a week: asked
# once in a while, not once per page opened.
CATALOGUE_TTL = 600
CATALOGUE_TIMEOUT = 15
_catalogue: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def catalogue(settings: OpenRouter) -> list[dict[str, Any]]:
    """Every model OpenRouter offers, as its API lists them.

    `{id, name, input, output, tools}` each: the price per million tokens read
    and written, and whether the model can use tools — which Claude Code cannot
    work without.

    Raises `Unavailable` with a sentence when it cannot be read — the console
    still offers the Claude models then, and says why the rest is missing.
    """
    base = settings.base_url.rstrip("/") or OPENROUTER_URL
    kept = _catalogue.get(base)
    if kept and time.monotonic() - kept[0] < CATALOGUE_TTL:
        return kept[1]
    try:
        sent = http.send(
            "openrouter",
            "GET",
            f"{base}/models",
            headers={"Authorization": f"Bearer {settings.key}", "X-Title": "ponos"},
            timeout=CATALOGUE_TIMEOUT,
        )
    except http.Unanswered as error:
        raise Unavailable(f"OpenRouter could not be reached: {error}") from error
    if sent.status >= 400:
        raise Unavailable(f"OpenRouter refused the list of models: {_said(sent)}")
    try:
        answer = json.loads(sent.body.decode("utf-8"))
    except ValueError as error:
        raise Unavailable("OpenRouter answered something that is not JSON") from error
    data = answer.get("data") if isinstance(answer, dict) else None
    models = [
        {
            "id": str(item["id"]),
            "name": str(item.get("name") or item["id"]),
            "input": _per_million(item, "prompt"),
            "output": _per_million(item, "completion"),
            "tools": "tools" in (item.get("supported_parameters") or []),
        }
        for item in data or []
        if isinstance(item, dict) and item.get("id")
    ]
    _catalogue[base] = (time.monotonic(), models)
    return models
