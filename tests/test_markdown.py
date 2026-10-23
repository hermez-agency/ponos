"""`markdown.py`: Markdown turned into Notion blocks."""

from __future__ import annotations

from support import case

from ponos import markdown

# -- markdown to Notion blocks -----------------------------------------------


@case
def markdown_keeps_its_shape_as_notion_blocks():
    blocks = markdown.to_blocks(
        "# Plan\n\nUn **paragraphe**.\n\n## Étapes\n- point\n- [x] fait\n1. numéroté\n\n"
        "> citation\n\n---\n\n```python\nprint(1)\n```\n"
    )
    assert [block["type"] for block in blocks] == [
        "heading_1",
        "paragraph",
        "heading_2",
        "bulleted_list_item",
        "to_do",
        "numbered_list_item",
        "quote",
        "divider",
        "code",
    ]
    assert blocks[4]["to_do"]["checked"] is True
    assert blocks[8]["code"]["language"] == "python"


@case
def an_unknown_code_language_does_not_break_the_publish():
    """Notion rejects a language it does not know; we fall back rather than fail."""
    blocks = markdown.to_blocks("```klingon\nnuqneH\n```")
    assert blocks[0]["code"]["language"] == "plain text"
    blocks = markdown.to_blocks("```sh\nls\n```")
    assert blocks[0]["code"]["language"] == "shell", "aliases resolve"


@case
def inline_formatting_becomes_annotations_and_links():
    parts = markdown.inline("Un **gras**, un [lien](https://x.fr), et `du code`")
    assert parts[1]["annotations"]["bold"] is True
    assert parts[3]["text"]["link"] == {"url": "https://x.fr"}
    assert parts[5]["annotations"]["code"] is True
    # Plain text carries no annotations object at all.
    assert "annotations" not in parts[0]


@case
def anything_unrecognised_still_reaches_the_page():
    blocks = markdown.to_blocks("| a | b |\n| - | - |\n| 1 | 2 |")
    assert all(block["type"] == "paragraph" for block in blocks)
    assert len(blocks) == 3, "a table degrades to rows, it does not vanish"


@case
def blocks_are_chunked_below_notions_append_limit():
    blocks = markdown.to_blocks("\n\n".join(f"ligne {index}" for index in range(250)))
    batches = markdown.chunked(blocks)
    assert len(batches) == 3
    assert all(len(batch) <= 100 for batch in batches)
    assert sum(len(batch) for batch in batches) == len(blocks)
    assert markdown.chunked([]) == [[]]


@case
def a_long_text_is_split_into_pieces_and_never_cut():
    """Notion caps one piece of rich text, not the block: nothing past it is lost."""
    body = "".join(f"ligne {index:05d}\n" for index in range(834))[:10_000]
    for text in (f"```python\n{body}\n```", body.replace("\n", " ").strip()):
        blocks = markdown.to_blocks(text)
        assert len(blocks) == 1
        assert markdown.plain(blocks[0]) == text
        parts = blocks[0][blocks[0]["type"]]["rich_text"]
        assert all(len(part["text"]["content"]) <= markdown.MAX_CONTENT for part in parts)


@case
def past_a_hundred_pieces_the_text_goes_on_in_the_next_block():
    body = "x" * (markdown.MAX_CONTENT * 250)
    blocks = markdown.to_blocks(f"```python\n{body}\n```\n\nfin")
    assert [block["type"] for block in blocks] == ["code"] * 3 + ["paragraph"]
    assert all(len(block["code"]["rich_text"]) <= 100 for block in blocks[:3])
    assert all(block["code"]["language"] == "python" for block in blocks[:3])
    assert "".join(markdown._rich(block, "code") for block in blocks[:3]) == body
