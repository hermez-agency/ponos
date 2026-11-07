"""`project_settings.py`: the path and the vault keys a project holds in `ponos.db`."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from support import _config, case

from ponos import config as C
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
def the_path_of_the_project_comes_before_the_one_of_the_file(state_home: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        filed = _repository(root, "filed")
        own = _repository(root, "own")
        resolver = projects.Resolver(root / "empty", {"Brevo": str(filed)})
        assert resolver.locate("Brevo", page_id=PROJECT) == filed, (
            "the file, while the project is silent"
        )
        project_settings.set_path(PROJECT, "Brevo", str(own))
        assert resolver.locate("Brevo", page_id=PROJECT) == own, "then the project's own word"
        assert resolver.locate("Brevo") == filed, "and a caller without a page keeps the file's"


@case
def the_doctor_reads_the_keys_a_project_holds_beside_the_ones_of_the_file(state_home: Path) -> None:
    config = _config("")
    config.vault = C.Vault(projects={"Brevo": {"A_TOKEN": "a"}})
    project_settings.set_vault(PROJECT, "brevo", {"B_TOKEN": "b", "ANTHROPIC_API_KEY": "x"})
    grants, problems = health_settings._grants(config)
    assert grants == {"Brevo": {"A_TOKEN": "a", "B_TOKEN": "b"}}
    assert len(problems) == 1 and "ANTHROPIC_API_KEY" in problems[0], "the runner's own is refused"
