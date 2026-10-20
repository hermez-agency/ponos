"""`projects.py`: finding the clone a ticket's project names, and never guessing it."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path

from support import case

from ponos import git as git_module
from ponos import notion, projects
from ponos.projects import _normalise

# -- projects ----------------------------------------------------------------


@case
def remotes_normalise_to_owner_and_name():
    for url in (
        "git@github.com:SalvadorCardona/trader-ia.git",
        "https://github.com/SalvadorCardona/trader-ia",
        "https://github.com/SalvadorCardona/trader-ia.git",
        "ssh://git@github.com/SalvadorCardona/trader-ia.git",
    ):
        assert _normalise(url) == "salvadorcardona/trader-ia", url
        # One reading of a reference, shared: the owner the account is chosen
        # by is the owner the project index files the clone under.

        assert git_module.owner(url) == _normalise(url).split("/")[0], url
    assert _normalise("SalvadorCardona/trader-ia") == "salvadorcardona/trader-ia"


class _ProjectClient:
    """Notion reduced to one project page, with the columns it was given."""

    def __init__(self, title: str, **columns: str) -> None:
        self._page = notion.Page(
            id="p-1",
            url="https://notion.so/p-1",
            title=title,
            properties={
                key: {"type": "rich_text", "rich_text": [{"plain_text": value}]}
                for key, value in columns.items()
            },
        )

    def page(self, page_id: str) -> notion.Page:
        return self._page

    def blocks_text(self, page_id: str, depth: int = 0, *, live: bool = True) -> str:
        return ""


@contextmanager
def _workspace(
    remotes: dict[str, str],
    renamed: dict[str, str] | None = None,
    cloned: list[tuple[str, Path]] | None = None,
):
    """A workspace_root of fake clones — folder name → origin remote — and a
    GitHub that answers `gh repo view` from `renamed`, old name → new name.

    Yields the resolver and the list of names GitHub was asked about, so a
    test can check that the network is the last thing tried, or not tried.

    Pass `cloned` to let this workspace be downloaded into: every clone lands
    there as (repository, path), and the folder it makes joins the remotes, so
    what follows sees the repository exactly as if it had always been here.
    Without it, cloning fails — which is what keeps a test that never meant to
    download anything from doing so for real.
    """
    asked: list[str] = []
    original = projects.git.remote_url, projects.git.current_name, projects.git.clone
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for folder in remotes:
            (root / folder / ".git").mkdir(parents=True)

        def clone(repository: str, into: Path, accounts=None) -> None:
            if cloned is None:
                raise projects.git.GitError(
                    f"{repository} could not be cloned into {into} — no network in this test"
                )
            cloned.append((repository, into))
            (into / ".git").mkdir(parents=True)
            remotes[str(into.relative_to(root))] = f"git@github.com:{repository}.git"

        projects.git.remote_url = lambda repo: remotes.get(str(repo.relative_to(root)), "")
        projects.git.current_name = lambda name, accounts=None: (
            asked.append(name),
            (renamed or {}).get(name, ""),
        )[1]
        projects.git.clone = clone
        try:
            yield projects.Resolver(root, {}), asked
        finally:
            projects.git.remote_url, projects.git.current_name, projects.git.clone = original


@case
def locating_a_project_shows_its_clone_and_never_asks_github_nor_clones():
    """The console shows where the clone is: found by path or by remote, else nowhere."""
    cloned: list[tuple[str, Path]] = []
    with _workspace(
        {"mobile-factory": "git@github.com:SalvadorCardona/mobile-factory.git"}, cloned=cloned
    ) as (resolver, asked):
        root = resolver._root  # noqa: SLF001
        by_remote = resolver.locate("Jeu", "", "SalvadorCardona/mobile-factory")
        assert by_remote == root / "mobile-factory"
        assert resolver.locate("Jeu", str(root / "mobile-factory")) == root / "mobile-factory"
        # A path that points nowhere is not shown as the repository.
        assert resolver.locate("Jeu", str(root / "gone")) is None
        # Declared and absent: nothing is cloned, nobody is asked.
        assert resolver.locate("Autre", "", "SalvadorCardona/never-cloned") is None
        assert resolver.locate("Document") is None
    assert asked == [] and cloned == []


@case
def a_path_that_exists_is_taken_before_anything_else():
    """Nothing is noted and GitHub is never asked: the first way answered."""
    with _workspace({"mobile-factory": "git@github.com:SalvadorCardona/mobile-factory.git"}) as (
        resolver,
        asked,
    ):
        client = _ProjectClient(
            "Jeu d'usine mobile",
            Path=str(resolver._root / "mobile-factory"),  # noqa: SLF001
            Repository="https://github.com/SalvadorCardona/somewhere-else",
        )
        project = resolver.resolve(client, "p-1")
    assert project.path.name == "mobile-factory"
    assert not project.is_stale and project.note == ""
    assert asked == []


@case
def a_wrong_path_gives_way_to_the_repository_property():
    """The case that blocked a real board: the clone was renamed on disk, and
    the page kept the old path — while its Repository column was still right.
    """
    with _workspace({"mobile-factory": "git@github.com:SalvadorCardona/mobile-factory.git"}) as (
        resolver,
        asked,
    ):
        client = _ProjectClient(
            "Jeu d'usine mobile",
            Path=str(resolver._root / "factory-mobile"),  # noqa: SLF001
            Repository="https://github.com/SalvadorCardona/mobile-factory",
        )
        project = resolver.resolve(client, "p-1")
    assert project.is_code and project.path.name == "mobile-factory"
    assert project.is_stale, "found, but not by the declaration that should have found it"
    assert (
        "factory-mobile, from the project's Path property, is not a git repository" in project.note
    )
    assert "salvadorcardona/mobile-factory" in project.note, "the note says how it was found"
    assert asked == [], "a remote that matches is not a question for GitHub"


@case
def a_repository_renamed_on_github_is_found_under_its_new_name():
    """GitHub redirects the old name, so `gh repo view old` says the new one."""
    with _workspace(
        {"mobile-factory": "git@github.com:SalvadorCardona/mobile-factory.git"},
        renamed={"salvadorcardona/factory-mobile": "SalvadorCardona/mobile-factory"},
    ) as (resolver, asked):
        client = _ProjectClient(
            "Jeu d'usine mobile", Repository="https://github.com/SalvadorCardona/factory-mobile"
        )
        project = resolver.resolve(client, "p-1")
    assert project.path.name == "mobile-factory"
    assert project.is_stale
    assert "which GitHub has renamed salvadorcardona/mobile-factory" in project.note
    assert asked == ["salvadorcardona/factory-mobile"], "asked once, about the name that failed"


@case
def a_project_no_way_leads_to_says_everything_that_was_tried():
    with _workspace({"other": "git@github.com:SalvadorCardona/other.git"}) as (resolver, asked):
        client = _ProjectClient(
            "Jeu d'usine mobile",
            Path=str(resolver._root / "factory-mobile"),  # noqa: SLF001
            Repository="https://github.com/SalvadorCardona/factory-mobile",
        )
        try:
            resolver.resolve(client, "p-1")
        except LookupError as error:
            message = str(error)
        else:
            raise AssertionError("nothing leads to a repository, so this has to fail")
    assert "“Jeu d'usine mobile”" in message
    assert "factory-mobile, from the project's Path property, is not a git repository" in message
    assert (
        "salvadorcardona/factory-mobile, from the project's Repository property, matches no origin remote"
        in message
    )
    assert "GitHub gave no other name" in message
    assert '"Jeu d\'usine mobile" = "/path/to/the/repo"' in message, "and what to do about it"
    assert asked == ["salvadorcardona/factory-mobile"]


@case
def a_wrong_path_alone_is_still_an_error_and_not_a_document():
    """Declaring a repository that is not there must not quietly turn the
    project's tickets into pages: the page meant a repository."""
    with _workspace({}) as (resolver, asked):
        client = _ProjectClient("Site", Path="/nowhere/at/all")
        try:
            resolver.resolve(client, "p-1")
        except LookupError as error:
            assert "/nowhere/at/all, from the project's Path property" in str(error)
        else:
            raise AssertionError("a wrong Path with nothing else is not a document project")
    assert asked == [], "there is no name to ask GitHub about"


