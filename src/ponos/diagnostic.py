"""A diagnostic: what its session is told, what it may reach, and what it hands back.

Born of a day spent in the console's chat on four sentences — « the controller
still does not work », « the Leadz chat does not work », « the emails do not
go out », an error in the console — each of which turned out to be something
nobody would have guessed: a ROG Ally X where a Steam Deck was assumed, a chat
still wired to OpenRouter after production had moved to Anthropic, a scheduler
that had never started. Without the investigation, each sentence would have
become a vague ticket, and a vague ticket becomes a fix made on a guess.

So the investigation is a ticket of its own (see kinds.py), and three choices
make it one a person can leave alone:

**It reads, and only reads.** Its session is given the repository to read and
never to change (the same road as a text: no worktree, no branch), and what
its project declares on its settings page — the admin MCP servers worth asking,
the machines it may open a shell on with a key of the vault, the production
addresses it may `curl`. Nothing in that list is a write access, and the prompt
says the rest: no commit, no deployment, no message sent.

**Its tickets are written by the session, created by the runner.** The session
knows what to fix; it does not get to decide how the board holds it. It writes
`FIXES.json` — each ticket's context, what is expected, when it is done and
what it must not touch, in four separate fields so that none can be forgotten
— and the runner creates them, in the diagnostic's project, as drafts unless
the project says Ready, each one « after » the diagnostic and after the fixes
it names: a relation the board waits on, not a sentence in a text. A file that
cannot be read creates nothing at all, rather than half a series.

**No cause, no ticket.** A session that did not find the cause stops blocked,
with what it ruled out and the question that would let it go on — and whatever
it may have left in `FIXES.json` is not read. A fix written for a cause nobody
proved is the very thing this ticket type exists to avoid.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import subtypes

# The file the session writes its fix tickets into, beside ANSWER.md.
FIXES = "FIXES.json"

# What a fix ticket may be: anything but another diagnostic, which would be a
# question passed on rather than answered.
FIX_KINDS = ("code", "writing", "external", "publication")

# A project's declarations, as the settings page sends them and `ponos.db` keeps
# them: no more of each than a person types by hand.
MOST = 20

# A machine reached over SSH: `user@host`, a port after a colon at most.
_ADDRESS = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+(?::\d{1,5})?$")
# A vault entry, as vault_store names one: an environment variable's name.
_ENTRY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# An MCP server, as Claude Code names it in `claude mcp list`.
_SERVER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:-]{0,63}$")


@dataclass(frozen=True)
class Host:
    """A machine a diagnostic may open a shell on, and the vault entry that opens it."""

    address: str
    entry: str = ""
    label: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"address": self.address, "entry": self.entry, "label": self.label}


@dataclass(frozen=True)
class Access:
    """What a project lets its diagnostics reach, and where their fix tickets land."""

    mcp: tuple[str, ...] = ()
    hosts: tuple[Host, ...] = ()
    urls: tuple[str, ...] = ()
    # Fix tickets straight in Ready rather than in the drafts.
    ready: bool = False

    def __bool__(self) -> bool:
        return bool(self.mcp or self.hosts or self.urls or self.ready)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mcp": list(self.mcp),
            "hosts": [host.as_dict() for host in self.hosts],
            "urls": list(self.urls),
            "ready": self.ready,
        }

    @property
    def entries(self) -> list[str]:
        """The vault entries the hosts name, each once."""
        return list(dict.fromkeys(host.entry for host in self.hosts if host.entry))


def _texts(value: object) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    if not isinstance(value, (list, tuple)):
        return []
    found: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in found:
            found.append(text)
    return found[:MOST]


def parse(raw: object) -> Access:
    """A project's declarations as `ponos.db` holds them — nothing readable is nothing.

    Lenient on the way in, since it is read at every diagnostic: an entry that
    does not have the shape of what it says is left out rather than refused
    here. `checked` is what refuses, when somebody saves.
    """
    if not isinstance(raw, Mapping):
        return Access()
    hosts: list[Host] = []
    for item in raw.get("hosts") or []:
        if not isinstance(item, Mapping):
            continue
        address = str(item.get("address") or "").strip()
        entry = str(item.get("entry") or "").strip()
        if not _ADDRESS.match(address) or (entry and not _ENTRY.match(entry)):
            continue
        hosts.append(Host(address, entry, " ".join(str(item.get("label") or "").split())))
    return Access(
        mcp=tuple(name for name in _texts(raw.get("mcp")) if _SERVER.match(name)),
        hosts=tuple(hosts[:MOST]),
        urls=tuple(url for url in _texts(raw.get("urls")) if _is_url(url)),
        ready=raw.get("ready") is True,
    )


def checked(raw: Mapping[str, Any]) -> Access:
    """What somebody saves, refused with the reason when one part of it is wrong."""
    for name in _texts(raw.get("mcp")):
        if not _SERVER.match(name):
            raise ValueError(f"“{name}” is not the name of an MCP server")
    for url in _texts(raw.get("urls")):
        if not _is_url(url):
            raise ValueError(f"“{url}” is not an http or https address")
    hosts = raw.get("hosts") or []
    if not isinstance(hosts, list):
        raise ValueError("hosts is a list")
    for item in hosts:
        if not isinstance(item, Mapping):
            raise ValueError("a host is an address and a vault entry")
        address = str(item.get("address") or "").strip()
        entry = str(item.get("entry") or "").strip()
        if not _ADDRESS.match(address):
            raise ValueError(f"“{address}” is not an SSH address (user@host)")
        if entry and not _ENTRY.match(entry):
            raise ValueError(f"“{entry}” is not the name of a vault entry")
    return parse(raw)


def _is_url(text: str) -> bool:
    return bool(re.match(r"^https?://[^\s/]+", text)) and " " not in text


# -- what the session is told ------------------------------------------------

PROMPT = """\
# This ticket is a diagnostic — find the cause, fix nothing

