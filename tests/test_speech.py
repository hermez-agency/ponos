"""`speech.py`: what of a reply is said aloud, and the voice when Piper is — or is not — there."""

from __future__ import annotations

import sys
import types
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

from support import _config, case

from ponos import speech

REPLY = """## Résultat

J'ai **corrigé** le bug dans [le module](https://example.com/x). Voici le code :

```python
def f():
    return 1
```

| a | b |
|---|---|
| 1 | 2 |

- premier point
- second point avec `du code`
"""


@case
def a_reply_loses_its_markup_its_code_and_its_tables() -> None:
    said = speech.clean(REPLY, "fr")
    lines = said.split("\n")
    assert "Résultat." in lines
    assert "J'ai corrigé le bug dans le module. Voici le code :" in lines
    assert lines.count("Je t'ai mis le code à l'écran.") == 1, "a block is said once, not per line"
    assert lines.count("Je t'ai mis un tableau à l'écran.") == 1
    assert "premier point." in lines and "second point avec du code." in lines
    for noise in ("def f", "return", "|", "```", "**", "http", "#"):
        assert noise not in said, noise


@case
def a_bare_link_is_a_link_and_the_english_is_said_in_english() -> None:
    said = speech.clean("See https://example.com/a?b=1 now.\n\n```\nx\n```", "en-US")
    assert said == "See a link now.\nI put the code on screen."
    assert speech.clean("", "fr") == ""


@case
def sentences_are_cut_at_their_ends_and_a_long_one_at_a_comma() -> None:
    assert speech.sentences("Un. Deux ! Trois ?\nQuatre") == ["Un.", "Deux !", "Trois ?", "Quatre"]
    long = ", ".join(["des mots qui se suivent"] * 20) + "."
    pieces = speech.sentences(long)
    assert len(pieces) > 1 and all(len(piece) <= speech.LONGEST_SENTENCE for piece in pieces)


@case
def a_long_reply_is_cut_short_and_points_at_the_screen() -> None:
    text = " ".join(f"Phrase numéro {n} qui dit assez de choses." for n in range(60))
    planned = speech.plan(text, "fr")
    assert planned[-1] == "Je t'ai mis le détail à l'écran."
    assert sum(len(sentence) for sentence in planned[:-1]) <= speech.SPOKEN_LIMIT
    short = speech.plan("Bonjour. Ça va ?", "fr")
    assert short == ["Bonjour.", "Ça va ?"], "a short reply is read whole"


@case
def the_plan_of_a_growing_text_only_ever_extends() -> None:
    """What was spoken of the start of a reply is never taken back by its end."""
    text = REPLY + "\nEt voilà la conclusion, en une phrase. Merci !"
    whole = speech.plan(text, "fr")
    held: list[str] = []
    for end in range(1, len(text) + 1):
        part = speech.plan(text[:end], "fr", final=False)
        assert part == whole[: len(part)], (text[:end], part)
        held = part
    assert held, "something was said before the end"
    assert speech.plan("Bonjour, je sui", "fr", final=False) == [], "half a sentence waits"
    assert speech.plan("Bonjour, je sui", "fr") == ["Bonjour, je sui."]


class _Voice:
    spoken: list[str] = []

    @classmethod
    def load(cls, path: str) -> _Voice:
        return cls()

    def synthesize_wav(self, text: str, sound: wave.Wave_write, syn_config: Any = None) -> None:
        _Voice.spoken.append(f"{text}|{syn_config.length_scale}")
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(16000)
        sound.writeframes(b"\x00\x00" * 160)


@contextmanager
def _piper() -> Iterator[None]:
    """A `piper` that is there, and a voice that never has to be downloaded."""
    fake = types.ModuleType("piper")
    fake.__spec__ = ModuleSpec("piper", None)
    fake.PiperVoice = _Voice  # type: ignore[attr-defined]
    fake.SynthesisConfig = lambda **kept: types.SimpleNamespace(**kept)  # type: ignore[attr-defined]
    before = sys.modules.get("piper")
    ensure, voices = speech.ensure, dict(speech._voices)
    sys.modules["piper"] = fake
    speech.ensure = lambda name: Path(f"/nowhere/{name}.onnx")
    speech._voices.clear()
    _Voice.spoken = []
    try:
        yield
    finally:
        speech.ensure = ensure
        speech._voices.clear()
        speech._voices.update(voices)
        if before is None:
            del sys.modules["piper"]
        else:
            sys.modules["piper"] = before


@case
def without_piper_the_voice_says_why_and_nothing_breaks() -> None:
    settings = _config("").speech
    original = speech.available
    speech.available = lambda: False
    try:
        assert "Piper" in speech.refusal(settings)
        try:
            speech.synthesize(settings, "Bonjour.", "fr")
        except speech.Unavailable as error:
            assert "piper-tts" in str(error)
        else:
            raise AssertionError("a voice spoke with no Piper")
    finally:
        speech.available = original
    off = _config(speech={"enabled": False}).speech
    assert "speech.enabled" in speech.refusal(off)


@case
def a_sentence_is_spoken_in_the_voice_of_its_language_at_the_speed_asked() -> None:
    settings = _config(speech={"speed": 200, "voice_en": "en_GB-alan-medium"}).speech
    with _piper():
        sound = speech.synthesize(settings, "Bonjour **tout** le monde.", "fr-FR")
        assert sound[:4] == b"RIFF" and b"WAVE" in sound[:12]
        speech.synthesize(settings, "Hello.", "en")
        assert _Voice.spoken == ["Bonjour tout le monde.|0.5", "Hello.|0.5"]
        assert set(speech._voices) == {"fr_FR-siwis-medium", "en_GB-alan-medium"}
        try:
            speech.synthesize(settings, "```\ncode\n```", "xx")
        except ValueError:
            raise AssertionError("a block of code is said as 'on screen', not refused") from None
        try:
            speech.synthesize(settings, "   ", "fr")
        except ValueError:
            pass
        else:
            raise AssertionError("nothing to say was synthesised")


@case
def a_voice_is_found_on_the_catalogue_by_its_name() -> None:
    model, described = speech.locate("fr_FR-siwis-medium")
    assert model.endswith("/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx")
    assert described == model + ".json"
    try:
        speech.locate("../../etc/passwd")
    except speech.SpeechError:
        pass
    else:
        raise AssertionError("a path was taken for a voice name")
