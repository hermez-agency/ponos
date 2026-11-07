"""`project_settings.py`: the path and the vault keys a project holds in `ponos.db`."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from support import case

from ponos import project_settings, projects
from ponos.health import settings as health_settings

PROJECT = "0123456789abcdef0123456789abcdef"


def _repository(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@case
def a_project_holds_its_path_and_its_vault_keys_and_lets_them_go(state_home: Path) -> None:
    assert project_settings.path(PROJECT) == "" and project_settings.vault(PROJECT) == {}
    project_settings.set_path(PROJECT, "Brevo", " ~/workspace/brevo ")
    project_settings.set_vault(PROJECT, "Brevo", {"NPM_TOKEN": "hermez/npm", " ": "x", "EMPTY": ""})
    assert project_settings.path(PROJECT) == "~/workspace/brevo"
    assert project_settings.vault(PROJECT) == {"NPM_TOKEN": "hermez/npm"}
    assert project_settings.every_vault() == {"Brevo": {"NPM_TOKEN": "hermez/npm"}}
    project_settings.set_path(PROJECT, "Brevo", "")
    project_settings.set_vault(PROJECT, "Brevo", {})
    assert project_settings.path(PROJECT) == "" and project_settings.every_vault() == {}


@case
def the_path_of_the_project_is_where_its_repository_is_looked_for(state_home: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        own = _repository(root, "own")
        resolver = projects.Resolver(root / "empty")
        assert resolver.locate("Brevo", page_id=PROJECT) is None, "nothing, while it is silent"
        project_settings.set_path(PROJECT, "Brevo", str(own))
        assert resolver.locate("Brevo", page_id=PROJECT) == own, "then the project's own word"
        assert resolver.locate("Brevo") is None, "which a caller without a page cannot read"


@case
def the_doctor_reads_the_keys_a_project_holds(state_home: Path) -> None:
    project_settings.set_vault(PROJECT, "Brevo", {"B_TOKEN": "b", "ANTHROPIC_API_KEY": "x"})
    grants, problems = health_settings._grants()
    assert grants == {"Brevo": {"B_TOKEN": "b"}}
    assert len(problems) == 1 and "ANTHROPIC_API_KEY" in problems[0], "the runner's own is refused"
