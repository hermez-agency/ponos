"""`skills.py`: les skills Claude Code que Ponos pose dans le worktree d'une session."""

from __future__ import annotations

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path

from support import case

from ponos import skills

SKILL = """---
name: lint-fr
description: >
  Relit un texte français.
  Utile avant une publication.
allowed-tools: Read
---

# Lint
Vérifie l'orthographe.
"""


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@case
def a_skill_md_is_read_and_rewritten_keeping_its_other_keys() -> None:
    name, description, body = skills.parse(SKILL)
    assert name == "lint-fr"
    assert description == "Relit un texte français. Utile avant une publication."
    assert body.startswith("# Lint")
    again = skills.compose(SKILL, "lint-fr", 'Dit "oui": vraiment', "# Neuf\n")
    assert skills.parse(again) == ("lint-fr", 'Dit "oui": vraiment', "# Neuf\n")
    assert "allowed-tools: Read" in again, "a key Ponos does not edit is kept"


@case
def a_skill_is_created_edited_disabled_and_deleted(state_home: Path) -> None:
    made = skills.create("revue", "Relit une PR.", "# Revue\n", ["Proj-X"])
    assert made["scope"] == ["projx"] and made["enabled"]
    assert skills.parse(made["markdown"])[0] == "revue"
    try:
        skills.create("revue", "Autre.", "")
    except ValueError:
        pass
    else:
        raise AssertionError("a name is taken once")
    for bad in ("Revue", "a b", "../x", ""):
        try:
            skills.create(bad, "d", "")
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} is not a skill name")

    skills.put_file(made["id"], "scripts/run.sh", b"echo hi\n")
    changed = skills.update(
        made["id"], body="# Neuf\n", enabled=False, scope=None, scope_given=True
    )
    assert changed["body"].startswith("# Neuf") and not changed["enabled"]
    assert changed["scope"] == [], "a scope said empty means every session"
    assert changed["attached"] == [{"path": "scripts/run.sh", "size": 8}]
    assert skills.read_file(made["id"], "scripts/run.sh") == b"echo hi\n"
    for bad in ("../x", "/etc/passwd", "a/../../b", ".ponos-skill"):
        try:
            skills.put_file(made["id"], bad, b"x")
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} is not a path of a skill")

    skills.remove_file(made["id"], "scripts/run.sh")
    assert skills.get(made["id"])["attached"] == []
    skills.delete(made["id"])
    assert skills.listing() == []


@case
def a_skill_comes_in_from_a_folder_or_a_zip(state_home: Path) -> None:
    folder = skills.import_files(
        {"mon-dossier/SKILL.md": SKILL.encode(), "mon-dossier/a/b.txt": b"b"}
    )
    assert folder["name"] == "lint-fr", "the name comes from the frontmatter"
    assert folder["attached"] == [{"path": "a/b.txt", "size": 1}]

    archive = skills.import_archive(
        _zip(
            {
                "__MACOSX/x": "junk",
                "autre/SKILL.md": SKILL.replace("lint-fr", "autre"),
                "autre/n.md": "n",
            }
        )
    )
    assert archive["name"] == "autre" and [item["path"] for item in archive["attached"]] == ["n.md"]
    for bad in (b"not a zip", _zip({"readme.md": "no skill here"})):
        try:
            skills.import_archive(bad)
        except ValueError:
            continue
        raise AssertionError("an archive with no SKILL.md is refused")
    try:
        skills.import_files({"x/SKILL.md": SKILL.encode()})
    except ValueError:
        pass
    else:
        raise AssertionError("a skill of the same name is refused, never overwritten")


@case
def a_skill_is_placed_for_its_scope_and_the_repository_wins(state_home: Path) -> None:
    with tempfile.TemporaryDirectory() as folder:
        _placed(Path(folder))


def _placed(tmp_path: Path) -> None:
    skills.create("pour-tous", "Pour tous.", "tous\n")
    skills.create("pour-x", "Pour X.", "x\n", ["proj-x"])
    skills.create("eteinte", "Éteinte.", "off\n", enabled=False)
    skills.create("du-depot", "Celle de Ponos.", "ponos\n")

    def worktree(name: str) -> Path:
        path = tmp_path / name
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        return path

    mine, theirs = worktree("x"), worktree("y")
    # The repository of X already holds a skill of that name.
    (mine / ".claude/skills/du-depot").mkdir(parents=True)
    (mine / ".claude/skills/du-depot/SKILL.md").write_text(
        "---\nname: du-depot\ndescription: Dépôt\n---\ndépôt\n"
    )

    placed = skills.install(mine, "proj-x")
    assert sorted(placed.placed) == ["pour-tous", "pour-x"]
    assert placed.kept_from_repository == ["du-depot"]
    assert "dépôt" in (mine / ".claude/skills/du-depot/SKILL.md").read_text(), "never overwritten"
    assert (mine / ".claude/skills/pour-x/SKILL.md").is_file()
    assert not (mine / ".claude/skills/eteinte").exists()

    other = skills.install(theirs, "proj-y")
    assert sorted(other.placed) == ["du-depot", "pour-tous"]
    assert not (theirs / ".claude/skills/pour-x").exists(), "absent from the other projects"

    # What was placed is invisible to `git add -A`; what the repository holds is not.
    subprocess.run(["git", "add", "-A"], cwd=mine, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=mine,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert staged == [".claude/skills/du-depot/SKILL.md"], staged

    # A worktree taken up again: ours are redone, the one switched off goes away.
    skills.update(next(s["id"] for s in skills.listing() if s["name"] == "pour-x"), enabled=False)
    again = skills.install(mine, "proj-x")
    assert again.placed == ["pour-tous"]
    assert not (mine / ".claude/skills/pour-x").exists()
    assert (mine / ".claude/skills/du-depot/SKILL.md").exists()
