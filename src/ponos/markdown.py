"""Markdown, turned into Notion blocks.

Only what an agent actually writes in a plan: headings, lists, checkboxes,
quotes, code fences, dividers, paragraphs, and inline bold, italic, code and
links. Nested lists are flattened — a plan reads perfectly well flat, and one
level of children would double the size of this file for very little.

Anything unrecognised falls through as a paragraph, which is the right failure:
the text always reaches the page, at worst without its formatting.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

# Notion rejects a code block whose language it does not know.
LANGUAGES = {
    "bash",
    "c",
    "c++",
    "c#",
    "css",
    "diff",
    "docker",
    "go",
    "graphql",
    "html",
    "java",
    "javascript",
    "json",
    "kotlin",
    "makefile",
    "markdown",
    "php",
    "python",
    "ruby",
    "rust",
    "shell",
    "sql",
    "swift",
    "toml",
    "typescript",
    "xml",
    "yaml",
}
ALIASES = {"sh": "shell", "js": "javascript", "ts": "typescript", "py": "python", "yml": "yaml"}

INLINE = re.compile(
    r"\*\*(?P<bold>.+?)\*\*"
    r"|`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)"
    r"|(?<!\*)\*(?P<italic>[^*]+)\*(?!\*)"
)
MAX_CONTENT = 1900
MAX_BLOCKS = 100
MAX_PIECES = 100


def _text(
    content: str, *, bold: bool = False, italic: bool = False, code: bool = False, url: str = ""
) -> list[dict[str, Any]]:
    """One run of text, in as many pieces as Notion needs to take all of it.

    Notion caps a piece of rich text, not the block that holds it: a long run is
    split, never cut, and every piece keeps the run's annotations and link.
    """
    pieces: list[dict[str, Any]] = []
    for start in range(0, max(len(content), 1), MAX_CONTENT):
        item: dict[str, Any] = {
            "type": "text",
            "text": {"content": content[start : start + MAX_CONTENT]},
        }
        if url:
            item["text"]["link"] = {"url": url}
        annotations = {"bold": bold, "italic": italic, "code": code}
        if any(annotations.values()):
            item["annotations"] = annotations
        pieces.append(item)
    return pieces


def inline(line: str) -> list[dict[str, Any]]:
    """A line of markdown, as Notion rich text."""
    parts: list[dict[str, Any]] = []
    position = 0
    for match in INLINE.finditer(line):
        if match.start() > position:
            parts += _text(line[position : match.start()])
        if match.group("bold"):
            parts += _text(match.group("bold"), bold=True)
        elif match.group("code"):
            parts += _text(match.group("code"), code=True)
        elif match.group("label"):
            parts += _text(match.group("label"), url=match.group("url"))
        elif match.group("italic"):
            parts += _text(match.group("italic"), italic=True)
        position = match.end()
    if position < len(line):
        parts += _text(line[position:])
    return parts or _text("")


def _block(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: payload}


def _blocks(kind: str, rich_text: list[dict[str, Any]], **payload: Any) -> list[dict[str, Any]]:
    """A block whose text Notion would refuse in one, as successive blocks of its kind.

    Past a hundred pieces of rich text, a block is turned away whole; the rest
    goes on in the next block, so that the text still reaches the page entire.
    """
    return [
        _block(kind, {"rich_text": rich_text[start : start + MAX_PIECES], **payload})
        for start in range(0, len(rich_text), MAX_PIECES)
    ]


def to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        index += 1

        if not line:
            continue

        if line.startswith("```"):
            language = ALIASES.get(line[3:].strip().lower(), line[3:].strip().lower())
            body: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1  # the closing fence
            blocks += _blocks(
                "code",
                _text("\n".join(body)),
                language=language if language in LANGUAGES else "plain text",
            )
            continue

        if set(line) <= {"-", "*", "_"} and len(line) >= 3:
            blocks.append(_block("divider", {}))
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            blocks += _blocks(f"heading_{level}", inline(heading.group(2)))
            continue

        todo = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.*)$", line)
        if todo:
            blocks += _blocks("to_do", inline(todo.group(2)), checked=todo.group(1).lower() == "x")
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", line)
        if bullet:
            blocks += _blocks("bulleted_list_item", inline(bullet.group(1)))
            continue

        numbered = re.match(r"^\d+[.)]\s+(.*)$", line)
        if numbered:
            blocks += _blocks("numbered_list_item", inline(numbered.group(1)))
            continue

        if line.startswith("> "):
            blocks += _blocks("quote", inline(line[2:]))
            continue

        # A table would need its own block type and a fixed column count; as a
        # paragraph the row still reads, pipes and all.
        blocks += _blocks("paragraph", inline(line))

    return blocks


def chunked(blocks: list[dict[str, Any]], size: int = MAX_BLOCKS) -> list[list[dict[str, Any]]]:
    """Notion accepts at most 100 blocks per append."""
    return [blocks[index : index + size] for index in range(0, len(blocks), size)] or [[]]


# -- and back again ----------------------------------------------------------


def _rich(block: dict[str, Any], kind: str) -> str:
    """The text of one block, whichever end of the wire it came from.

    Notion hands a piece of rich text back with `plain_text` on it; a block this
    module has just *built* carries `text.content` instead. Reading both is what
    lets `plain` serve the two callers it has — flattening a page the API
    returned, and writing down blocks the live report made.
    """
    return "".join(
        part.get("plain_text") or (part.get("text") or {}).get("content", "")
        for part in block.get(kind, {}).get("rich_text", [])
    )


def plain(block: dict[str, Any]) -> str:
    """One Notion block, as the markdown line it came from.

    The return journey, and it lives here rather than in the client because a
    block is the shape a *page* is made of, not a shape the HTTP layer invented:
    the Notion client flattens a page with it, and a board made of files writes
    the live report's blocks down with it.

    Lossy where Notion is richer than a line of text — a toggle keeps its title
    and loses its fold, a table comes back empty — and that is the trade the
    whole conversion is: the text always reaches the reader, at worst without
    its furniture.
    """
    kind = block.get("type", "")
    if kind == "paragraph":
        return _rich(block, kind)
    if kind in ("heading_1", "heading_2", "heading_3"):
        return f"{'#' * int(kind[-1])} {_rich(block, kind)}"
    if kind == "bulleted_list_item":
        return f"- {_rich(block, kind)}"
    if kind == "numbered_list_item":
        return f"1. {_rich(block, kind)}"
    if kind == "to_do":
        done = block.get(kind, {}).get("checked")
        return f"- [{'x' if done else ' '}] {_rich(block, kind)}"
    if kind in ("quote", "callout"):
        return f"> {_rich(block, kind)}"
    if kind == "toggle":
        return _rich(block, kind)
    if kind == "code":
        language = block.get(kind, {}).get("language", "")
        return f"```{language}\n{_rich(block, kind)}\n```"
    if kind == "divider":
        return "---"
    if kind in ("image", "file", "pdf"):
        return attached(block)
    if kind == "bookmark":
        return str(block.get(kind, {}).get("url", ""))
    if kind == "child_page":
        return f"[sub-page: {block.get(kind, {}).get('title', '')}]"
    if kind in ("table", "table_row", "column_list", "column"):
        return ""
    return _rich(block, kind)


# What `plain` and `to_blocks` carry both ways without changing it: the block is
# the same block once it has been through the text and back.
ROUND_TRIP = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "quote",
    "code",
    "divider",
}
# Blocks that only hold the ones that count: a table row or a column is lost
# with its table or its column list, which is said once.
HOLDERS = {"table_row", "column"}


def lost(block: dict[str, Any]) -> list[str]:
    """What writing this block back as Markdown would drop, by name.

    The other half of `plain`'s docstring: that one says the conversion is
    lossy, this one says *where*, so that a page is never rewritten from its
    text without having been told what that costs. A block that survives the
    trip answers nothing. The names are the console's to say in words: a block
    type as Notion spells it (`toggle`, `child_database`…), or one of the four
    things a line of rich text carries that `plain` reads past — `mention`,
    `equation`, `link` and `formatting`.
    """
    kind = block.get("type", "")
    if kind in HOLDERS:
        return []
    if kind not in ROUND_TRIP:
        return [kind or "unknown"]
    found: list[str] = []
    for part in block.get(kind, {}).get("rich_text", []):
        if part.get("type") in ("mention", "equation"):
            found.append(part["type"])
        elif part.get("href"):
            found.append("link")
        notes = part.get("annotations") or {}
        coloured = notes.get("color") not in (None, "default")
        if coloured or any(value for name, value in notes.items() if name != "color"):
            found.append("formatting")
    return found


def attached(block: dict[str, Any]) -> str:
    """An image, a file or a PDF on the page, as one line naming it.

    Never its URL. A file Notion keeps is behind an address signed for an hour,
    and that address cut off its signature — which is what this line used to
    carry — answers 403 from the start: a link nobody can open, in the prompt
    as on the console. What is written instead is what the file *is* (its
    caption, else its name) and which block holds it, which is everything a
    session needs to know there is a picture, and everything the console needs
    to ask the board for a fresh address when it draws one: `/api/files/<block>`.

    The sentence is the console's to recognise, `ATTACHED` here and in
    `markdown.tsx`; a block without an id — one this module built — has nothing
    to point at and is only named.
    """
    kind = block.get("type", "")
    payload = block.get(kind) or {}
    source = (payload.get("external") or {}).get("url") or (payload.get("file") or {}).get(
        "url", ""
    )
    caption = "".join(part.get("plain_text", "") for part in payload.get("caption", [])).strip()
    name = urllib.parse.unquote(urllib.parse.urlsplit(source).path.rsplit("/", 1)[-1])
    label = " ".join((caption or name).split())
    said = f"{kind} attached to the ticket{': ' + label if label else ''}"
    identifier = str(block.get("id", "")).replace("-", "")
    return f"[{said} (Notion block {identifier})]" if identifier else f"[{said}]"


# The line `attached` writes, as the console reads it back.
ATTACHED = re.compile(
    r"^\[(?P<kind>image|file|pdf) attached to the ticket(?:: (?P<label>.*))?"
    r" \(Notion block (?P<block>[0-9a-f]{32})\)\]$"
)
