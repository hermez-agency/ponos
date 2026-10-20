"""Passwords and tokens, kept out of what a ticket says.

An answer typed at a ticket becomes a Notion comment, and a comment stays: it
is read by every run after, by whoever the page is shared with, and nothing in
the runner ever deletes one. The day an answer carried a password in clear, it
stayed on the page for as long as the page did. So the three roads by which a
person's words reach a ticket — the console's discussion, its decisions, and a
reply from a phone — pass through `masked` first, and what it hides never
reaches the page, the live stream or a log line.

What it looks for is narrow on purpose. A comment is full of long hexadecimal
strings that are no secret at all — a commit, a session, a page id — and a mask
that ate those would make every report unreadable. So it only knows two kinds
of thing: a value somebody *labelled* as one (« mot de passe : … », `token=…`),
and tokens whose shape their issuer made recognisable on purpose (`ghp_`,
`sk-ant-`, `npm_`, a private key block…). A secret with neither is not found,
and that is the honest limit: the console warns before sending, but only about
what it can see.

The same patterns are written a second time in `frontend/src/lib/secrets.ts`,
which is what warns before the message leaves the page; a test keeps the two
lists identical.
"""

from __future__ import annotations

import re

# What a hidden value is replaced by: no word, so that it reads in any language.
MASK = "••••••"

# Tokens that say what they are by their shape alone.
TOKENS: tuple[str, ...] = (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
    r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    r"\bgithub_pat_[A-Za-z0-9_]{30,}",
    r"\bglpat-[A-Za-z0-9_-]{20,}",
    r"\bsk-[A-Za-z0-9_-]{20,}",
    r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
    r"\bnpm_[A-Za-z0-9]{30,}",
    r"\b(?:ntn|secret)_[A-Za-z0-9]{30,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
)

# The words a person puts in front of a secret, in the two languages spoken here.
LABELS = (
    r"passwords?|passwd|pwd|pass ?phrase|mots? de passe|mdp|"
    r"tokens?|jetons?|secrets?|api[ _-]?keys?|cl[ée]s? (?:d['’])?api|access[ _-]?keys?|"
    r"credentials?"
)

# A labelled value: the label, up to four words naming what it is for
# (« le mot de passe npm de l'agence »), then `:` or `=` — or `is` / `est`, in
# which case the value has to look like a secret, a digit or a sign in it,
# since « le token est expiré » hides nothing.
LABELLED = re.compile(
    rf"\b(?:{LABELS})\b(?:[ \t]+[^\s:=]+){{0,4}}?"
    r"(?:[ \t]*[:=][ \t]*|[ \t]+(?:is|est)[ \t]+(?:[:=][ \t]*)?)"
    r"[\"'`«“]?[ \t]*(?P<value>[^\s\"'`»”]{4,})",
    re.IGNORECASE,
)

# A password inside an address: https://user:password@host.
IN_URL = re.compile(r"(?<=://)(?P<user>[^\s/:@]+):(?P<value>[^\s/@]+)(?=@)")

SHAPED = re.compile("|".join(f"(?:{pattern})" for pattern in TOKENS))

# What the console warns about, by kind, so that the list stays short.
KINDS = ("token", "password", "address")


def _plain(value: str) -> bool:
    """A word rather than a secret: letters only, the way a sentence goes on."""
    return value.isalpha()


def found(text: str) -> list[str]:
    """The kinds of secret in a text, in the order of `KINDS`; empty when none."""
    kinds = set()
    if SHAPED.search(text):
        kinds.add("token")
    if any(not _skipped(match) for match in LABELLED.finditer(text)):
        kinds.add("password")
    if IN_URL.search(text):
        kinds.add("address")
    return [kind for kind in KINDS if kind in kinds]


def _skipped(match: re.Match[str]) -> bool:
    """A labelled value said with `is`/`est` that is only a word: not a secret."""
    separator = match.group(0)[: match.start("value") - match.start(0)]
    return not re.search(r"[:=]", separator) and _plain(match.group("value").rstrip(".,;!?"))


def masked(text: str) -> str:
    """The text with every secret `found` sees replaced by `MASK`."""
    text = SHAPED.sub(MASK, text)
    text = IN_URL.sub(lambda match: f"{match.group('user')}:{MASK}", text)

    def hide(match: re.Match[str]) -> str:
        if _skipped(match) or match.group("value").startswith(MASK):
            return match.group(0)
        start = match.start("value") - match.start(0)
        # The sentence's own comma stays: « est ••••••, publie » still reads.
        # One sign of the password may show with it, which tells nothing.
        value = match.group("value")
        kept = value[len(value.rstrip(".,;")) :]
        return match.group(0)[:start] + MASK + kept

    return LABELLED.sub(hide, text)