Somebody said that something does not work, or asked why it behaves as it \
does. Your work is to find out why, with proof, and to write the tickets that \
will fix it. Each of those tickets will be carried out by another session, \
alone, with nothing but what you write in it.

**Read only.** You may read everything you are given: the project's \
repository (`git fetch`, then read `origin/main` — `git show origin/main:<path>`, \
`git log`, `git blame` — not whatever branch the clone is on), its recent \
pull requests (`gh pr list --state all --limit 20`, `gh pr view`), Ponos's own \
state and logs (`ponos status`, `ponos history`, `ponos logs`), and the \
accesses listed under « What you may reach ». You change nothing, anywhere: \
no commit, no push, no pull request, no write in production — not a row, not \
a setting, not a file on a server —, no restart, no deployment, no email or \
message sent. A command that would change something is not run, even to test \
an idea: say what it would show instead.

How you investigate:
- Start from the symptom as it was said; observe it where you can (the \
production address, the logs, an admin tool), then follow it to what \
produces it.
- Every claim comes with its proof: a file and a line (`path/to/file.py:42`, \
as read on `origin/main`), an extract of a log, a command and what it \
answered. A hypothesis is said as one.
- Stop once the cause is proven: this is not an audit of the whole project.

What you hand back, once the cause is found:
1. `ANSWER.md` — the report, in four parts: **Symptom** (what was said, and \
what you observed of it); **Cause** (what is wrong, each proof with it: files \
and lines, log extracts, commands and their output); **What remains \
uncertain**; **Fixes** (one line per fix ticket, by its title).
2. `{fixes}` — the fix tickets, which the runner creates for you and links to \
this diagnostic. A JSON array, one object per ticket, in the order they are to \
be done:

   [{{"title": "...", "context": "...", "expected": "...", "done": "...", \
"out": "...", "type": "code", "subtype": "bug", "priority": 50, "after": []}}]

   - `title`: one line, what the ticket does.
   - `context`: what is broken, its cause and the proof — enough for a session \
that never saw this diagnostic. `expected`: what must change, and where \
(files, functions). `done`: how anybody checks that it is fixed — a test, a \
command, a page. `out`: what this ticket must not touch. Markdown, in the \
language of the ticket, each at the level of detail of a ticket written by \
hand. The four are required.
   - `type`: {kinds} — code unless the fix is not in a repository. `subtype`, \
for code only: {subtypes}. `priority`, optional: from 0 to 100.
   - `after`: the positions (from 0) of the fix tickets earlier in this array \
that this one cannot start before. Only real dependencies: two fixes that can \
be done in either order have none.
   - One ticket per change that can be reviewed on its own; often there is \
only one.

**If you cannot find the cause, stop.** Write neither `ANSWER.md` nor \
`{fixes}`, and end `RESULT: blocked`, `CATEGORY: question`, with — in your \
report — what you checked and what you ruled out, and as the question the \
precise thing that would let you go on (an access, a log, a fact only a \
person knows). Never write a fix for a cause you did not prove: a fix ticket \
written on a guess is worse than a question.
"""


def prompt(access: Access, variables: Mapping[str, list[str]] | None = None) -> str:
    """The section a diagnostic's session is given, with what its project lets it reach.

    `variables` are the names each vault entry of a host becomes in the
    session's environment — two for a login, one otherwise — and never a value.
    """
    return (
        PROMPT.format(
            fixes=FIXES,
            kinds=", ".join(FIX_KINDS),
            subtypes=", ".join(subtypes.KEYS),
        )
        + "\n"
        + reach(access, variables or {})
    )


def reach(access: Access, variables: Mapping[str, list[str]]) -> str:
    """« What you may reach »: the project's declarations, or the plain absence of any."""
    lines: list[str] = []
    if access.mcp:
        servers = ", ".join(f"`{name}`" for name in access.mcp)
        lines.append(
            f"- Admin MCP servers: {servers}. Call only their tools that read — health, "
            "recent errors, status, configuration, lists — never one that creates, "
            "changes, sends, pauses or deletes."
        )
    for host in access.hosts:
        named = f" ({host.label})" if host.label else ""
        given = variables.get(host.entry) or ([host.entry] if host.entry else [])
        if given:
            held = " and ".join(f"`${name}`" for name in given)
            opened = (
                f" — what opens it is in {held}: a private key goes into a file only you "
                "can read (`chmod 600`), used with `ssh -i`, and deleted when you are done"
            )
        else:
            opened = " — with the keys this machine already has"
        lines.append(
            f"- SSH: `{host.address}`{named}{opened}. Commands that read only: `cat`, `ls`, "
            "`ps`, `df`, `journalctl`, `systemctl status`, `docker ps`, `docker logs`…"
        )
    if access.urls:
        listed = ", ".join(access.urls)
        lines.append(
            f"- Production: {listed}. `curl` and GET requests only — never a POST, PUT, "
            "PATCH or DELETE, never a form submitted."
        )
    if not lines:
        return (
            "# What you may reach\n\n"
            "This project declares no access beyond its repository and Ponos itself "
            "(its settings page, Diagnostic, is where admin MCP servers, SSH hosts and "
            "production addresses are declared). Whatever you would need from outside "
            "and cannot reach is a question, not a guess.\n"
        )
    return "# What you may reach\n\n" + "\n".join(lines) + "\n"


