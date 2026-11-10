"""A ticket's result: the deliverable, kept apart from the account of the session.

A ticket used to come back as one part, « What was done », where the post a
writing ticket asked for sat under the runner's line about the session and above
its history — to copy the post, you copied around the rest. So a ticket has
three parts now (see tickets.py): the **mission**, what is asked; the
**result**, what was asked for, ready to use; and the **journal**, the session's
report, its tries and what they cost.

**Where a session says it.** A ticket with no repository writes its deliverable
to `ANSWER.md`, as it always did: that file is the result, whole, and the
session's own message is the journal. A code ticket has no such file — a file
in the worktree would be committed with the rest — so its message carries the
result between two lines of their own, `<result>` and `</result>`, and the rest
of the message is its report. The runner adds to it what only it knows: the
files the branch touches, and where to read the diff.

**A result is versioned.** Every one written — by a session, by a hand in the
console, by a session asked for a change — is a row of `ticket_results`, and
the ticket's column holds the last of them. Nothing is ever overwritten.

**Tickets from before.** Their part « What was done » is cut once by the
migration (`legacy`): what the session handed over, on a ticket that ended
done, becomes the result; the runner's lines and the history stay the journal.
Anything it cannot tell apart stays journal, whole.

Nothing here imports anything but the standard library: `db.py`'s migration
reads `legacy`, and the database must open without the rest of the runner.
"""

from __future__ import annotations

import re

OPEN = "<result>"
CLOSE = "</result>"

# The block a code session writes its result in, on lines of their own.
_BLOCK = re.compile(r"^[ \t]*<result>[ \t]*\n(.*?)\n[ \t]*</result>[ \t]*$", re.S | re.M)

# Who wrote a version of a result.
SOURCES = ("session", "edit", "revision", "migration")


def extract(answer: str) -> tuple[str, str]:
    """The result a session wrote in its message, and the message without it.

    The last block wins: a session that quotes the format before writing its
    own is not taken at its quote. ("", answer) when there is none.
    """
    text = str(answer or "")
    found = list(_BLOCK.finditer(text))
    if not found:
        return "", text.strip()
    last = found[-1]
    rest = (text[: last.start()] + text[last.end() :]).strip()
    rest = re.sub(r"\n{3,}", "\n\n", rest)
    return last.group(1).strip(), rest


def without(answer: str) -> str:
    """A session's message without its result block: what its journal keeps."""
    return extract(answer)[1]


# The lines the runner writes on top of a session's report, in either language,
# as `ticket_page.report` wrote them — told apart from what the session said.
# Read without their asterisks: a page that went through a board and back lost
# its bold, and its blank lines with it.
_RESULT_LINE = re.compile(r"^(?:Result|Résultat)\s*:\s*(.*)$")
_PULL_REQUEST = re.compile(r"^Pull request\s*:")
_QUESTION = re.compile(r"^(?:The question it asks is in the comments|La question posée est dans)")
_TO_CHECK = re.compile(r"^(?:Left to check|Reste à vérifier)\s*:?$")
_HISTORY = re.compile(r"^#{1,3}\s+(?:History|Historique)\s*$", re.I)


def _bare(line: str) -> str:
    return line.replace("*", "").strip()


def legacy(done: str) -> tuple[str, str]:
    """A part « What was done » of before, as its result and its journal.

    The result is the session's own words — what `ANSWER.md` or its report
    said — on a ticket whose result line says ✅. Everything else, and every
    part that cannot be told apart, is the journal.
    """
    text = str(done or "").strip()
    if not text:
        return "", ""
    lines = text.splitlines()
    cut = next((index for index, line in enumerate(lines) if _HISTORY.match(line.strip())), None)
    report = lines[:cut] if cut is not None else lines
    start = next((index for index, line in enumerate(report) if line.strip()), None)
    first = _RESULT_LINE.match(_bare(report[start])) if start is not None else None
    if start is None or first is None or not first.group(1).strip().startswith("✅"):
        return "", text
    kept: list[str] = [report[start]]
    said: list[str] = []
    checking = False
    for line in report[start + 1 :]:
        bare = _bare(line)
        if checking and (not bare or bare.startswith("- ")):
            kept.append(line)
            continue
        checking = False
        if _PULL_REQUEST.match(bare) or _QUESTION.match(bare) or _TO_CHECK.match(bare):
            kept.append(line)
            checking = bool(_TO_CHECK.match(bare))
            continue
        said.append(line)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(said)).strip()
    if not result:
        return "", text
    journal = re.sub(r"\n{3,}", "\n\n", "\n\n".join(line for line in kept if line.strip()))
    if cut is not None:
        journal = f"{journal}\n\n" + "\n".join(lines[cut:]).strip()
    return result, journal.strip()


def excerpt(text: str, lines: int = 3, limit: int = 280) -> str:
    """The first lines of a result, as a card or a notification shows them.

    Plain words: the marks of Markdown that would be read as noise on a lock
    screen go — the hashes of a heading, the fences of code, a table's rules.
    """
    kept: list[str] = []
    for line in str(text or "").splitlines():
        said = plain_line(line)
        if not said:
            continue
        kept.append(said)
        if len(kept) >= lines:
            break
    joined = "\n".join(kept)
    if len(joined) > limit:
        joined = joined[: limit - 1].rstrip() + "…"
    return joined


_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)(.+?)\1")


def plain_line(line: str) -> str:
    """One line of Markdown, without its marks — "" for a line that is only marks."""
    said = line.strip()
    if not said or said.startswith("```") or re.fullmatch(r"[|:\-\s]+", said):
        return ""
    said = re.sub(r"^#{1,6}\s+", "", said)
    said = re.sub(r"^>\s?", "", said)
    said = re.sub(r"^[-*+]\s+(\[[ xX]\]\s+)?", "• ", said)
    said = _LINK.sub(lambda found: found.group(1), said)
    said = _EMPHASIS.sub(lambda found: found.group(2), said)
    if said.startswith("|"):
        said = " · ".join(cell.strip() for cell in said.strip("|").split("|") if cell.strip())
    return said.strip()


def code_appendix(stat: str, pull_request: str, *, files: str, diff: str) -> str:
    """What the runner adds under a code session's result: the files, the diff.

    `stat` is `git diff --stat` of the branch; `files` and `diff` the words of
    the heading and of the link, in the runner's language.
    """
    parts: list[str] = []
    stat = stat.strip("\n").rstrip()
    if stat.strip():
        parts.append(f"**{files}**\n\n```\n{stat}\n```")
    if pull_request.startswith("http"):
        parts.append(f"[{diff}]({pull_request.rstrip('/')}/files)")
    return "\n\n".join(parts)
