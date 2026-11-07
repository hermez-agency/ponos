"""`library.py`: the reference files sessions are told about."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from support import case

from ponos import library, prompt
from ponos.web import attachments

COMMON: dict[str, Any] = dict(title="t", body="b", repo="/r", branch="br", base="main", url="u")
MB = 1024 * 1024


def _keep(name: str, data: bytes = b"%PDF-1.4 hello", **fields: Any) -> dict[str, Any]:
    return library.save(name, io.BytesIO(data), len(data), 5 * MB, **fields)


@case
def a_pdf_for_one_project_is_in_its_prompt_and_in_no_other(state_home: Path) -> None:
    kept = _keep("charter.pdf", description="The brand charter", project_list=["projx"])
    _keep("cv.pdf", description="Everyone's CV")  # every project

    mine = library.for_prompt("proj-x")
    assert any("charter.pdf — The brand charter" in line for line in mine)
    assert any("cv.pdf" in line for line in mine)
    other = library.for_prompt("proj-y")
    assert not any("charter.pdf" in line for line in other)
    assert not any("charter.pdf" in line for line in library.for_prompt(""))

    # The path in the prompt is a file the session can read.
    line = next(item for item in mine if "charter.pdf" in item)
    assert Path(line.split(" — ")[0]).read_bytes() == b"%PDF-1.4 hello"
    assert library.path_of(kept).is_file()

    text = prompt.build(prompt.DEFAULT, project="X", library=mine, **COMMON)
    away = prompt.build(prompt.DEFAULT, project="Y", library=other, **COMMON)
    assert "# Reference files" in text and "charter.pdf" in text
    assert "charter.pdf" not in away


@case
def files_are_renamed_moved_filtered_and_deleted(state_home: Path) -> None:
    kept = _keep("quote.pdf", tag_list="Contract, 2026")
    assert kept["tags"] == ["contract", "2026"]
    assert [item["id"] for item in library.listing(tag="contract")] == [kept["id"]]
    assert library.listing(search="QUOTE") and not library.listing(search="invoice")

    library.edit(kept["id"], name="devis.pdf", project_list=["proj-x"], description="A quote")
    found = library.get(kept["id"])
    assert (found["name"], found["projects"]) == ("devis.pdf", ["projx"])
    assert library.listing(project="proj-y") == []
    assert library.listing(project="proj-x")

    try:
        library.edit(kept["id"], name="devis.png")
    except ValueError:
        pass
    else:
        raise AssertionError("a rename keeps the extension")

    count, size = library.used()
    assert (count, size) == (1, len(b"%PDF-1.4 hello"))
    path = library.path_of(found)
    library.delete(kept["id"])
    assert not path.exists() and library.used()[0] == 0


@case
def a_file_past_the_limit_or_of_a_forbidden_kind_is_refused(state_home: Path) -> None:
    for name, data, limit, error in (
        ("page.html", b"<script>", MB, ValueError),
        ("big.pdf", b"x" * 20, 10, attachments.TooLarge),
        ("empty.pdf", b"", MB, ValueError),
    ):
        try:
            library.save(name, io.BytesIO(data), len(data), limit)
        except error:
            pass
        else:
            raise AssertionError(name)
    assert library.used()[0] == 0
    assert not [path for path in library.folder().iterdir()], "nothing was left on the disk"

    # A length that lied: cut short, and what was written goes.
    try:
        library.save("cut.pdf", io.BytesIO(b"abc"), 10, MB)
    except ValueError:
        pass
    assert not list(library.folder().iterdir())


@case
def a_prompt_lists_only_what_fits(state_home: Path) -> None:
    for number in range(60):
        _keep(f"file-{number}.txt", b"x", description="d" * 200)
    lines = library.for_prompt("p")
    assert sum(len(line) for line in lines[:-1]) <= library.PROMPT_LIMIT
    assert "left out" in lines[-1]


@case
def a_conversation_attachment_is_kept_by_copy(state_home: Path) -> None:
    state_home.mkdir(parents=True, exist_ok=True)
    source = state_home / "shot.png"
    source.write_bytes(b"\x89PNG data")
    kept = library.keep_file(source, "shot.png", MB, project_list=["projx"])
    assert library.path_of(kept).read_bytes() == b"\x89PNG data"
    assert source.exists(), "the attachment stays where it was"
    assert kept["kind"] == "image" and kept["projects"] == ["projx"]
