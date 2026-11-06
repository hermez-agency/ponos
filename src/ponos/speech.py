"""Ponos talking back: a reply turned into what is worth saying aloud, then into sound.

**Piper, here and nowhere else.** The voice is synthesised on this machine by
`piper-tts` (the `voice` extra): no hosted service hears what the workspace
answers. It is imported when the first sentence is spoken, not before — the
core runs with the standard library and its five dependencies, and a machine
without Piper must still import every other module (`available` says which
case this is, and the console greys its button out with the reason).

**A reply is not read as it is written.** A code block, a table, a link and
the markdown around the words are for the eyes: read aloud they are noise, and
three minutes of it. `clean` keeps the sentences, says once that a block went
to the screen, and `plan` stops after `SPOKEN_LIMIT` characters with "I put the
detail on screen" rather than reading on. The full text stays displayed.

**`plan` is stable on a growing text.** The page calls it as a reply streams
in, and speaks the sentences it has not spoken yet: the first one is heard while
the rest is still being written. So the sentences of a prefix are the first
sentences of the whole, and the last one — which may still be half-written — is
held back until `final`. That is also why the limit counts characters of
completed sentences and not of the whole reply.

**The models are downloaded on first use**, not shipped: `.onnx` and its
`.onnx.json` from the `rhasspy/piper-voices` repository, into
`cache_dir()/voices`. A medium voice weighs about 60 MB.
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import logging
import re
import threading
import wave
from pathlib import Path
from typing import Any

from . import config as config_module
from . import http, voice

log = logging.getLogger(__name__)

VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
# Models are tens of megabytes: a slow line must not be cut at the usual 30 s.
DOWNLOAD_TIMEOUT = 300
DOWNLOAD_LIMIT = 200 * 1024 * 1024

# What is spoken of a reply before the rest is left on the screen, and the most
# one request synthesises: the page asks for a sentence at a time.
SPOKEN_LIMIT = 700
REQUEST_LIMIT = 2000
LONGEST_SENTENCE = 220

_SAID = {
    "fr": {
        "code": "Je t'ai mis le code à l'écran.",
        "table": "Je t'ai mis un tableau à l'écran.",
        "link": "un lien",
        "detail": "Je t'ai mis le détail à l'écran.",
    },
    "en": {
        "code": "I put the code on screen.",
        "table": "I put a table on screen.",
        "link": "a link",
        "detail": "I put the details on screen.",
    },
}


class Unavailable(RuntimeError):
    """Nothing to speak with — said as the reason, not as an error code."""


class SpeechError(RuntimeError):
    """The voice could not be fetched or could not speak."""


def available() -> bool:
    """Whether `piper-tts` is installed in the environment this runs in."""
    try:
        return importlib.util.find_spec("piper") is not None
    except (ImportError, ValueError):
        return False


def refusal(settings: config_module.Speech) -> str:
    """Why the voice cannot be offered, or nothing when it can."""
    if not settings.enabled:
        return "Voice is off: speech.enabled is false"
    if not available():
        return "Voice needs Piper: install the `voice` extra (pip install piper-tts)"
    return ""


def voice_dir() -> Path:
    return config_module.cache_dir() / "voices"


def language(raw: str) -> str:
    return voice.understood(raw)


def chosen(settings: config_module.Speech, lang: str) -> str:
    return settings.voice_fr if language(lang) == "fr" else settings.voice_en


_NAME = re.compile(r"^([a-z]{2})_([A-Z]{2})-([A-Za-z0-9]+)-([a-z_]+)$")


def locate(name: str) -> tuple[str, str]:
    """Where a voice is on the Piper catalogue: its model and its description.

    `fr_FR-siwis-medium` is `fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx`.
    """
    found = _NAME.match(name)
    if not found:
        raise SpeechError(f"{name!r} is not a Piper voice name (e.g. fr_FR-siwis-medium)")
    short, region, speaker, quality = found.groups()
    base = f"{VOICES_URL}/{short}/{short}_{region}/{speaker}/{quality}/{name}"
    return f"{base}.onnx", f"{base}.onnx.json"


def _fetch(url: str, target: Path) -> None:
    try:
        got = http.send(
            "piper", "GET", url, timeout=DOWNLOAD_TIMEOUT, limit=DOWNLOAD_LIMIT, attempts=2
        )
    except http.Unanswered as error:
        raise SpeechError(f"the voice could not be downloaded from {url}: {error}") from error
    if got.status != 200:
        raise SpeechError(f"the voice could not be downloaded from {url}: HTTP {got.status}")
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(got.body)
    partial.replace(target)


_download = threading.Lock()


def ensure(name: str) -> Path:
    """The `.onnx` of a voice, downloaded with its `.json` the first time it is asked for."""
    model_url, config_url = locate(name)
    folder = voice_dir()
    model = folder / f"{name}.onnx"
    described = folder / f"{name}.onnx.json"
    with _download:
        if model.exists() and described.exists():
            return model
        folder.mkdir(parents=True, exist_ok=True)
        log.info("downloading the Piper voice %s into %s", name, folder)
        _fetch(config_url, described)
        _fetch(model_url, model)
    return model


# -- the text to say ---------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE = re.compile(r"^\s*\|")
_RULE = re.compile(r"^\s*([-*_]\s*){3,}$")
_TERMINAL = ".!?…:;"
# A link, a span of code or a URL still being written on the last line.
_OPEN = re.compile(r"\[[^\]]*$|\]\([^)]*$|`[^`]*$|\*\*[^*]*$|\bhttps?:\S*$")
_CLOSING = ")»*_\"'`~ \t"


def _inline(line: str, said: dict[str, str]) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"<(https?://[^>]+)>", said["link"], line)
    line = re.sub(r"https?://\S+", said["link"], line)
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"`+([^`]*)`+", r"\1", line)
    line = re.sub(r"(\*\*|__)(.+?)\1", r"\2", line)
    line = re.sub(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])", r"\2", line)
    line = re.sub(r"~~(.+?)~~", r"\1", line)
    return re.sub(r"\s+", " ", line).strip()


def clean(text: str, lang: str = "en") -> str:
    """What to say of a reply: its sentences, one per line, without the markup.

    A run of code lines or table rows becomes one sentence saying it is on the
    screen. A line that does not end like a sentence is given a full stop, so
    that a list item is a sentence and not the start of the next one.
    """
    said = _SAID[language(lang)]
    out: list[str] = []
    fenced = False
    previous = ""
    for raw in text.replace("\r\n", "\n").split("\n"):
        if _FENCE.match(raw):
            fenced = not fenced
            kind = "code"
        elif fenced:
            kind = "code"
        elif _TABLE.match(raw):
            kind = "table"
        else:
            kind = ""
        if kind:
            if previous != kind:
                out.append(said[kind])
            previous = kind
            continue
        previous = ""
        line = raw.strip()
        if not line or _RULE.match(line):
            continue
        line = re.sub(r"^(#{1,6}\s+|>+\s*|[-*+]\s+|\d+[.)]\s+)", "", line)
        line = _inline(line, said)
        if not re.search(r"\w", line):
            continue
        out.append(line if line[-1] in _TERMINAL + ")»\"'" else line + ".")
    return "\n".join(out)


def sentences(spoken: str) -> list[str]:
    """The cleaned text, cut where a sentence ends — and where a line does."""
    found: list[str] = []
    for line in spoken.split("\n"):
        for part in re.split(r"(?<=[.!?…])\s+(?=\S)", line):
            part = part.strip()
            while len(part) > LONGEST_SENTENCE:
                cut = part.rfind(", ", 0, LONGEST_SENTENCE)
                if cut < 40:
                    cut = part.rfind(" ", 0, LONGEST_SENTENCE)
                if cut < 1:
                    break
                found.append(part[: cut + 1].strip())
                part = part[cut + 1 :].strip()
            if re.search(r"\w", part):
                found.append(part)
    return found


def plan(text: str, lang: str = "en", final: bool = True) -> list[str]:
    """The sentences to say of `text`, so far.

    Not `final`, the last one is kept back when the text stops mid-sentence.
    Past `SPOKEN_LIMIT` characters the rest is left to the screen, with a
    sentence that says so.
    """
    said = _SAID[language(lang)]
    found = sentences(clean(text, lang))
    # A text ends a sentence when its last word does — behind any markup that
    # closes it (`**Done.**`) — or when its last line is over.
    last = text.rstrip(" \t")
    ended = last.endswith("\n") or (
        last.rstrip(_CLOSING)[-1:] in _TERMINAL and not _OPEN.search(last.rsplit("\n", 1)[-1])
    )
    if not final and found and not ended:
        found = found[:-1]
    kept: list[str] = []
    length = 0
    for sentence in found:
        if kept and length + len(sentence) > SPOKEN_LIMIT:
            return [*kept, said["detail"]]
        kept.append(sentence)
        length += len(sentence) + 1
    return kept


# -- the sound ---------------------------------------------------------------

_voices: dict[str, Any] = {}
_loading = threading.Lock()


def _loaded(name: str) -> Any:
    with _loading:
        if name not in _voices:
            path = ensure(name)
            try:
                piper = importlib.import_module("piper")
                _voices[name] = piper.PiperVoice.load(str(path))
            except Exception as error:  # noqa: BLE001 - whatever the model runtime raises
                raise SpeechError(f"the voice {name} could not be loaded: {error}") from error
        return _voices[name]


def warm(settings: config_module.Speech, lang: str) -> None:
    """Load the voice of `lang` in the background, so the first sentence does not wait for it.

    Loading the model takes about two seconds, which is the whole budget of the
    first sound: the page asks for it as the voice mode opens, and a voice
    already loaded costs nothing.
    """
    name = chosen(settings, lang)
    if refusal(settings) or name in _voices:
        return

    def load() -> None:
        try:
            _loaded(name)
        except Exception as error:  # noqa: BLE001 - the sentence itself will say why
            log.warning("the voice %s could not be warmed up: %s", name, error)

    threading.Thread(target=load, name=f"piper-{name}", daemon=True).start()


def synthesize(settings: config_module.Speech, text: str, lang: str = "en") -> bytes:
    """A WAV of `text` in the voice the settings give the language.

    Raises `Unavailable` when the voice is off or Piper is not installed.
    """
    reason = refusal(settings)
    if reason:
        raise Unavailable(reason)
    spoken = " ".join(sentences(clean(text, lang)))[:REQUEST_LIMIT].strip()
    if not spoken:
        raise ValueError("there is nothing to say")
    name = chosen(settings, lang)
    model = _loaded(name)
    piper = importlib.import_module("piper")
    scale = 100 / max(settings.speed, 1)
    buffer = io.BytesIO()
    try:
        with wave.open(buffer, "wb") as sound:
            model.synthesize_wav(
                spoken, sound, syn_config=piper.SynthesisConfig(length_scale=scale)
            )
    except Exception as error:  # noqa: BLE001
        raise SpeechError(f"the voice {name} could not speak: {error}") from error
    return buffer.getvalue()