@case
def a_folder_named_like_the_project_is_not_a_match():
    """Only the remote designates a repository. A clone whose folder happens to
    carry the declared name, with another remote, is somebody else's project."""
    with _workspace({"factory-mobile": "git@github.com:SomebodyElse/factory-mobile.git"}) as (
        resolver,
        asked,
    ):
        client = _ProjectClient(
            "Jeu", Repository="https://github.com/SalvadorCardona/factory-mobile"
        )
        try:
            resolver.resolve(client, "p-1")
        except LookupError as error:
            assert "matches no origin remote" in str(error)
        else:
            raise AssertionError("a folder name is a resemblance, not a declaration")


@case
def two_clones_of_one_remote_answer_for_neither():
    with _workspace(
        {
            "trader-ia": "git@github.com:SalvadorCardona/trader-ia.git",
            "labo/trader-ia-copy": "https://github.com/SalvadorCardona/trader-ia",
        }
    ) as (resolver, asked):
        client = _ProjectClient("Trader IA", Repository="SalvadorCardona/trader-ia")
        try:
            resolver.resolve(client, "p-1")
        except LookupError as error:
            message = str(error)
        else:
            raise AssertionError("two candidates is no answer")
    assert "is the remote of 2 repositories" in message
    assert "trader-ia-copy" in message and "trader-ia" in message


