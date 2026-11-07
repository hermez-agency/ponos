"""`memory.py`: what Ponos remembers from one session to the next."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from support import case

from ponos import memory, prompt, question

COMMON: dict[str, Any] = dict(title="t", body="b", repo="/r", branch="br", base="main", url="u")


@case
def an_accepted_memory_reaches_its_project_and_no_other(state_home: Path) -> None:
    made = memory.propose("The client reads French only.", "project", "proj-x", "ticket", "t1")
    assert made and made["status"] == memory.PROPOSED
    assert memory.for_prompt("proj-x") == [], "a proposal is not read by anyone"

    memory.accept(made["id"])
    memory.add("It is a ROG Ally X, not a Steam Deck.", "reference")  # global

    mine = memory.for_prompt("proj-x")
    assert mine[0] == "[project] The client reads French only."
    assert "[reference] It is a ROG Ally X, not a Steam Deck." in mine
    assert memory.for_prompt("proj-y") == ["[reference] It is a ROG Ally X, not a Steam Deck."]

    text = prompt.build(prompt.DEFAULT, project="X", memories=mine, **COMMON)
    other = prompt.build(
        prompt.DEFAULT, project="Y", memories=memory.for_prompt("proj-y"), **COMMON
    )
    assert "# What you remember" in text and "French only" in text
    assert "French only" not in other and "ROG Ally X" in other
    assert "MEMORY:" in text, "every ticket is told how to propose a memory"


@case
def a_refused_proposal_is_not_proposed_again(state_home: Path) -> None:
    first = memory.propose("Never deploy on Fridays.", "preference")
    assert first
    memory.refuse(first["id"])
    assert memory.propose("never deploy on fridays", "preference") is None
    assert memory.listing(status=memory.REFUSED)[0]["id"] == first["id"]
    assert memory.propose("   ") is None
    try:
        memory.add("NEVER deploy on Fridays!")
    except ValueError:
        pass
    else:
        raise AssertionError("a known fact is not added twice")


@case
def the_auto_accept_setting_lifts_the_wait(state_home: Path) -> None:
    assert memory.options()[memory.AUTO_ACCEPT] is False
    memory.set_option(memory.AUTO_ACCEPT, True)
    made = memory.propose("Prefers short reports.", "preference")
    assert made and made["status"] == memory.ACCEPTED
    assert memory.for_prompt() == ["[preference] Prefers short reports."]


@case
def a_memory_is_filtered_edited_and_deleted(state_home: Path) -> None:
    one = memory.add("Likes tabs.", "preference", "proj-x")
    two = memory.add("Owner is Léa.", "person")
    assert [m["id"] for m in memory.listing(scope="proj-x")] == [one["id"]]
    assert [m["id"] for m in memory.listing(scope="")] == [two["id"]]
    assert [m["id"] for m in memory.listing(kind="person")] == [two["id"]]
    assert [m["id"] for m in memory.listing(search="tabs")] == [one["id"]]
    assert memory.listing(search="100%") == []

    changed = memory.edit(one["id"], text="Likes spaces.", scope="")
    assert changed["text"] == "Likes spaces." and changed["scope"] == ""
    memory.delete(two["id"])
    assert [m["id"] for m in memory.listing()] == [one["id"]]
    try:
        memory.delete(two["id"])
    except ValueError:
        pass
    else:
        raise AssertionError("deleting twice is told")


@case
def the_prompt_carries_a_bounded_number_of_characters(state_home: Path) -> None:
    for number in range(60):
        memory.add(f"Fact number {number} " + "x" * 200)
    lines = memory.for_prompt()
    assert sum(len(line) for line in lines[:-1]) <= memory.PROMPT_LIMIT
    assert lines[-1].startswith("(") and "left out" in lines[-1]
    assert len(memory.clean("y" * 1000)) == memory.FACT_LIMIT


@case
def a_session_proposes_memories_on_the_lines_above_its_result() -> None:
    answer = (
        "Done.\n"
        "CAVEAT: not run on Windows\n"
        "LESSON: Run the tests with TMPDIR.\n"
        "MEMORY: preference | global | Answers in French.\n"
        "MEMORY: project | The API is versioned in the URL.\n"
        "RESULT: ok — done"
    )
    said = question.memories(answer)
    assert said == [
        "preference | global | Answers in French.",
        "project | The API is versioned in the URL.",
    ]
    assert memory.parse(said[0]) == ("preference", "global", "Answers in French.")
    assert memory.parse(said[1]) == ("project", "project", "The API is versioned in the URL.")
    assert memory.parse("nonsense | global | Fact.") == ("preference", "global", "Fact.")
    assert memory.parse("project |") is None
    assert question.caveats(answer) == ["not run on Windows"]
    assert question.lesson(answer) == "Run the tests with TMPDIR."
    assert "MEMORY" not in question.prose(answer)
    assert question.memories("Done.\nMEMORY: a | b | c\nSome prose.\nRESULT: ok") == []


@case
def the_assistants_memory_files_are_imported_once(state_home: Path) -> None:
    folder = state_home / "memory"
    folder.mkdir(parents=True)
    (folder / "MEMORY.md").write_text("- [x](x.md) — index\n")
    (folder / "rog.md").write_text(
        "---\nname: rog\ndescription: It is a ROG Ally X\nmetadata:\n  type: user\n---\n\nbody\n"
    )
    (folder / "style.md").write_text(
        "---\nname: style\ndescription: Short reports\nmetadata:\n  type: feedback\n---\n"
    )
    (folder / "bare.md").write_text("no frontmatter")
    assert [path.name for path in memory.importable(folder)] == ["bare.md", "rog.md", "style.md"]
    assert memory.import_files(folder) == 2
    assert memory.import_files(folder) == 0
    assert [path.name for path in memory.importable(folder)] == ["bare.md"]
    kinds = {item["text"]: item["kind"] for item in memory.listing()}
    assert kinds == {"It is a ROG Ally X": "person", "Short reports": "preference"}
    assert all(item["source"] == "chat" for item in memory.listing())
    assert memory.files_folder("/home/a/work").parts[-2] == "-home-a-work"