# -- what the session hands back ---------------------------------------------


@dataclass
class Fix:
    """One fix ticket, as the session wrote it."""

    title: str
    context: str
    expected: str
    done: str
    out: str
    kind: str = "code"
    subtype: str = ""
    priority: int | None = None
    after: list[int] = field(default_factory=list)


def read_fixes(workdir: Path) -> tuple[list[Fix], str]:
    """The fix tickets a session left in its working directory, or why they cannot be read.

    No file is no fix — a cause can be found that nothing in a repository will
    fix. Anything else wrong refuses the whole file: a series created up to its
    first mistake is a series nobody can trust the order of.
    """
    path = workdir / FIXES
    if not path.is_file():
        return [], ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace") or "[]")
    except ValueError as error:
        return [], f"{FIXES} is not JSON: {error}"
    return fixes(raw)


def fixes(raw: object) -> tuple[list[Fix], str]:
    """The fix tickets out of the JSON a session wrote — see `read_fixes`."""
    if isinstance(raw, Mapping) and isinstance(raw.get("tickets"), list):
        raw = raw["tickets"]
    if not isinstance(raw, list):
        return [], f"{FIXES} is not an array of tickets"
    found: list[Fix] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            return [], f"ticket {index} of {FIXES} is not an object"
        texts = {
            name: str(item.get(name) or "").strip()
            for name in ("title", "context", "expected", "done", "out")
        }
        missing = [name for name, text in texts.items() if not text]
        if missing:
            return [], f"ticket {index} of {FIXES} has no {', '.join(missing)}"
        kind = str(item.get("type") or "code").strip().lower()
        if kind not in FIX_KINDS:
            return [], f"ticket {index} of {FIXES} is of type “{kind}”, not one of {FIX_KINDS}"
        subtype = str(item.get("subtype") or "").strip().lower() if kind == "code" else ""
        if subtype and subtype not in subtypes.KEYS:
            subtype = ""
        after = item.get("after") or []
        if not isinstance(after, list) or not all(
            isinstance(one, int) and not isinstance(one, bool) and 0 <= one < index for one in after
        ):
            return [], (
                f"ticket {index} of {FIXES} comes after something other than an earlier "
                "ticket of the array"
            )
        found.append(
            Fix(
                title=" ".join(texts["title"].split())[:200],
                context=texts["context"],
                expected=texts["expected"],
                done=texts["done"],
                out=texts["out"],
                kind=kind,
                subtype=subtype,
                priority=_priority(item.get("priority")),
                after=sorted(set(after)),
            )
        )
    return found, ""


def _priority(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, min(100, int(value)))


def body(fix: Fix, headings: Mapping[str, str], diagnostic: str = "") -> str:
    """A fix ticket's mission: its four parts under their headings, and where it comes from.

    `headings` holds the words of the four parts and of the last line, in the
    runner's language: `context`, `expected`, `done`, `out` and `from`.
    """
    parts = [
        f"### {headings['context']}\n\n{fix.context}",
        f"### {headings['expected']}\n\n{fix.expected}",
        f"### {headings['done']}\n\n{fix.done}",
        f"### {headings['out']}\n\n{fix.out}",
    ]
    if diagnostic:
        parts.append(f"*{headings['from']} {diagnostic}*")
    return "\n\n".join(parts)


def granted(access: Access, listed: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """The variables each host's vault entry becomes, by entry — read off the vault's listing.

    An entry the vault does not hold is left out: the session is told only of
    what it is given.
    """
    by_name = {str(entry.get("name") or ""): entry for entry in listed}
    given: dict[str, list[str]] = {}
    for name in access.entries:
        entry = by_name.get(name)
        if entry is None:
            continue
        given[name] = [str(variable) for variable in entry.get("variables") or [name]]
    return given