@case
def a_project_made_of_its_github_link_alone_is_cloned():
    """The whole of "I created the project with just its GitHub": nothing on
    this machine answers for that remote, so the clone is made under the root
    and the ticket runs on it, instead of the project being put back."""
    cloned: list[tuple[str, Path]] = []
    with _workspace(
        {}, renamed={"salvadorcardona/trader-ia": "SalvadorCardona/trader-ia"}, cloned=cloned
    ) as (resolver, asked):
        client = _ProjectClient(
            "Trader IA", Repository="https://github.com/SalvadorCardona/trader-ia"
        )
        project = resolver.resolve(client, "p-1", clone=True)
        root = resolver._root  # noqa: SLF001
    assert project.is_code and project.path == root / "trader-ia"
    assert cloned == [("SalvadorCardona/trader-ia", root / "trader-ia")], (
        "under the name GitHub uses"
    )
    assert not project.is_stale, "nothing on the page is wrong — the clone was only missing"
    assert "cloned into" in project.cloned, "and the ticket's comment says where it came from"


@case
def reading_the_board_downloads_nothing():
    """`resolve` only clones when it is asked to: listing the projects, or a
    dry run, must not start pulling repositories down in the background."""
    cloned: list[tuple[str, Path]] = []
    with _workspace({}, cloned=cloned) as (resolver, asked):
        client = _ProjectClient("Trader IA", Repository="SalvadorCardona/trader-ia")
        try:
            resolver.resolve(client, "p-1")
        except LookupError as error:
            assert "matches no origin remote" in str(error)
        else:
            raise AssertionError("without clone=True this is the refusal it always was")
    assert cloned == []


@case
def a_clone_is_never_made_where_two_already_answer():
    """Ambiguity is not something a third copy would settle."""
    cloned: list[tuple[str, Path]] = []
    with _workspace(
        {
            "trader-ia": "git@github.com:SalvadorCardona/trader-ia.git",
            "labo/trader-ia-copy": "https://github.com/SalvadorCardona/trader-ia",
        },
        cloned=cloned,
    ) as (resolver, asked):
        client = _ProjectClient("Trader IA", Repository="SalvadorCardona/trader-ia")
        try:
            resolver.resolve(client, "p-1", clone=True)
        except LookupError as error:
            assert "is the remote of 2 repositories" in str(error)
        else:
            raise AssertionError("two candidates is still no answer")
    assert cloned == []


@case
def a_wrong_path_is_still_reported_under_the_repository_that_was_cloned():
    """The clone is the fallback the tickets now run on, so the page is still
    wrong and the note still says which line of it to correct."""
    cloned: list[tuple[str, Path]] = []
    with _workspace({}, cloned=cloned) as (resolver, asked):
        client = _ProjectClient(
            "Trader IA",
            Path=str(resolver._root / "trader-ia-elsewhere"),  # noqa: SLF001
            Repository="SalvadorCardona/trader-ia",
        )
        project = resolver.resolve(client, "p-1", clone=True)
    assert project.is_stale and "is not a git repository" in project.note
    assert "matches no origin remote" not in project.note, "a missing clone is nobody's mistake"
    assert cloned and project.cloned


@case
def a_clone_that_cannot_be_made_joins_the_ways_that_were_tried():
    with _workspace({}) as (resolver, asked):
        client = _ProjectClient("Trader IA", Repository="SalvadorCardona/trader-ia")
        try:
            resolver.resolve(client, "p-1", clone=True)
        except LookupError as error:
            message = str(error)
        else:
            raise AssertionError("a clone that fails leaves the project unresolved")
    assert "matches no origin remote" in message, "every earlier way is still listed"
    assert "could not be cloned" in message and "no network in this test" in message
